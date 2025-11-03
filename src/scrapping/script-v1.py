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
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager

def initialize_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36")
    chrome_options.add_argument("--log-level=3")
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except Exception as e:
        print(f"Error setting up WebDriver: {e}")
        return None

def find_element_by_heuristics(driver, selectors):
    for selector_type, selector_value in selectors:
        try:
            if selector_type == "text":
                return driver.find_element(By.XPATH, f"//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{selector_value}')]")
            else:
                return driver.find_element(selector_type, selector_value)
        except NoSuchElementException:
            continue
    return None

def scrape_generalized_consent_data(driver, url: str):
    data = {
        "url": url,
        "timestamp": pd.Timestamp.now().isoformat(),
        "cmp_vendor": "Unknown",
        "initial_banner_analysis": {
            "accept_all_present": False,
            "reject_all_present": False,
            "settings_button_present": False,
            "legal_text_summary": ""
        },
        "purpose_details": {
            "purposes": [],
            "pre_ticked_non_essential_count": 0,
            "total_purposes_count": 0,
            "strictly_necessary_count": 0
        },
        "compliance_indicators": {
            "reject_as_easy_as_accept": False,
            "no_pre_ticked_boxes": True
        },
        "errors": []
    }

    try:
        driver.get(url)
        print(f"INFO: Scraping {url}...")
        banner_selectors = [
            (By.ID, "onetrust-banner-sdk"),
            (By.CSS_SELECTOR, "div[role='dialog']"),
            (By.CSS_SELECTOR, "div[id*='consent']"),
            (By.CSS_SELECTOR, "div[class*='consent']"),
            (By.CSS_SELECTOR, "div[id*='cookie']"),
        ]
        banner_element = None
        for by, value in banner_selectors:
            try:
                WebDriverWait(driver, 5).until(EC.visibility_of_element_located((by, value)))
                banner_element = driver.find_element(by, value)
                print(f"  - Banner found with: {value}")
                break
            except TimeoutException:
                continue

        if not banner_element:
            data["errors"].append("No recognizable consent banner found.")
            print("  - WARNING: No consent banner found on this site.")
            return data

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        accept_selectors = [(By.ID, "onetrust-accept-btn-handler"), (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept all')]")]
        reject_selectors = [(By.ID, "onetrust-reject-all-handler"), (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'necessary')]"), (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'reject')]")]
        settings_selectors = [(By.ID, "onetrust-pc-btn-handler"), (By.CSS_SELECTOR, ".cookie-setting-link"), ("text", "settings"), ("text", "manage"), ("text", "customize")]

        data["initial_banner_analysis"]["accept_all_present"] = bool(find_element_by_heuristics(driver, accept_selectors))
        data["initial_banner_analysis"]["reject_all_present"] = bool(find_element_by_heuristics(driver, reject_selectors))
        settings_button = find_element_by_heuristics(driver, settings_selectors)
        data["initial_banner_analysis"]["settings_button_present"] = bool(settings_button)

        data["compliance_indicators"]["reject_as_easy_as_accept"] = (
            data["initial_banner_analysis"]["accept_all_present"] and data["initial_banner_analysis"]["reject_all_present"]
        )

        if settings_button:
            try:
                driver.execute_script("arguments[0].click();", settings_button)
                print("  - Clicked settings/manage button.")
                pc_selectors = [(By.ID, "onetrust-pc-sdk"), (By.ID, "ot-pc-desc"), (By.CSS_SELECTOR, "div[class*='preference']")]
                for by, value in pc_selectors:
                    try:
                        WebDriverWait(driver, 5).until(EC.visibility_of_element_located((by, value)))
                        print(f"  - Preference center found with: {value}")
                        break
                    except TimeoutException:
                        continue
                time.sleep(2)
            except Exception as e:
                data["errors"].append(f"Could not interact with settings button: {str(e)}")
                print(f"  - ERROR: Could not interact with settings button: {e}")
                return data
        else:
            data["errors"].append("No settings button found.")
            print("  - INFO: No settings button found. Analysis limited to initial banner.")
            return data

        pc_soup = BeautifulSoup(driver.page_source, 'html.parser')
        purpose_items = pc_soup.select('.ot-cat-item, div[data-optanongroupid], div.purpose-vendor-container')
        if not purpose_items:
            data["errors"].append("Could not find purpose/category items in preference center.")
            print("  - WARNING: Could not extract purpose details from preference center.")
            return data

        for item in purpose_items:
            title = (item.find(class_='ot-cat-header') or item.find('h3') or item.find('h4')).get_text(strip=True) if (item.find(class_='ot-cat-header') or item.find('h3') or item.find('h4')) else "N/A"
            is_always_active = 'ot-always-active' in (item.find(class_='ot-cat-header-wrapper').get('class', []) if item.find(class_='ot-cat-header-wrapper') else [])
            toggle = item.find('input', type='checkbox')
            is_ticked = toggle.has_attr('checked') if toggle else False

            data["purpose_details"]["purposes"].append({"title": title, "is_strictly_necessary": is_always_active, "is_ticked_by_default": is_ticked})

            if is_always_active:
                data["purpose_details"]["strictly_necessary_count"] += 1
            elif is_ticked:
                data["purpose_details"]["pre_ticked_non_essential_count"] += 1

        data["purpose_details"]["total_purposes_count"] = len(purpose_items)
        data["compliance_indicators"]["no_pre_ticked_boxes"] = data["purpose_details"]["pre_ticked_non_essential_count"] == 0
        print(f"  - SUCCESS: Extracted {data['purpose_details']['total_purposes_count']} purposes.")

    except Exception as e:
        data["errors"].append(f"Top-level error: {str(e)}")
        print(f"  - FATAL ERROR during scrape: {e}")
    
    return data

