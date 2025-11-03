"""
Enhanced GDPR consent banner scraper using Selenium and BeautifulSoup.
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
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime

# Configuration
URL_LIST_FILE = "websites.csv"
OUTPUT_CSV_FILE = "enhanced_gdpr_dataset-v1.3.csv"
DEBUG_HTML_DIR = "debug_html_failures"
HEADLESS_MODE = False

# CMP vendor identifiers for detection
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

# List of keywords to detect user rights in legal text
USER_RIGHTS_KEYWORDS = [
    "right to access", "access your data", "data portability", "rectification",
    "erasure", "right to be forgotten", "restrict processing", "object to processing",
    "withdraw consent", "lodge a complaint", "data protection authority"
]

def initialize_driver():
    """Set up Selenium Chrome WebDriver with stealth options."""
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

def enhanced_legal_text_extraction(driver, banner_element, data):
    """Enhanced legal text extraction with multiple strategies."""
    legal_texts = []
    
    try:
        # Strategy 1: Extract from banner element directly
        banner_legal_selectors = [
            ".//p[string-length(text()) > 50]",  # Paragraphs with substantial content
            ".//div[contains(@class, 'text') and string-length(text()) > 50]",
            ".//div[contains(@class, 'description') and string-length(text()) > 50]",
            ".//div[contains(@class, 'policy') and string-length(text()) > 50]",
            ".//div[contains(@class, 'notice') and string-length(text()) > 50]",
            ".//div[contains(@id, 'policy') and string-length(text()) > 50]",
            ".//span[contains(@class, 'text') and string-length(text()) > 50]",
            ".//div[contains(@class, 'content') and string-length(text()) > 50]",
            ".//div[contains(@class, 'message') and string-length(text()) > 50]"
        ]
        
        for selector in banner_legal_selectors:
            try:
                elements = banner_element.find_elements(By.XPATH, selector)
                for elem in elements:
                    text = elem.text.strip()
                    if text and len(text) > 50:  # Only meaningful text
                        legal_texts.append(text)
            except:
                continue
        
        # Strategy 2: Look for specific consent-related text patterns
        consent_text_patterns = [
            ".//div[contains(text(), 'cookie') and string-length(text()) > 30]",
            ".//p[contains(text(), 'consent') and string-length(text()) > 30]",
            ".//div[contains(text(), 'privacy') and string-length(text()) > 30]",
            ".//p[contains(text(), 'personal data') and string-length(text()) > 30]",
            ".//div[contains(text(), 'we use') and string-length(text()) > 30]",
            ".//p[contains(text(), 'processing') and string-length(text()) > 30]"
        ]
        
        for pattern in consent_text_patterns:
            try:
                elements = banner_element.find_elements(By.XPATH, pattern)
                for elem in elements:
                    text = elem.text.strip()
                    if text and len(text) > 30 and text not in legal_texts:
                        legal_texts.append(text)
            except:
                continue
        
        # Strategy 3: BeautifulSoup parsing for hidden or nested content
        try:
            banner_html = banner_element.get_attribute('outerHTML')
            soup = BeautifulSoup(banner_html, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Find text in various containers
            text_containers = soup.find_all(['p', 'div', 'span'], 
                string=lambda text: text and len(text.strip()) > 50)
            
            for container in text_containers:
                text = container.get_text(strip=True)
                if text and len(text) > 50 and text not in legal_texts:
                    legal_texts.append(text)
                    
        except Exception as e:
            print(f"BeautifulSoup parsing failed: {e}")
        
        # Strategy 4: Look in the whole page if banner extraction failed
        if not legal_texts:
            try:
                page_legal_selectors = [
                    "//div[contains(@class, 'cookie') and contains(@class, 'banner')]//p",
                    "//div[contains(@class, 'consent')]//p",
                    "//div[contains(@class, 'privacy')]//p",
                    "//div[contains(@id, 'cookie')]//p",
                    "//div[contains(@id, 'consent')]//div[string-length(text()) > 50]"
                ]
                
                for selector in page_legal_selectors:
                    try:
                        elements = driver.find_elements(By.XPATH, selector)
                        for elem in elements:
                            text = elem.text.strip()
                            if text and len(text) > 50:
                                legal_texts.append(text)
                    except:
                        continue
            except:
                pass
        
        # Clean and deduplicate texts
        cleaned_texts = []
        seen_texts = set()
        
        for text in legal_texts:
            # Clean the text
            text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
            text = text.strip()
            
            # Skip if too short, too long, or already seen
            if len(text) < 30 or len(text) > 1000 or text in seen_texts:
                continue
                
            # Skip if it's just button text or navigation
            if any(skip_word in text.lower() for skip_word in 
                   ['accept all', 'reject all', 'settings', 'manage preferences', 'customize']):
                continue
            
            cleaned_texts.append(text)
            seen_texts.add(text)
        
        # Combine the best texts (prioritize longer, more informative ones)
        final_legal_text = '. '.join(cleaned_texts[:4])  # Take up to 4 best texts
        
        if final_legal_text:
            data["legal_text_summary"] = final_legal_text
            print(f" -> Extracted legal text: {len(final_legal_text)} characters")
        else:
            data["legal_text_summary"] = ""
            data["error_log"].append("No substantial legal text found")
            
    except Exception as e:
        data["error_log"].append(f"Legal text extraction failed: {type(e).__name__}")
        data["legal_text_summary"] = ""

def enhanced_positional_button_finder(driver, banner_element, data):
    """
    Enhanced button finder using positional logic instead of text matching.
    Most consent dialogs have 2-4 buttons in predictable positions.
    """
    try:
        # Find all clickable elements
        all_clickables = banner_element.find_elements(
            By.XPATH, 
            ".//button | .//a[@role='button'] | .//div[@role='button'] | .//span[@role='button'] | .//a[contains(@class, 'btn')] | .//div[contains(@class, 'button')]"
        )
        
        # Filter for visible and enabled elements
        visible_buttons = []
        for element in all_clickables:
            try:
                if element.is_displayed() and element.is_enabled():
                    text = (element.text or element.get_attribute('aria-label') or element.get_attribute('title') or '').strip()
                    if text:  # Only include buttons with some text
                        visible_buttons.append({
                            'element': element,
                            'text': text.lower(),
                            'classes': element.get_attribute('class') or '',
                            'id': element.get_attribute('id') or ''
                        })
            except:
                continue
        
        if not visible_buttons:
            data["error_log"].append("No visible buttons found in banner.")
            return False
        
        print(f" -> Found {len(visible_buttons)} visible buttons")
        for i, btn in enumerate(visible_buttons):
            print(f"    {i+1}. '{btn['text'][:50]}' (classes: {btn['classes'][:30]})")
        
        # Categorize buttons
        accept_buttons = []
        reject_buttons = []
        settings_buttons = []
        other_buttons = []
        
        accept_keywords = ['accept', 'allow', 'agree', 'consent', 'continue', 'ok', 'got it', 'enable']
        reject_keywords = ['reject', 'decline', 'deny', 'refuse', 'no thanks', 'disable']
        settings_keywords = [
            'setting', 'preference', 'manage', 'customize', 'customise', 'option', 'choice',
            'detail', 'more', 'configure', 'control', 'cookie setting', 'cookie preference',
            'privacy setting', 'show', 'view', 'learn more', 'cookie policy'
        ]
        
        for btn in visible_buttons:
            text = btn['text']
            classes_and_id = (btn['classes'] + ' ' + btn['id']).lower()
            
            # Check for accept buttons
            if any(keyword in text for keyword in accept_keywords):
                accept_buttons.append(btn)
            # Check for reject buttons
            elif any(keyword in text for keyword in reject_keywords):
                reject_buttons.append(btn)
            # Check for settings buttons (broader criteria)
            elif (any(keyword in text for keyword in settings_keywords) or 
                  any(keyword in classes_and_id for keyword in ['setting', 'preference', 'manage', 'customize', 'option'])):
                settings_buttons.append(btn)
            else:
                other_buttons.append(btn)
        
        data["accept_all_present"] = len(accept_buttons) > 0
        data["reject_all_present"] = len(reject_buttons) > 0
        
        # Strategy 1: Try identified settings buttons first
        if settings_buttons:
            for btn in settings_buttons:
                try:
                    print(f" -> Trying identified settings button: '{btn['text']}'")
                    data["settings_button_present"] = True
                    data["settings_button_text"] = btn['text']
                    
                    # Try multiple click methods
                    try:
                        driver.execute_script("arguments[0].click();", btn['element'])
                    except:
                        btn['element'].click()
                    
                    data["preference_center_accessed"] = True
                    time.sleep(3)
                    return True
                except Exception as e:
                    print(f"    Failed to click: {e}")
                    continue
        
        # Strategy 2: Positional approach - try buttons that are NOT accept/reject
        remaining_buttons = other_buttons.copy()
        
        # If we have 3+ buttons total, the 3rd+ buttons are likely settings/more info
        if len(visible_buttons) >= 3:
            # Sort by position (try to get consistent ordering)
            try:
                all_sorted = sorted(visible_buttons, key=lambda x: (
                    x['element'].location['y'], 
                    x['element'].location['x']
                ))
                
                # Skip the first 2 buttons (likely accept/reject) and try the rest
                for btn in all_sorted[2:]:
                    # Skip if it's clearly an accept/reject button
                    if (any(keyword in btn['text'] for keyword in accept_keywords) or
                        any(keyword in btn['text'] for keyword in reject_keywords)):
                        continue
                    
                    try:
                        print(f" -> Trying positional button #{all_sorted.index(btn)+1}: '{btn['text']}'")
                        data["settings_button_present"] = True
                        data["settings_button_text"] = btn['text']
                        
                        # Try multiple click methods
                        try:
                            driver.execute_script("arguments[0].click();", btn['element'])
                        except:
                            btn['element'].click()
                        
                        data["preference_center_accessed"] = True
                        time.sleep(3)
                        return True
                    except Exception as e:
                        print(f"    Failed to click: {e}")
                        continue
            except Exception as e:
                print(f"Position-based sorting failed: {e}")
        
        # Strategy 3: Try any remaining non-accept/reject buttons
        for btn in remaining_buttons:
            try:
                print(f" -> Trying remaining button: '{btn['text']}'")
                data["settings_button_present"] = True
                data["settings_button_text"] = btn['text']
                
                # Try multiple click methods
                try:
                    driver.execute_script("arguments[0].click();", btn['element'])
                except:
                    btn['element'].click()
                
                data["preference_center_accessed"] = True
                time.sleep(3)
                return True
            except Exception as e:
                print(f"    Failed to click: {e}")
                continue
        
        # Strategy 4: Last resort - try all buttons except clear accept buttons
        for btn in visible_buttons:
            if not any(keyword in btn['text'] for keyword in ['accept all', 'allow all', 'agree to all']):
                try:
                    print(f" -> Last resort - trying: '{btn['text']}'")
                    data["settings_button_present"] = True
                    data["settings_button_text"] = btn['text']
                    
                    # Try multiple click methods
                    try:
                        driver.execute_script("arguments[0].click();", btn['element'])
                    except:
                        btn['element'].click()
                    
                    data["preference_center_accessed"] = True
                    time.sleep(3)
                    return True
                except Exception as e:
                    print(f"    Failed to click: {e}")
                    continue
        
        data["error_log"].append(f"No clickable settings button found among {len(visible_buttons)} buttons")
        return False

    except Exception as e:
        data["error_log"].append(f"Enhanced button finder failed: {type(e).__name__}")
        return False

def extract_enhanced_data(driver, data):
    """Enhanced data extraction with comprehensive analysis - KEEPING SUCCESSFUL PURPOSE_JSON LOGIC."""
    try:
        # Wait for preference center content with multiple strategies
        wait_selectors = [
            "div[id*='pc-content']", "div[class*='ot-sdk-container']", "div[class*='cookie']", 
            "div[class*='consent']", "div[class*='preference']", "div[class*='settings']",
            "div[role='dialog']", "div[role='tabpanel']"
        ]
        
        content_found = False
        for selector in wait_selectors:
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                content_found = True
                break
            except TimeoutException:
                continue
        
        if not content_found:
            # Try one more time with any new content
            time.sleep(2)

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # CMP Vendor Detection
        data["cmp_vendor"] = detect_cmp_vendor(driver, soup)
        
        # KEEPING THE SUCCESSFUL PURPOSE EXTRACTION LOGIC FROM ENHANCED SCRIPT
        purpose_selectors = [
            # OneTrust
            '.ot-cat-item', 'div[class*="ot-cat"]', 'div.ot-accordion-layout',
            # Cookiebot  
            'div[class*="purpose-item"]', 'div[class*="category"]', 'div[data-cookieconsent]',
            # TrustArc
            'div[class*="trustarc"]', 'div[class*="truste"]',
            # Generic
            'div[class*="purpose"]', 'div[class*="consent-item"]', 'div[class*="cookie-category"]',
            'div[role="checkbox"]', 'label[class*="consent"]', 'fieldset',
            # Fallback
            'label', 'li[class*="purpose"]', 'tr[class*="purpose"]'
        ]
        
        purpose_items = []
        for selector in purpose_selectors:
            items = soup.select(selector)
            if items:
                purpose_items.extend(items)
        
        # Remove duplicates
        purpose_items = list(set(purpose_items))
        
        purposes_list = []
        
        for item in purpose_items:
            # Enhanced title extraction
            title_element = (
                item.find(['h3', 'h4', 'h5'], class_=lambda c: c and any(x in str(c).lower() for x in ['title', 'header', 'name', 'label'])) or
                item.find(['h3', 'h4', 'h5']) or
                item.find('label') or
                item.find(['span', 'div'], class_=lambda c: c and any(x in str(c).lower() for x in ['title', 'name']))
            )
            
            if title_element:
                title = title_element.get_text(strip=True)
            else:
                # Fallback - use any text in the item
                title = item.get_text(strip=True).split('\n')[0]  # First line
            
            # Filter out invalid titles
            if (len(title) < 3 or len(title) > 200 or 
                title.lower() in ['on', 'off', 'yes', 'no', 'true', 'false', 'ok']):
                continue
                
            checkbox = item.find('input', type='checkbox')
            is_ticked = checkbox and checkbox.has_attr('checked')
            is_disabled = checkbox and checkbox.has_attr('disabled')
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

        data["total_purposes_count"] = len(purposes_list)
        data["purposes_json"] = json.dumps(purposes_list)
        
        # Enhanced Vendor Count Detection
        vendor_selectors = [
            '.vendor-list-container', '#vendor-list', 'div[class*="vendor"]', 
            'div[class*="partner"]', '[class*="third-party"]', 'div[class*="suppliers"]',
            'ul[class*="vendor"]', 'table[class*="vendor"]'
        ]
        
        vendor_count = 0
        for selector in vendor_selectors:
            vendor_section = soup.select_one(selector)
            if vendor_section:
                vendors = vendor_section.select('.vendor-list-item, li, div[class*="vendor-row"], tr, .vendor-item')
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
        
        # Status determination
        if data["total_purposes_count"] > 0:
            data["status"] = "Success"
        elif data["preference_center_accessed"]:
            data["status"] = "Partial"
        else:
            data["status"] = "Failed"

    except Exception as e:
        data["error_log"].append(f"Enhanced data extraction failed: {type(e).__name__}")
        data["status"] = "Failed"

def analyze_consent_banner_enhanced(driver, data):
    """Enhanced consent banner analysis with robust button detection and legal text extraction."""
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
            "div[role='banner']",
            "div[role='region']",
            "[class*='notice']",
            "[class*='popup']",
            "[class*='modal']"
        ]
        
        banner = None
        for selector in banner_selectors:
            try:
                banner = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                print(f" -> Found banner with selector: {selector}")
                break
            except TimeoutException:
                continue
        
        if not banner:
            data["status"] = "Failed"
            data["error_log"].append("No consent banner found")
            return

        data["initial_banner_found"] = True
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # ENHANCED LEGAL TEXT EXTRACTION - NEW IMPROVED LOGIC
        enhanced_legal_text_extraction(driver, banner, data)
        
        # Dark Patterns Analysis
        data["dark_pattern_score"] = analyze_dark_patterns(soup, banner, data)
        
        # CMP Vendor Detection
        data["cmp_vendor"] = detect_cmp_vendor(driver, soup)
        
        # Enhanced button detection and interaction
        if not enhanced_positional_button_finder(driver, banner, data):
            data["status"] = "Partial (Interaction Failed)"
            return

        # Enhanced data extraction
        extract_enhanced_data(driver, data)
        
        # Final compliance scoring
        data["compliance_score"] = calculate_compliance_score(data)
        
        # GDPR Article 13 compliance check
        compliance_indicators = 0
        text_lower = data["legal_text_summary"].lower()
        
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
        
        data["gdpr_article_13_compliance"] = compliance_indicators >= 4
        
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
        
        if result.get('legal_text_summary'):
            print(f"Legal Text Length: {len(result['legal_text_summary'])} chars")
        
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
    print(f"Partial extractions: {len(final_df[final_df['status'].str.contains('Partial', na=False)])}")
    print(f"Failed extractions: {len(final_df[final_df['status'] == 'Failed'])}")
    print(f"Average compliance score: {final_df['compliance_score'].mean():.2f}")
    print(f"Most common CMP vendor: {final_df['cmp_vendor'].mode().iloc[0] if not final_df['cmp_vendor'].mode().empty else 'N/A'}")
    print(f"Websites with dark patterns: {len(final_df[final_df['dark_pattern_score'] > 0])}")
    print(f"GDPR Article 13 compliant: {len(final_df[final_df['gdpr_article_13_compliance'] == True])}")
    print(f"Sites with substantial legal text: {len(final_df[final_df['legal_text_summary'].str.len() > 100])}")
    print(f"\nResults saved to: {OUTPUT_CSV_FILE}")

if __name__ == "__main__":
    main()
