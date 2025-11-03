import pandas as pd
import re
from sklearn.model_selection import train_test_split, KFold
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, classification_report, confusion_matrix
from sklearn.multiclass import OneVsRestClassifier
import joblib
import numpy as np
import scipy.sparse
from sentence_transformers import SentenceTransformer
import torch
import textstat

# --- Phase 2: Dataset Creation and Preprocessing ---
import json

# 1. Load Data
print("Loading datasets...")
try:
    df_gdpr = pd.read_csv('cleaned_gdpr_dataset.csv')
    df_farhan = pd.read_csv('cleaned-by-farhan.csv')
    df_manual = pd.read_csv('manual_final_annotated_dataset_v3.csv')
    df_new_mix = pd.read_csv('new_mix.csv')
    df_purpose = pd.read_csv('purpose_json.csv') # Load the new purpose data
    print("Datasets loaded successfully.")
except FileNotFoundError as e:
    print(f"Error loading file: {e}. Please ensure all CSV files are in the correct directory.")
    exit()

# 2. Data Consolidation Strategy
print("Consolidating datasets...")
combined_df = pd.concat([df_manual, df_farhan[~df_farhan['url'].isin(df_manual['url'])], df_gdpr[~df_gdpr['url'].isin(df_manual['url'])], df_new_mix[~df_new_mix['url'].isin(df_manual['url'])]], ignore_index=True)
combined_df.drop_duplicates(subset=['url'], keep='last', inplace=True)

# --- New: Process and Merge `purpose_json.csv` ---
print("Processing and merging purpose_json.csv data...")

def parse_purpose_json(json_str):
    if pd.isna(json_str) or json_str.strip() == '[]':
        return 0, 0, ""
    try:
        purposes = json.loads(json_str)
        num_pre_ticked = sum(1 for p in purposes if p.get('is_ticked_by_default', False))
        num_strictly_necessary = sum(1 for p in purposes if p.get('is_strictly_necessary', False))
        titles = " ".join([p.get('title', '') for p in purposes])
        return num_pre_ticked, num_strictly_necessary, titles
    except (json.JSONDecodeError, TypeError):
        return 0, 0, ""

df_purpose[['num_pre_ticked_boxes', 'num_strictly_necessary', 'purpose_titles']] = df_purpose['purposes_json'].apply(lambda x: pd.Series(parse_purpose_json(x)))

# Merge with the main dataframe
combined_df = pd.merge(combined_df, df_purpose[['url', 'num_pre_ticked_boxes', 'num_strictly_necessary', 'purpose_titles']], on='url', how='left')

# Fill NaNs for URLs not in purpose_json.csv
combined_df['num_pre_ticked_boxes'].fillna(0, inplace=True)
combined_df['num_strictly_necessary'].fillna(0, inplace=True)
combined_df['purpose_titles'].fillna("", inplace=True)

print("Finished processing purpose_json.csv data.")

# Drop columns that are not needed or cause issues
columns_to_drop = [
    'timestamp', 'status', 'cmp_vendor', 'initial_banner_found',
    'accept_all_present', 'reject_all_present', 'settings_button_present',
    'settings_button_text', 'preference_center_accessed', 'total_purposes_count',
    'strictly_necessary_count', 'purposes_json', 'error_log', 'vendor_count',
    'dpv_concept', 'html_content'
]

columns_to_drop_existing = [col for col in columns_to_drop if col in combined_df.columns]
combined_df.drop(columns=columns_to_drop_existing, inplace=True, errors='ignore')

print(f"Combined dataset shape: {combined_df.shape}")

# 3. Data Cleaning and Normalization
print("Cleaning and normalizing text data...")
def clean_text(text):
    if pd.isna(text):
        return ""
    text = re.sub(r'<.*?>', '', str(text))  # Remove HTML tags, ensure string
    text = text.lower()  # Convert to lowercase
    text = re.sub(r'[^a-z0-9\s]', '', text)  # Remove punctuation and special characters
    text = re.sub(r'\s+', ' ', text).strip()  # Remove extra whitespace
    return text

combined_df['cleaned_text_content'] = combined_df['text_content'].apply(clean_text)
combined_df['cleaned_legal_text_summary'] = combined_df['legal_text_summary'].apply(clean_text)

combined_df['cleaned_text_content'].fillna('', inplace=True)
combined_df['cleaned_legal_text_summary'].fillna('', inplace=True)
print("Text cleaning complete.")

# Create combined_text BEFORE applying conceptual functions
combined_df['combined_text'] = combined_df['cleaned_text_content'] + " " + combined_df['cleaned_legal_text_summary'] + " " + combined_df['purpose_titles']

