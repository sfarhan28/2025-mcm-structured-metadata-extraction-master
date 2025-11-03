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
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager
import textstat
from datetime import datetime
import requests
from urllib.parse import urlparse

# --- Configuration ---
URL_LIST_FILE = "websites.csv"
OUTPUT_CSV_FILE = "enhanced_gdpr_dataset-v1.csv"
DEBUG_HTML_DIR = "debug_html_failures"
HEADLESS_MODE = False

# --- Enhanced Data Structures ---
CMP_VENDORS = {
    'onetrust': ['onetrust', 'ot-sdk', 'optanon'],
    'cookiebot': ['cookiebot', 'cb-', 'cookieconsent'],
    'trustarc': ['trustarc', 'truste', 'trustbutton'],
    'quantcast': ['quantcast', 'qc-cmp'],
    'didomi': ['didomi', 'notice'],
    'usercentrics': ['usercentrics', 'uc-'],
    'consensu': ['consensu', 'cmp'],
    'iubenda': ['iubenda', '_iub'],
    'termly': ['termly'],
    'complianz': ['complianz', 'cmplz']
}

DPV_PURPOSE_CATEGORIES = [
    "dpv:ServiceProvision",
    "dpv:Analytics", 
    "dpv:Marketing",
    "dpv:ServicePersonalization",
    "dpv:SocialMediaIntegration",
    "dpv:Security",
    "dpv:Unknown"
]

GDPR_ARTICLE_13_REQUIREMENTS = [
    "controller_identity",
    "processing_purposes", 
    "data_categories",
    "recipients",
    "retention_period",
    "data_subject_rights",
    "withdrawal_right",
    "complaint_right",
    "dpo_contact",
    "legal_basis"
]

USER_RIGHTS_KEYWORDS = [
    "right to access", "access your data", "data portability", "rectification",
    "erasure", "right to be forgotten", "restrict processing", "object to processing",
    "withdraw consent", "lodge a complaint", "data protection authority"
]

DARK_PATTERN_INDICATORS = [
    "pre_selected_non_essential",
    "hidden_reject_button", 
    "emphasized_accept_button",
    "confusing_language",
    "lengthy_rejection_process",
    "misleading_button_text",
    "forced_action"
]

