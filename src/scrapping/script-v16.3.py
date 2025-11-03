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
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, ElementClickInterceptedException, WebDriverException

# Other Imports
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager

# --- Configuration ---
URL_LIST_FILE = "websites.csv"
OUTPUT_CSV_FILE = "enhanced_gdpr_dataset-v2.3.csv"
DEBUG_HTML_DIR = "debug_html_failures"
HEADLESS_MODE = False

# --- Helper Functions (initialize_driver, save_debug_html, find_consent_banner, intelligent_button_finder remain the same as v12) ---
def initialize_driver():
    """Sets up a robust, humanized Selenium WebDriver."""
    chrome_options = Options()
    if HEADLESS_MODE:
        chrome_options.add_argument("--headless=new")
    
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
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': "Object.defineProperty(navigator, 'webdriver', { get: () => undefined })"
        })
        return driver
    except Exception as e:
        print(f"FATAL: Could not initialize WebDriver: {e}")
        return None

def save_debug_html(driver, url, stage):
    if not os.path.exists(DEBUG_HTML_DIR):
        os.makedirs(DEBUG_HTML_DIR)
    filename = re.sub(r'[^a-zA-Z0-9]', '_', url) + f"_FAIL_AT_{stage}.html"
    try:
        with open(os.path.join(DEBUG_HTML_DIR, filename), 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
    except Exception as e:
        print(f"Could not save debug file: {e}")

def find_consent_banner(driver):
    banner_selectors = [
        (By.ID, "onetrust-banner-sdk"), (By.ID, "CybotCookiebotDialog"),
        (By.ID, "trustarc-notice-content"), (By.ID, "qc-cmp2-container"),
        (By.CSS_SELECTOR, "div[class*='cookie']"), (By.CSS_SELECTOR, "div[id*='cookie']"),
        (By.CSS_SELECTOR, "div[class*='consent']"), (By.CSS_SELECTOR, "div[id*='consent']"),
        (By.CSS_SELECTOR, "div[aria-modal='true'][role='dialog']"),
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

def intelligent_button_finder(driver, banner_element, data):
    try:
        positive_keywords = {
            'manage': 6, 'settings': 6, 'preferences': 6, 'options': 5,
            'customize': 5, 'customise': 5, 'configure': 4, 'adjust': 4,
            'details': 3, 'more info': 2, 'learn more': 2, 'cookie settings': 7
        }
        negative_keywords = ['accept', 'agree', 'allow', 'confirm', 'ok', 'got it', 'reject', 'decline', 'deny', 'necessary only']

        buttons = banner_element.find_elements(By.XPATH, ".//button | .//a")
        if not buttons:
            data["error_log"].append("No buttons or links found in banner.")
            return False

        button_scores = {}
        for i, button in enumerate(buttons):
            try:
                text = (button.get_attribute('innerText') or button.get_attribute('textContent') or "").lower().strip()
                if not text or not button.is_displayed() or not button.is_enabled():
                    continue
                
                if any(keyword in text for keyword in negative_keywords):
                    button_scores[i] = -100
                    continue

                score = sum(value for keyword, value in positive_keywords.items() if keyword in text)
                if len(text.split()) <= 3: score += 2
                button_scores[i] = score
            except Exception:
                continue

        if not button_scores or max(button_scores.values()) <= 0:
            data["error_log"].append("No suitable settings/preferences button found after scoring.")
            return False

        best_button_index = max(button_scores, key=button_scores.get)
        best_button = buttons[best_button_index]
        
        button_text_raw = best_button.get_attribute('innerText') or best_button.get_attribute('textContent')
        print(f" -> Clicking settings button: '{button_text_raw.strip()}'")
        data["settings_button_present"] = True; data["settings_button_text"] = button_text_raw.strip()
        
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", best_button)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", best_button)
        
        data["preference_center_accessed"] = True
        return True
    except Exception as e:
        data["error_log"].append(f"Button interaction failed: {type(e).__name__}")
        save_debug_html(driver, data['url'], "button_interaction")
        return False

# --- RE-ENGINEERED EXTRACTION FUNCTION ---
def extract_and_parse_purposes(driver, data):
    """
    Finds the preference center, captures its text, actively interacts with it
    by clicking tabs/accordions, and then performs a final, robust parse.
    """
    try:
        # 1. Broadly identify the main preference center container
        pc_container = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, 
                "div[id*='pc-container'], div[class*='pc-container'], #ot-pc-desc, "
                "div[class*='cookie-setting'], div[role='dialog'], div[class*='preference']"
            ))
        )
        if not pc_container:
            data["error_log"].append("Preference center container not found after click."); return
        
        # 2. CAPTURE LEGAL TEXT (This logic remains the same and is working well)
        detailed_text = pc_container.text
        if detailed_text:
            data["legal_text_summary"] += "\n\n--- PREFERENCE CENTER TEXT ---\n" + ' '.join(detailed_text.splitlines())

        # 3. INTERACTIVE PARSING: Click through all tabs/categories to reveal content
        # This is the key improvement to handle dynamic content loading
        clickable_category_headers = pc_container.find_elements(By.XPATH, 
            ".//button[contains(@id, 'category')] | .//a[@role='tab'] | .//h3[./button] | .//div[contains(@class, 'ot-cat-header')]"
        )
        if clickable_category_headers:
            print(f" -> Found {len(clickable_category_headers)} clickable category headers. Iterating...")
            for i in range(len(clickable_category_headers)):
                try:
                    # Re-find elements in each loop to avoid stale element exceptions
                    header = pc_container.find_elements(By.XPATH, 
                        ".//button[contains(@id, 'category')] | .//a[@role='tab'] | .//h3[./button] | .//div[contains(@class, 'ot-cat-header')]"
                    )[i]
                    driver.execute_script("arguments[0].click();", header)
                    time.sleep(1) # Wait for content to expand
                except (StaleElementReferenceException, ElementClickInterceptedException, IndexError):
                    continue # Ignore if element becomes stale or unclickable

        # 4. FINAL PARSE: Now that all content is hopefully visible, parse the entire container
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        purposes_list = []
        
        # More resilient selectors for finding the rows/containers for each purpose
        purpose_containers = soup.select(
            'div.ot-cat-item, div.ot-accordion-layout, div[class*="category-group"], '
            'div[class*="purpose-item"], tr[class*="consent-"], li[role="tabpanel"], div[role="listitem"]'
        )

        for item in purpose_containers:
            # Broader search for the title element
            title_el = item.find(['h3', 'h4', 'h5', 'h6', 'label', 'span', 'p'], text=True)
            title = title_el.get_text(strip=True) if title_el else None
            if not title or len(title) > 150: continue

            # Robust toggle/checkbox state detection
            is_ticked, is_disabled = False, False
            checkbox = item.find('input', type='checkbox')
            if checkbox:
                is_ticked = checkbox.has_attr('checked') or 'checked' in str(checkbox)
                is_disabled = checkbox.has_attr('disabled')
            else:
                toggle = item.find(attrs={'role': 'switch'})
                if toggle:
                    is_ticked = toggle.get('aria-checked') == 'true'
                    is_disabled = toggle.get('aria-disabled') == 'true'

            item_text_lower = item.get_text().lower()
            is_strictly_necessary = is_disabled or 'strictly necessary' in item_text_lower or 'always active' in item_text_lower
            
            purposes_list.append({
                "title": title.strip(), "is_strictly_necessary": is_strictly_necessary,
                "is_ticked_by_default": bool(is_ticked)
            })

        # De-duplicate results, as interactive clicking might parse the same item multiple times
        unique_purposes = list({p['title']: p for p in purposes_list if p['title']}.values())
        data["purposes_json"] = json.dumps(unique_purposes) if unique_purposes else "[]"
        
        for purpose in unique_purposes:
            if purpose["is_strictly_necessary"]: data["strictly_necessary_count"] += 1
            elif purpose["is_ticked_by_default"]: data["pre_ticked_non_essential_count"] += 1
        
        data["total_purposes_count"] = len(unique_purposes)
        if data["total_purposes_count"] > 0:
            data["status"] = "Success"
        else:
            data["status"] = "Partial (No purposes parsed from preference center)"
            data["error_log"].append("Final parse found 0 purpose items.")
            save_debug_html(driver, data['url'], "final_parse_failure")

    except Exception as e:
        data["error_log"].append(f"Preference extraction failed: {type(e).__name__}")
        save_debug_html(driver, data['url'], "preference_extraction_error")

