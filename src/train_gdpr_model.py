import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from transformers import BertTokenizer, BertModel
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report
import argparse
import os
import joblib

class GDPRDataset(Dataset):
    """PyTorch Dataset for GDPR data."""
    def __init__(self, dataframe, tokenizer, text_cols, numerical_cols, target_cols, max_len=128):
        self.tokenizer = tokenizer
        self.df = dataframe
        self.text_cols = text_cols
        self.numerical_cols = numerical_cols
        self.target_cols = target_cols
        self.max_len = max_len

    def __len__(self):
        return len(self.df)

    def __getitem__(self, index):
        text = " ".join([str(self.df.loc[index, col]) for col in self.text_cols])
        inputs = self.tokenizer.encode_plus(
            text,
            None,
            add_special_tokens=True,
            max_length=self.max_len,
            padding='max_length',
            return_token_type_ids=True,
            truncation=True
        )
        ids = inputs['input_ids']
        mask = inputs['attention_mask']

        numerical_values = self.df.loc[index, self.numerical_cols].values.tolist()
        numerical_features = torch.tensor([float(v) for v in numerical_values], dtype=torch.float)
        target_values = self.df.loc[index, self.target_cols].values.tolist()
        targets = torch.tensor([float(v) for v in target_values], dtype=torch.float)

        return {
            'ids': torch.tensor(ids, dtype=torch.long),
            'mask': torch.tensor(mask, dtype=torch.long),
            'numerical_features': numerical_features,
            'targets': targets
        }

class MultiInputModel(nn.Module):
    """Multi-input model combining BERT and a Feed-Forward Neural Network."""
    def __init__(self, bert_model_name, num_numerical_features, num_labels):
        super(MultiInputModel, self).__init__()
        self.bert = BertModel.from_pretrained(bert_model_name)
        self.fnn = nn.Sequential(
            nn.Linear(num_numerical_features, 128),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Dropout(0.2)
        )
        self.classifier = nn.Linear(self.bert.config.hidden_size + 64, num_labels)

    def forward(self, ids, mask, numerical_features):
        bert_output = self.bert(ids, attention_mask=mask)
        cls_token_output = bert_output.pooler_output
        fnn_output = self.fnn(numerical_features)
        combined_output = torch.cat([cls_token_output, fnn_output], dim=1)
        logits = self.classifier(combined_output)
        return logits

