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
OUTPUT_CSV_FILE = "gdpr_master_dataset-v4.csv"
DEBUG_HTML_DIR = "debug_html_failures"
HEADLESS_MODE = True # Set to False to watch the browser for debugging

# --- Helper Functions ---
def initialize_driver():
    """Sets up a robust Selenium WebDriver."""
    chrome_options = Options()
    if HEADLESS_MODE: chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080"); chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--no-sandbox"); chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36")
    try:
        return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    except Exception as e:
        print(f"FATAL: Could not initialize WebDriver: {e}"); return None

def get_shadow_root(driver, host_element):
    """Safely gets the shadow root of an element."""
    try: return driver.execute_script('return arguments[0].shadowRoot', host_element)
    except Exception: return None

def save_debug_html(driver, url, stage):
    """Saves the current page source on failure for offline analysis."""
    if not os.path.exists(DEBUG_HTML_DIR): os.makedirs(DEBUG_HTML_DIR)
    filename = re.sub(r'[^a-zA-Z0-9]', '_', url) + f"_FAIL_AT_{stage}.html"
    with open(os.path.join(DEBUG_HTML_DIR, filename), 'w', encoding='utf-8') as f: f.write(driver.page_source)

# --- EXPERT HANDLER ---
def handle_onetrust_expert(driver, data):
    """Specialized handler for OneTrust, capable of piercing Shadow DOM."""
    try:
        shadow_host = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "onetrust-banner-sdk")))
        banner_root = get_shadow_root(driver, shadow_host)
        if not banner_root:
            data["error_log"].append("Expert: OneTrust host found, but Shadow DOM inaccessible.")
            return False # Signal failure

        # Interact with elements INSIDE the Shadow DOM
        settings_button = banner_root.find_element(By.CSS_SELECTOR, "#onetrust-pc-btn-handler")
        data["settings_button_present"] = True
        driver.execute_script("arguments[0].click();", settings_button)
        data["preference_center_accessed"] = True
        
        pc_host = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "onetrust-pc-sdk")))
        pc_root = get_shadow_root(driver, pc_host)
        if not pc_root:
            data["error_log"].append("Expert: OneTrust PC Shadow DOM inaccessible.")
            return False

        pc_html = driver.execute_script('return arguments[0].innerHTML', pc_root)
        pc_soup = BeautifulSoup(pc_html, 'html.parser')
        
        purpose_items = pc_soup.select('.ot-cat-item')
        if not purpose_items:
            data["error_log"].append("Expert: Parsed PC Shadow DOM, but found no .ot-cat-item containers.")
            save_debug_html(driver, data['url'], "expert_parsing")
            return False

        purposes_list = []
        for item in purpose_items:
            title = (item.find(class_='ot-cat-header').get_text(strip=True) if item.find(class_='ot-cat-header') else "Title Not Found")
            is_always_active = 'ot-always-active' in (item.find(class_='ot-cat-header-wrapper').get('class', []) if item.find(class_='ot-cat-header-wrapper') else [])
            is_ticked = item.find('input', type='checkbox').has_attr('checked') if item.find('input', type='checkbox') else False
            purposes_list.append({"title": title, "is_strictly_necessary": is_always_active, "is_ticked_by_default": is_ticked})
            if is_always_active: data["strictly_necessary_count"] += 1
            elif is_ticked: data["pre_ticked_non_essential_count"] += 1
        
        data["total_purposes_count"] = len(purposes_list)
        data["purposes_json"] = json.dumps(purposes_list)
        data["status"] = "Success (Expert)"
        return True # Signal success
    except Exception as e:
        data["error_log"].append(f"Expert Handler Failed: {type(e).__name__}")
        return False