def main_scraper_workflow(driver, url):
    """Main workflow to navigate, find banner, interact, and extract data."""
    data = {
        "url": url, "timestamp": datetime.now().isoformat(), "status": "Pending",
        "initial_banner_found": False, "preference_center_accessed": False,
        "total_purposes_count": 0, "pre_ticked_non_essential_count": 0, "strictly_necessary_count": 0,
        "purposes_json": "[]", "legal_text_summary": "", "error_log": []
    }

    try:
        driver.get(url)
        WebDriverWait(driver, 30).until(lambda d: d.execute_script('return document.readyState') == 'complete')
        time.sleep(5)
        
        banner = find_consent_banner(driver)
        if not banner:
            data["status"] = "Failed"; data["error_log"].append("Consent banner not found.")
            save_debug_html(driver, url, "banner_not_found")
            return data
            
        data["initial_banner_found"] = True
        data["legal_text_summary"] = ' '.join(banner.text.splitlines())
        
        if intelligent_button_finder(driver, banner, data):
            extract_and_parse_purposes(driver, data)
        else:
            data["status"] = "Partial (Interaction Failed)"

    except TimeoutException:
        data["status"] = "Failed"; data["error_log"].append("Page load timed out.")
    except WebDriverException as e:
        data["status"] = "Failed"; data["error_log"].append(f"WebDriverException: {str(e)[:100]}")
    except Exception as e:
        data["status"] = "Failed"; data["error_log"].append(f"Critical error: {type(e).__name__}")
        save_debug_html(driver, url, "critical_error")
    
    data["error_log"] = json.dumps(data["error_log"])
    return data

