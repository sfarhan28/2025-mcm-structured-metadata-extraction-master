import pandas as pd
import time
import os
import json
import re
from datetime import datetime

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, ElementClickInterceptedException, WebDriverException

# Other Imports
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager

# --- Configuration ---
URL_LIST_FILE = "websites.csv"
OUTPUT_CSV_FILE = "enhanced_gdpr_dataset-v2.4.csv"
DEBUG_HTML_DIR = "debug_html_failures"
HEADLESS_MODE = False 

# --- Helper Functions ---
def initialize_driver():
    """Sets up a robust, humanized Selenium WebDriver."""
    chrome_options = Options()
    if HEADLESS_MODE:
        chrome_options.add_argument("--headless=new")
    
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--log-level=3")

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': "Object.defineProperty(navigator, 'webdriver', { get: () => undefined })"
        })
        return driver
    except Exception as e:
        print(f"FATAL: Could not initialize WebDriver: {e}")
        return None

def save_debug_html(driver, url, stage):
    if not os.path.exists(DEBUG_HTML_DIR): os.makedirs(DEBUG_HTML_DIR)
    filename = re.sub(r'[^a-zA-Z0-9]', '_', url) + f"_FAIL_AT_{stage}.html"
    try:
        with open(os.path.join(DEBUG_HTML_DIR, filename), 'w', encoding='utf-8') as f: f.write(driver.page_source)
    except Exception as e: print(f"Could not save debug file: {e}")

def find_consent_banner(driver):
    banner_selectors = [
        (By.ID, "onetrust-banner-sdk"), (By.ID, "CybotCookiebotDialog"),
        (By.ID, "trustarc-banner"), (By.ID, "qc-cmp2-container"),
        (By.XPATH, "//*[div[contains(text(),'uses cookies')]]"),
        (By.CSS_SELECTOR, "div[class*='consent'], div[id*='consent']"),
        (By.CSS_SELECTOR, "div[aria-modal='true'][role='dialog']")
    ]
    for by, selector in banner_selectors:
        try:
            return WebDriverWait(driver, 2).until(EC.visibility_of_element_located((by, selector)))
        except TimeoutException: continue
    return None

def intelligent_button_finder(driver, banner_element, data):
    """Vastly improved button finder to address interaction failures."""
    try:
        # Higher weight for exact matches, broader keyword set
        positive_keywords = {
            'cookie settings': 10, 'manage preferences': 9, 'manage settings': 9, 'adjust my preferences': 9,
            'manage': 6, 'settings': 6, 'preferences': 6, 'options': 5, 'customize': 5, 'customise': 5
        }
        negative_keywords = ['accept', 'agree', 'allow', 'confirm', 'ok', 'got it', 'reject', 'decline', 'deny', 'necessary']
        
        # Broader search including links and elements with button roles
        buttons = banner_element.find_elements(By.XPATH, ".//button | .//a")
        if not buttons:
            data["error_log"].append("No buttons or links found in banner."); return False

        button_scores = {}
        for i, button in enumerate(buttons):
            try:
                text = (button.text or button.get_attribute('textContent') or button.get_attribute('aria-label') or "").lower().strip()
                if not text or not button.is_displayed(): continue
                
                if any(keyword in text for keyword in negative_keywords): button_scores[i] = -100; continue
                
                score = sum(value for keyword, value in positive_keywords.items() if keyword in text)
                if len(text.split()) <= 3: score += 2
                button_scores[i] = score
            except Exception: continue

        if not button_scores or max(button_scores.values()) <= 0:
            data["error_log"].append("No suitable settings button found."); return False

        best_button = buttons[max(button_scores, key=button_scores.get)]
        button_text = (best_button.text or best_button.get_attribute('textContent')).strip()
        print(f" -> Clicking settings button: '{button_text}'")
        data["settings_button_present"] = True; data["settings_button_text"] = button_text
        
        try: # Attempt multiple click methods for robustness
            driver.execute_script("arguments[0].scrollIntoView(true);", best_button)
            time.sleep(0.5)
            best_button.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", best_button) # JS fallback
        
        data["preference_center_accessed"] = True
        return True
    except Exception as e:
        data["error_log"].append(f"Button interaction failed: {type(e).__name__}"); return False

