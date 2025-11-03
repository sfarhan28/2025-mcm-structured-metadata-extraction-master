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
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

# Other Imports
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager
import textstat # For readability scores. Install with: pip install textstat

# --- Configuration ---
URL_LIST_FILE = "websites.csv"
OUTPUT_CSV_FILE = "enhanced_gdpr_dataset-v2.csv"
DEBUG_HTML_DIR = "debug_html_failures"
HEADLESS_MODE = False # Keep False for debugging, set to True for production runs

# --- Helper Functions ---

def initialize_driver():
    """Sets up a robust, humanized Selenium WebDriver."""
    chrome_options = Options()
    if HEADLESS_MODE:
        chrome_options.add_argument("--headless=new")
    
    # Anti-Bot Evasion Techniques
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--log-level=3")

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        # Hide navigator.webdriver flag
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': "Object.defineProperty(navigator, 'webdriver', { get: () => undefined })"
        })
        return driver
    except Exception as e:
        print(f"FATAL: Could not initialize WebDriver: {e}")
        return None

def save_debug_html(driver, url, stage):
    """Saves page source on failure for offline analysis."""
    if not os.path.exists(DEBUG_HTML_DIR):
        os.makedirs(DEBUG_HTML_DIR)
    filename = re.sub(r'[^a-zA-Z0-9]', '_', url) + f"_FAIL_AT_{stage}.html"
    try:
        with open(os.path.join(DEBUG_HTML_DIR, filename), 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
    except Exception as e:
        print(f"Could not save debug file: {e}")

def find_consent_banner(driver):
    """Finds the cookie consent banner using a list of common selectors."""
    banner_selectors = [
        (By.ID, "onetrust-banner-sdk"),
        (By.ID, "CybotCookiebotDialog"),
        (By.CSS_SELECTOR, "div[id*='cookie']"),
        (By.CSS_SELECTOR, "div[class*='cookie']"),
        (By.CSS_SELECTOR, "div[id*='consent']"),
        (By.CSS_SELECTOR, "div[class*='consent']"),
        (By.CSS_SELECTOR, "div[aria-modal='true'][role='dialog']"),
        (By.XPATH, "//*[contains(text(), 'uses cookies')]")
    ]
    for by, selector in banner_selectors:
        try:
            banner = WebDriverWait(driver, 2).until(
                EC.visibility_of_element_located((by, selector))
            )
            return banner
        except TimeoutException:
            continue
    return None
    
def identify_cmp_vendor(banner_element):
    """Identifies the CMP vendor based on element attributes."""
    if not banner_element:
        return "Unknown/Custom"
    
    # Check attributes of the banner itself
    banner_html = banner_element.get_attribute('outerHTML').lower()
    if 'onetrust' in banner_html: return "OneTrust"
    if 'cybot' in banner_html or 'cookiebot' in banner_html: return "Cookiebot"
    if 'trustarc' in banner_html: return "TrustArc"
    if 'quantcast' in banner_html: return "Quantcast"
    
    return "Unknown/Custom"

def analyze_legal_text(text):
    """Performs basic NLP and heuristic analysis on the legal text."""
    analysis = {
        'data_retention_mentioned': False,
        'user_rights_mentioned': False,
        'legitimate_interest_present': False,
        'legal_readability_score': 0.0
    }
    if not text:
        return analysis

    text_lower = text.lower()
    analysis['data_retention_mentioned'] = bool(re.search(r'retain|retention|store for', text_lower))
    analysis['user_rights_mentioned'] = bool(re.search(r'your rights|right to access|right to erase', text_lower))
    analysis['legitimate_interest_present'] = 'legitimate interest' in text_lower
    
    try:
        # Flesch-Kincaid Grade Level is a good proxy for readability
        analysis['legal_readability_score'] = textstat.flesch_kincaid_grade(text)
    except:
        analysis['legal_readability_score'] = 0.0 # Default on error
        
    return analysis

def intelligent_button_finder(driver, banner_element, data):
    """More robustly finds and clicks the most likely settings/preferences button."""
    try:
        # Expanded keywords with higher weights for more specific terms
        positive_keywords = {
            'manage': 6, 'settings': 6, 'preferences': 6, 'options': 5,
            'customize': 5, 'customise': 5, 'configure': 4, 
            'more info': 3, 'details': 2, 'learn more': 2
        }
        negative_keywords = ['accept', 'agree', 'allow', 'confirm', 'ok', 'got it', 'reject', 'decline', 'deny', 'necessary']

        buttons = banner_element.find_elements(By.XPATH, ".//button | .//a[@role='button']")
        if not buttons:
            data["error_log"].append("No buttons or link-buttons found in banner.")
            return False

        button_scores = {}
        for i, button in enumerate(buttons):
            try:
                text = (button.text or button.get_attribute('aria-label') or "").lower().strip()
                if not text or not button.is_displayed() or not button.is_enabled():
                    continue

                # Heavily penalize negative keywords
                if any(keyword in text for keyword in negative_keywords):
                    button_scores[i] = -100
                    continue
                
                # Score based on positive keywords
                score = 0
                for keyword, value in positive_keywords.items():
                    if keyword in text:
                        score += value
                
                # Bonus for shorter, more specific buttons
                if len(text.split()) <= 3:
                    score += 2
                    
                button_scores[i] = score
            except Exception:
                continue

        if not button_scores or max(button_scores.values()) <= 0:
            data["error_log"].append("No suitable settings/preferences button found.")
            return False

        best_button_index = max(button_scores, key=button_scores.get)
        best_button = buttons[best_button_index]
        
        print(f" -> Clicking settings button: '{best_button.text}' (Score: {button_scores[best_button_index]})")
        data["settings_button_present"] = True
        data["settings_button_text"] = best_button.text
        
        driver.execute_script("arguments[0].scrollIntoView(true);", best_button)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", best_button)
        
        data["preference_center_accessed"] = True
        time.sleep(3)  # Wait for modal/page to update
        return True

    except Exception as e:
        data["error_log"].append(f"Button interaction failed: {type(e).__name__}")
        save_debug_html(driver, data['url'], "button_interaction")
        return False

def extract_preferences_data(driver, data):
    """Extracts detailed data from the preference center."""
    try:
        # A more generic wait for any kind of preference center content
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[id*='pc-'], div[class*='-pc-'], div[id*='preferences'], div[class*='preferences']"))
        )
        soup = BeautifulSoup(driver.page_source, 'html.parser')
    except TimeoutException:
        data["error_log"].append("Preference center content did not load.")
        save_debug_html(driver, data['url'], "preference_center_load")
        return

    purposes_list = []
    # Generic selectors for purpose items
    purpose_containers = soup.select('div[class*="category"], div[class*="purpose"], tr[class*="consent-"], li[role="tab"]')

    if not purpose_containers:
        data["error_log"].append("No purpose containers found in preference center.")
        save_debug_html(driver, data['url'], "purpose_extraction")
        return

    for item in purpose_containers:
        title_el = item.find(['h3', 'h4', 'h5', 'h6', 'span', 'label'], text=True)
        title = title_el.get_text(strip=True) if title_el else "Title Not Found"
        
        checkbox = item.find('input', type='checkbox')
        is_ticked = checkbox and checkbox.has_attr('checked')
        is_disabled = checkbox and checkbox.has_attr('disabled')
        
        is_strictly_necessary = is_disabled or 'strictly necessary' in title.lower() or 'always active' in (item.get_text().lower())

        purposes_list.append({
            "title": title,
            "is_strictly_necessary": is_strictly_necessary,
            "is_ticked_by_default": bool(is_ticked)
        })

        if is_strictly_necessary:
            data["strictly_necessary_count"] += 1
        elif is_ticked:
            data["pre_ticked_non_essential_count"] += 1
    
    data["total_purposes_count"] = len(purposes_list)
    data["purposes_json"] = json.dumps(purposes_list) if purposes_list else "[]"
    
    # Vendor Count Extraction
    vendor_link = driver.find_elements(By.XPATH, "//*[contains(translate(text(),'V','v'),'vendor') or contains(translate(text(),'P','p'),'partner')]")
    if vendor_link:
        try:
            # Simple count; more advanced logic could click and count from a new view
            data["vendor_count"] = len(soup.select('[class*="vendor-"], [class*="partner-"]'))
        except Exception:
            data["vendor_count"] = -1 # Indicates link was found but counting failed
    
    if data["total_purposes_count"] > 0:
        data["status"] = "Success"
    else:
        data["status"] = "Partial (No purposes parsed)"
        
