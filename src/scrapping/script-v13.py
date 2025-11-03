"""
GDPR consent banner scraper with robust anti-bot and retry logic.
"""

import pandas as pd
import time
import random
import os
import json
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager

# Configuration
URL_LIST_FILE = "websites_300.csv"
OUTPUT_CSV_FILE = "gdpr_final_dataset-v8.1.csv"
DEBUG_HTML_DIR = "debug_html_failures"
HEADLESS_MODE = False  # Set to True to run browser in background
MAX_RETRIES = 2
REQUEST_TIMEOUT = 30

# --- Anti-Detection Measures ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Firefox/126.0"
]

def initialize_driver():
    """Sets up a robust, humanized Selenium WebDriver."""
    chrome_options = Options()
    if HEADLESS_MODE:
        chrome_options.add_argument("--headless=new")
    
    # Advanced evasion techniques to counter anti-bot measures
    chrome_options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--lang=en-US,en;q=0.9")
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # Mask automation traces from JavaScript
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = window.chrome || {};
                window.chrome.runtime = window.chrome.runtime || {};
            '''
        })
        return driver
    except Exception as e:
        print(f"FATAL: Could not initialize WebDriver: {e}"); return None

# --- Helper Functions (Including the corrected function) ---
def get_shadow_content(driver, element):
    """Safely gets the shadow root of an element."""
    try:
        return driver.execute_script("return arguments[0].shadowRoot", element)
    except Exception:
        return None

def save_debug_html(driver, url, stage):
    """Saves the current page source on failure for offline analysis."""
    if not os.path.exists(DEBUG_HTML_DIR): os.makedirs(DEBUG_HTML_DIR)
    filename = re.sub(r'[^a-zA-Z0-9]', '_', url) + f"_FAIL_AT_{stage}.html"
    with open(os.path.join(DEBUG_HTML_DIR, filename), 'w', encoding='utf-8') as f: f.write(driver.page_source)

# --- Intelligent Interaction System ---
def click_settings_button(banner):
    """Advanced button detection with multiple fallback strategies."""
    button_scores = {
        'preferences': 5, 'manage': 5, 'options': 4, 
        'settings': 4, 'customize': 4, 'control': 3, 'more': 2, 'details': 2
    }
    negative_terms = ['accept', 'agree', 'allow', 'ok', 'reject', 'necessary', 'essential', 'confirm', 'save']
    
    candidates = banner.find_elements(By.XPATH, ".//button | .//a[@role='button']")
    best_button = None
    max_score = 0
    
    for btn in candidates:
        try:
            text = btn.text.lower()
            if not text or any(term in text for term in negative_terms) or not btn.is_displayed():
                continue
            
            score = sum(value for word, value in button_scores.items() if word in text)
            if score > max_score:
                max_score = score
                best_button = btn
        except Exception:
            continue
    
    return best_button

# --- Robust Extraction Pipeline ---
def extract_purposes(driver):
    """Multi-layered extraction strategy to get purpose details."""
    WebDriverWait(driver, 5).until(lambda d: d.execute_script("return document.readyState === 'complete'"))
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    
    purpose_selectors = [
        '.ot-cat-item', 'div[class*="purpose"]', 'div[data-purpose-id]', '.uc-list-item'
    ]
    purposes = soup.select(','.join(purpose_selectors))
    
    results = []
    for item in purposes:
        try:
            title_element = item.find(['h2', 'h3', 'h4', 'label'], class_=re.compile('title|header|heading'))
            title = title_element.get_text(strip=True) if title_element else "Unlabeled Purpose"
            
            checkbox = item.find('input', type='checkbox')
            if not checkbox: continue
                
            is_ticked = checkbox.has_attr('checked')
            is_disabled = checkbox.has_attr('disabled')
            is_necessary = is_disabled or "necessary" in title.lower() or "essential" in title.lower()
            
            results.append({
                "title": title,
                "is_strictly_necessary": is_necessary,
                "is_ticked_by_default": is_ticked and not is_necessary
            })
        except Exception:
            continue
            
    return results

# --- Main Workflow with Retry Logic ---
def process_website(driver, url):
    """Processes a single website with retry logic and advanced interaction."""
    data = {
        "url": url, "status": "Failed", "total_purposes_count": 0,
        "purposes_json": "[]", "error_log": []
    }
    
    for attempt in range(MAX_RETRIES + 1):
        try:
            driver.get(url)
            
            banner_selectors = ['div[role="dialog"]', 'div[id*="consent"]', 'div[class*="cookie-banner"]']
            banner = WebDriverWait(driver, REQUEST_TIMEOUT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ", ".join(banner_selectors)))
            )
            
            settings_btn = None
            try:
                settings_btn = banner.find_element(By.ID, "onetrust-pc-btn-handler")
            except NoSuchElementException:
                settings_btn = click_settings_button(banner)
            
            if settings_btn:
                driver.execute_script("arguments[0].click();", settings_btn)
                time.sleep(3)
                
                purposes = extract_purposes(driver)
                if purposes:
                    data["status"] = "Success"
                    data["total_purposes_count"] = len(purposes)
                    data["purposes_json"] = json.dumps(purposes)
                    return data
            
            data["error_log"].append("No interactive settings button found.")
            data["status"] = "Partial - No Settings Button"
            break

        except Exception as e:
            error_msg = f"Attempt {attempt+1}: {type(e).__name__}"
            if attempt == MAX_RETRIES:
                data["error_log"].append(error_msg)
                save_debug_html(driver, url, f"final_failure_{type(e).__name__}")
                break
            time.sleep(2 * (attempt + 1))
            
    return data

def main():
    """Main execution function to run the scraper."""
    driver = initialize_driver()
    if not driver: return
    
    try:
        websites = pd.read_csv(URL_LIST_FILE)['url'].dropna().unique().tolist()
    except FileNotFoundError:
        print(f"ERROR: '{URL_LIST_FILE}' not found. Please create it with a 'url' column.")
        driver.quit()
        return
    
    results = []
    for idx, url in enumerate(websites, 1):
        print(f"Processing ({idx}/{len(websites)}): {url}")
        result = process_website(driver, url)
        results.append(result)
        
    driver.quit()
    
    # Calculate and print success rate
    success_count = sum(1 for r in results if r["status"] == "Success")
    success_rate = (success_count / len(results)) * 100 if results else 0
    print(f"\n--- Scraping Complete ---")
    print(f"Success Rate: {success_rate:.2f}% ({success_count}/{len(results)})")
    
    # Save to CSV
    pd.DataFrame(results).to_csv(OUTPUT_CSV_FILE, index=False)
    print(f"Results saved to '{OUTPUT_CSV_FILE}'")

if __name__ == "__main__":
    main()