def train_model(args):
    """Main function to train and evaluate the model."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    with open("progress_log.md", 'a') as f:
        f.write("\n## Phase 2: Model Training\n")
        f.write(f"Using device: {device}\n")

    try:
        df = pd.read_csv(args.input_file)
    except FileNotFoundError:
        with open("progress_log.md", 'a') as f:
            f.write(f"Error: Input file not found at {args.input_file}\n")
        return

    text_cols = ['text_content', 'legal_text_summary', 'html_content']
    
    # Identify numerical columns: all columns that are not text, targets, or the URL.
    numerical_cols = [col for col in df.columns if col not in text_cols and col not in args.target_cols and col != 'url']

    # A more robust way to ensure all these columns are numeric.
    for col in numerical_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    scaler = StandardScaler()
    if numerical_cols:
        df[numerical_cols] = scaler.fit_transform(df[numerical_cols])

    train_df, test_df = train_test_split(df, test_size=0.2, random_state=42)
    train_df, val_df = train_test_split(train_df, test_size=0.2, random_state=42)

    tokenizer = BertTokenizer.from_pretrained(args.model_name)

    train_dataset = GDPRDataset(train_df.reset_index(drop=True), tokenizer, text_cols, numerical_cols, args.target_cols, args.max_len)
    val_dataset = GDPRDataset(val_df.reset_index(drop=True), tokenizer, text_cols, numerical_cols, args.target_cols, args.max_len)
    test_dataset = GDPRDataset(test_df.reset_index(drop=True), tokenizer, text_cols, numerical_cols, args.target_cols, args.max_len)

    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, num_workers=0) # num_workers set to 0 for Windows compatibility
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False, num_workers=0)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size, shuffle=False, num_workers=0)

    model = MultiInputModel(args.model_name, len(numerical_cols), len(args.target_cols))
    model.to(device)

    pos_weights = torch.tensor([ (len(train_df) - train_df[col].sum()) / (train_df[col].sum() + 1e-9) for col in args.target_cols], dtype=torch.float).to(device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)

    best_val_f1 = 0.0
    epochs_no_improve = 0
    early_stopping_patience = 3

    with open("progress_log.md", 'a') as f:
        f.write(f"\n--- Training with Advanced Features and Early Stopping ---\n")
        f.write(f"Early stopping patience set to {early_stopping_patience} epochs.\n")

    for epoch in range(args.epochs):
        model.train()
        total_loss = 0
        for batch in train_loader:
            ids = batch['ids'].to(device)
            mask = batch['mask'].to(device)
            numerical_features = batch['numerical_features'].to(device)
            targets = batch['targets'].to(device)

            optimizer.zero_grad()
            logits = model(ids, mask, numerical_features)
            loss = criterion(logits, targets)
            total_loss += loss.item()
            loss.backward()
            optimizer.step()
        
        avg_train_loss = total_loss / len(train_loader)
        with open("progress_log.md", 'a') as f:
            f.write(f"\nEpoch {epoch+1}/{args.epochs} - Training Loss: {avg_train_loss:.4f}\n")

        model.eval()
        val_preds = []
        val_targets = []
        with torch.no_grad():
            for batch in val_loader:
                ids = batch['ids'].to(device)
                mask = batch['mask'].to(device)
                numerical_features = batch['numerical_features'].to(device)
                targets = batch['targets'].to(device)

                logits = model(ids, mask, numerical_features)
                preds = torch.sigmoid(logits) > 0.5
                val_preds.extend(preds.cpu().numpy())
                val_targets.extend(targets.cpu().numpy())

        report = classification_report(val_targets, val_preds, target_names=args.target_cols, output_dict=True, zero_division=0)
        val_f1 = report['weighted avg']['f1-score']
        with open("progress_log.md", 'a') as f:
            f.write(f"Epoch {epoch+1}/{args.epochs} - Validation F1-score: {val_f1:.4f}\n")
            f.write(classification_report(val_targets, val_preds, target_names=args.target_cols, zero_division=0))

        if val_f1 > best_val_f1:
            best_val_f1 = val_f1
            torch.save(model.state_dict(), os.path.join(args.model_save_path, 'best_model.pth'))
            epochs_no_improve = 0
            with open("progress_log.md", 'a') as f:
                f.write(f"\nSaved new best model with F1-score: {val_f1:.4f}\n")
        else:
            epochs_no_improve += 1
            if epochs_no_improve >= early_stopping_patience:
                with open("progress_log.md", 'a') as f:
                    f.write(f"\n--- Early stopping triggered after {epoch+1} epochs. ---\n")
                break

    torch.save(model.state_dict(), os.path.join(args.model_save_path, 'final_model.pth'))
    tokenizer.save_pretrained(args.model_save_path)
    joblib.dump(scaler, os.path.join(args.model_save_path, 'scaler.pkl'))

    model.eval()
    test_preds = []
    test_targets = []
    with torch.no_grad():
        for batch in test_loader:
            ids = batch['ids'].to(device)
            mask = batch['mask'].to(device)
            numerical_features = batch['numerical_features'].to(device)
            targets = batch['targets'].to(device)

            logits = model(ids, mask, numerical_features)
            preds = torch.sigmoid(logits) > 0.5
            test_preds.extend(preds.cpu().numpy())
            test_targets.extend(targets.cpu().numpy())
    
    with open("progress_log.md", 'a') as f:
        f.write("\n\n--- Final Test Set Evaluation ---\n")
        f.write(classification_report(test_targets, test_preds, target_names=args.target_cols, zero_division=0))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Train a multi-input model for GDPR compliance prediction.')
    parser.add_argument('--input_file', type=str, default='C:/Users/ritvi/Code/Practicum/restart/new-project/src/new_src/cleaned_gdpr_dataset.csv', help='Path to the cleaned GDPR dataset.')
    parser.add_argument('--model_name', type=str, default='bert-base-uncased', help='Name of the pre-trained BERT model.')
    parser.add_argument('--epochs', type=int, default=15, help='Number of training epochs.')
    parser.add_argument('--batch_size', type=int, default=16, help='Batch size for training.')
    parser.add_argument('--learning_rate', type=float, default=1e-5, help='Learning rate for the optimizer.')
    parser.add_argument('--max_len', type=int, default=128, help='Maximum length of the tokenized text.')
    parser.add_argument('--model_save_path', type=str, default='C:/Users/ritvi/Code/Practicum/restart/new-project/src/new_src/model', help='Directory to save the trained model.')
    parser.add_argument('--target_cols', nargs='+', default=['has_Collect_Personal_Information', 'has_Data_Processing_Purposes', 'has_Right_to_Object_to_Processing', 'has_Right_to_Access', 'has_Right_to_Rectify_or_Erase', 'has_Data_Retention_Period', 'has_Right_to_Lodge_a_Complaint', 'has_Right_to_Restrict_of_Processing', 'has_Right_to_Data_Portability', 'has_Contact_Details', 'has_Obstruction', 'has_Interface_Interference', 'has_Pre_ticked_Boxes'], help='List of target columns.')
    args = parser.parse_args()

    if not os.path.exists(args.model_save_path):
        os.makedirs(args.model_save_path)

    train_model(args)