def identify_cmp_vendor(driver):
    """Identifies the CMP vendor to route to the correct parser."""
    page_source = driver.page_source.lower()
    if 'onetrust' in page_source or 'ot-sdk' in page_source: return "OneTrust"
    if 'cookiebot' in page_source or 'cybot' in page_source: return "Cookiebot"
    if 'trustarc' in page_source: return "TrustArc"
    if 'quantcast' in page_source: return "Quantcast"
    if 'iab' in page_source and 'cmp' in page_source: return "IAB_Framework"
    return "Unknown/Custom"

# --- CMP-SPECIFIC PARSING LOGIC ---
def _parse_onetrust(soup, data):
    purposes_list = []
    # OneTrust uses these specific classes
    for item in soup.select('div.ot-cat-item'):
        title_el = item.select_one('h4.ot-cat-header')
        title = title_el.get_text(strip=True) if title_el else "OT_Title_Fail"
        
        checkbox = item.select_one('input[type="checkbox"]')
        is_ticked = 'checked' in str(checkbox) if checkbox else False
        is_disabled = 'disabled' in str(checkbox) if checkbox else False
        is_always_active = 'always active' in item.get_text().lower() or is_disabled
        
        purposes_list.append({"title": title, "is_strictly_necessary": is_always_active, "is_ticked_by_default": is_ticked})
    return purposes_list

def _parse_cookiebot(soup, data):
    purposes_list = []
    # Cookiebot often uses tables
    for row in soup.select('tr[data-cookie-type]'):
        cells = row.select('td')
        if len(cells) > 1:
            title = cells[0].get_text(strip=True)
            checkbox = row.select_one('input[type="checkbox"]')
            is_ticked = checkbox and checkbox.has_attr('checked')
            is_strictly_necessary = "necessary" in row['data-cookie-type'].lower()
            
            purposes_list.append({"title": title, "is_strictly_necessary": is_strictly_necessary, "is_ticked_by_default": bool(is_ticked)})
    return purposes_list

def _parse_generic(soup, data):
    # Fallback parser if vendor is not recognized
    purposes_list = []
    for item in soup.select('div[class*="purpose"], div[class*="category"], li[class*="item"]'):
        title = item.find(['h3','h4','label','span'], text=True)
        title = title.get_text(strip=True) if title else "Generic_Title_Fail"
        checkbox = item.find('input', type='checkbox')
        is_ticked = checkbox and checkbox.has_attr('checked')
        is_disabled = checkbox and checkbox.has_attr('disabled')
        is_always_active = is_disabled or "always active" in item.get_text().lower()
        purposes_list.append({"title": title, "is_strictly_necessary": is_always_active, "is_ticked_by_default": is_ticked})
    return purposes_list

def extract_and_parse_purposes(driver, data, cmp_vendor):
    """
    Main extraction function. Captures full text and routes to the correct
    CMP-specific parser based on the identified vendor.
    """
    try:
        # Wait for preference center to appear and get its container
        pc_container = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, 
                "div[id*='pc-container'], div[class*='pc-container'], #ot-pc-desc, "
                "div#CybotCookiebotDialogBody, div[class*='preference'], div[role='dialog']"
            ))
        )
        # Capture the comprehensive legal text (this part works well)
        data["legal_text_summary"] += "\n\n--- PREFERENCE CENTER TEXT ---\n" + ' '.join(pc_container.text.splitlines())
        
        # Interactive part: click tabs for OneTrust if they exist
        if cmp_vendor == "OneTrust":
            headers = pc_container.find_elements(By.CSS_SELECTOR, "h4.ot-cat-header button")
            for header in headers:
                try: driver.execute_script("arguments[0].click();", header); time.sleep(0.5)
                except Exception: continue
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # --- ROUTER TO VENDOR-SPECIFIC PARSER ---
        if cmp_vendor == "OneTrust":
            purposes_list = _parse_onetrust(soup, data)
        elif cmp_vendor == "Cookiebot":
            purposes_list = _parse_cookiebot(soup, data)
        else:
            purposes_list = _parse_generic(soup, data) # Fallback

        unique_purposes = list({p['title']: p for p in purposes_list if "Fail" not in p['title'] and p['title']}.values())
        data["purposes_json"] = json.dumps(unique_purposes)
        
        for p in unique_purposes:
            if p["is_strictly_necessary"]: data["strictly_necessary_count"] += 1
            elif p["is_ticked_by_default"]: data["pre_ticked_non_essential_count"] += 1
        
        data["total_purposes_count"] = len(unique_purposes)
        data["status"] = "Success" if data["total_purposes_count"] > 0 else "Partial (No purposes parsed)"
        if data["status"] == "Partial (No purposes parsed)":
             data["error_log"].append(f"Parser '{cmp_vendor}' found 0 items.")
             save_debug_html(driver, data['url'], f"parse_fail_{cmp_vendor}")

    except Exception as e:
        data["error_log"].append(f"Preference extraction failed: {type(e).__name__}")
        save_debug_html(driver, data['url'], "preference_extraction_error")

