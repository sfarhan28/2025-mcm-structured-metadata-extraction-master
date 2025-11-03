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

# --- Configuration ---
URL_LIST_FILE = "websites.csv"
OUTPUT_CSV_FILE = "gdpr_final_dataset-v3.csv"
DEBUG_HTML_DIR = "debug_html_failures"
# CRITICAL: Running with the browser visible is ESSENTIAL for debugging interaction.
HEADLESS_MODE = False

# --- Helper Functions ---
def initialize_driver():
    """Sets up a robust, humanized Selenium WebDriver."""
    chrome_options = Options()
    if HEADLESS_MODE: chrome_options.add_argument("--headless=new")
    
    # Anti-bot evasion techniques to counter dynamic evasion tactics
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

    chrome_options.add_argument("--window-size=1920,1080"); chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--no-sandbox"); chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--log-level=3")
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined })
            '''
        })
        return driver
    except Exception as e:
        print(f"FATAL: Could not initialize WebDriver: {e}"); return None

def save_debug_html(driver, url, stage):
    """Saves the current page source on failure for offline analysis."""
    if not os.path.exists(DEBUG_HTML_DIR): os.makedirs(DEBUG_HTML_DIR)
    filename = re.sub(r'[^a-zA-Z0-9]', '_', url) + f"_FAIL_AT_{stage}.html"
    with open(os.path.join(DEBUG_HTML_DIR, filename), 'w', encoding='utf-8') as f: f.write(driver.page_source)

def intelligent_button_finder(driver, banner_element: WebElement, data: dict) -> bool:
    """Dynamically finds, scores, and clicks the most likely settings button."""
    try:
        buttons = banner_element.find_elements(By.XPATH, ".//button | .//a[@role='button']")
        if not buttons:
            data["error_log"].append("No buttons found in banner.")
            return False

        positive_keywords = {
            'preferences': 5, 'manage': 5, 'options': 4, 'settings': 4, 
            'customize': 4, 'customise': 4, 'configure': 3, 'more': 2, 'details': 2
        }
        negative_keywords = ['accept', 'agree', 'allow', 'confirm', 'ok', 'reject', 'decline', 'deny', 'necessary']

        button_scores = {}
        for i, button in enumerate(buttons):
            try:
                text = button.text.lower()
                if not text or not button.is_displayed() or not button.is_enabled(): continue
                if any(keyword in text for keyword in negative_keywords): button_scores[i] = -99; continue
                score = sum(value for keyword, value in positive_keywords.items() if keyword in text)
                if len(text.split()) > 2: score += 1
                button_scores[i] = score
            except Exception: continue

        if not button_scores or max(button_scores.values()) <= 0:
            data["error_log"].append("No button with positive settings keywords found.")
            return False

        best_button_index = max(button_scores, key=button_scores.get)
        best_button = buttons[best_button_index]
        
        print(f"  -> Clicking settings button: '{best_button.text}' (Score: {button_scores[best_button_index]})")
        data["settings_button_present"] = True
        data["settings_button_text"] = best_button.text
        
        driver.execute_script("arguments[0].click();", best_button)
        data["preference_center_accessed"] = True
        time.sleep(3) # A necessary pause for JS to render the new content
        return True
    except Exception as e:
        data["error_log"].append(f"Button interaction failed: {type(e).__name__}"); return False

def extract_comprehensive_data(driver, data):
    """Extracts all raw data points needed for the final analysis."""
    try:
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # --- Purpose Extraction ---
        purpose_selectors = ['.ot-cat-item', 'div[class*="purpose-item"]', 'div[class*="category"]', 'div.uc-list-container']
        purpose_items = soup.select(','.join(purpose_selectors))
        
        if not purpose_items:
            data["error_log"].append("No purpose containers found after interaction.")
            save_debug_html(driver, data['url'], "purpose_extraction")
            return

        purposes_list = []
        for item in purpose_items:
            title_element = item.find(['h3', 'h4', 'h5'], class_=lambda c: c and 'title' in c) or item.find('label')
            title = title_element.get_text(strip=True) if title_element else "Title Not Found"
            
            checkbox = item.find('input', type='checkbox')
            is_ticked = checkbox.has_attr('checked') if checkbox else False
            is_disabled = checkbox.has_attr('disabled') if checkbox else False
            is_always_active = is_disabled or "strictly necessary" in title.lower()
            
            purposes_list.append({"title": title, "is_strictly_necessary": is_always_active, "is_ticked_by_default": is_ticked})
            if is_always_active: data["strictly_necessary_count"] += 1
            elif is_ticked: data["pre_ticked_non_essential_count"] += 1
        
        data["total_purposes_count"] = len(purposes_list)
        data["purposes_json"] = json.dumps(purposes_list)
        
        # --- Vendor Count Extraction ---
        vendor_section = soup.select_one('.vendor-list, #vendor-list, div[class*="vendor"], div[class*="partner"]')
        if vendor_section:
            data["vendor_count"] = len(vendor_section.select('.vendor-item, li, div[class*="vendor-row"]'))
        
        if data["total_purposes_count"] > 0:
            data["status"] = "Success"
        else:
            data["status"] = "Partial (Parsing resulted in zero purposes)"

    except Exception as e:
        data["error_log"].append(f"Data extraction failed: {type(e).__name__}"); data["status"] = "Failed"

def analyze_consent_banner(driver, data):
    """Main analysis function that orchestrates the data collection."""
    try:
        banner_selectors = ["div[role='dialog']", "div[id*='cookie']", "div[class*='consent']"]
        banner = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ", ".join(banner_selectors))))
        data["initial_banner_found"] = True

        # --- Button Presence Analysis ---
        accept_xpath = ".//button[contains(translate(., 'ACDEGIKLNOPRSTUWY', 'acdegiklnoprstuwy'), 'accept')]"
        reject_xpath = ".//button[contains(translate(., 'CDEIJLNORSTUY', 'cdeijlnorstuy'), 'reject')]"
        data["accept_all_present"] = bool(banner.find_elements(By.XPATH, accept_xpath))
        data["reject_all_present"] = bool(banner.find_elements(By.XPATH, reject_xpath))
        
        # --- Legal Text Extraction ---
        legal_text_elements = banner.find_elements(By.XPATH, ".//p | .//div[contains(@class, 'text')]")
        data["legal_text_summary"] = ' '.join([elem.text for elem in legal_text_elements if elem.text.strip()][:3])
        
        # --- Intelligent Interaction ---
        if not intelligent_button_finder(driver, banner, data):
            data["status"] = "Partial (Interaction Failed)"
            return
        
        # --- Post-Interaction Data Extraction ---
        extract_comprehensive_data(driver, data)
    except Exception as e:
        data["status"] = "Failed"; data["error_log"].append(f"Analysis failed: {type(e).__name__}")

def main_scraper_workflow(driver, url):
    """Main scraping function designed to collect the 12 specified data points."""
    # This dictionary defines the exact columns for your output CSV.
    data = {
        "url": url,
        "timestamp": pd.Timestamp.now().isoformat(),
        "status": "Pending",
        "accept_all_present": False,
        "reject_all_present": False,
        "settings_button_present": False,
        "settings_button_text": "",
        "preference_center_accessed": False,
        "total_purposes_count": 0,
        "pre_ticked_non_essential_count": 0,
        "strictly_necessary_count": 0,
        "purposes_json": "[]",
        "vendor_count": 0,
        "legal_text_summary": "",
        "error_log": []
    }
    try:
        driver.get(url)
        WebDriverWait(driver, 20).until(lambda d: d.execute_script('return document.readyState') == 'complete')
        time.sleep(4) # A generous wait for banners to fully animate and appear
        analyze_consent_banner(driver, data)
    except Exception as e:
        data["status"] = "Failed"; data["error_log"].append(f"Critical error: {type(e).__name__}")
    return data

def main():
    try: urls = pd.read_csv(URL_LIST_FILE)['url'].dropna().unique().tolist()
    except FileNotFoundError: print(f"FATAL: Input file '{URL_LIST_FILE}' not found."); return

    driver = initialize_driver()
    if not driver: return

    all_results = []
    for i, url in enumerate(urls, 1):
        print(f"\n--- Processing ({i}/{len(urls)}): {url} ---")
        result = main_scraper_workflow(driver, url)
        all_results.append(result)
        print(f"Status: {result.get('status', 'Unknown')}")
        if result.get('total_purposes_count', 0) > 0:
            print(f"  - Extracted {result['total_purposes_count']} purposes")
        if result.get('error_log'):
            print(f"  - Log: {'; '.join(result['error_log'])}")

    driver.quit()
    # Ensure only the requested columns are saved
    final_df = pd.DataFrame(all_results)
    requested_columns = [
        "url", "timestamp", "status", "accept_all_present", "reject_all_present",
        "settings_button_present", "settings_button_text", "preference_center_accessed",
        "total_purposes_count", "pre_ticked_non_essential_count", "strictly_necessary_count",
        "purposes_json", "vendor_count", "legal_text_summary", "error_log"
    ]
    final_df = final_df[requested_columns]
    final_df.to_csv(OUTPUT_CSV_FILE, index=False)
    
    print(f"\nScraping complete. Master dataset saved to '{OUTPUT_CSV_FILE}'")

if __name__ == "__main__":
    main()
