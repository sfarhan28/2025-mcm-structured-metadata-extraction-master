import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import MultiLabelBinarizer
import re

# This script outlines the enhancement of dark pattern detection to include multiple categories.
# It assumes an expanded dataset with multiple boolean columns for different dark patterns.

def clean_text(text):
    if pd.isna(text):
        return ""
    text = re.sub(r'<.*?>', '', str(text))  # Remove HTML tags, ensure string
    text = text.lower()  # Convert to lowercase
    text = re.sub(r'[^a-z0-9\s]', '', text)  # Remove punctuation and special characters
    text = re.sub(r'\s+', ' ', text).strip()  # Remove extra whitespace
    return text

print("--- Dark Pattern Detection Enhancement Outline ---")

# 1. Conceptual Data Loading (assuming a dataset with multiple dark pattern labels)
# In a real scenario, you would load your consolidated dataset here.
# For demonstration, we'll create a dummy DataFrame.

data = {
    'url': ['site_a.com', 'site_b.com', 'site_c.com', 'site_d.com', 'site_e.com'],
    'text_content': [
        'This site uses cookies. Accept all or manage settings.',
        'We value your privacy. Click accept to continue.',
        'Our partners use cookies for advertising. Opt-out in settings.',
        'By using this site, you agree to cookies. Learn more.',
        'Strictly necessary cookies are enabled by default.'
    ],
    'legal_text_summary': [
        'Data collected for analytics and marketing.',
        'Personal data processed for personalized ads.',
        'Third-party sharing for targeted content.',
        'No clear reject option on first layer.',
        'Functional cookies are essential.'
    ],
    'has_Obstruction': [1, 0, 0, 1, 0],
    'has_Interface_Interference': [0, 1, 0, 1, 0], # Example new dark pattern
    'has_Pre_ticked_Boxes': [0, 0, 1, 0, 1] # Example new dark pattern
}
df = pd.DataFrame(data)

print("Simulated dataset with multiple dark pattern labels created.")
print(df.head())

# 2. Data Cleaning and Feature Engineering
df['cleaned_text_content'] = df['text_content'].apply(clean_text)
df['cleaned_legal_text_summary'] = df['legal_text_summary'].apply(clean_text)
df['combined_text'] = df['cleaned_text_content'] + " " + df['cleaned_legal_text_summary']

# Define all dark pattern label columns
dark_pattern_labels = [
    'has_Obstruction',
    'has_Interface_Interference',
    'has_Pre_ticked_Boxes'
]

# Prepare target variable for multi-label classification
# MultiLabelBinarizer is useful if labels are in a list format, but here they are separate columns
# For separate columns, we can directly use them as multiple target variables.

X = df['combined_text']
y = df[dark_pattern_labels]

# TF-IDF Vectorization (fit only on training data in a real CV setup)
tfidf_vectorizer = TfidfVectorizer(max_features=1000)
X_tfidf = tfidf_vectorizer.fit_transform(X)

print(f"TF-IDF features shape: {X_tfidf.shape}")
print(f"Target labels shape: {y.shape}")

# 3. Model Training (Conceptual Multi-label Classification)
# For multi-label classification, you can train a separate classifier for each label
# or use a multi-output classifier like OneVsRestClassifier.

print("\nTraining conceptual multi-label classification model...")

# Split data (conceptual split for demonstration)
X_train, X_test, y_train, y_test = train_test_split(X_tfidf, y, test_size=0.3, random_state=42)

# Train a OneVsRestClassifier for multi-label prediction
# Each label is treated as a separate binary classification problem
model = OneVsRestClassifier(LogisticRegression(solver='liblinear', random_state=42))
model.fit(X_train, y_train)

print("Conceptual multi-label model training complete.")

# 4. Conceptual Evaluation
print("\nConceptual Model Evaluation:")
y_pred = model.predict(X_test)

# Print classification report for each label
for i, label in enumerate(dark_pattern_labels):
    print(f"\n--- Evaluation for {label} ---")
    print(classification_report(y_test[label], y_pred[:, i]))

print("\nThis script demonstrates the conceptual approach to expanding dark pattern detection.")
print("In a full implementation, this would involve more extensive data annotation,")
print("and potentially more sophisticated NLP models (e.g., transformer-based) for better performance.")