def main_scraper_workflow(driver, url):
    """Main workflow now includes CMP identification and routing."""
    data = {
        "url": url, "timestamp": datetime.now().isoformat(), "status": "Pending", "cmp_vendor": "N/A",
        "settings_button_present": False, "settings_button_text": "", "preference_center_accessed": False,
        "total_purposes_count": 0, "pre_ticked_non_essential_count": 0, "strictly_necessary_count": 0,
        "purposes_json": "[]", "legal_text_summary": "", "error_log": []
    }

    try:
        driver.get(url)
        WebDriverWait(driver, 30).until(lambda d: d.execute_script('return document.readyState') == 'complete')
        time.sleep(5)
        
        banner = find_consent_banner(driver)
        if not banner:
            data["status"] = "Failed"; data["error_log"].append("Consent banner not found."); return data
            
        data["legal_text_summary"] = ' '.join(banner.text.splitlines())
        cmp_vendor = identify_cmp_vendor(driver)
        data["cmp_vendor"] = cmp_vendor
        
        if intelligent_button_finder(driver, banner, data):
            extract_and_parse_purposes(driver, data, cmp_vendor)
        else:
            data["status"] = "Partial (Interaction Failed)"

    except WebDriverException as e:
        data["status"] = "Failed"; data["error_log"].append(f"WebDriverException: {str(e)[:100]}")
    except Exception as e:
        data["status"] = "Failed"; data["error_log"].append(f"Critical error: {type(e).__name__}")
    
    data["error_log"] = json.dumps(data["error_log"])
    return data

def main():
    try:
        urls = pd.read_csv(URL_LIST_FILE)['url'].dropna().unique().tolist()
    except FileNotFoundError: print(f"FATAL: Input file '{URL_LIST_FILE}' not found."); return

    driver = initialize_driver()
    if not driver: return
    
    all_results = []
    if os.path.exists(OUTPUT_CSV_FILE):
        results_df = pd.read_csv(OUTPUT_CSV_FILE); all_results = results_df.to_dict('records')
        processed_urls = set(results_df['url']); urls = [u for u in urls if u not in processed_urls]
        print(f"Resuming scan. {len(processed_urls)} URLs already processed. {len(urls)} new URLs to scan.")

    for i, url in enumerate(urls, 1):
        print(f"\n--- Processing ({i}/{len(urls)}): {url} ---")
        result = main_scraper_workflow(driver, url)
        all_results.append(result)
        
        print(f"Status: {result.get('status', 'Unknown')} | CMP: {result.get('cmp_vendor', 'N/A')}")
        if result.get('total_purposes_count', 0) > 0: print(f" -> Extracted {result['total_purposes_count']} purposes.")
        if result.get('error_log') != '[]': print(f" -> Log: {result['error_log']}")
        
        if i % 10 == 0: pd.DataFrame(all_results).to_csv(OUTPUT_CSV_FILE, index=False); print(" -> Progress saved.")

    driver.quit()
    pd.DataFrame(all_results).to_csv(OUTPUT_CSV_FILE, index=False)
    print(f"\nScraping complete. Final dataset saved to '{OUTPUT_CSV_FILE}'")

if __name__ == "__main__":
    main()