# Update has_Pre_ticked_Boxes based on the new data
combined_df['has_Pre_ticked_Boxes'] = combined_df['num_pre_ticked_boxes'].apply(lambda x: 1 if x > 0 else 0)

# Enhanced Conceptual DPV-2 Mapping Function
def conceptual_semantic_mapping(text):
    dpv_concepts = set() # Use a set to avoid duplicates
    text_lower = text.lower()

    # Purposes
    if re.search(r'(marketing|advertising|promotional)', text_lower):
        dpv_concepts.add("dpv:Marketing")
    if re.search(r'(analytics|statistics|performance)', text_lower):
        dpv_concepts.add("dpv:Analytics")
    if re.search(r'(service improvement|product development)', text_lower):
        dpv_concepts.add("dpv:ServiceImprovement")
    if re.search(r'(personalization|customization)', text_lower):
        dpv_concepts.add("dpv:Personalization")
    if re.search(r'(security|fraud prevention)', text_lower):
        dpv_concepts.add("dpv:Security")

    # Data Categories (simplified)
    if re.search(r'(personal information|personal data|identifiable information)', text_lower):
        dpv_concepts.add("dpv:PersonalInformation")
    if re.search(r'(ip address|device id|cookies)', text_lower):
        dpv_concepts.add("dpv:TechnicalData")

    # Legal Bases (simplified)
    if re.search(r'(consent|your agreement)', text_lower):
        dpv_concepts.add("dpv:Consent")
    if re.search(r'(legitimate interest)', text_lower):
        dpv_concepts.add("dpv:LegitimateInterest")

    # Other relevant terms
    if re.search(r'(data retention|storage period)', text_lower):
        dpv_concepts.add("dpv:DataRetentionPeriod")
    if re.search(r'(contact us|reach out)', text_lower):
        dpv_concepts.add("dpv:ContactDetails")
    if re.search(r'(third-party|partners|affiliates)', text_lower):
        dpv_concepts.add("dpv:ThirdPartySharing")

    return ", ".join(sorted(list(dpv_concepts))) if dpv_concepts else "dpv:Undefined"

# Banner Compliance Score Calculation based on checklist.md
def calculate_banner_compliance(row):
    score = 100
    justification = []

    # 1. Choice Equality (Unequal choice design)
    if row['clicks_to_reject'] > row['clicks_to_accept']:
        score -= 30
        justification.append("Rejecting requires more clicks than accepting, violating the 'as easy to refuse as to consent' principle.")

    # 2. Pre-ticked Boxes
    if row['num_pre_ticked_boxes'] > row['num_strictly_necessary']:
        score -= 30
        justification.append("Non-essential cookies are pre-ticked by default, which is not a valid form of consent.")

    # 3. Information Transparency (Opaque or missing information)
    if not row['policy_link_present']:
        score -= 15
        justification.append("A clear link to the privacy/cookie policy was not detected on the banner.")
    if not row['text_mentions_contact']:
        score -= 5
        justification.append("Contact information for the data controller appears to be missing.")
    if not row['text_mentions_duration']:
        score -= 5
        justification.append("Information on data retention periods could not be found.")

    # 4. Purpose Specificity (Bundle-consent) 
    if row['dpv2_concepts'] == 'dpv:Undefined':
        score -= 15
        justification.append("The purposes for data processing are not clearly specified or are bundled under vague terms.")

    return max(0, score), ", ".join(justification)

# Apply conceptual functions
combined_df['dpv2_concepts'] = combined_df['combined_text'].apply(conceptual_semantic_mapping)
compliance_results = combined_df.apply(calculate_banner_compliance, axis=1)
combined_df['banner_compliance_score'], combined_df['compliance_justification'] = zip(*compliance_results)


# 4. Feature Engineering - Prepare raw data for vectorization and numerical features
print("Preparing data for feature engineering...")

# Define all relevant boolean labels for dark patterns (reverted to original 3)
dark_pattern_labels = [
    'has_Obstruction',
    'has_Interface_Interference',
    'has_Pre_ticked_Boxes'
]

# Define all target labels for the multi-label model (reverted to original 3 dark patterns)
all_target_labels = dark_pattern_labels

# Define other numerical features (non-labels)
numerical_features = [
    'clicks_to_accept', 'clicks_to_reject', 'policy_link_present',
    'text_mentions_contact', 'text_mentions_duration',
    'banner_compliance_score', # NEW: Replaced readability with a compliance score
    'num_pre_ticked_boxes',
    'num_strictly_necessary'
]

