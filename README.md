# Automated Assessment of Cookie Consent Dialogues for GDPR Compliance

This project presents an end-to-end system for automatically assessing the GDPR compliance of website cookie consent banners. It combines web scraping, Natural Language Processing (NLP), and structural analysis to detect dark patterns and evaluate banners against GDPR requirements. The project culminates in a Streamlit web application that provides real-time compliance analysis for any given URL.

## 1. Project Overview

The General Data Protection Regulation (GDPR) mandates that user consent for data processing must be freely given, specific, informed, and unambiguous. However, many websites employ "dark patterns" in their cookie banners to nudge users toward less private choices, undermining the principle of informed consent.

This project addresses the challenge of manually auditing these banners at scale by providing an automated solution.

### Key Objectives:
1.  **Automated Data Collection:** Develop a web crawler to automatically extract content and structural data from cookie consent dialogues across a wide range of websites.
2.  **Dark Pattern Detection:** Utilize an NLP model to analyze textual content and a rules-based engine to analyze structural features, identifying common dark patterns like **Obstruction**, **Interface Interference**, and **Pre-ticked Boxes**.
3.  **Semantic Standardization:** Map unstructured consent-related text to the standardized **Data Privacy Vocabulary (DPV-2)** to create machine-readable compliance metadata.
4.  **Real-time Analysis Tool:** Build an interactive web application that allows users to input a URL and receive an instant, multi-faceted compliance report.

## 2. Methodology

The project follows a multi-stage methodology, from data collection to the final deployment of the analysis tool.

### a. Data Collection and Preprocessing

A resilient web crawler was built using **Python** and **Selenium WebDriver**. The crawler was designed to:
- Navigate to target URLs and handle dynamic, JavaScript-rendered content.
- Accurately identify and extract the HTML content and text from cookie banners.
- Interact with banner elements (e.g., "Settings" buttons) to access second-layer consent preferences.
- Collect interaction metrics, such as the number of clicks required to accept versus reject cookies.

The collected data was sourced from over 300 websites across various domains.

### b. Manual Annotation and Dataset Creation

A crucial step was the manual annotation of the collected data to create a high-quality dataset for model training. This process involved:
- **Compliance Labeling:** Each banner was meticulously checked against GDPR Article 13 requirements and EDPB guidelines.
- **Dark Pattern Classification:** Design elements were systematically classified into established dark pattern taxonomies.
- **Data Consolidation:** The annotated data was merged with the crawler's output to create the final `final_annotated_dataset.csv`, which contains 31 unique attributes per entry.

### c. Model Development and Training

A multi-label classification model was developed to detect dark patterns automatically.
- **Architecture:** The model uses a hybrid approach, combining textual and structural features.
  - **Text Encoder:** A pre-trained `SentenceTransformer` model (`all-MiniLM-L6-v2`) generates 384-dimensional embeddings from the banner text.
  - **Feature Integration:** These embeddings are concatenated with eight numerical features (e.g., click counts, compliance scores, policy link presence).
  - **Classifier:** A `OneVsRestClassifier` with a `LogisticRegression` base estimator predicts the presence of multiple dark patterns simultaneously.
- **Training:** The model was trained on the annotated dataset using a 5-fold cross-validation strategy to ensure robustness and prevent overfitting. The final trained model, along with the TF-IDF vectorizer and scaler, is saved in the `/model` directory.

### d. Compliance Scoring Algorithm

A quantitative compliance score is calculated based on a checklist derived from GDPR requirements:
- **Choice Equality (-30 points):** If rejecting cookies requires more clicks than accepting.
- **Default Settings (-30 points):** If non-essential cookies are pre-ticked by default.
- **Information Transparency (-15 points):** If a link to the privacy policy is missing.
- **Purpose Specificity (-15 points):** If the purposes of data processing are unclear.
- **Contact Information (-5 points):** If controller contact details are not provided.
- **Data Retention (-5 points):** If the data retention period is not mentioned.

## 3. The Streamlit Application

The core of this project is the interactive dashboard built with **Streamlit**. It provides a user-friendly interface for real-time compliance analysis.

### Features:
- **URL Analysis:** Users can enter any website URL to initiate a compliance check.
- **Live Scraping:** If the URL is not in the pre-analyzed dataset, the application performs live scraping to fetch the consent banner content.
- **Key Metrics:** Displays the **Overall Compliance Score**, **Banner Compliance Score**, and the number of **Dark Patterns Detected**.
- **GDPR Article 13 View:** Visualizes the website's compliance with key requirements of GDPR Article 13 in an easy-to-read lollipop chart.
- **Dark Pattern Analysis:** Presents a table detailing which specific dark patterns were detected.
- **Data Processing Purposes:** Shows a donut chart of the DPV-2 concepts identified in the banner text.

## 4. How to Run the Project

To run the GDPR Compliance Dashboard locally, follow these steps:

### Prerequisites
- Python 3.9+
- `pip` for package management

### Installation
1.  **Clone the repository:**
    ```bash
    git clone https://github.com/sfarhan28/2025-mcm-structured-metadata-extraction-master.git
    cd src
    ```
2.  **Install the required dependencies:**
    A `requirements.txt` file should be created containing all necessary packages.
    ```bash
    pip install -r requirements.txt
    ```

### Running the App
Execute the following command in your terminal:
```bash
streamlit run app.py
```
This will start the application, and you can access it in your web browser at the local URL provided (`http://localhost:8501`).

## 5. Important Files & Folders

- app.py: The main Streamlit application file.
- selenium_scraper.py: Module containing the web scraping logic.
- final_annotated_dataset.csv: The primary dataset used by the application.
- model/: Directory containing the trained machine learning model (final_multi_label_model.pth), scaler, and vectorizer.
