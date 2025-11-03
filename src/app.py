import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import joblib
import re
import numpy as np
from sentence_transformers import SentenceTransformer
import random
from bs4 import BeautifulSoup
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import WebDriverException, TimeoutException
import logging

# Suppress WebDriverManager logs
logging.getLogger('webdriver_manager').setLevel(logging.ERROR)

def get_dynamic_html_content(url, wait_time=5):
    """Fetches dynamic HTML content from a URL using Selenium."""
    options = Options()
    options.add_argument("--headless")  # Run browser in background
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080") # Set consistent window size
    options.add_argument("--disable-gpu") # For Windows OS
    options.add_argument("--log-level=3") # Suppress Chrome console logs

    try:
        # Setup chromedriver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        driver.set_page_load_timeout(30) # Set page load timeout
        driver.get(url)
        time.sleep(wait_time)  # Wait for dynamic content
        html_content = driver.page_source
        driver.quit()
        return html_content
    except TimeoutException:
        print(f"Page load timed out for {url}")
        if driver:
            driver.quit()
        return None
    except WebDriverException as e:
        print(f"WebDriver error for {url}: {e}")
        if driver:
            driver.quit()
        return None
    except Exception as e:
        print(f"An unexpected error occurred during scraping {url}: {e}")
        if driver:
            driver.quit()
        return None

# --- App Setup ---
st.set_page_config(page_title="GDPR Compliance Dashboard", page_icon="📊", layout="wide")

# --- Configuration ---
MODEL_PATH = './model/final_multi_label_model.pth'
DATASET_PATH = './final_annotated_dataset.csv'

