import pandas as pd
import numpy as np
import re

def clean_data(input_path, output_path, log_path):
    with open(log_path, 'a') as f:
        f.write("## Phase 1: Data Cleaning and Preparation\n")
        f.write(f"Loading data from {input_path}\n")

    try:
        df = pd.read_csv(input_path)
        with open(log_path, 'a') as f:
            f.write("Data loaded successfully.\n")
    except Exception as e:
        with open(log_path, 'a') as f:
            f.write(f"Error loading data: {e}\n")
        return

    with open(log_path, 'a') as f:
        f.write("### Initial Data Analysis\n")
        f.write(f"Shape of the dataset: {df.shape}\n")
        f.write("Data types of each column:\n")
        f.write(str(df.dtypes) + "\n")
        f.write("Summary of missing values per column:\n")
        f.write(str(df.isnull().sum()) + "\n")
        f.write(f"Number of duplicate rows: {df.duplicated().sum()}\n")

    # Data Cleaning and Imputation
    df['text_content'] = df['text_content'].fillna('')
    df['legal_text_summary'] = df['legal_text_summary'].fillna('')
    df['html_content'] = df['html_content'].fillna('')

    df['clicks_to_accept'] = df['clicks_to_accept'].fillna(df['clicks_to_accept'].median())

    boolean_like_cols = [
        'accept_btn_prominent', 'reject_hidden_in_settings', 'policy_link_present',
        'text_mentions_contact', 'text_mentions_duration'
    ] + [col for col in df.columns if col.startswith('has_')]

    map_to_int = lambda x: 1 if str(x).strip().upper() in ['TRUE', '1', '1.0'] else 0

    for col in boolean_like_cols:
        if col in df.columns:
            df[col] = df[col].apply(map_to_int)
            df[col] = df[col].fillna(0).astype(int)

    with open(log_path, 'a') as f:
        f.write("\n### Imputation Strategy Justification\n")
        f.write("Missing values in boolean-like columns are imputed with 0 (False) after attempting to map all values to 1/0. This assumes a null value signifies the absence of the feature.\n")

    # Sanitize text fields
    def sanitize_text(text):
        if isinstance(text, str):
            return re.sub(r'\s+', ' ', text).strip()
        return text

    for col in ['text_content', 'legal_text_summary']:
        if col in df.columns:
            df[col] = df[col].apply(sanitize_text)

    # --- Advanced Feature Engineering ---
    with open(log_path, 'a') as f:
        f.write("\n### Advanced Feature Engineering\n")
        f.write("Creating new features: text_length, num_links, num_buttons.\n")

    # Calculate text length
    df['text_length'] = df['text_content'].str.len()

    # Count links and buttons in HTML
    df['num_links'] = df['html_content'].str.count('<a ')
    df['num_buttons'] = df['html_content'].str.count('<button')

    # Fill any potential NaNs in new features
    df['text_length'] = df['text_length'].fillna(0).astype(int)
    df['num_links'] = df['num_links'].fillna(0).astype(int)
    df['num_buttons'] = df['num_buttons'].fillna(0).astype(int)

    with open(log_path, 'a') as f:
        f.write("\n### Final Cleaned Data Types\n")
        f.write(str(df.dtypes) + "\n")

    try:
        df.to_csv(output_path, index=False)
    except PermissionError:
        import os
        os.remove(output_path)
        df.to_csv(output_path, index=False)

    with open(log_path, 'a') as f:
        f.write("\n### Data Cleaning and Preparation Complete\n")
        f.write(f"Cleaned data saved to {output_path}\n")

if __name__ == '__main__':
    INPUT_DATA_PATH = '/new_mix.csv'
    CLEANED_DATA_PATH = '/cleaned_gdpr_dataset.csv'
    clean_data(INPUT_DATA_PATH, CLEANED_DATA_PATH,)