import streamlit as st
import pandas as pd
import numpy as np
import torch
import re
from bs4 import BeautifulSoup
from transformers import BertTokenizer, BertForSequenceClassification
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# App/model configuration
MODEL_PATH = './gdpr_compliance_model'
LABEL_COLUMNS = [
    'has_Collect_Personal_Information', 'has_Data_Retention_Period', 
    'has_Data_Processing_Purposes', 'has_Contact_Details', 'has_Right_to_Access', 
    'has_Right_to_Rectify_or_Erase', 'has_Right_to_Restrict_of_Processing', 
    'has_Right_to_Object_to_Processing', 'has_Right_to_Data_Portability', 
    'has_Right_to_Lodge_a_Complaint', 'has_Obstruction', 
    'has_Interface_Interference', 'has_Pre_ticked_Boxes'
]
MAX_LEN = 256
COOKIE_BANNER_SELECTORS = [
    '[id*="consent"]', '[class*="consent"]', '[id*="cookie"]', '[class*="cookie"]',
    '[id*="banner"]', '[class*="banner"]', '[id*="notice"]', '[class*="notice"]',
    '#onetrust-banner-sdk', '#truste-consent-track'
]

# Cache model and tokenizer for faster inference
@st.cache_resource
def load_model_and_tokenizer(model_path):
    print("Loading model and tokenizer for the first time...")
    model = BertForSequenceClassification.from_pretrained(model_path)
    tokenizer = BertTokenizer.from_pretrained(model_path)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model.to(device)
    return model, tokenizer, device

# Website scraping using Selenium
def scrape_website(url):
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument("--log-level=3")

    driver = None
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.get(url)
        wait = WebDriverWait(driver, 15)
        combined_selector = ", ".join(COOKIE_BANNER_SELECTORS)
        
        banner_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, combined_selector)))
        
        html_content = banner_element.get_attribute('outerHTML')
        soup = BeautifulSoup(html_content, 'html.parser')
        text_content = soup.get_text(separator=' ', strip=True)
        
        return {'success': True, 'text': text_content, 'html': html_content}
    except Exception as e:
        return {'success': False, 'error': str(e)}
    finally:
        if driver:
            driver.quit()

# Run model prediction on banner text
def predict_compliance(text, model, tokenizer, device):
    model.eval()
    inputs = tokenizer.encode_plus(
        text, None, add_special_tokens=True, max_length=MAX_LEN, padding='max_length',
        return_token_type_ids=False, truncation=True, return_attention_mask=True, return_tensors='pt'
    )
    
    input_ids = inputs['input_ids'].to(device)
    attention_mask = inputs['attention_mask'].to(device)
    
    with torch.no_grad():
        outputs = model(input_ids=input_ids, attention_mask=attention_mask)
        logits = outputs.logits
        
    predictions = torch.sigmoid(logits).cpu().numpy() > 0.5
    return dict(zip(LABEL_COLUMNS, predictions[0]))

# Additional compliance checks using heuristics
def analyze_extra_compliance(html_content, text_content):
    results = {}
    soup = BeautifulSoup(html_content, 'html.parser')

    if re.search(r'advertising|marketing', text_content, re.I):
        results['DPV-2 Concept'] = 'dpv:Marketing'
    elif re.search(r'analytics|statistics', text_content, re.I):
        results['DPV-2 Concept'] = 'dpv:Analytics'
    else:
        results['DPV-2 Concept'] = 'Not Identified'
        
    results['ISO: Layered Notice'] = bool(soup.find('a', href=re.compile(r'policy|privacy|settings')))
    results['ISO: Freely Given Consent'] = bool(soup.find(lambda tag: tag.name in ['button', 'a'] and re.search(r'reject|decline', tag.text, re.I)))
    
    return results

# Streamlit UI setup
st.set_page_config(page_title="GDPR Compliance Analyzer", layout="wide")
st.title("🤖 GDPR Compliance Analysis System")
st.markdown("This application uses a fine-tuned BERT model to analyze the cookie consent dialogues of websites for GDPR compliance and dark patterns.")

model, tokenizer, device = load_model_and_tokenizer(MODEL_PATH)

st.header("Enter a Website URL to Analyze")
url = st.text_input("e.g., https://www.example.com", "")

if st.button("Analyze Website"):
    if url:
        with st.spinner("Scraping website and analyzing content... This may take a moment."):
            scrape_result = scrape_website(url)
            
            if not scrape_result['success']:
                st.error("Failed to scrape the website. Error: Could not find a cookie banner or the site is protected.")
            else:
                text_content = scrape_result['text']
                html_content = scrape_result['html']
                
                model_predictions = predict_compliance(text_content, model, tokenizer, device)
                extra_analysis = analyze_extra_compliance(html_content, text_content)

        st.success("Analysis Complete!")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("✅ GDPR Compliance Checklist")
            for label, is_present in model_predictions.items():
                if 'has_' in label and 'Interface' not in label and 'Obstruction' not in label and 'Pre_ticked' not in label:
                    if is_present:
                        st.markdown(f"**{label.replace('has_', '')}:** <span style='color:green;'>✔️ Found</span>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"**{label.replace('has_', '')}:** <span style='color:red;'>❌ Not Found</span>", unsafe_allow_html=True)
        
        with col2:
            st.subheader("🕵️ Dark Pattern Detection")
            for label, is_present in model_predictions.items():
                if 'Interface' in label or 'Obstruction' in label or 'Pre_ticked' in label:
                    if is_present:
                        st.markdown(f"**{label.replace('has_', '')}:** <span style='color:red;'>⚠️ Detected</span>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"**{label.replace('has_', '')}:** <span style='color:green;'>✔️ Not Detected</span>", unsafe_allow_html=True)
            
            st.subheader("🏛️ Standards Mapping")
            for key, value in extra_analysis.items():
                # Show standards mapping results
                if isinstance(value, bool):
                    if value:
                        status_html = "<span style='color:green;'>✔️ Yes</span>"
                    else:
                        status_html = "<span style='color:red;'>❌ No</span>"
                    st.markdown(f"**{key}:** {status_html}", unsafe_allow_html=True)
                else:
                    st.markdown(f"**{key}:** {value}")

        with st.expander("Show Raw Scraped Text"):
            st.text_area("Text Content from Banner", text_content, height=250)

    else:
        st.warning("Please enter a URL to analyze.")