def perform_final_analysis(data):
    """Calculates heuristic scores based on extracted data."""
    # Dark Pattern Score (lower is better)
    dark_pattern_score = 0
    if not data["reject_all_present"]: dark_pattern_score += 3
    if not data["settings_button_present"]: dark_pattern_score += 2
    if data["pre_ticked_non_essential_count"] > 0: dark_pattern_score += 5
    data["dark_pattern_score"] = dark_pattern_score

    # Granular Control Check
    data["has_granular_control"] = data["preference_center_accessed"] and data["total_purposes_count"] > 1
    
    # Placeholder for more complex scores
    data["compliance_score"] = 0.0 # Requires complex rule engine or ML model
    data["gdpr_article_13_compliance"] = False # Requires deep text analysis beyond summary

def main_scraper_workflow(driver, url):
    """Main workflow to navigate, find banner, interact, and extract data."""
    # Initialize a dictionary with all target columns
    data = {
        "url": url, "timestamp": datetime.now().isoformat(), "status": "Pending",
        "cmp_vendor": "N/A", "initial_banner_found": False,
        "accept_all_present": False, "reject_all_present": False,
        "settings_button_present": False, "settings_button_text": "",
        "preference_center_accessed": False, "total_purposes_count": 0,
        "pre_ticked_non_essential_count": 0, "strictly_necessary_count": 0,
        "purposes_json": "[]", "vendor_count": 0, "legal_text_summary": "",
        "data_retention_mentioned": False, "user_rights_mentioned": False,
        "legitimate_interest_present": False, "dark_pattern_score": 0,
        "legal_readability_score": 0.0, "has_granular_control": False,
        "compliance_score": 0.0, "gdpr_article_13_compliance": False,
        "error_log": []
    }

    try:
        driver.get(url)
        WebDriverWait(driver, 25).until(lambda d: d.execute_script('return document.readyState') == 'complete')
        time.sleep(4) # Generous wait for dynamic content/banners to appear
        
        banner = find_consent_banner(driver)
        if not banner:
            data["status"] = "Failed"
            data["error_log"].append("Consent banner not found.")
            save_debug_html(driver, url, "banner_not_found")
            return data
            
        data["initial_banner_found"] = True
        data["cmp_vendor"] = identify_cmp_vendor(banner)
        
        # Extract initial banner data
        banner_text = banner.text
        data["legal_text_summary"] = ' '.join(banner_text.splitlines())
        
        # Simple button presence checks
        banner_text_lower = banner_text.lower()
        data["accept_all_present"] = any(kw in banner_text_lower for kw in ['accept all', 'allow all', 'agree to all'])
        data["reject_all_present"] = any(kw in banner_text_lower for kw in ['reject all', 'deny all', 'necessary only'])
        
        # Analyze legal text for keywords
        legal_analysis = analyze_legal_text(data["legal_text_summary"])
        data.update(legal_analysis)

        if intelligent_button_finder(driver, banner, data):
            extract_preferences_data(driver, data)
        else:
            data["status"] = "Partial (Interaction Failed)"

    except TimeoutException:
        data["status"] = "Failed"
        data["error_log"].append("Page load timed out.")
    except WebDriverException as e:
        data["status"] = "Failed"
        data["error_log"].append(f"WebDriverException: {str(e)[:100]}")
    except Exception as e:
        data["status"] = "Failed"
        data["error_log"].append(f"Critical error: {type(e).__name__}")
        save_debug_html(driver, url, "critical_error")
    
    perform_final_analysis(data)
    # Convert error log to a string for CSV
    data["error_log"] = json.dumps(data["error_log"])
    return data

def main():
    try:
        urls = pd.read_csv(URL_LIST_FILE)['url'].dropna().unique().tolist()
    except FileNotFoundError:
        print(f"FATAL: Input file '{URL_LIST_FILE}' not found. Please create it with a 'url' column.")
        return

    driver = initialize_driver()
    if not driver:
        return

    all_results = []
    for i, url in enumerate(urls, 1):
        print(f"\n--- Processing ({i}/{len(urls)}): {url} ---")
        result = main_scraper_workflow(driver, url)
        all_results.append(result)
        print(f"Status: {result.get('status', 'Unknown')}")
        if result.get('total_purposes_count', 0) > 0:
            print(f" -> Extracted {result['total_purposes_count']} purposes.")
        if result.get('error_log') != '[]':
            print(f" -> Log: {result['error_log']}")
    
    driver.quit()

    # Create DataFrame with all columns in the desired order
    final_df = pd.DataFrame(all_results)
    final_df.to_csv(OUTPUT_CSV_FILE, index=False)
    print(f"\nScraping complete. Enhanced dataset saved to '{OUTPUT_CSV_FILE}'")

if __name__ == "__main__":
    main()