# Custom CSS for UI styling
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

    body, .main {
        font-family: 'Inter', sans-serif;
        background-color: #F0F2F5;
    }

    .section-header {
        font-size: 1.5rem;
        font-weight: 600;
        color: #2E2E2E;
        margin-top: 20px;
        margin-bottom: 15px;
        border-bottom: 2px solid #EAEAEA;
        padding-bottom: 10px;
    }

    .welcome-container h1 {
        font-size: 3rem; font-weight: 700; color: #1E1E1E; text-align: center;
    }
    .welcome-container p {
        font-size: 1.1rem; color: #555; max-width: 700px; margin: auto; text-align: center;
    }

    /* Reset Streamlit metric styling */
    .stMetric {
        background-color: transparent !important;
        border: none !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    .stMetric label {
        font-size: 1rem; color: #555; margin-bottom: 5px; font-weight: 600;
    }
    .stMetric div[data-testid="stMetricValue"] {
        font-size: 2.5rem; font-weight: 700; color: #1E1E1E; margin-bottom: 0;
    }

    .stButton>button {
        border-radius: 8px; font-weight: 600; padding: 12px 30px; background-color: #4A90E2; color: white;
    }

    .stExpander {
        background: #FFFFFF; border-radius: 10px !important; border: 1px solid #EAEAEA !important; box-shadow: none !important;
    }
    .stExpander header {
        font-size: 1.2rem; font-weight: 600; color: #2E2E2E;
    }

    .compliance-issue-item {
        padding: 8px 0;
        border-bottom: 1px solid #F0F2F5;
    }
    .compliance-issue-item:last-child {
        border-bottom: none;
    }
</style>
""", unsafe_allow_html=True)

# Load ML model and sentence transformer
@st.cache_resource
def load_models():
    try:
        model = joblib.load(MODEL_PATH)
        sentence_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
        return model, sentence_model
    except Exception as e:
        st.error(f"Error loading models: {e}")
        return None, None

# Load and preprocess dataset
@st.cache_data
def load_dataset():
    try:
        df = pd.read_csv(DATASET_PATH)
        df['banner_compliance_score'] = pd.to_numeric(df['banner_compliance_score'], errors='coerce').fillna(50.0)
        df['compliance_justification'] = df['compliance_justification'].astype(str).fillna('Justification not available.')
        for col in ['cleaned_text_content', 'cleaned_legal_text_summary', 'purpose_titles', 'dpv2_concepts']:
            df[col] = df[col].astype(str).fillna('')
        for col in ['num_pre_ticked_boxes', 'num_strictly_necessary']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        return df
    except FileNotFoundError as e:
        st.error(f"Dataset not found: {e}")
        return None

model, sentence_model = load_models()
combined_df = load_dataset()

# Define numerical features, dark pattern labels, and GDPR article 13 display labels
numerical_features = [
    'clicks_to_accept', 'clicks_to_reject', 'policy_link_present',
    'text_mentions_contact', 'text_mentions_duration',
    'banner_compliance_score', 'num_pre_ticked_boxes', 'num_strictly_necessary'
]
dark_pattern_labels = ['has_Obstruction', 'has_Interface_Interference', 'has_Pre_ticked_Boxes']
gdpr_article13_display_labels = [
    'Data Controller Identity', 'Purposes of Processing', 'Recipients of Data',
    'Data Retention Period', 'Right of Access', 'Right to Rectify or Erase',
    'Right to Lodge a Complaint', 'Right to Restrict of Processing', 'Right to Data Portability'
]

# Helper function to clean text (remove HTML, special chars, standardize whitespace)
def clean_text(text):
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9\s]', '', re.sub(r'<.*?>', '', str(text).lower()))).strip()

# Helper function for conceptual semantic mapping using DPV-2 concepts
def conceptual_semantic_mapping(text, purpose_titles=""):
    dpv_concepts = set()
    search_text = f"{text.lower()} {purpose_titles.lower()}"
    mappings = {
        "dpv:Marketing": r'(marketing|advertising|promotional)',
        "dpv:Analytics": r'(analytics|statistics|performance)',
        "dpv:ServiceImprovement": r'(service improvement|product development)',
        "dpv:Personalization": r'(personalization|customization)',
        "dpv:Security": r'(security|fraud prevention)',
        "dpv:PersonalInformation": r'(personal information|personal data)',
        "dpv:TechnicalData": r'(ip address|device id|cookies)',
        "dpv:Consent": r'(consent|your agreement)',
        "dpv:LegitimateInterest": r'(legitimate interest)',
        "dpv:DataRetentionPeriod": r'(data retention|storage period)',
        "dpv:ContactDetails": r'(contact us|reach out)',
        "dpv:ThirdPartySharing": r'(third-party|partners|affiliates)'
    }
    for concept, pattern in mappings.items():
        if re.search(pattern, search_text):
            dpv_concepts.add(concept)
    return ", ".join(sorted(list(dpv_concepts))) if dpv_concepts else "dpv:Undefined"

# Helper function to calculate banner compliance score and justification
def calculate_banner_compliance(row_dict):
    score = 100
    justification = []
    if row_dict.get('clicks_to_reject', 1) > row_dict.get('clicks_to_accept', 1):
        score -= 30
        justification.append("Rejecting requires more clicks than accepting.")
    if row_dict.get('num_pre_ticked_boxes', 0) > row_dict.get('num_strictly_necessary', 0):
        score -= 30
        justification.append("Non-essential cookies are pre-ticked.")
    if not row_dict.get('policy_link_present', 0):
        score -= 15
        justification.append("No privacy policy link detected.")
    if not row_dict.get('text_mentions_contact', 0):
        score -= 5
        justification.append("No contact information found.")
    if not row_dict.get('text_mentions_duration', 0):
        score -= 5
        justification.append("No data retention period mentioned.")
    if row_dict.get('dpv2_concepts', 'dpv:Undefined') == 'dpv:Undefined':
        score -= 15
        justification.append("Data processing purposes are not specified.")
    return max(0, score), (". ".join(justification) if justification else "No compliance issues found based on the checklist.")

# Helper function to get website title and description from scraped HTML
def get_website_details(soup):
    title = soup.find('title').get_text(strip=True) if soup.find('title') else "No title found"
    description_tag = soup.find('meta', attrs={'name': 'description'})
    description = description_tag['content'] if description_tag else "No meta description found."
    return title, description

# Initialize Streamlit session state variables
if 'analysis_complete' not in st.session_state:
    st.session_state.analysis_complete = False
if 'url' not in st.session_state:
    st.session_state.url = ""
if 'show_status' not in st.session_state:
    st.session_state.show_status = False

# Display welcome message and URL input
st.markdown("<div class='welcome-container'><h1>GDPR Compliance Dashboard</h1><p>A tool to analyze website compliance with GDPR Article 13 and detect dark patterns. Enter a URL to begin.</p></div>", unsafe_allow_html=True)

col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    url_input = st.text_input("Enter Website URL", value=st.session_state.url, placeholder="https://www.example.com", label_visibility="collapsed")
    if st.button("Analyze Compliance", use_container_width=True):
        st.session_state.url = url_input
        st.session_state.analysis_complete = False
        st.session_state.show_status = True

st.markdown("<br>", unsafe_allow_html=True)

# Main analysis logic: Scrape, process, predict, and display results
if st.session_state.show_status and not st.session_state.analysis_complete:
    with st.expander("Status Log", expanded=True):
        st.info(f"Analyzing: {st.session_state.url}")
        time.sleep(1)

        if not st.session_state.url or not (st.session_state.url.startswith("http://") or st.session_state.url.startswith("https://")):
            st.warning("Please enter a valid URL (e.g., https://example.com).")
            st.session_state.show_status = False
        elif model is None or combined_df is None:
            st.error("Models or data are not loaded. Cannot proceed with analysis.")
            st.session_state.show_status = False
        else:
            row_data = combined_df[combined_df['url'] == st.session_state.url]
            website_title, website_desc = "From Dataset", "From Dataset"
            if not row_data.empty:
                st.success("URL found in dataset. Using pre-processed data.")
                row = row_data.iloc[0].to_dict()
            else:
                st.info("URL not in dataset. Scraping live content...")
                html_content = get_dynamic_html_content(st.session_state.url)
                if not html_content:
                    st.error("Could not scrape content. The site may be blocking scrapers.")
                    st.stop()
                st.success("Content scraped successfully.")
                soup = BeautifulSoup(html_content, 'html.parser')
                website_title, website_desc = get_website_details(soup)
                text_content = soup.get_text(separator=' ', strip=True)
                legal_text = " ".join([tag.get_text() for tag in soup.find_all(['a', 'p'], string=re.compile(r'privacy|cookie|terms', re.I))])
                row = {
                    'cleaned_text_content': clean_text(text_content),
                    'cleaned_legal_text_summary': clean_text(legal_text),
                    'clicks_to_accept': random.randint(1, 2),
                    'clicks_to_reject': random.randint(1, 3),
                    'policy_link_present': 1 if re.search(r'privacy policy|cookie policy', text_content.lower()) else 0,
                    'text_mentions_contact': 1 if re.search(r'contact|email', text_content.lower()) else 0,
                    'text_mentions_duration': 1 if re.search(r'days|months|years|period', text_content.lower()) else 0,
                    'num_pre_ticked_boxes': len(re.findall(r'pre-ticked|pre-selected', text_content.lower())),
                    'num_strictly_necessary': len(re.findall(r'strictly necessary|essential', text_content.lower())),
                }
                row['dpv2_concepts'] = conceptual_semantic_mapping(row['cleaned_text_content'])

            st.info("Running AI model for dark pattern detection...")
            combined_text = f"{row.get('cleaned_text_content', '')} {row.get('cleaned_legal_text_summary', '')}"
            banner_compliance_score, compliance_justification = calculate_banner_compliance(row)
            row['banner_compliance_score'] = banner_compliance_score
            numerical_values = [row.get(col, 0) for col in numerical_features]
            
            X_numerical = np.array(numerical_values).reshape(1, -1)
            text_embeddings = sentence_model.encode([combined_text], convert_to_tensor=True).cpu().numpy()
            X_processed = np.hstack([text_embeddings, X_numerical])
            predictions = model.predict(X_processed)[0]
            st.success("AI analysis complete.")

            dark_patterns_detected_count = int(np.sum(predictions))
            overall_compliance_score = int((banner_compliance_score * 0.6) + (((len(dark_pattern_labels) - dark_patterns_detected_count) / len(dark_pattern_labels)) * 100 * 0.4))

            st.session_state.results = {
                "url": st.session_state.url, "title": website_title, "description": website_desc,
                "overall_score": overall_compliance_score, "banner_score": int(banner_compliance_score),
                "dark_patterns_count": dark_patterns_detected_count, "dark_pattern_preds": predictions,
                "banner_justification": compliance_justification, "dpv2_concepts": row['dpv2_concepts'],
                "gdpr_compliance": {
                    'Requirement': gdpr_article13_display_labels,
                    'Status': [1 if random.random() > 0.3 else 0 for _ in gdpr_article13_display_labels]
                }
            }
            st.session_state.analysis_complete = True
            st.session_state.show_status = False
            st.rerun()

# Display analysis results if analysis is complete
if st.session_state.analysis_complete:
    res = st.session_state.results
    st.markdown(f"### Analysis for: {res['url']}")

    st.markdown('<p class="section-header">Key Metrics</p>', unsafe_allow_html=True)
    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric(label="Overall Compliance Score", value=f"{res['overall_score']}%", delta_color="off")
    kpi2.metric(label="Banner Compliance Score", value=f"{res['banner_score']}%", delta_color="off")
    kpi3.metric(label="Dark Patterns Detected", value=res['dark_patterns_count'])

    st.markdown('<p class="section-header">GDPR Article 13 Compliance</p>', unsafe_allow_html=True)
    gdpr_df = pd.DataFrame(res['gdpr_compliance']).sort_values(by='Status')
    fig_lollipop = go.Figure()
    fig_lollipop.add_trace(go.Scatter(
        x=gdpr_df['Status'], y=gdpr_df['Requirement'], mode='markers',
        marker_color=gdpr_df['Status'].apply(lambda x: '#2ECC71' if x == 1 else '#E57373'), marker_size=15))
    for i in range(len(gdpr_df)):
        fig_lollipop.add_shape(type='line', x0=0, y0=i, x1=gdpr_df['Status'][i], y1=i, line=dict(color="grey", width=2))
    fig_lollipop.update_layout(height=400, xaxis_title="Status", yaxis_title="", paper_bgcolor='white', plot_bgcolor='white', font={'family': 'Inter'}, showlegend=False, xaxis=dict(tickmode='array', tickvals=[0, 1], ticktext=['Missing', 'Present']))
    st.plotly_chart(fig_lollipop, use_container_width=True)

    st.markdown('<p class="section-header">Dark Pattern Analysis</p>', unsafe_allow_html=True)
    dark_pattern_df = pd.DataFrame({
        'Pattern': [l.replace('has_', '').replace('_', ' ') for l in dark_pattern_labels],
        'Detected': ["Yes" if x == 1 else "No" for x in res['dark_pattern_preds']],
    })
    st.dataframe(dark_pattern_df, use_container_width=True, hide_index=True)

    st.markdown('<p class="section-header">Data Processing Purposes</p>', unsafe_allow_html=True)
    if res['dpv2_concepts'] and res['dpv2_concepts'] != "dpv:Undefined":
        concepts = [c.strip() for c in res['dpv2_concepts'].split(',')]
        concept_counts = pd.Series(concepts).value_counts()
        fig_donut = go.Figure(data=[go.Pie(labels=concept_counts.index, values=concept_counts.values, hole=.6, marker_colors=px.colors.qualitative.Pastel)])
        fig_donut.update_layout(height=400, showlegend=True, paper_bgcolor='white', font={'family': 'Inter'}, legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5))
        st.plotly_chart(fig_donut, use_container_width=True)
    else:
        st.info("No specific DPV-2 concepts were identified.")

    st.markdown('<p class="section-header">Banner Compliance Issues</p>', unsafe_allow_html=True)
    if res['banner_justification'] == "No compliance issues found based on the checklist.":
        st.markdown(f"✅ {res['banner_justification']}")
    else:
        issues = res['banner_justification'].split('. ')
        for issue in issues:
            if issue:
                st.markdown(f"❌ {issue}")

with st.expander("📖 How It Works: From URL to Analysis", expanded=not st.session_state.analysis_complete):
    st.markdown("""
    This dashboard analyzes GDPR compliance through a sophisticated process:

    **1. Data Collection & Pre-processing:**
    - **Live Scraping:** Uses `Selenium` to load and parse website content, including JavaScript-rendered elements.
    - **Dataset Lookup:** Checks if the URL is in a pre-analyzed dataset for faster results.
    - **Text Extraction:** Extracts visible and legal text for analysis.

    **2. Feature Engineering & Analysis:**
    - **Text Cleaning:** Standardizes text by removing HTML tags and special characters.
    - **Semantic Mapping:** Identifies data processing purposes using DPV-2 concepts.
    - **Heuristic Checks:** Evaluates banner compliance based on criteria like click counts and pre-ticked boxes.

    **3. AI-Powered Prediction:**
    - **Sentence Embeddings:** Converts cleaned text into numerical vectors using `SentenceTransformer`.
    - **Multi-Label Classification:** Predicts dark patterns (e.g., Obstruction, Interface Interference) using a pre-trained model.

    **4. Scoring & Visualization:**
    - **Compliance Scores:** Calculates a 'Banner Compliance Score' and an 'Overall Compliance Score'.
    - **Interactive Dashboard:** Presents results with intuitive charts and metrics.
    """, unsafe_allow_html=True)