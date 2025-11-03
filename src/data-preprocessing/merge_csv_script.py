import pandas as pd

# --- Configuration ---
CONTEXT_CSV = 'cleaned.csv'
SCRAPED_CSV = 'successful_scrapes.csv'
OUTPUT_CSV = 'data_for_annotation.csv'

# Load context and scraped data
context_df = pd.read_csv(CONTEXT_CSV)
scraped_df = pd.read_csv(SCRAPED_CSV)

# Standardize column names for merging
if 'Website' in context_df.columns:
    context_df = context_df.rename(columns={'Website': 'url'})
elif 'url' not in context_df.columns:
    raise ValueError("cleaned.csv must have a 'Website' or 'url' column.")

if 'website_url' in scraped_df.columns:
    scraped_df = scraped_df.rename(columns={'website_url': 'url'})
elif 'url' not in scraped_df.columns:
    raise ValueError("successful_scrapes.csv must have a 'website_url' or 'url' column.")

# Remove any duplicate URLs in context data (keep first occurrence)
context_df = context_df.drop_duplicates(subset=['url'])

# Merge on 'url'
merged_df = pd.merge(scraped_df, context_df, on='url', how='left')

# Save the merged file
merged_df.to_csv(OUTPUT_CSV, index=False)

print(f"Combined file saved as '{OUTPUT_CSV}'. Use this as input for annotation.")
