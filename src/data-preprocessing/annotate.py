import pandas as pd
import re
from bs4 import BeautifulSoup
import json
import numpy as np

# --- Configuration ---
INPUT_CSV_PATH = 'data_for_annotation.csv'
OUTPUT_CSV_PATH = 'annotation_workspace.csv'

# --- Enhanced GDPR Rules & DPV Mappings (from previous versions) ---
# [Note: The GDPR_RULES and DPV_MAPPING dictionaries remain the same as the previous complete script]
GDPR_RULES = {
    'has_Collect_Personal_Information': [r'collect personal (data|information)', r'gather.*information', r'your data.*collected'],
    'has_Data_Retention_Period': [r'retention period', r'retain data', r'data retention', r'how long.*keep'],
    'has_Data_Processing_Purposes': [r'purpose of processing', r'for the purpose', r'why we process'],
    'has_Contact_Details': [r'contact us', r'contact details', r'@', r'dpo@', r'dataprotection@'],
    'has_Right_to_Access': [r'right to access', r'access your data', r'request.*copy.*information'],
    'has_Right_to_Rectify_or_Erase': [r'right to (rectify|erase|delete|correct)', r'correct.*information', r'update.*data'],
    'has_Right_to_Restrict_of_Processing': [r'right to restrict', r'limit.*processing'],
    'has_Right_to_Object_to_Processing': [r'right to object', r'opt.*out'],
    'has_Right_to_Data_Portability': [r'right to data portability', r'transfer.*data', r'receive.*data'],
    'has_Right_to_Lodge_a_Complaint': [r'lodge a complaint', r'supervisory authority', r'data protection authority']
}
DPV_MAPPING = {
    r'advertising|marketing': 'dpv:Marketing',
    r'analytics|statistics': 'dpv:Analytics',
    r'service.*improve': 'dpv:ServiceImprovement',
    r'security|protect': 'dpv:Security',
    r'personalization|recommend': 'dpv:Personalization'
}

# --- NEW: Function to safely parse the purposes_json column ---
def analyze_json_purposes(json_string):
    """Safely parses a JSON string and extracts purpose names."""
    if not isinstance(json_string, str) or not json_string.strip():
        return []
    try:
        # The data might be a JSON array of objects, each with a 'name' key
        purposes = json.loads(json_string)
        if isinstance(purposes, list):
            # Extract the 'name' from each dictionary in the list
            return [p.get('name', '').lower() for p in purposes if isinstance(p, dict)]
    except json.JSONDecodeError:
        return []
    return []


def analyze_row(row):
    """
    Apply annotation rules to a single row, now using contextual data.
    """
    # Get all relevant data fields from the row
    text_content = str(row.get('text_content', '')).lower()
    html_content = str(row.get('html_content', ''))
    legal_text = str(row.get('legal_text_summary', '')).lower()
    purposes_json = str(row.get('purposes_json', ''))
    
    # --- NEW: Combine banner text and legal summary for comprehensive analysis ---
    combined_text = text_content + " " + legal_text
    
    # --- UPDATED: GDPR Compliance Analysis using combined text ---
    gdpr_flags = {}
    for label, patterns in GDPR_RULES.items():
        # Check for patterns in the combined text field
        gdpr_flags[label] = any(re.search(p, combined_text, re.IGNORECASE) for p in patterns)
        
    # --- NEW: Override 'has_Data_Processing_Purposes' using the JSON data ---
    # This is a more reliable source than keyword matching for this specific label.
    parsed_purposes = analyze_json_purposes(purposes_json)
    if parsed_purposes:
        gdpr_flags['has_Data_Processing_Purposes'] = True

    # --- Structural and Dark Pattern analysis (remains the same as previous script) ---
    # This part still relies on HTML and the primary banner text for heuristics.
    # [Note: The logic from the previous script for analyze_html_structure, ISO checks, etc., is assumed here]
    # For brevity, I'll call a simplified version here, but you should use the full version from the previous response.
    html_flags = {} # Placeholder for the full analyze_html_structure function
    dark_flags = {} # Placeholder for the full dark pattern logic
    
    # Example for obstruction dark pattern
    positive_keywords = ['settings', 'manage', 'customize', 'options', 'preferences']
    negative_keywords = ['reject', 'decline', 'refuse', 'deny']
    has_positive = any(re.search(kw, text_content) for kw in positive_keywords)
    has_negative = any(re.search(kw, text_content) for kw in negative_keywords)
    dark_flags['has_Obstruction'] = has_positive and not has_negative
    
    # --- DPV-2 Mapping using combined text ---
    dpv_concept = ''
    for pattern, concept in DPV_MAPPING.items():
        if re.search(pattern, combined_text, re.IGNORECASE):
            dpv_concept = concept
            break
            
    # Combine all generated flags
    return {**gdpr_flags, **dark_flags, **html_flags, 'dpv_concept': dpv_concept}


# --- Main Script Execution ---
print(f"Reading enriched data from '{INPUT_CSV_PATH}'...")
df = pd.read_csv(INPUT_CSV_PATH)
print(f"Found {len(df)} rows. Starting enhanced annotation...")

# Apply the new, more intelligent annotation rules to each row
results = [analyze_row(row) for _, row in df.iterrows()]
annotation_df = pd.DataFrame(results)

# Combine the new annotation columns with the original enriched DataFrame
final_df = pd.concat([df, annotation_df], axis=1)

# Remove duplicate columns if they exist after the merge (e.g., if annotation_df recreates an existing column)
final_df = final_df.loc[:, ~final_df.columns.duplicated()]

print(f"Saving the smarter annotation workspace to '{OUTPUT_CSV_PATH}'...")
final_df.to_csv(OUTPUT_CSV_PATH, index=False)

print("\n--- Process Complete ---")
print("Key enhancements applied to this annotation pass:")
print("- Used `legal_text_summary` for more accurate GDPR rights detection.")
print("- Parsed `purposes_json` to reliably identify data processing purposes.")
print(f"'{OUTPUT_CSV_PATH}' is now ready for Day 2: Manual review.")