# --- GENERALIST HANDLER ---
def handle_generic_robust(driver, data):
    """A robust, interactive handler for any banner, inspired by the script for consent_analysis_4.csv."""
    try:
        # Step 1: Find the main banner using broad heuristics
        banner_selectors = ["div[role='dialog']", "div[id*='cookie']", "div[class*='consent']", "div[class*='banner']"]
        banner = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ", ".join(banner_selectors))))
        data["initial_banner_found"] = True

        # Step 2: Use resilient XPath to find buttons within the banner
        accept_xpath = ".//button[contains(translate(., 'ACDEGIKLNOPRSTUWY', 'acdegiklnoprstuwy'), 'accept') or contains(translate(., 'ACDEGIKLNOPRSTUWY', 'acdegiklnoprstuwy'), 'allow') or contains(translate(., 'ACDEGIKLNOPRSTUWY', 'acdegiklnoprstuwy'), 'agree')]"
        reject_xpath = ".//button[contains(translate(., 'CDEIJLNORSTUY', 'cdeijlnorstuy'), 'reject') or contains(translate(., 'CDEIJLNORSTUY', 'cdeijlnorstuy'), 'decline') or contains(translate(., 'CDEIJLNORSTUY', 'cdeijlnorstuy'), 'necessary')]"
        settings_xpath = ".//button[contains(translate(., 'AEGIMNST', 'aegimnst'), 'setting') or contains(translate(., 'AEGIMNST', 'aegimnst'), 'manage') or contains(translate(., 'AEGIMNST', 'aegimnst'), 'customize') or contains(translate(., 'AEGIMNST', 'aegimnst'), 'options')]"
        
        data["accept_all_present"] = bool(banner.find_elements(By.XPATH, accept_xpath))
        data["reject_all_present"] = bool(banner.find_elements(By.XPATH, reject_xpath))
        
        try:
            settings_button = banner.find_element(By.XPATH, settings_xpath)
            data["settings_button_present"] = True
            driver.execute_script("arguments[0].click();", settings_button)
            data["preference_center_accessed"] = True
            # Wait for a change. A simple pause is often the most reliable way after a JS click.
            time.sleep(2)
        except (NoSuchElementException, TimeoutException):
            data["status"] = "Partial (No Settings Button)"
            data["error_log"].append("Generic: Banner found but no interactive settings path.")
            return

        # Step 3: Re-parse the ENTIRE page and look for purpose details
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        purpose_selectors = ['.ot-cat-item', 'div[class*="purpose-item"]', 'div.category-group', 'div.uc-list-container']
        purpose_items = soup.select(','.join(purpose_selectors))
        if not purpose_items:
            data["status"] = "Partial (No Purposes Found After Click)"
            data["error_log"].append("Generic: Accessed secondary view, but could not parse purpose containers.")
            save_debug_html(driver, data['url'], "generic_parsing")
            return

        purposes_list = []
        for item in purpose_items:
            title_element = item.find(['h3', 'h4', 'h5', 'span'], class_=lambda c: c and ('header' in c or 'title' in c))
            title = title_element.get_text(strip=True) if title_element else "Title Not Found"
            is_ticked = item.find('input', type='checkbox').has_attr('checked') if item.find('input', type='checkbox') else False
            is_always_active = 'always-active' in ' '.join(item.get('class', [])) or (title.lower() == "strictly necessary")
            
            purposes_list.append({"title": title, "is_strictly_necessary": is_always_active, "is_ticked_by_default": is_ticked})
            if is_always_active: data["strictly_necessary_count"] += 1
            elif is_ticked: data["pre_ticked_non_essential_count"] += 1

        data["total_purposes_count"] = len(purposes_list)
        data["purposes_json"] = json.dumps(purposes_list)
        data["status"] = "Success (Generic)"

    except Exception as e:
        data["error_log"].append(f"Generic Handler Failed: {type(e).__name__}")
        data["status"] = "Failed"

# --- MAIN WORKFLOW ---
def main_scraper_workflow(driver, url):
    """The main workflow that orchestrates the scraping process."""
    data = {
        "url": url, "timestamp": pd.Timestamp.now().isoformat(), "status": "Pending", "cmp_vendor": "Unknown",
        "initial_banner_found": False, "accept_all_present": False, "reject_all_present": False, "settings_button_present": False,
        "preference_center_accessed": False, "total_purposes_count": 0, "pre_ticked_non_essential_count": 0,
        "strictly_necessary_count": 0, "purposes_json": "[]", "error_log": []
    }
    
    try:
        driver.get(url)
        WebDriverWait(driver, 20).until(lambda d: d.execute_script('return document.readyState') == 'complete')
        time.sleep(3) # Generous wait for all scripts to load and banners to appear

        # --- CMP Detection Logic (from your reference script) ---
        cmp_indicators = {
            'OneTrust': ['#onetrust-banner-sdk', '[id*="onetrust"]'],
            'Cookiebot': ['#CybotCookiebotDialog', '[id*="cookiebot"]'],
            'Quantcast': ['#qc-cmp2-container', '[class*="qc-cmp"]'],
            'TrustArc': ['#truste-consent-track', '[class*="truste_"]'],
            'CookieLaw': ['#cookie-law-info-bar', '[class*="cli-bar"]']
        }
        
        detected_cmp = "Unknown"
        for vendor, selectors in cmp_indicators.items():
            for selector in selectors:
                if driver.find_elements(By.CSS_SELECTOR, selector):
                    detected_cmp = vendor
                    break
            if detected_cmp != "Unknown":
                break
        
        data["cmp_vendor"] = detected_cmp

        # --- STRATEGIC DISPATCHER ---
        if detected_cmp == 'OneTrust':
            print(f"  -> {detected_cmp} detected. Deploying expert handler...")
            if not handle_onetrust_expert(driver, data):
                print("  -> Expert handler failed. Falling back to generic handler.")
                handle_generic_robust(driver, data)
        else:
            if detected_cmp != "Unknown":
                print(f"  -> {detected_cmp} detected. Deploying generic handler...")
            else:
                print("  -> No known CMP detected. Deploying generic handler.")
            handle_generic_robust(driver, data)

    except TimeoutException:
        data["status"] = "Failed"; data["error_log"].append("Page failed to load within time limit.")
    except Exception as e:
        data["status"] = "Failed"; data["error_log"].append(f"Critical Workflow Error: {type(e).__name__}")
        
    return data

def main():
    """Drives the entire batch scraping and saving process."""
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
        if result.get('error_log'): print(f"  - Log: {'; '.join(result['error_log'])}")

    driver.quit()
    
    pd.DataFrame(all_results).to_csv(OUTPUT_CSV_FILE, index=False)
    print(f"\nScraping complete. Master dataset saved to '{OUTPUT_CSV_FILE}'")

if __name__ == "__main__":
    main()
