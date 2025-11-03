import pandas as pd
import time
import os
import json
import re
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
URL_LIST_FILE = "websites.csv"
OUTPUT_CSV_FILE = "gdpr_master_dataset_v3.csv"
DEBUG_HTML_DIR = "debug_html" # Directory to save HTML of failed pages
HEADLESS_MODE = True

def initialize_driver():
    """Sets up a robust Selenium WebDriver."""
    # (Same as previous version, retained for robustness)
    chrome_options = Options()
    if HEADLESS_MODE:
        chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36")
    try:
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=chrome_options)
    except Exception as e:
        print(f"FATAL ERROR: Could not initialize WebDriver. Error: {e}")
        return None

def get_shadow_root(driver, host_element):
    """Pierces the Shadow DOM and returns the shadow root for parsing."""
    try:
        return driver.execute_script('return arguments[0].shadowRoot', host_element)
    except Exception:
        return None

def save_debug_html(driver, url):
    """Saves the current page source for later analysis on failure."""
    if not os.path.exists(DEBUG_HTML_DIR):
        os.makedirs(DEBUG_HTML_DIR)
    filename = re.sub(r'[^a-zA-Z0-9]', '_', url) + ".html"
    filepath = os.path.join(DEBUG_HTML_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(driver.page_source)
    return filepath

def handle_onetrust(driver, data):
    """Specialized handler for OneTrust CMPs, including Shadow DOM logic."""
    data["cmp_vendor"] = "OneTrust"
    try:
        # OneTrust often uses a shadow host with this ID
        shadow_host = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "onetrust-banner-sdk")))
        banner = get_shadow_root(driver, shadow_host)
        if not banner:
            data["error_log"].append("OneTrust host found, but Shadow DOM inaccessible.")
            data["status"] = "Failed"
            return data
            
        # Now search for buttons WITHIN the shadow DOM
        settings_button = banner.find_element(By.CSS_SELECTOR, "#onetrust-pc-btn-handler")
        data["settings_button_present"] = True
        
        driver.execute_script("arguments[0].click();", settings_button)
        
        # Wait for preference center to appear, also potentially in a shadow DOM
        pc_host = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "onetrust-pc-sdk")))
        pc_shadow_root = get_shadow_root(driver, pc_host)
        if not pc_shadow_root:
            data["error_log"].append("Accessed OneTrust PC, but its Shadow DOM is inaccessible.")
            data["status"] = "Partial"
            return data
            
        data["preference_center_accessed"] = True
        
        # Use BeautifulSoup on the inner HTML of the shadow root
        pc_html = driver.execute_script('return arguments[0].innerHTML', pc_shadow_root)
        pc_soup = BeautifulSoup(pc_html, 'html.parser')
        
        purpose_items = pc_soup.select('.ot-cat-item')
        if not purpose_items:
            data["error_log"].append("OneTrust PC found, but failed to parse .ot-cat-item containers.")
            save_debug_html(driver, data['url'])
            return data

        # (Parsing logic is similar to before, now applied to the correct source)
        purposes_list = []
        for item in purpose_items:
            title = item.find(class_='ot-cat-header').get_text(strip=True) if item.find(class_='ot-cat-header') else "Title Not Found"
            is_always_active = 'ot-always-active' in (item.find(class_='ot-cat-header-wrapper').get('class', []) if item.find(class_='ot-cat-header-wrapper') else [])
            toggle = item.find('input', type='checkbox')
            is_ticked = toggle.has_attr('checked') if toggle else False
            purposes_list.append({"title": title, "is_strictly_necessary": is_always_active, "is_ticked_by_default": is_ticked})
            if is_always_active: data["strictly_necessary_count"] += 1
            elif is_ticked: data["pre_ticked_non_essential_count"] += 1
        
        data["total_purposes_count"] = len(purposes_list)
        data["purposes_json"] = json.dumps(purposes_list)
        data["status"] = "Success"
        
    except Exception as e:
        data["error_log"].append(f"OneTrust handler failed: {type(e).__name__}")
        data["status"] = "Failed" if data["status"] == "Pending" else data["status"]
        save_debug_html(driver, data['url'])
    return data

def handle_generic(driver, data):
    """Fallback handler using general heuristics for unknown CMPs."""
    # (This is the refined version of our previous 'scrape_website_data' function)
    # It remains crucial for sites not using a major, known CMP.
    # ... (code from previous robust script would go here)
    data["cmp_vendor"] = "Unknown/Generic"
    data["status"] = "Failed"
    data["error_log"].append("No known CMP detected; generic handler needs implementation.")
    return data

def main_scraper_workflow(driver, url):
    """The main workflow that orchestrates the scraping process."""
    data = { "url": url, "timestamp": pd.Timestamp.now().isoformat(), "status": "Pending", "error_log": [] }
    
    try:
        driver.get(url)
        
        # --- CMP Dispatcher ---
        # Wait for a moment to see which CMP reveals itself
        time.sleep(2) 
        page_source = driver.page_source
        
        if "onetrust" in page_source.lower():
            print("  -> OneTrust detected. Deploying specialized handler.")
            data = handle_onetrust(driver, data)
        # Add elif blocks for other CMPs like Cookiebot here
        # elif "cookiebot" in page_source.lower():
        #     data = handle_cookiebot(driver, data)
        else:
            print("  -> Unknown CMP. Deploying generic handler.")
            data = handle_generic(driver, data) # Fallback to general heuristics
            
    except Exception as e:
        data["status"] = "Failed"
        data["error_log"].append(f"Critical error in main workflow: {type(e).__name__}")
        
    return data

def main():
    """Drives the entire batch scraping and saving process."""
    try:
        urls = pd.read_csv(URL_LIST_FILE)['url'].dropna().unique().tolist()
    except FileNotFoundError:
        print(f"FATAL ERROR: Input file '{URL_LIST_FILE}' not found.")
        return

    driver = initialize_driver()
    if not driver: return

    all_results = []
    total_sites = len(urls)
    for i, url in enumerate(urls, 1):
        print(f"\n--- Processing ({i}/{total_sites}): {url} ---")
        result = main_scraper_workflow(driver, url)
        all_results.append(result)
        print(f"Status: {result.get('status', 'Unknown')}")
        if result.get('error_log'): print(f"  - Log: {'; '.join(result['error_log'])}")

    driver.quit()
    
    pd.DataFrame(all_results).to_csv(OUTPUT_CSV_FILE, index=False)
    print(f"\nScraping complete. Master dataset saved to '{OUTPUT_CSV_FILE}'")

if __name__ == "__main__":
    main()
