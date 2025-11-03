from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import pandas as pd
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def setup_driver():
    chrome_options = Options()
    # chrome_options.add_argument("--headless")  # Commented out for debugging
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def extract_category_info(driver, category_id):
    try:
        # Click on the category tab
        category = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, f"ot-header-id-{category_id}"))
        )
        driver.execute_script("arguments[0].click();", category)
        time.sleep(2)

        # Get the updated content
        category_content = driver.find_element(By.ID, f"ot-desc-id-{category_id}")
        soup = BeautifulSoup(category_content.get_attribute('innerHTML'), 'html.parser')
        
        # Extract category description
        description = soup.find('p', class_='ot-category-desc')
        description_text = description.text.strip() if description else ""

        # Extract vendors if present
        vendors = []
        vendor_items = soup.find_all('div', class_='ot-vnd-item')
        for vendor in vendor_items:
            vendor_name = vendor.find('h4', class_='ot-cat-header')
            if vendor_name:
                vendors.append(vendor_name.text.strip())

        return {
            'description': description_text,
            'vendors': vendors
        }
    except Exception as e:
        logger.error(f"Error extracting category {category_id}: {str(e)}")
        return None

def scrape_onetrust_consent():
    url = "https://www.onetrust.com/"
    driver = setup_driver()
    consent_data = {}

    try:
        logger.info(f"Navigating to {url}")
        driver.get(url)
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(5)

        # Click cookie settings button
        logger.info("Looking for cookie settings button")
        cookie_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "onetrust-pc-btn-handler"))
        )
        driver.execute_script("arguments[0].click();", cookie_button)
        logger.info("Clicked cookie settings button")
        time.sleep(3)

        # Extract general information
        general_info = driver.find_element(By.ID, "ot-pc-desc").text
        consent_data["General Information"] = general_info
        logger.info("Extracted general information")

        # Extract information from each category
        categories = {
            "1": "Strictly Necessary Cookies",
            "2": "Performance Cookies",
            "3": "Functional Cookies",
            "4": "Targeting Cookies"
        }

        for cat_id, cat_name in categories.items():
            logger.info(f"Extracting information for {cat_name}")
            category_info = extract_category_info(driver, cat_id)
            if category_info:
                consent_data[f"{cat_name} Description"] = category_info['description']
                consent_data[f"{cat_name} Vendors"] = ", ".join(category_info['vendors']) if category_info['vendors'] else "No vendors listed"

    except Exception as e:
        logger.error(f"Error scraping OneTrust consent: {str(e)}")
        logger.error(f"Error details: ", exc_info=True)
    finally:
        driver.quit()

    return consent_data

def main():
    consent_info = scrape_onetrust_consent()
    if consent_info:
        logger.info("Consent information found:")
        for category, description in consent_info.items():
            logger.info(f"- {category}:")
            logger.info(f"  {description[:100]}...")
        
        df = pd.DataFrame([consent_info])
        df.to_csv('onetrust_consent_data.csv', index=False)
        logger.info("Data saved to onetrust_consent_data.csv")
    else:
        logger.warning("No consent information found or unable to scrape.")

if __name__ == "__main__":
    main()