def save_to_csv(all_data, filename="consent_analysis_4.csv"):
    if not all_data:
        print("No data collected, CSV not created.")
        return
    flat_data = [pd.json_normalize(d, sep='_') for d in all_data]
    df = pd.concat(flat_data, ignore_index=True)
    df.to_csv(filename, index=False)
    print(f"\nSUCCESS: All data saved to {filename}")

if __name__ == "__main__":
    urls_to_scrape = [
        "https://eu.puma.com/ie/en/home",
        "https://www.adobe.com/ie/",
        "https://www2.hm.com/en_ie/index.html",
        "https://www.rte.ie/",
        "https://www.did.ie/",
        "https://www.amazon.ie/",
        "https://www.zalando.ie/",
        "https://deliveroo.ie/",
    ]
    driver = initialize_driver()
    if driver:
        all_results = []
        for url in urls_to_scrape:
            result = scrape_generalized_consent_data(driver, url)
            if result:
                all_results.append(result)
        driver.quit()
        save_to_csv(all_results)
    
    # Flatten the complex dictionary structure for easy CSV analysis
    flat_data = [pd.json_normalize(d, sep='_') for d in all_data]
    df = pd.concat(flat_data, ignore_index=True)
    
    df.to_csv(filename, index=False)
    print(f"\nSUCCESS: All data saved to {filename}")


if __name__ == "__main__":
    # --- Define your list of target websites here ---
    urls_to_scrape = [
        "https://eu.puma.com/ie/en/home",
        "https://www.adobe.com/ie/",
        "https://www2.hm.com/en_ie/index.html",
        "https://www.rte.ie/",
        "https://www.did.ie/",
        "https://www.amazon.ie/",
        "https://www.zalando.ie/",
        "https://deliveroo.ie/",
        # Add up to 100 URLs here
    ]
    
    driver = initialize_driver()
    if driver:
        all_results = []
        for url in urls_to_scrape:
            result = scrape_generalized_consent_data(driver, url)
            if result:
                all_results.append(result)
        
        driver.quit()
        save_to_csv(all_results)