def main():
    try:
        urls_df = pd.read_csv(URL_LIST_FILE)
        urls = urls_df['url'].dropna().unique().tolist()
    except FileNotFoundError:
        print(f"FATAL: Input file '{URL_LIST_FILE}' not found."); return

    driver = initialize_driver()
    if not driver: return

    all_results = []
    if os.path.exists(OUTPUT_CSV_FILE):
        try:
            results_df = pd.read_csv(OUTPUT_CSV_FILE)
            all_results = results_df.to_dict('records')
            processed_urls = set(results_df['url'])
            urls = [u for u in urls if u not in processed_urls]
            print(f"Resuming scan. Found {len(all_results)} existing results. {len(urls)} new URLs to process.")
        except pd.errors.EmptyDataError:
            print("Output file is empty. Starting new scan.")
            processed_urls = set()
    
    for i, url in enumerate(urls, 1):
        print(f"\n--- Processing ({i}/{len(urls)}): {url} ---")
        result = main_scraper_workflow(driver, url)
        all_results.append(result)
        
        print(f"Status: {result.get('status', 'Unknown')}")
        if result.get('total_purposes_count', 0) > 0:
            print(f" -> Extracted {result['total_purposes_count']} purposes.")
        if result.get('error_log') != '[]':
            print(f" -> Log: {result['error_log']}")
        
        if i % 5 == 0:
            pd.DataFrame(all_results).to_csv(OUTPUT_CSV_FILE, index=False)
            print(" -> Progress saved.")

    driver.quit()
    
    pd.DataFrame(all_results).to_csv(OUTPUT_CSV_FILE, index=False)
    print(f"\nScraping complete. Final dataset saved to '{OUTPUT_CSV_FILE}'")

if __name__ == "__main__":
    main()
