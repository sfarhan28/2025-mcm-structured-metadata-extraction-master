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
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def scrape_puma_consent():
    url = "https://eu.puma.com/ie/en/home"
    driver = setup_driver()
    consent_data = {}

    try:
        logger.info(f"Navigating to {url}")
        driver.get(url)
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        # Find and click the cookie settings button
        cookie_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "onetrust-pc-btn-handler"))
        )
        driver.execute_script("arguments[0].click();", cookie_button)
        logger.info("Clicked cookie settings button")

        # Wait for the cookie settings panel to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "ot-pc-content"))
        )
        time.sleep(5)  # Wait for dynamic content to load

        # Parse the page source with BeautifulSoup
        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # Extract general information
        consent_data["General Information"] = soup.find('div', id='ot-pc-desc').text.strip()

        # Extract cookie categories and descriptions
        categories = soup.find_all('div', class_='ot-accordion-layout ot-cat-item ot-vs-config')
        for category in categories:
            category_name = category.find('h4', class_='ot-cat-header').text.strip()
            category_description = category.find('p', class_='ot-category-desc').text.strip()
            consent_data[category_name] = category_description
            logger.info(f"Extracted category: {category_name}")

        # Extract website tags information
        website_tags = soup.find('p', id='ot-desc-id-C0007')
        if website_tags:
            consent_data["Website Tags"] = website_tags.text.strip()
            logger.info("Extracted website tags information")

    except Exception as e:
        logger.error(f"Error scraping PUMA consent: {str(e)}")
    finally:
        driver.quit()

    return consent_data
    
def main():
    consent_info = scrape_puma_consent()
    if consent_info:
        logger.info("Consent information found:")
        for category, description in consent_info.items():
            logger.info(f"- {category}:")
            logger.info(f"  {description[:100]}...")
        
        df = pd.DataFrame([consent_info])
        df.to_csv('puma_consent_data.csv', index=False)
        logger.info("Data saved to puma_consent_data.csv")
    else:
        logger.warning("No consent information found or unable to scrape.")

if __name__ == "__main__":
    main()