import pandas as pd

# --- Configuration ---
# The raw data file produced by your parallel scraper.
RAW_SCRAPED_DATA_PATH = 'scraped_data.csv'
# The clean output file that will be used for annotation.
SUCCESSFUL_SCRAPES_PATH = 'successful_scrapes.csv'

def main():
    """
    Reads the raw scraped data, filters for successful scrapes,
    and saves the result to a new CSV file.
    """
    print(f"Reading raw data from '{RAW_SCRAPED_DATA_PATH}'...")
    try:
        # Load the scraped data into a pandas DataFrame.
        df = pd.read_csv(RAW_SCRAPED_DATA_PATH)
    except FileNotFoundError:
        print(f"FATAL ERROR: The input file '{RAW_SCRAPED_DATA_PATH}' was not found.")
        print("Please ensure you have run the scraper and the file exists in the same directory.")
        return

    # --- Analysis and Filtering ---
    total_rows = len(df)
    success_rows = df[df['status'] == 'Success']
    num_success = len(success_rows)
    num_failed = total_rows - num_success
    success_rate = (num_success / total_rows) * 100 if total_rows > 0 else 0

    print("\n--- Analysis of Scraped Data ---")
    print(f"Total websites processed: {total_rows}")
    print(f"  - Successful scrapes: {num_success}")
    print(f"  - Failed scrapes:     {num_failed}")
    print(f"Success Rate: {success_rate:.2f}%")
    print("---------------------------------")

    if num_success == 0:
        print("No successful scrapes were found. The output file will not be created.")
        return

    # Create a new DataFrame containing only the successful rows.
    # We use .copy() to ensure we are working with a new DataFrame, not a view.
    successful_df = success_rows.copy()
    
    # The 'status' column is now redundant because all rows have a 'Success' status.
    # We drop it to clean up the dataset for the next step.
    successful_df.drop(columns=['status'], inplace=True)
    
    # Save the cleaned DataFrame to the new output file.
    print(f"\nSaving {num_success} successful scrapes to '{SUCCESSFUL_SCRAPES_PATH}'...")
    successful_df.to_csv(SUCCESSFUL_SCRAPES_PATH, index=False)
    
    print("\nProcess complete.")
    print(f"The file '{SUCCESSFUL_SCRAPES_PATH}' is now ready to be used as input for the annotation script.")

# This ensures the main function is called only when the script is executed directly.
if __name__ == '__main__':
    main()
