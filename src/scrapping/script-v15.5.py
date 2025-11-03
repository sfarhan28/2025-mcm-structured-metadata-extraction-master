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
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager
import textstat
from datetime import datetime

URL_LIST_FILE = "300websites.csv"
OUTPUT_CSV_FILE = "enhanced_gdpr_dataset-v1.5.csv"
HEADLESS_MODE = False

def initialize_driver():
    chrome_options = Options()
    if HEADLESS_MODE: 
        chrome_options.add_argument("--headless=new")
    
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--log-level=3")
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
            '''
        })
        return driver
    except Exception as e:
        print(f"FATAL: Could not initialize WebDriver: {e}")
        return None

def detect_cmp_vendor(driver):
    page_source = driver.page_source.lower()
    
    if 'onetrust' in page_source or 'ot-sdk' in page_source:
        return "OneTrust"
    elif 'cookiebot' in page_source:
        return "Cookiebot"
    elif 'trustarc' in page_source:
        return "TrustArc"
    elif 'quantcast' in page_source:
        return "Quantcast"
    elif 'didomi' in page_source:
        return "Didomi"
    elif any(x in page_source for x in ['cookie', 'consent', 'privacy']):
        return "Unknown/Custom"
    
    return "None"

def super_aggressive_button_finder(driver, banner_element, data):
    try:
        all_elements = banner_element.find_elements(
            By.XPATH, 
            ".//*[self::button or self::a or self::div or self::span][not(contains(@style, 'display: none')) and not(contains(@style, 'visibility: hidden'))]"
        )
        
        clickable_elements = []
        for element in all_elements:
            try:
                if element.is_displayed() and element.is_enabled():
                    text = (element.text or element.get_attribute('aria-label') or 
                           element.get_attribute('title') or element.get_attribute('value') or '').strip()
                    clickable_elements.append({
                        'element': element,
                        'text': text.lower(),
                        'tag': element.tag_name
                    })
            except:
                continue
        
        if not clickable_elements:
            data["error_log"].append("No clickable elements found in banner")
            return False
        
        print(f" -> Found {len(clickable_elements)} clickable elements")
        
        skip_keywords = [
            'accept all', 'allow all', 'agree all', 'consent all', 'ok', 'agree and close',
            'reject all', 'decline all', 'deny all', 'refuse all'
        ]
        
        for elem in clickable_elements:
            text = elem['text']
            
            if any(skip in text for skip in skip_keywords):
                continue
                
            if len(text) < 2:
                continue
            
            try:
                print(f" -> Trying element: '{text}' (tag: {elem['tag']})")
                data["settings_button_present"] = True
                data["settings_button_text"] = text
                
                try:
                    driver.execute_script("arguments[0].click();", elem['element'])
                except:
                    elem['element'].click()
                
                time.sleep(4)
                
                new_content = driver.find_elements(By.XPATH, "//*[contains(@class, 'modal') or contains(@class, 'popup') or contains(@class, 'dialog') or contains(@id, 'settings') or contains(@id, 'preferences') or contains(@id, 'consent')]")
                
                if new_content or len(driver.page_source) > len(banner_element.get_attribute('outerHTML')) * 1.5:
                    data["preference_center_accessed"] = True
                    print(f" -> SUCCESS: Clicked '{text}' and detected new content")
                    return True
                    
            except Exception as e:
                print(f"    Failed clicking '{text}': {e}")
                continue
        
        print(" -> Strategy 1 failed, trying ANY button with text...")
        for elem in clickable_elements:
            text = elem['text']
            
            if not text or len(text) < 1:
                continue
                
            try:
                print(f" -> Desperately trying: '{text}'")
                data["settings_button_present"] = True
                data["settings_button_text"] = text
                
                driver.execute_script("arguments[0].click();", elem['element'])
                time.sleep(3)
                
                if driver.current_url != data["url"]:
                    data["preference_center_accessed"] = True
                    return True
                    
                if driver.find_elements(By.XPATH, "//*[contains(@role, 'dialog') or contains(@class, 'modal')]"):
                    data["preference_center_accessed"] = True
                    return True
                    
            except Exception as e:
                print(f"    Failed: {e}")
                continue
        
        data["error_log"].append(f"Tried {len(clickable_elements)} elements, none worked")
        return False

    except Exception as e:
        data["error_log"].append(f"Aggressive button finder failed: {type(e).__name__}")
        return False

def simple_legal_text_extraction(driver, banner_element, data):
    legal_texts = []
    
    try:
        text_elements = banner_element.find_elements(
            By.XPATH, 
            ".//p | .//div[string-length(normalize-space(text())) > 30]"
        )
        
        for elem in text_elements:
            text = elem.text.strip()
            if len(text) > 30 and len(text) < 1000:
                legal_texts.append(text)
        
        if not legal_texts or sum(len(t) for t in legal_texts) < 50:
            page_elements = driver.find_elements(
                By.XPATH,
                "//p[contains(text(), 'cookie') or contains(text(), 'privacy') or contains(text(), 'consent') or contains(text(), 'data')]"
            )
            
            for elem in page_elements[:3]:
                text = elem.text.strip()
                if len(text) > 30:
                    legal_texts.append(text)
        
        if legal_texts:
            unique_texts = list(dict.fromkeys(legal_texts))
            combined_text = '. '.join(unique_texts[:3])
            data["legal_text_summary"] = combined_text[:2000]
            print(f" -> Extracted legal text: {len(data['legal_text_summary'])} characters")
        else:
            data["legal_text_summary"] = ""
            
    except Exception as e:
        data["error_log"].append(f"Legal text extraction failed: {e}")
        data["legal_text_summary"] = ""

def extract_purposes_and_data(driver, data):
    try:
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        purpose_selectors = [
            '.ot-cat-item',
            'div[class*="purpose"]',
            'div[class*="category"]', 
            'div[class*="consent"]',
            'label',
            'li[class*="purpose"]',
            'div[role="checkbox"]',
            'fieldset legend',
            'h3', 'h4', 'h5'
        ]
        
        purposes_list = []
        found_elements = set()
        
        for selector in purpose_selectors:
            items = soup.select(selector)
            for item in items:
                title = item.get_text(strip=True)
                
                if (not title or len(title) < 3 or len(title) > 150 or 
                    title in found_elements or
                    title.lower() in ['on', 'off', 'yes', 'no', 'ok', 'close']):
                    continue
                
                found_elements.add(title)
                
                checkbox = item.find('input', type='checkbox')
                is_ticked = bool(checkbox and checkbox.has_attr('checked'))
                is_disabled = bool(checkbox and checkbox.has_attr('disabled'))
                is_always_active = (is_disabled or 
                                   any(keyword in title.lower() for keyword in 
                                       ["strictly necessary", "essential", "required", "mandatory"]))

                purposes_list.append({
                    "title": title,
                    "is_strictly_necessary": is_always_active,
                    "is_ticked_by_default": is_ticked
                })
                
                if is_always_active:
                    data["strictly_necessary_count"] += 1
                elif is_ticked:
                    data["pre_ticked_non_essential_count"] += 1

        unique_purposes = []
        seen_titles = set()
        for purpose in purposes_list:
            if purpose["title"] not in seen_titles:
                unique_purposes.append(purpose)
                seen_titles.add(purpose["title"])

        data["total_purposes_count"] = len(unique_purposes)
        data["purposes_json"] = json.dumps(unique_purposes)
        
        vendor_keywords = ['vendor', 'partner', 'third-party', 'supplier']
        vendor_count = 0
        page_text = soup.get_text().lower()
        for keyword in vendor_keywords:
            count = page_text.count(keyword)
            vendor_count = max(vendor_count, count)
        
        data["vendor_count"] = min(vendor_count, 200)
        
        print(f" -> Found {data['total_purposes_count']} purposes, {data['vendor_count']} vendors")
        
    except Exception as e:
        data["error_log"].append(f"Purpose extraction failed: {e}")

def analyze_consent_banner_simple(driver, data):
    try:
        banner_selectors = [
            "#onetrust-banner-sdk",
            "[id*='cookie']", "[id*='consent']", "[id*='privacy']",
            "[class*='cookie']", "[class*='consent']", "[class*='privacy']", "[class*='notice']",
            "div[role='dialog']", "div[role='banner']", "div[role='region']",
            "[class*='popup']", "[class*='modal']", "[class*='overlay']"
        ]
        
        banner = None
        used_selector = ""
        
        for selector in banner_selectors:
            try:
                banners = driver.find_elements(By.CSS_SELECTOR, selector)
                for b in banners:
                    if b.is_displayed() and b.size['height'] > 20 and b.size['width'] > 100:
                        banner = b
                        used_selector = selector
                        break
                if banner:
                    break
            except:
                continue
        
        if not banner:
            data["status"] = "Failed"
            data["error_log"].append("No consent banner found with any selector")
            return

        data["initial_banner_found"] = True
        print(f" -> Found banner with selector: {used_selector}")
        
        all_buttons = banner.find_elements(By.XPATH, ".//button | .//a[@role='button'] | .//div[@role='button'] | .//a[contains(@class, 'btn')]")
        button_texts = [btn.text.lower() for btn in all_buttons if btn.text.strip()]
        
        data["accept_all_present"] = any('accept' in text for text in button_texts)
        data["reject_all_present"] = any('reject' in text or 'decline' in text for text in button_texts)
        
        simple_legal_text_extraction(driver, banner, data)
        
        if not super_aggressive_button_finder(driver, banner, data):
            data["status"] = "Partial (Interaction Failed)"
            return

        extract_purposes_and_data(driver, data)
        
        if data["total_purposes_count"] > 0:
            data["status"] = "Success"
        elif data["preference_center_accessed"]:
            data["status"] = "Partial"
        else:
            data["status"] = "Failed"
            
    except Exception as e:
        data["status"] = "Failed"
        data["error_log"].append(f"Banner analysis failed: {type(e).__name__}")

def main_workflow(driver, url):
    data = {
        "url": url,
        "timestamp": pd.Timestamp.now().isoformat(),
        "status": "Pending",
        "cmp_vendor": "None",
        "initial_banner_found": False,
        "accept_all_present": False,
        "reject_all_present": False,
        "settings_button_present": False,
        "settings_button_text": "",
        "preference_center_accessed": False,
        "total_purposes_count": 0,
        "pre_ticked_non_essential_count": 0,
        "strictly_necessary_count": 0,
        "purposes_json": "[]",
        "compliance_score": 0.0,
        "error_log": [],
        "legal_text_summary": "",
        "vendor_count": 0,
        "data_retention_mentioned": False,
        "user_rights_mentioned": False,
        "legitimate_interest_present": False,
        "purpose_categories": [],
        "dark_pattern_score": 0,
        "legal_readability_score": 0.0,
        "has_granular_control": False,
        "gdpr_article_13_compliance": False
    }

    try:
        print(f"Loading: {url}")
        driver.get(url)
        
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script('return document.readyState') == 'complete'
        )
        time.sleep(5)
        
        data["cmp_vendor"] = detect_cmp_vendor(driver)
        
        analyze_consent_banner_simple(driver, data)
        
        legal_text = data["legal_text_summary"].lower()
        data["user_rights_mentioned"] = any(keyword in legal_text for keyword in 
            ["right to access", "data portability", "withdraw consent", "right to be forgotten"])
        data["data_retention_mentioned"] = bool(re.search(r'\d+\s*(?:days?|months?|years?)', legal_text))
        data["legitimate_interest_present"] = 'legitimate interest' in legal_text
        data["has_granular_control"] = data["total_purposes_count"] > 2 and data["preference_center_accessed"]
        
        score = 0
        if data["accept_all_present"]: score += 1
        if data["reject_all_present"]: score += 1
        if data["settings_button_present"]: score += 1
        if data["preference_center_accessed"]: score += 1
        if data["has_granular_control"]: score += 2
        data["compliance_score"] = min(1.0, score / 6.0)
        
    except Exception as e:
        data["status"] = "Failed"
        data["error_log"].append(f"Critical error: {type(e).__name__}")
        print(f"Error processing {url}: {e}")

    return data

def main():
    try:
        urls = pd.read_csv(URL_LIST_FILE)['url'].dropna().unique().tolist()
    except FileNotFoundError:
        print(f"FATAL: Input file '{URL_LIST_FILE}' not found.")
        return

    driver = initialize_driver()
    if not driver:
        return

    all_results = []
    
    for i, url in enumerate(urls, 1):
        print(f"\n--- Processing ({i}/{len(urls)}): {url} ---")
        
        result = main_workflow(driver, url)
        all_results.append(result)
        
        print(f"Status: {result.get('status', 'Unknown')}")
        print(f"Button Found: {result.get('settings_button_text', 'None')}")
        print(f"Purposes: {result.get('total_purposes_count', 0)}")
        print(f"Legal Text: {len(result.get('legal_text_summary', ''))} chars")
        
        if result.get('error_log'):
            print(f"Errors: {'; '.join(result['error_log'][:2])}")
        
        time.sleep(2)

    driver.quit()

    final_df = pd.DataFrame(all_results)
    final_df.to_csv(OUTPUT_CSV_FILE, index=False)
    
    print(f"\n{'='*60}")
    print(f"AGGRESSIVE SCRAPING COMPLETE")
    print(f"{'='*60}")
    print(f"Total websites processed: {len(final_df)}")
    print(f"Successful extractions: {len(final_df[final_df['status'] == 'Success'])}")
    print(f"Partial extractions: {len(final_df[final_df['status'].str.contains('Partial', na=False)])}")
    print(f"Button interactions successful: {len(final_df[final_df['preference_center_accessed'] == True])}")
    print(f"Results saved to: {OUTPUT_CSV_FILE}")

if __name__ == "__main__":
    main()
