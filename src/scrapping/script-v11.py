"""
GDPR consent banner scraper with robust element finding and error logging.
"""

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
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, ElementClickInterceptedException, StaleElementReferenceException
)
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager

# Configuration
URL_LIST_FILE = "D:\DCU\Practicum\code\websites.csv"
OUTPUT_CSV_FILE = "gdpr_final_dataset-v6.csv"
DEBUG_HTML_DIR = "debug_html_failures"
HEADLESS_MODE = False

def initialize_driver():
    chrome_options = Options()
    if HEADLESS_MODE:
        chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--log-level=3")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver

def save_debug_html(driver, url, stage):
    if not os.path.exists(DEBUG_HTML_DIR):
        os.makedirs(DEBUG_HTML_DIR)
    filename = re.sub(r'[^a-zA-Z0-9]', '_', url) + f"_FAIL_AT_{stage}.html"
    with open(os.path.join(DEBUG_HTML_DIR, filename), 'w', encoding='utf-8') as f:
        f.write(driver.page_source)

def find_clickable_elements(panel, keywords_include, keywords_exclude=None):
    # Find all visible, clickable buttons/links/spans
    elements = panel.find_elements(By.XPATH, ".//button | .//a[@role='button'] | .//span[@role='button'] | .//input[@type='button']")
    scored = []
    for el in elements:
        try:
            text = el.text.strip().lower()
            if not text or not el.is_displayed() or not el.is_enabled():
                continue
            if keywords_exclude and any(x in text for x in keywords_exclude):
                continue
            score = sum(k in text for k in keywords_include)
            scored.append((score, el, text))
        except Exception:
            continue
    scored.sort(key=lambda x: -x[0])
    return scored

def expand_all_multistep(panel):
    """Recursively click all expanders/accordions/tabs inside the current panel."""
    expand_keywords = ["expand", "show all", "more", "see all", "details", "arrow", "vendors", "partners"]
    for el in panel.find_elements(By.XPATH, ".//*"):
        try:
            text = el.text.strip().lower()
            classes = el.get_attribute("class") or ""
            aria = el.get_attribute("aria-label") or ""
            if any(kw in text or kw in classes or kw in aria for kw in expand_keywords):
                if el.is_displayed() and el.is_enabled():
                    el.click()
                    time.sleep(0.5)
        except Exception:
            continue

def extract_legal_text(banner):
    # Try several methods to extract the legal summary
    candidates = []
    for xpath in [
        ".//p", ".//div[contains(@class, 'text') or contains(@id, 'policy')]",
        ".//span", ".//div"
    ]:
        try:
            eles = banner.find_elements(By.XPATH, xpath)
            candidates.extend([e.text.strip() for e in eles if e.text and len(e.text.strip()) > 50])
        except Exception:
            continue
    return " ".join(candidates[:2])

def extract_purposes_and_vendors(html):
    # Many selector approaches
    soup = BeautifulSoup(html, "html.parser")
    purpose_selectors = [
        '.ot-cat-item', 'div[class*="purpose"]', 'div[class*="category"]', 'div[class*="consent-item"]', 'li[class*="purpose"]',
        'div[class*="option"]', '.preference-item', '[data-purpose]', "[aria-label*='purpose']", "[aria-label*='category']"
    ]
    purposes = []
    for selector in purpose_selectors:
        for item in soup.select(selector):
            title = "Title Not Found"
            for t in ['h4', 'h3', 'h5', 'label', 'span', 'div']:
                el = item.find(t)
                if el and el.text.strip():
                    title = el.text.strip()
                    break
            checkbox = item.find('input', {'type': 'checkbox'})
            is_ticked = bool(checkbox and checkbox.has_attr('checked'))
            is_disabled = bool(checkbox and checkbox.has_attr('disabled'))
            is_always_active = is_disabled or ("strictly necessary" in title.lower()) or ("essential" in title.lower())
            purposes.append({
                "title": title, "is_strictly_necessary": is_always_active, "is_ticked_by_default": is_ticked
            })
    # Vendors
    vendor_count = 0
    vendor_selectors = [
        ".vendor-list", "#vendor-list", 'div[class*="vendor"]', 'div[class*="partner"]', '[aria-label*="vendor"]'
    ]
    for vs in vendor_selectors:
        vendor_cont = soup.select_one(vs)
        if vendor_cont:
            vendor_count += len(vendor_cont.find_all("li")) or len(vendor_cont.find_all("div"))
    return purposes, vendor_count

