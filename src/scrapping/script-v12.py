"""
GDPR consent banner scraper with multi-vendor support and anti-bot measures.
"""

import pandas as pd
import time
import os
import json
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager

# Configuration
URL_LIST_FILE = "websites.csv"
OUTPUT_CSV_FILE = "gdpr_final_dataset-v7.csv"
DEBUG_HTML_DIR = "debug_html_failures"
HEADLESS_MODE = False  # Set to True to run browser in background

# --- Anti-Bot Configuration ---
def initialize_driver():
    chrome_options = Options()
    if HEADLESS_MODE:
        chrome_options.add_argument("--headless=new")
    
    # Critical anti-detection measures
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-notifications")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Mask webdriver status
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        '''
    })
    return driver

# --- Intelligent Button Detection ---
def find_settings_button(driver, banner):
    button_metrics = {
        'preferences': 5, 'manage': 5, 'settings': 4, 
        'customize': 4, 'options': 3, 'details': 2
    }
    negative_terms = ['accept', 'agree', 'allow', 'ok', 'reject', 'necessary']
    
    candidates = banner.find_elements(By.XPATH, ".//button | .//a[@role='button'] | .//div[@role='button']")
    scored = []
    
    for btn in candidates:
        try:
            text = btn.text.lower()
            if not text or any(term in text for term in negative_terms):
                continue
                
            score = sum(button_metrics[key] for key in button_metrics if key in text)
            if len(text.split()) > 2:  # Prefer descriptive buttons
                score += 2
                
            scored.append((btn, score))
        except Exception:
            continue
    
    if not scored:
        return None
    
    # Select highest score with fallback to first candidate
    return max(scored, key=lambda x: x[1])[0]

# --- Shadow DOM Handling ---
def get_shadow_content(driver, element):
    return driver.execute_script("return arguments[0].shadowRoot", element)

# --- Core Workflow ---
def process_website(driver, url):
    data = {
        "url": url,
        "status": "Failed",
        "purposes": [],
        "error_log": []
    }
    
    try:
        driver.get(url)
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
        
        # Handle potential iframes
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in frames:
            try:
                driver.switch_to.frame(frame)
                if handle_consent_banner(driver, data):
                    break
                driver.switch_to.default_content()
            except Exception:
                continue
                
        if not handle_consent_banner(driver, data):
            data["error_log"].append("No banner found")
            return data
            
        # Post-click processing
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".ot-sdk-container, .privacy-settings, [id*='consent']"))
        )
        extract_purposes(driver, data)
        
    except Exception as e:
        data["error_log"].append(f"Critical error: {type(e).__name__}")
    
    return data

def handle_consent_banner(driver, data):
    try:
        banner = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='dialog'], .cookie-banner, #onetrust-banner"))
        )
        
        # Check shadow DOM
        shadow_root = get_shadow_content(driver, banner)
        if shadow_root:
            banner = shadow_root
            
        settings_btn = find_settings_button(driver, banner)
        if not settings_btn:
            data["error_log"].append("No settings button found")
            return False
            
        driver.execute_script("arguments[0].scrollIntoView(true);", settings_btn)
        driver.execute_script("arguments[0].click();", settings_btn)
        time.sleep(2)  # Allow AJAX loading
        
        return True
        
    except TimeoutException:
        return False

def extract_purposes(driver, data):
    try:
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        purposes = []
        
        # Multi-vendor support
        for item in soup.select('.ot-sdk-row, .privacy-category, [data-purpose]'):
            title = item.find(['h3', 'h4', 'span'], class_=re.compile('title|header'))
            checkbox = item.find('input', {'type': 'checkbox'})
            
            if not title or not checkbox:
                continue
                
            purposes.append({
                "title": title.get_text(strip=True),
                "is_strictly_necessary": 'disabled' in checkbox.attrs,
                "is_ticked_by_default": 'checked' in checkbox.attrs
            })
        
        data["purposes"] = purposes
        data["status"] = "Success" if purposes else "No purposes found"
        
    except Exception as e:
        data["error_log"].append(f"Extraction failed: {type(e).__name__}")

# --- Main Execution ---
def main():
    driver = initialize_driver()
    websites = pd.read_csv(URL_LIST_FILE)['url'].tolist()
    
    results = []
    for url in websites:
        print(f"Processing {url}")
        result = process_website(driver, url)
        results.append({
            "url": url,
            "status": result["status"],
            "purposes": json.dumps(result["purposes"]),
            "errors": "; ".join(result["error_log"])
        })
    
    pd.DataFrame(results).to_csv(OUTPUT_CSV_FILE, index=False)
    driver.quit()

if __name__ == "__main__":
    main()
