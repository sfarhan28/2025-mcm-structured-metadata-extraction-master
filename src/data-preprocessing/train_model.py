import pandas as pd
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from transformers import BertTokenizer, BertForSequenceClassification
from torch.optim import AdamW
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

# Configuration
INPUT_CSV_PATH = 'final_annotated_dataset.csv'
MODEL_NAME = 'bert-base-uncased'
MODEL_SAVE_PATH = './gdpr_compliance_model'
MAX_LEN = 256
BATCH_SIZE = 8
EPOCHS = 4
LEARNING_RATE = 2e-5

# Set device (GPU if available, else CPU)
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f"Using device: {device}")

# Load the dataset
print(f"Loading dataset from '{INPUT_CSV_PATH}'...")
df = pd.read_csv(INPUT_CSV_PATH)

# List of columns that are not labels
DATA_COLUMNS = [
    'website_url', 'html_content', 'text_content', 
    'url', 'Vendor', 'Category', 'Website', 'Country', 
    'purposes_json', 'legal_text_summary'
]

# Find label columns automatically
label_candidates = [col for col in df.columns if col not in DATA_COLUMNS]
LABEL_COLUMNS = [col for col in label_candidates if 'has_' in col or 'clicks_' in col]

print("\nAutomatically identified the following label columns for training:")
for col in LABEL_COLUMNS:
    print(f"- {col}")
print(f"Total labels found: {len(LABEL_COLUMNS)}\n")

# Prepare text and label columns
df['text_content'] = df['text_content'].astype(str).fillna('')
for col in LABEL_COLUMNS:
    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

# Split into train and validation sets
train_df, val_df = train_test_split(df, test_size=0.2, random_state=42)
print(f"Training set size: {len(train_df)}, Validation set size: {len(val_df)}")

# PyTorch dataset for GDPR data
class GDPRDataset(Dataset):
    def __init__(self, dataframe, tokenizer, max_len, label_columns):
        self.tokenizer = tokenizer
        self.data = dataframe
        self.text = dataframe.text_content
        self.targets = dataframe[label_columns].values
        self.max_len = max_len

    def __len__(self):
        return len(self.text)

    def __getitem__(self, index):
        text = str(self.text.iloc[index])
        inputs = self.tokenizer.encode_plus(
            text, None, add_special_tokens=True, max_length=self.max_len, padding='max_length',
            return_token_type_ids=False, truncation=True, return_attention_mask=True, return_tensors='pt',
        )
        return {
            'input_ids': inputs['input_ids'].flatten(),
            'attention_mask': inputs['attention_mask'].flatten(),
            'labels': torch.FloatTensor(self.targets[index])
        }

# Initialize tokenizer and dataloaders
tokenizer = BertTokenizer.from_pretrained(MODEL_NAME)
train_dataset = GDPRDataset(train_df, tokenizer, MAX_LEN, LABEL_COLUMNS)
val_dataset = GDPRDataset(val_df, tokenizer, MAX_LEN, LABEL_COLUMNS)

train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
val_loader = DataLoader(val_dataset, batch_size=BATCH_SIZE, shuffle=False)

# Compute class weights for imbalanced data
print("Calculating weights for imbalanced classes...")
pos_counts = train_df[LABEL_COLUMNS].sum()
neg_counts = len(train_df) - pos_counts
pos_weights = neg_counts / (pos_counts + 1e-8)
pos_weights = torch.tensor(pos_weights.values, dtype=torch.float).to(device)

print("Class weights calculated:")
for i, col in enumerate(LABEL_COLUMNS):
    print(f"- {col}: {pos_weights[i]:.2f}")

loss_function = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weights)

# Initialize model and optimizer
model = BertForSequenceClassification.from_pretrained(
    MODEL_NAME,
    num_labels=len(LABEL_COLUMNS),
    problem_type="multi_label_classification"
)
model.to(device)

optimizer = AdamW(model.parameters(), lr=LEARNING_RATE)

# Training and validation loop
for epoch in range(EPOCHS):
    print(f"\n--- Epoch {epoch + 1}/{EPOCHS} ---")
    
    model.train()
    total_loss = 0
    for batch in train_loader:
        optimizer.zero_grad()
        input_ids = batch['input_ids'].to(device)
        attention_mask = batch['attention_mask'].to(device)
        labels = batch['labels'].to(device)
        outputs = model(input_ids, attention_mask=attention_mask, labels=labels)
        loss = loss_function(outputs.logits, labels)
        total_loss += loss.item()
        loss.backward()
        optimizer.step()
        
    avg_train_loss = total_loss / len(train_loader)
    print(f"Average Training Loss: {avg_train_loss:.4f}")

    model.eval()
    all_preds, all_labels = [], []
    with torch.no_grad():
        for batch in val_loader:
            input_ids = batch['input_ids'].to(device)
            attention_mask = batch['attention_mask'].to(device)
            labels = batch['labels'].to(device)
            outputs = model(input_ids, attention_mask=attention_mask)
            preds = torch.sigmoid(outputs.logits) > 0.5
            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())
            
    print("\nValidation Results:")
    report = classification_report(np.array(all_labels), np.array(all_preds), target_names=LABEL_COLUMNS, zero_division=0)
    print(report)

# Save the trained model and tokenizer
print("\nTraining complete. Saving model...")
model.save_pretrained(MODEL_SAVE_PATH)
tokenizer.save_pretrained(MODEL_SAVE_PATH)
print(f"Model saved to '{MODEL_SAVE_PATH}'")
