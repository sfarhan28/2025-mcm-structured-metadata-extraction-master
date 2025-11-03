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

def extract_category_info(driver, category_button):
    try:
        # Click to expand category
        driver.execute_script("arguments[0].click();", category_button)
        time.sleep(2)
        
        # Get the parent div containing all category information
        category_div = category_button.find_element(By.XPATH, "./ancestor::div[contains(@class, 'ot-accordion-layout')]")
        
        # Extract category name
        category_name = category_div.find_element(By.CLASS_NAME, "ot-cat-header").text.strip()
        
        # Extract category description
        description = category_div.find_element(By.CLASS_NAME, "ot-acc-grpdesc").text.strip()
        
        return {
            'name': category_name,
            'description': description
        }
    except Exception as e:
        logger.error(f"Error extracting category info: {str(e)}")
        return None

def scrape_deloitte_consent():
    url = "https://www.deloitte.com/ie/en.html"
    driver = setup_driver()
    consent_data = {}

    try:
        logger.info(f"Navigating to {url}")
        driver.get(url)
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(5)

        # Click cookie preferences button
        logger.info("Looking for cookie preferences button")
        cookie_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Tailor your cookie preferences')]"))
        )
        driver.execute_script("arguments[0].click();", cookie_button)
        logger.info("Clicked cookie preferences button")
        time.sleep(3)

        # Extract general information
        general_info = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "ot-pc-desc"))
        )
        consent_data["General Information"] = general_info.text.strip()
        logger.info("Extracted general information")

        # Find all category buttons
        category_buttons = driver.find_elements(By.XPATH, "//button[@ot-accordion='true']")
        
        for button in category_buttons:
            category_info = extract_category_info(driver, button)
            if category_info:
                consent_data[category_info['name']] = category_info['description']
                logger.info(f"Extracted {category_info['name']}")

    except Exception as e:
        logger.error(f"Error scraping Deloitte consent: {str(e)}")
        logger.error(f"Error details: ", exc_info=True)
    finally:
        driver.quit()

    return consent_data

def main():
    consent_info = scrape_deloitte_consent()
    if consent_info:
        logger.info("Consent information found:")
        for category, description in consent_info.items():
            logger.info(f"- {category}:")
            logger.info(f"  {description[:100]}...")
        
        df = pd.DataFrame([consent_info])
        df.to_csv('deloitte_consent_data.csv', index=False)
        logger.info("Data saved to deloitte_consent_data.csv")
    else:
        logger.warning("No consent information found or unable to scrape.")

if __name__ == "__main__":
    main()