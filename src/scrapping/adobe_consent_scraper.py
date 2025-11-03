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

def scrape_adobe_consent():
    url = "https://www.adobe.com/express/"
    driver = setup_driver()
    consent_data = {}

    try:
        logger.info(f"Navigating to {url}")
        driver.get(url)
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        # Scroll to trigger consent dialogue
        logger.info("Scrolling to trigger consent dialogue")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(5)

        # Wait for and click cookie settings button
        logger.info("Waiting for cookie settings button")
        cookie_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "onetrust-pc-btn-handler"))
        )
        driver.execute_script("arguments[0].click();", cookie_button)
        logger.info("Clicked cookie settings button")

        # Wait for cookie settings panel
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "ot-main-content"))
        )
        time.sleep(3)

        # Get the page source after the dialogue is loaded
        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # Extract cookie categories and their descriptions
        categories = soup.find_all('div', class_='accordion-text category-item')
        for category in categories:
            category_name = category.find('h4', class_='category-header')
            if category_name:
                name = category_name.text.strip()
                description = category.find('div', class_='ot-cookie-description')
                if description:
                    consent_data[name] = description.text.strip()
                    logger.info(f"Extracted category: {name}")

        # Extract general information
        general_info = soup.find('div', class_='ot-general')
        if general_info:
            consent_data["General Information"] = general_info.get_text(strip=True)
            logger.info("Extracted general information")

        # Extract enabled/disabled information
        enabled_section = soup.find('div', class_='ot-enable')
        if enabled_section:
            enabled_items = enabled_section.find_all('li')
            consent_data["If enabled"] = " ".join([item.text.strip() for item in enabled_items])
            logger.info("Extracted 'if enabled' information")

        disabled_section = soup.find('div', class_='ot-disable')
        if disabled_section:
            disabled_items = disabled_section.find_all('li')
            consent_data["If disabled"] = " ".join([item.text.strip() for item in disabled_items])
            logger.info("Extracted 'if disabled' information")

    except Exception as e:
        logger.error(f"Error scraping Adobe consent: {str(e)}")
        logger.error(f"Error details: ", exc_info=True)
    finally:
        driver.quit()

    return consent_data

def main():
    consent_info = scrape_adobe_consent()
    if consent_info:
        logger.info("Consent information found:")
        for category, description in consent_info.items():
            logger.info(f"- {category}:")
            logger.info(f"  {description[:100]}...")
        
        df = pd.DataFrame([consent_info])
        df.to_csv('adobe_consent_data.csv', index=False)
        logger.info("Data saved to adobe_consent_data.csv")
    else:
        logger.warning("No consent information found or unable to scrape.")

if __name__ == "__main__":
    main()