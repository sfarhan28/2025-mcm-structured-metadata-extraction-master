import pandas as pd
import time
import os
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager

# --- Configuration ---
URL_LIST_FILE = "websites.csv"  # Your input CSV file with a 'url' column
OUTPUT_CSV_FILE = "gdpr_master_dataset.csv"
HEADLESS_MODE = True  # Set to False to watch the browser in action for debugging

def initialize_driver():
    """Sets up and returns a Selenium WebDriver with robust options."""
    chrome_options = Options()
    if HEADLESS_MODE:
        chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--log-level=3")  # Suppress non-critical console logs
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36")
    
    try:
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=chrome_options)
    except Exception as e:
        print(f"FATAL ERROR: Could not initialize WebDriver. Error: {e}")
        return None

def find_element_by_heuristics(driver, selectors, timeout=3):
    """Tries a prioritized list of selectors to find an element."""
    for by, value in selectors:
        try:
            return WebDriverWait(driver, timeout).until(EC.visibility_of_element_located((by, value)))
        except TimeoutException:
            continue
    return None

def scrape_website_data(driver, url):
    """
    Applies a multi-stage, heuristic-based process to scrape consent data.
    This is the core logic engine of the scraper.
    """
    # --- 1. Initialize Data Structure ---
    # This structure is designed to capture the full story of the scrape.
    data = {
        "url": url,
        "timestamp": pd.Timestamp.now().isoformat(),
        "status": "Pending",  # Will become "Success", "Partial", or "Failed"
        "cmp_vendor": "Unknown",
        "initial_banner_found": False,
        "accept_all_present": False,
        "reject_all_present": False,
        "settings_button_present": False,
        "preference_center_accessed": False,
        "total_purposes_count": 0,
        "pre_ticked_non_essential_count": 0,
        "strictly_necessary_count": 0,
        "purposes_json": "[]",
        "error_log": []
    }

    try:
        driver.get(url)
        
        # --- 2. Heuristic-Based Banner Detection ---
        banner_selectors = [
            (By.ID, "onetrust-banner-sdk"), (By.ID, "CybotCookiebotDialog"),
            (By.ID, "qc-cmp2-container"), (By.CSS_SELECTOR, "div[class*='consent-modal']"),
            (By.CSS_SELECTOR, "div[role='dialog']"), (By.CSS_SELECTOR, "div[id*='cookie']"),
            (By.CSS_SELECTOR, "div[class*='cookie']"), (By.CSS_SELECTOR, "div[class*='consent']")
        ]
        banner_element = find_element_by_heuristics(driver, banner_selectors, timeout=10)

        if not banner_element:
            data["status"] = "Failed"
            data["error_log"].append("No recognizable consent banner found.")
            return data
        
        data["initial_banner_found"] = True
        
        # --- 3. Initial Banner Analysis (Buttons) ---
        # This uses more resilient XPath selectors that are case-insensitive and check for multiple keywords.
        accept_xpath = "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'allow') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'agree')]"
        reject_xpath = "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'reject') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'decline') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'necessary')]"
        settings_xpath = "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'setting') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'manage') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'customize') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'options')]"
        
        data["accept_all_present"] = bool(find_element_by_heuristics(driver, [(By.XPATH, accept_xpath)]))
        data["reject_all_present"] = bool(find_element_by_heuristics(driver, [(By.XPATH, reject_xpath)]))
        settings_button = find_element_by_heuristics(driver, [(By.XPATH, settings_xpath), (By.ID, "onetrust-pc-btn-handler")])
        data["settings_button_present"] = bool(settings_button)

        # --- 4. INTERACTION: Attempt to Access Preference Center ---
        if not settings_button:
            data["status"] = "Partial"
            data["error_log"].append("Initial banner found, but no settings/manage button detected.")
            return data
            
        try:
            driver.execute_script("arguments[0].scrollIntoView(true); arguments[0].click();", settings_button)
            time.sleep(2) # Crucial pause for JS to render the new content.
            data["preference_center_accessed"] = True
        except (ElementClickInterceptedException, NoSuchElementException) as e:
            data["status"] = "Partial"
            data["error_log"].append(f"Found settings button but failed to click: {type(e).__name__}")
            return data

        # --- 5. DETAILED SCRAPE: Parse the Preference Center ---
        pc_soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # A more generalized set of selectors for purpose containers
        purpose_selectors = ['.ot-cat-item', 'div[data-optanongroupid]', '.purpose-vendor-container', 'div[class*="purpose-item"]']
        purpose_items = pc_soup.select(','.join(purpose_selectors))

        if not purpose_items:
            data["status"] = "Partial"
            data["error_log"].append("Accessed preference center, but could not find purpose containers.")
            return data

        purposes_list = []
        for item in purpose_items:
            title_element = item.find(['h3', 'h4', 'h5', 'span'], class_=lambda c: c and ('header' in c or 'title' in c))
            title = title_element.get_text(strip=True) if title_element else "Title Not Found"

            is_always_active = 'always-active' in ' '.join(item.get('class', []))
            
            toggle = item.find('input', type='checkbox')
            is_ticked = toggle.has_attr('checked') if toggle else False

            purposes_list.append({"title": title, "is_strictly_necessary": is_always_active, "is_ticked_by_default": is_ticked})
            
            if is_always_active:
                data["strictly_necessary_count"] += 1
            elif is_ticked:
                data["pre_ticked_non_essential_count"] += 1
        
        data["total_purposes_count"] = len(purposes_list)
        data["purposes_json"] = json.dumps(purposes_list)
        data["status"] = "Success"

    except Exception as e:
        data["status"] = "Failed"
        data["error_log"].append(f"Top-level script error: {type(e).__name__} - {str(e)}")
    
    return data

def main():
    """Main workflow to drive the scraping process for multiple websites."""
    try:
        websites_df = pd.read_csv(URL_LIST_FILE)
        urls = websites_df['url'].dropna().unique().tolist()
    except FileNotFoundError:
        print(f"FATAL ERROR: Input file '{URL_LIST_FILE}' not found. Please create it with a 'url' column.")
        return

    driver = initialize_driver()
    if not driver:
        return

    all_results = []
    total_sites = len(urls)
    for i, url in enumerate(urls, 1):
        print(f"\n--- Processing ({i}/{total_sites}): {url} ---")
        result = scrape_website_data(driver, url)
        all_results.append(result)
        print(f"Status: {result['status']}")
        if result['error_log']:
            print(f"  - Errors: {', '.join(result['error_log'])}")

    driver.quit()
    
    # --- Save Final Results ---
    results_df = pd.DataFrame(all_results)
    results_df.to_csv(OUTPUT_CSV_FILE, index=False)
    print(f"\nScraping complete. Master dataset saved to '{OUTPUT_CSV_FILE}'")

if __name__ == "__main__":
    main()
