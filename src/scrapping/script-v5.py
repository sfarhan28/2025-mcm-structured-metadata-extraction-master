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
OUTPUT_CSV_FILE = "gdpr_master_dataset-v5.csv"
DEBUG_HTML_DIR = "debug_html_failures"
# CRITICAL: Forcing headful mode is a key anti-detection strategy.
# Set to True only after confirming functionality.
HEADLESS_MODE = False

# --- Helper Functions ---
def initialize_driver():
    """Sets up a robust, humanized Selenium WebDriver."""
    chrome_options = Options()
    if HEADLESS_MODE: chrome_options.add_argument("--headless")
    
    # --- KEY ANTI-BOT EVASION TECHNIQUES ---
    # 1. Disables the "Chrome is being controlled by automated test software" infobar
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    # 2. Sets a common, modern user-agent
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")

    chrome_options.add_argument("--window-size=1920,1080"); chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--no-sandbox"); chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--log-level=3")
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        # 3. Hides the navigator.webdriver flag
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                  get: () => undefined
                })
            '''
        })
        return driver
    except Exception as e:
        print(f"FATAL: Could not initialize WebDriver: {e}"); return None

def get_shadow_root(driver, host_element):
    try: return driver.execute_script('return arguments[0].shadowRoot', host_element)
    except Exception: return None

def save_debug_html(driver, url, stage):
    if not os.path.exists(DEBUG_HTML_DIR): os.makedirs(DEBUG_HTML_DIR)
    filename = re.sub(r'[^a-zA-Z0-9]', '_', url) + f"_FAIL_AT_{stage}.html"
    with open(os.path.join(DEBUG_HTML_DIR, filename), 'w', encoding='utf-8') as f: f.write(driver.page_source)

# --- EXPERT HANDLER ---
def handle_onetrust_expert(driver, data):
    """Specialized handler for OneTrust with anti-evasion waits."""
    try:
        banner_root = WebDriverWait(driver, 10).until(
            lambda d: get_shadow_root(d, d.find_element(By.ID, "onetrust-banner-sdk")))
        if not banner_root: return False
        
        settings_button = banner_root.find_element(By.CSS_SELECTOR, "#onetrust-pc-btn-handler")
        data["settings_button_present"] = True
        driver.execute_script("arguments[0].click();", settings_button)
        data["preference_center_accessed"] = True
        
        pc_root = WebDriverWait(driver, 10).until(
            lambda d: get_shadow_root(d, d.find_element(By.ID, "onetrust-pc-sdk")))
        if not pc_root: return False

        pc_html = pc_root.get_attribute('innerHTML')
        pc_soup = BeautifulSoup(pc_html, 'html.parser')
        
        purpose_items = pc_soup.select('.ot-cat-item')
        if not purpose_items:
            data["error_log"].append("Expert: Parsed PC Shadow DOM, but found no .ot-cat-item containers.")
            save_debug_html(driver, data['url'], "expert_parsing")
            return False

        purposes_list = []
        for item in purpose_items:
            title_element = item.find(class_='ot-cat-header')
            title = title_element.get_text(strip=True) if title_element else "Title Not Found"
            is_always_active = 'ot-always-active' in (item.find(class_='ot-cat-header-wrapper').get('class', []) if item.find(class_='ot-cat-header-wrapper') else [])
            is_ticked = item.find('input', type='checkbox').has_attr('checked') if item.find('input', type='checkbox') else False
            purposes_list.append({"title": title, "is_strictly_necessary": is_always_active, "is_ticked_by_default": is_ticked})
            if is_always_active: data["strictly_necessary_count"] += 1
            elif is_ticked: data["pre_ticked_non_essential_count"] += 1
        
        data["total_purposes_count"] = len(purposes_list)
        data["purposes_json"] = json.dumps(purposes_list)
        data["status"] = "Success (Expert)"
        return True
    except Exception as e:
        data["error_log"].append(f"Expert Handler Failed: {type(e).__name__}"); return False

# --- GENERALIST HANDLER (UPGRADED PARSING) ---
def handle_generic_robust(driver, data):
    """A robust, interactive handler with aggressive parsing."""
    try:
        banner_selectors = ["div[role='dialog']", "div[id*='cookie']", "div[class*='consent']", "div[class*='banner']"]
        banner = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ", ".join(banner_selectors))))
        data["initial_banner_found"] = True

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
            time.sleep(2)
        except (NoSuchElementException, TimeoutException):
            data["status"] = "Partial (No Settings Button)"; data["error_log"].append("Generic: Banner found but no interactive settings path.")
            return

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        purpose_selectors = ['.ot-cat-item', 'div[class*="purpose-item"]', 'div.category-group', 'div.uc-list-container']
        purpose_items = soup.select(','.join(purpose_selectors))
        if not purpose_items:
            data["status"] = "Partial (No Purposes Found After Click)"; data["error_log"].append("Generic: Accessed secondary view, but could not parse purpose containers.")
            save_debug_html(driver, data['url'], "generic_parsing")
            return

        purposes_list = []
        for item in purpose_items:
            # --- AGGRESSIVE TITLE PARSING ---
            title_element = item.find(['h3', 'h4', 'h5', 'span'], class_=lambda c: c and ('header' in c or 'title' in c or 'heading' in c))
            title = title_element.get_text(strip=True) if title_element else item.find('label').get_text(strip=True) if item.find('label') else "Title Not Found"
            
            is_ticked = item.find('input', type='checkbox').has_attr('checked') if item.find('input', type='checkbox') else False
            # --- MORE ROBUST 'ALWAYS ACTIVE' DETECTION ---
            is_disabled = item.find('input', type='checkbox').has_attr('disabled') if item.find('input', type='checkbox') else False
            is_always_active = is_disabled or (title.lower().startswith("strictly necessary"))
            
            purposes_list.append({"title": title, "is_strictly_necessary": is_always_active, "is_ticked_by_default": is_ticked})
            if is_always_active: data["strictly_necessary_count"] += 1
            elif is_ticked: data["pre_ticked_non_essential_count"] += 1

        data["total_purposes_count"] = len(purposes_list); data["purposes_json"] = json.dumps(purposes_list); data["status"] = "Success (Generic)"

    except Exception as e:
        data["error_log"].append(f"Generic Handler Failed: {type(e).__name__}"); data["status"] = "Failed"

# --- MAIN WORKFLOW & DISPATCHER ---
def main_scraper_workflow(driver, url):
    # (Identical to previous version)
    data = {
        "url": url, "timestamp": pd.Timestamp.now().isoformat(), "status": "Pending", "cmp_vendor": "Unknown",
        "initial_banner_found": False, "accept_all_present": False, "reject_all_present": False, "settings_button_present": False,
        "preference_center_accessed": False, "total_purposes_count": 0, "pre_ticked_non_essential_count": 0,
        "strictly_necessary_count": 0, "purposes_json": "[]", "error_log": []
    }
    
    try:
        driver.get(url)
        WebDriverWait(driver, 20).until(lambda d: d.execute_script('return document.readyState') == 'complete')
        time.sleep(3)

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
            if detected_cmp != "Unknown": break
        data["cmp_vendor"] = detected_cmp

        if detected_cmp == 'OneTrust':
            if not handle_onetrust_expert(driver, data):
                print("  -> Expert handler failed. Falling back to generic handler.")
                handle_generic_robust(driver, data)
        else:
            if detected_cmp != "Unknown": print(f"  -> {detected_cmp} detected. Deploying generic handler...")
            else: print("  -> No known CMP detected. Deploying generic handler.")
            handle_generic_robust(driver, data)

    except TimeoutException:
        data["status"] = "Failed"; data["error_log"].append("Page failed to load within time limit.")
    except Exception as e:
        data["status"] = "Failed"; data["error_log"].append(f"Critical Workflow Error: {type(e).__name__}")
        
    return data

def main():
    # (Identical to previous version)
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