def scrape_consent_dialogue(driver, url):
    log = []
    accept_all_present = reject_all_present = settings_button_present = False
    settings_button_text = ""
    preference_center_accessed = False
    total_purposes_count = pre_ticked_non_essential_count = strictly_necessary_count = vendor_count = 0
    purposes_json = "[]"
    legal_text_summary = ""

    try:
        driver.get(url)
        WebDriverWait(driver, 20).until(lambda d: d.execute_script('return document.readyState') == 'complete')
        time.sleep(2)

        # Find and interact with cookie banner
        possible_banners = [
            (By.ID, "onetrust-banner-sdk"),
            (By.CSS_SELECTOR, "div[role=dialog]"),
            (By.CSS_SELECTOR, "div[class*='cookie']"),
            (By.CSS_SELECTOR, "div[class*='consent']"),
            (By.CSS_SELECTOR, "div[class*='gdpr']"),
            (By.CSS_SELECTOR, ".CookieConsent")
        ]
        banner = None
        for by, sel in possible_banners:
            try:
                banner = WebDriverWait(driver, 5).until(EC.presence_of_element_located((by, sel)))
                break
            except TimeoutException:
                continue
        if not banner:
            log.append("Banner not found.")
            return [
                url, pd.Timestamp.now().isoformat(), "Failed",
                False, False, False, "", False, 0, 0, 0, "[]", 0, "", log
            ]

        accept_all_present = bool(find_clickable_elements(banner, ["accept", "allow"], None))
        reject_all_present = bool(find_clickable_elements(banner, ["reject", "decline", "deny"], None))

        # Intelligent interaction
        settings_keywords = ["settings", "preferences", "manage", "customize", "customise", "details", "options"]
        settings_buttons = find_clickable_elements(banner, settings_keywords, ["accept", "reject", "decline", "allow", "necessary"])
        if settings_buttons:
            settings_button_present = True
            settings_button_text = settings_buttons[0][2]
            try:
                driver.execute_script("arguments[0].click();", settings_buttons[0][1])
                preference_center_accessed = True
                time.sleep(2)
            except Exception as e:
                log.append(f"Settings click error: {type(e).__name__}")
        else:
            log.append("No settings button found.")

        # Try to expand all toggles/accordions/tabs in the opened panel
        try:
            panel = driver.find_element(By.XPATH, "//div[contains(@id, 'ot-pc-content')] | //div[contains(@class, 'preference') or contains(@class, 'settings')]")
            expand_all_multistep(panel)
        except Exception:
            # Try again later or fallback to page source scraping
            pass

        # Extract legal text, purposes, vendors
        legal_text_summary = extract_legal_text(banner)
        purposes, vendor_count = extract_purposes_and_vendors(driver.page_source)
        purposes_json = json.dumps(purposes, ensure_ascii=False)
        total_purposes_count = len(purposes)
        pre_ticked_non_essential_count = sum(1 for p in purposes if not p["is_strictly_necessary"] and p["is_ticked_by_default"])
        strictly_necessary_count = sum(1 for p in purposes if p["is_strictly_necessary"])

        status = "Success" if total_purposes_count > 0 else "Partial"
    except Exception as e:
        status = "Failed"
        log.append(f"Critical error: {type(e).__name__}")

    return [
        url, pd.Timestamp.now().isoformat(), status,
        accept_all_present, reject_all_present, settings_button_present, settings_button_text,
        preference_center_accessed, total_purposes_count, pre_ticked_non_essential_count,
        strictly_necessary_count, purposes_json, vendor_count, legal_text_summary, log
    ]


def main():
    OUTPUT_COLUMNS = [
        "url", "timestamp", "status",
        "accept_all_present", "reject_all_present",
        "settings_button_present", "settings_button_text",
        "preference_center_accessed", "total_purposes_count",
        "pre_ticked_non_essential_count", "strictly_necessary_count",
        "purposes_json", "vendor_count", "legal_text_summary", "error_log"
    ]
    if not os.path.exists(URL_LIST_FILE):
        print(f"Input file '{URL_LIST_FILE}' not found.")
        return
    urls = pd.read_csv(URL_LIST_FILE)['url'].dropna().unique().tolist()
    print(f"Loaded {len(urls)} URLs for scraping")

    driver = initialize_driver()
    results = []
    for i, url in enumerate(urls, 1):
        print(f"\n--- Scraping ({i}/{len(urls)}): {url} ---")
        row = scrape_consent_dialogue(driver, url)
        results.append(row)
        print(f"Result: {row[2]}, Purposes: {row[8]}, Vendors: {row[12]}")
        if row[14]:
            print(f"  Log: {'; '.join(row[14])}")
    driver.quit()
    pd.DataFrame(results, columns=OUTPUT_COLUMNS).to_csv(OUTPUT_CSV_FILE, index=False)
    print(f"\nScraping complete. Results saved to '{OUTPUT_CSV_FILE}'")

if __name__ == "__main__":
    main()