# Ensure all features and labels are present and handle missing values
# No dummy data generation for new labels, as we are reverting
for col in all_target_labels:
    if col not in combined_df.columns:
        combined_df[col] = 0  # Ensure existing labels are present, default to 0 if missing
    if combined_df[col].dtype == 'bool':
        combined_df[col] = combined_df[col].astype(int)
    combined_df[col] = pd.to_numeric(combined_df[col], errors='coerce').fillna(0)

# Ensure numerical features are present and handle missing values
for col in numerical_features:
    if col not in combined_df.columns:
        combined_df[col] = 0  # Add missing columns with default value
    if combined_df[col].dtype == 'bool':
        combined_df[col] = combined_df[col].astype(int)
    combined_df[col] = pd.to_numeric(combined_df[col], errors='coerce').fillna(0)

# Define target variables (only the 3 dark pattern labels)
y = combined_df[all_target_labels]

print(f"Target variables (all labels) class distribution:\n{y.sum()}")

# Save the final processed dataset (optional, but good for reproducibility)
final_dataset_path = 'final_annotated_dataset.csv'
combined_df.to_csv(final_dataset_path, index=False)
print(f"Final annotated dataset saved to {final_dataset_path}")

# Load SentenceTransformer model
# This model will be downloaded on first run
print("Loading SentenceTransformer model...")
# Use a smaller, efficient model for faster processing
sentence_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
print("SentenceTransformer model loaded.")

# --- Phase 3: Model Retraining and Evaluation with Cross-Validation ---

print("Starting model retraining and evaluation with 5-fold cross-validation...")

kf = KFold(n_splits=5, shuffle=True, random_state=42)
f1_scores_per_label = {label: [] for label in all_target_labels}

for fold, (train_index, test_index) in enumerate(kf.split(combined_df)):
    print(f"\n--- Fold {fold + 1} ---")
    X_train_raw, X_test_raw = combined_df['combined_text'].iloc[train_index], combined_df['combined_text'].iloc[test_index]
    y_train, y_test = y.iloc[train_index], y.iloc[test_index]

    # Generate embeddings for text data
    print("Generating transformer embeddings for training data...")
    X_train_embeddings = sentence_model.encode(X_train_raw.tolist(), convert_to_tensor=True)
    print("Generating transformer embeddings for test data...")
    X_test_embeddings = sentence_model.encode(X_test_raw.tolist(), convert_to_tensor=True)

    # Convert embeddings to numpy array for hstack
    X_train_embeddings_np = X_train_embeddings.cpu().numpy()
    X_test_embeddings_np = X_test_embeddings.cpu().numpy()

    # Get numerical features for this fold
    X_train_numerical = combined_df[numerical_features].iloc[train_index].values
    X_test_numerical = combined_df[numerical_features].iloc[test_index].values

    # Combine all features for this fold
    X_train = np.hstack([X_train_embeddings_np, X_train_numerical])
    X_test = np.hstack([X_test_embeddings_np, X_test_numerical])

    print(f"Fold {fold + 1} - Training samples: {X_train.shape[0]}, Test samples: {X_test.shape[0]}")

    # Train multi-label model
    model = OneVsRestClassifier(LogisticRegression(max_iter=1000, solver='liblinear', random_state=42))
    model.fit(X_train, y_train)

    # Evaluate model
    y_pred = model.predict(X_test)

    print(f"Fold {fold + 1} - Classification Report:")
    for i, label in enumerate(all_target_labels):
        report = classification_report(y_test[label], y_pred[:, i], output_dict=True, zero_division=0)
        f1_scores_per_label[label].append(report['weighted avg']['f1-score'])
        print(f"  {label}:\n{classification_report(y_test[label], y_pred[:, i], zero_division=0)}")
        print(f"  {label} Confusion Matrix:\n{confusion_matrix(y_test[label], y_pred[:, i])}")

print("\nAverage F1 Scores across all folds per label:")
for label, scores in f1_scores_per_label.items():
    print(f"  {label}: Average F1 = {np.mean(scores):.3f}, Std = {np.std(scores):.3f}")

# Retrain on full dataset and save (optional, but common practice)
print("\nRetraining model on full dataset for final deployment...")
# Generate embeddings for the full dataset
X_full_embeddings = sentence_model.encode(combined_df['combined_text'].tolist(), convert_to_tensor=True)
X_full_embeddings_np = X_full_embeddings.cpu().numpy()

X_full_numerical = combined_df[numerical_features].values
X_full = np.hstack([X_full_embeddings_np, X_full_numerical])

final_model = OneVsRestClassifier(LogisticRegression(max_iter=1000, solver='liblinear', random_state=42))
final_model.fit(X_full, y)

model_path = 'model/final_multi_label_model.pth' # New name for multi-label model

joblib.dump(final_model, model_path)
print(f"Trained final multi-label model saved to {model_path}")

print("Model retraining and evaluation process complete.")
