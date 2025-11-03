import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import time
import multiprocessing

INPUT_CSV_PATH = 'cleaned.csv'
FINAL_OUTPUT_CSV = 'scraped_data.csv'
NUM_WORKERS = 5  # The number of parallel batches you requested
COOKIE_BANNER_SELECTORS = [
    '[id*="consent"]', '[class*="consent"]',
    '[id*="cookie"]', '[class*="cookie"]',
    '[id*="banner"]', '[class*="banner"]',
    '[id*="notice"]', '[class*="notice"]',
    '#onetrust-banner-sdk', '#truste-consent-track'
]

def scrape_website(url):
    """
    This function is the "work" each of the 5 parallel processes will do.
    It scrapes a single URL and returns its data.
    """
    process_name = multiprocessing.current_process().name
    print(f"[{process_name}] Scraping: {url}")
    
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--log-level=3') # Suppress console logs from Chrome
    options.add_experimental_option('excludeSwitches', ['enable-logging'])

    driver = None # Initialize driver to None
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.get(url)

        wait = WebDriverWait(driver, 15)
        combined_selector = ", ".join(COOKIE_BANNER_SELECTORS)
        
        banner_element = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, combined_selector))
        )
        
        html_content = banner_element.get_attribute('outerHTML')
        soup = BeautifulSoup(html_content, 'html.parser')
        text_content = soup.get_text(separator=' ', strip=True)

        print(f"    -> [{process_name}] Success: Banner found on {url}")
        return {
            'website_url': url,
            'html_content': html_content,
            'text_content': text_content,
            'status': 'Success'
        }
            
    except Exception as e:
        print(f"    -> [{process_name}] ERROR: Could not find banner or process {url}. Reason: {str(e).splitlines()[0]}")
        return {
            'website_url': url,
            'html_content': '',
            'text_content': '',
            'status': 'Failed'
        }
    finally:
        if driver:
            driver.quit()

# --- Main Execution Block ---
if __name__ == '__main__':
    # 1. Read URLs from the input file
    print(f"Reading URLs from '{INPUT_CSV_PATH}'...")
    try:
        urls_df = pd.read_csv(INPUT_CSV_PATH)
        if 'url' not in urls_df.columns:
            # If no 'url' column, assume the first column contains the URLs
            urls_df.rename(columns={urls_df.columns[0]: 'url'}, inplace=True)
        urls_to_scrape = urls_df['url'].dropna().unique().tolist()
    except Exception as e:
        print(f"FATAL ERROR: Could not read '{INPUT_CSV_PATH}'. Make sure it exists and has a 'url' column. Error: {e}")
        exit()

    print(f"Found {len(urls_to_scrape)} unique URLs to scrape.")

    # 2. Scrape the URLs in parallel using a pool of workers
    print(f"\nStarting parallel scraping with {NUM_WORKERS} workers...")
    
    # The 'with' statement ensures the pool is properly closed
    with multiprocessing.Pool(processes=NUM_WORKERS) as pool:
        # pool.map applies the 'scrape_website' function to each URL in the list
        # and distributes the work among the worker processes.
        # It waits for all results and returns them in a list.
        results = pool.map(scrape_website, urls_to_scrape)

    print("\nAll scraping batches have completed.")

    # 3. Combine results and save the final file
    # Filter out any potential None results if the function failed unexpectedly
    successful_results = [res for res in results if res is not None and res['status'] == 'Success']
    failed_results = [res for res in results if res is not None and res['status'] != 'Success']

    print(f"Successfully scraped {len(successful_results)} websites.")
    if failed_results:
        print(f"Failed to scrape {len(failed_results)} websites.")

    if successful_results:
        final_df = pd.DataFrame(successful_results)
        final_df.to_csv(FINAL_OUTPUT_CSV, index=False)
        print(f"\nScraped data has been combined and saved to '{FINAL_OUTPUT_CSV}'.")
        print("You can now use this file as input for the annotation script.")
    else:
        print("\nNo websites were successfully scraped. The output file was not created.")

