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

def scrape_yum_consent():
    url = "https://www.yum.com/wps/portal/yumbrands/Yumbrands/"
    driver = setup_driver()
    consent_data = {}

    try:
        logger.info(f"Navigating to {url}")
        driver.get(url)
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(5)  # Wait for initial load

        # Try different selectors for the Manage button
        manage_button_selectors = [
            (By.CLASS_NAME, "manage-consent-button"),
            (By.CLASS_NAME, "ot-link-btn"),
            (By.ID, "onetrust-pc-btn-handler"),
            (By.XPATH, "//button[contains(text(), 'MANAGE')]"),
            (By.CSS_SELECTOR, "button.ot-link-btn.manage-consent-button")
        ]

        manage_button = None
        for selector_type, selector_value in manage_button_selectors:
            try:
                manage_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((selector_type, selector_value))
                )
                if manage_button:
                    break
            except:
                continue

        if manage_button:
            logger.info("Found Manage button, attempting to click")
            driver.execute_script("arguments[0].scrollIntoView(true);", manage_button)
            time.sleep(2)
            driver.execute_script("arguments[0].click();", manage_button)
            logger.info("Clicked Manage button")
            
            # Wait for consent dialogue to appear
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "ot-pc-header"))
            )
            time.sleep(3)

            # Parse the page source
            soup = BeautifulSoup(driver.page_source, 'html.parser')

            # Extract general information
            general_info = soup.find('div', id='ot-pc-desc')
            if general_info:
                consent_data["General Information"] = general_info.text.strip()
                logger.info("Extracted general information")

            # Extract cookie categories
            categories = soup.find_all('div', class_='ot-accordion-layout ot-cat-item')
            for category in categories:
                category_name = category.find('h4', class_='ot-cat-header')
                if category_name:
                    name = category_name.text.strip()
                    description = category.find('p', class_='ot-acc-grpdesc')
                    if description:
                        consent_data[name] = description.text.strip()
                        logger.info(f"Extracted category: {name}")

        else:
            logger.error("Could not find Manage button")

    except Exception as e:
        logger.error(f"Error scraping Yum consent: {str(e)}")
        logger.error(f"Error details: ", exc_info=True)
    finally:
        driver.quit()

    return consent_data

def main():
    consent_info = scrape_yum_consent()
    if consent_info:
        logger.info("Consent information found:")
        for category, description in consent_info.items():
            logger.info(f"- {category}:")
            logger.info(f"  {description[:100]}...")
        
        df = pd.DataFrame([consent_info])
        df.to_csv('yum_consent_data.csv', index=False)
        logger.info("Data saved to yum_consent_data.csv")
    else:
        logger.warning("No consent information found or unable to scrape.")

if __name__ == "__main__":
    main()