def initialize_driver():
    """Enhanced WebDriver setup with better stealth capabilities."""
    chrome_options = Options()
    if HEADLESS_MODE: 
        chrome_options.add_argument("--headless=new")
    
    # Enhanced anti-detection
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-features=VizDisplayCompositor")
    chrome_options.add_argument("--log-level=3")
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # Enhanced stealth
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });
            '''
        })
        return driver
    except Exception as e:
        print(f"FATAL: Could not initialize WebDriver: {e}")
        return None

def detect_cmp_vendor(driver, soup):
    """Detect which CMP vendor is being used."""
    page_source = driver.page_source.lower()
    
    for vendor, identifiers in CMP_VENDORS.items():
        for identifier in identifiers:
            if identifier in page_source:
                return vendor.title()
    
    # Check for custom implementations
    if any(x in page_source for x in ['cookie', 'consent', 'privacy']):
        return "Unknown/Custom"
    
    return "None"

def calculate_compliance_score(data):
    """Calculate GDPR compliance score based on multiple factors."""
    score = 0.0
    max_score = 10.0
    
    # Basic requirements (4 points)
    if data["accept_all_present"]: score += 1.0
    if data["reject_all_present"]: score += 1.0
    if data["settings_button_present"]: score += 1.0
    if data["preference_center_accessed"]: score += 1.0
    
    # Granular control (2 points)
    if data["has_granular_control"]: score += 2.0
    
    # User rights (2 points)
    if data["user_rights_mentioned"]: score += 1.0
    if data["data_retention_mentioned"]: score += 1.0
    
    # Dark patterns penalty (2 points)
    score -= (data["dark_pattern_score"] / 10.0) * 2.0
    
    return max(0.0, min(1.0, score / max_score))

def analyze_dark_patterns(soup, banner_element, data):
    """Detect dark patterns in consent interface."""
    dark_pattern_score = 0
    
    try:
        # Check for pre-selected non-essential cookies
        checkboxes = soup.find_all('input', type='checkbox')
        pre_selected_count = 0
        for checkbox in checkboxes:
            if checkbox.get('checked') and not any(keyword in str(checkbox).lower() for keyword in ['necessary', 'essential']):
                pre_selected_count += 1
        
        if pre_selected_count > 0:
            dark_pattern_score += 3
            data["pre_ticked_non_essential_count"] = pre_selected_count
        
        # Check for hidden or hard-to-find reject button
        reject_buttons = soup.find_all(['button', 'a'], string=re.compile(r'reject|decline|no', re.I))
        accept_buttons = soup.find_all(['button', 'a'], string=re.compile(r'accept|allow|agree', re.I))
        
        if len(accept_buttons) > len(reject_buttons):
            dark_pattern_score += 2
        
        # Check for emphasized accept vs reject buttons
        for button in accept_buttons:
            if any(keyword in str(button.get('class', [])).lower() for keyword in ['primary', 'highlighted', 'btn-success']):
                dark_pattern_score += 1
                break
        
        # Check for confusing button text
        confusing_patterns = ['legitimate interest', 'partners', 'improve experience']
        for pattern in confusing_patterns:
            if pattern in soup.get_text().lower():
                dark_pattern_score += 1
                break
                
    except Exception as e:
        print(f"Dark pattern analysis failed: {e}")
    
    return min(dark_pattern_score, 10)  # Cap at 10

def calculate_readability_score(text):
    """Calculate readability using multiple metrics."""
    if not text or len(text.split()) < 10:
        return 0.0
    
    try:
        # Multiple readability metrics
        flesch_score = textstat.flesch_reading_ease(text)
        flesch_kincaid = textstat.flesch_kincaid_grade(text)
        
        # Normalize to 0-1 scale (higher = more readable)
        normalized_flesch = max(0, min(100, flesch_score)) / 100.0
        normalized_fk = max(0, 1.0 - (flesch_kincaid / 20.0))  # Assume grade 20+ is unreadable
        
        return (normalized_flesch + normalized_fk) / 2.0
    except:
        return 0.5  # Default moderate readability

def detect_user_rights(text):
    """Detect mention of user rights in legal text."""
    text_lower = text.lower()
    rights_found = 0
    
    for right in USER_RIGHTS_KEYWORDS:
        if right in text_lower:
            rights_found += 1
    
    return rights_found > 0

def detect_data_retention(text):
    """Detect mention of data retention periods."""
    retention_patterns = [
        r'\d+\s*(?:days?|months?|years?)',
        r'retain.*?(?:until|for|period)',
        r'storage.*?period',
        r'keep.*?data.*?(?:until|for)',
        r'delete.*?after'
    ]
    
    text_lower = text.lower()
    for pattern in retention_patterns:
        if re.search(pattern, text_lower):
            return True
    return False

def detect_legitimate_interest(text):
    """Detect mention of legitimate interest as legal basis."""
    return 'legitimate interest' in text.lower()

def categorize_purposes(purposes_json):
    """Categorize purposes using DPV vocabulary."""
    try:
        purposes = json.loads(purposes_json)
        categories = set()
        
        for purpose in purposes:
            title = purpose.get('title', '').lower()
            
            if any(keyword in title for keyword in ['necessary', 'essential', 'functional']):
                categories.add("dpv:ServiceProvision")
            elif any(keyword in title for keyword in ['analytics', 'performance', 'statistics']):
                categories.add("dpv:Analytics")
            elif any(keyword in title for keyword in ['marketing', 'advertising', 'targeting']):
                categories.add("dpv:Marketing")
            elif any(keyword in title for keyword in ['personalization', 'customization']):
                categories.add("dpv:ServicePersonalization")
            elif any(keyword in title for keyword in ['social', 'media', 'sharing']):
                categories.add("dpv:SocialMediaIntegration")
            elif any(keyword in title for keyword in ['security', 'fraud', 'safety']):
                categories.add("dpv:Security")
            else:
                categories.add("dpv:Unknown")
        
        return list(categories)
    except:
        return ["dpv:Unknown"]

def check_gdpr_article_13_compliance(legal_text, data):
    """Check compliance with GDPR Article 13 requirements."""
    compliance_indicators = 0
    text_lower = legal_text.lower()
    
    # Check for various Article 13 requirements
    if any(term in text_lower for term in ['data controller', 'controller', 'we collect', 'we process']):
        compliance_indicators += 1
    
    if any(term in text_lower for term in ['purpose', 'why we', 'use your data']):
        compliance_indicators += 1
    
    if any(term in text_lower for term in ['personal data', 'information we collect', 'data we collect']):
        compliance_indicators += 1
    
    if any(term in text_lower for term in ['third party', 'partners', 'recipients']):
        compliance_indicators += 1
    
    if detect_data_retention(text_lower):
        compliance_indicators += 1
    
    if detect_user_rights(text_lower):
        compliance_indicators += 1
    
    if any(term in text_lower for term in ['withdraw consent', 'opt out']):
        compliance_indicators += 1
    
    if any(term in text_lower for term in ['complaint', 'supervisory authority', 'data protection authority']):
        compliance_indicators += 1
    
    if any(term in text_lower for term in ['data protection officer', 'dpo', 'privacy officer']):
        compliance_indicators += 1
    
    if any(term in text_lower for term in ['legal basis', 'lawful basis']):
        compliance_indicators += 1
    
    # Return True if at least 6 out of 10 requirements are met
    return compliance_indicators >= 6

def enhanced_button_finder(driver, banner_element, data):
    """Enhanced button finding with better detection."""
    try:
        # Find all interactive elements
        buttons = banner_element.find_elements(By.XPATH, ".//button | .//a[@role='button'] | .//div[@role='button'] | .//span[@role='button']")
        
        if not buttons:
            data["error_log"].append("No buttons found in banner.")
            return False

        positive_keywords = {
            'preferences': 5, 'manage': 5, 'options': 4, 'settings': 4,
            'customize': 4, 'customise': 4, 'configure': 3, 'more': 2, 'details': 2,
            'show': 2, 'privacy': 3, 'cookie': 2, 'consent': 2
        }

        negative_keywords = ['accept', 'agree', 'allow', 'confirm', 'ok', 'reject', 'decline', 'deny', 'necessary']

        button_scores = {}
        
        for i, button in enumerate(buttons):
            try:
                text = (button.text or button.get_attribute('aria-label') or '').lower().strip()
                if not text or not button.is_displayed() or not button.is_enabled(): 
                    continue

                if any(keyword in text for keyword in negative_keywords): 
                    button_scores[i] = -99
                    continue

                score = sum(value for keyword, value in positive_keywords.items() if keyword in text)
                if len(text.split()) > 2: score += 1
                
                # Bonus for common settings button patterns
                if re.search(r'manage|preferences|settings|options', text):
                    score += 2
                
                button_scores[i] = score
            except Exception:
                continue

        if not button_scores or max(button_scores.values()) <= 0:
            data["error_log"].append("No button with positive settings keywords found.")
            return False

        best_button_index = max(button_scores, key=button_scores.get)
        best_button = buttons[best_button_index]

        print(f" -> Clicking settings button: '{best_button.text}' (Score: {button_scores[best_button_index]})")
        data["settings_button_present"] = True
        data["settings_button_text"] = best_button.text or best_button.get_attribute('aria-label') or "Settings"

        # Try multiple click methods
        try:
            driver.execute_script("arguments[0].click();", best_button)
        except:
            try:
                best_button.click()
            except:
                return False

        data["preference_center_accessed"] = True
        time.sleep(3)
        return True

    except Exception as e:
        data["error_log"].append(f"Button interaction failed: {type(e).__name__}")
        return False

def extract_enhanced_data(driver, data):
    """Enhanced data extraction with comprehensive analysis."""
    try:
        # Wait for preference center content
        WebDriverWait(driver, 10).until(
            EC.any_of(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[id*='pc-content'], div[class*='ot-sdk-container'], div[class*='cookie'], div[class*='consent']")),
                EC.presence_of_element_located((By.XPATH, "//*[contains(@class, 'preference') or contains(@class, 'settings')]"))
            )
        )

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # CMP Vendor Detection
        data["cmp_vendor"] = detect_cmp_vendor(driver, soup)
        
        # Purpose Extraction (Enhanced)
        purpose_selectors = [
            '.ot-cat-item', 'div[class*="purpose-item"]', 'div[class*="category"]', 
            'div.ot-accordion-layout', '[class*="purpose"]', '[class*="consent-item"]',
            'div[role="checkbox"]', 'label'
        ]
        
        purpose_items = soup.select(','.join(purpose_selectors))
        purposes_list = []
        
        for item in purpose_items:
            title_element = item.find(['h3', 'h4', 'h5', 'label', 'span'], 
                                     class_=lambda c: c and any(x in str(c).lower() for x in ['title', 'header', 'name', 'label']))
            if not title_element:
                title_element = item.find(['h3', 'h4', 'h5', 'label', 'span'])
            
            if title_element:
                title = title_element.get_text(strip=True)
                if len(title) < 5 or len(title) > 200:  # Filter out invalid titles
                    continue
                    
                checkbox = item.find('input', type='checkbox')
                is_ticked = checkbox and checkbox.has_attr('checked')
                is_disabled = checkbox and checkbox.has_attr('disabled')
                is_always_active = is_disabled or "strictly necessary" in title.lower() or "essential" in title.lower()

                purposes_list.append({
                    "title": title, 
                    "is_strictly_necessary": is_always_active, 
                    "is_ticked_by_default": is_ticked
                })

                if is_always_active: 
                    data["strictly_necessary_count"] += 1
                elif is_ticked: 
                    data["pre_ticked_non_essential_count"] += 1

        data["total_purposes_count"] = len(purposes_list)
        data["purposes_json"] = json.dumps(purposes_list)
        
        # Purpose Categorization
        data["purpose_categories"] = categorize_purposes(data["purposes_json"])
        
        # Vendor Count (Enhanced)
        vendor_selectors = [
            '.vendor-list-container', '#vendor-list', 'div[class*="vendor"]', 
            'div[class*="partner"]', '[class*="third-party"]'
        ]
        
        vendor_count = 0
        for selector in vendor_selectors:
            vendor_section = soup.select_one(selector)
            if vendor_section:
                vendors = vendor_section.select('.vendor-list-item, li, div[class*="vendor-row"], tr')
                vendor_count = max(vendor_count, len(vendors))
        
        data["vendor_count"] = vendor_count
        
        # Granular Control Detection
        data["has_granular_control"] = len(purposes_list) > 2 and data["preference_center_accessed"]
        
        # Enhanced Legal Text Analysis
        legal_text = data["legal_text_summary"]
        data["user_rights_mentioned"] = detect_user_rights(legal_text)
        data["data_retention_mentioned"] = detect_data_retention(legal_text)
        data["legitimate_interest_present"] = detect_legitimate_interest(legal_text)
        data["legal_readability_score"] = calculate_readability_score(legal_text)
        data["gdpr_article_13_compliance"] = check_gdpr_article_13_compliance(legal_text, data)
        
        # Status determination
        if data["total_purposes_count"] > 0:
            data["status"] = "Success"
        else:
            data["status"] = "Partial"

    except Exception as e:
        data["error_log"].append(f"Enhanced data extraction failed: {type(e).__name__}")
        data["status"] = "Failed"

def analyze_consent_banner_enhanced(driver, data):
    """Enhanced consent banner analysis."""
    try:
        # Multiple banner detection strategies
        banner_selectors = [
            "#onetrust-banner-sdk",
            "[class*='cookie']",
            "[class*='consent']", 
            "[class*='privacy']",
            "[id*='cookie']",
            "[id*='consent']",
            "div[role='dialog']",
            "div[role='banner']"
        ]
        
        banner = None
        for selector in banner_selectors:
            try:
                banner = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                break
            except TimeoutException:
                continue
        
        if not banner:
            data["status"] = "Failed"
            data["error_log"].append("No consent banner found")
            return

        data["initial_banner_found"] = True
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # Enhanced button detection
        accept_patterns = ['accept', 'allow', 'agree', 'enable', 'continue', 'got it', 'ok']
        reject_patterns = ['reject', 'decline', 'deny', 'disable', 'refuse', 'no thanks']
        
        all_buttons = banner.find_elements(By.XPATH, ".//button | .//a[@role='button'] | .//div[@role='button']")
        
        data["accept_all_present"] = any(
            any(pattern in (btn.text or '').lower() for pattern in accept_patterns)
            for btn in all_buttons
        )
        
        data["reject_all_present"] = any(
            any(pattern in (btn.text or '').lower() for pattern in reject_patterns)
            for btn in all_buttons
        )
        
        # Enhanced legal text extraction
        legal_elements = banner.find_elements(By.XPATH, ".//p | .//div[contains(@class, 'text')] | .//span[contains(@class, 'text')]")
        legal_texts = [elem.text.strip() for elem in legal_elements if elem.text.strip() and len(elem.text.strip()) > 20]
        data["legal_text_summary"] = ' '.join(legal_texts[:3])  # First 3 substantial text blocks
        
        # Dark Patterns Analysis
        data["dark_pattern_score"] = analyze_dark_patterns(soup, banner, data)
        
        # CMP Vendor Detection (early)
        data["cmp_vendor"] = detect_cmp_vendor(driver, soup)
        
        # Try to access preference center
        if not enhanced_button_finder(driver, banner, data):
            data["status"] = "Partial (Interaction Failed)"
            return

        # Enhanced data extraction
        extract_enhanced_data(driver, data)
        
        # Final compliance scoring
        data["compliance_score"] = calculate_compliance_score(data)
        
    except Exception as e:
        data["status"] = "Failed"
        data["error_log"].append(f"Enhanced analysis failed: {type(e).__name__}")

def main_enhanced_workflow(driver, url):
    """Enhanced main workflow with comprehensive data collection."""
    data = {
        # Original fields
        "url": url,
        "timestamp": pd.Timestamp.now().isoformat(),
        "status": "Pending",
        "accept_all_present": False,
        "reject_all_present": False,
        "settings_button_present": False,
        "settings_button_text": "",
        "preference_center_accessed": False,
        "total_purposes_count": 0,
        "pre_ticked_non_essential_count": 0,
        "strictly_necessary_count": 0,
        "purposes_json": "[]",
        "vendor_count": 0,
        "legal_text_summary": "",
        "error_log": [],
        
        # Enhanced fields
        "cmp_vendor": "None",
        "initial_banner_found": False,
        "compliance_score": 0.0,
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
        
        # Enhanced wait for page load
        WebDriverWait(driver, 20).until(
            lambda d: d.execute_script('return document.readyState') == 'complete'
        )
        time.sleep(4)  # Additional wait for dynamic content
        
        analyze_consent_banner_enhanced(driver, data)
        
    except Exception as e:
        data["status"] = "Failed"
        data["error_log"].append(f"Critical error: {type(e).__name__}")
        print(f"Error processing {url}: {e}")

    return data

def main():
    """Enhanced main function."""
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
        
        result = main_enhanced_workflow(driver, url)
        all_results.append(result)
        
        # Enhanced progress reporting
        print(f"Status: {result.get('status', 'Unknown')}")
        print(f"CMP Vendor: {result.get('cmp_vendor', 'Unknown')}")
        print(f"Compliance Score: {result.get('compliance_score', 0.0):.2f}")
        
        if result.get('total_purposes_count', 0) > 0:
            print(f"Purposes Found: {result['total_purposes_count']}")
        
        if result.get('dark_pattern_score', 0) > 0:
            print(f"Dark Pattern Score: {result['dark_pattern_score']}/10")
            
        if result.get('error_log'):
            print(f"Errors: {'; '.join(result['error_log'][:2])}")  # Show first 2 errors
        
        # Small delay between requests
        time.sleep(1)

    driver.quit()

    # Create enhanced DataFrame
    final_df = pd.DataFrame(all_results)
    
    # Define enhanced column order
    enhanced_columns = [
        "url", "timestamp", "status", "cmp_vendor", "initial_banner_found",
        "accept_all_present", "reject_all_present", "settings_button_present", 
        "settings_button_text", "preference_center_accessed", "total_purposes_count",
        "pre_ticked_non_essential_count", "strictly_necessary_count", "purposes_json",
        "compliance_score", "error_log", "legal_text_summary", "vendor_count",
        "data_retention_mentioned", "user_rights_mentioned", "legitimate_interest_present",
        "purpose_categories", "dark_pattern_score", "legal_readability_score",
        "has_granular_control", "gdpr_article_13_compliance"
    ]
    
    final_df_filtered = final_df.reindex(columns=enhanced_columns)
    final_df_filtered.to_csv(OUTPUT_CSV_FILE, index=False)
    
    # Enhanced summary statistics
    print(f"\n{'='*60}")
    print(f"ENHANCED SCRAPING COMPLETE")
    print(f"{'='*60}")
    print(f"Total websites processed: {len(final_df)}")
    print(f"Successful extractions: {len(final_df[final_df['status'] == 'Success'])}")
    print(f"Average compliance score: {final_df['compliance_score'].mean():.2f}")
    print(f"Most common CMP vendor: {final_df['cmp_vendor'].mode().iloc[0] if not final_df['cmp_vendor'].mode().empty else 'N/A'}")
    print(f"Websites with dark patterns: {len(final_df[final_df['dark_pattern_score'] > 0])}")
    print(f"GDPR Article 13 compliant: {len(final_df[final_df['gdpr_article_13_compliance'] == True])}")
    print(f"\nResults saved to: {OUTPUT_CSV_FILE}")

if __name__ == "__main__":
    main()
