from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
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
    chrome_options.add_argument("--disable-dev-shm-usage")
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

        logger.info("Waiting for cookie settings button")
        cookie_button = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.ID, "onetrust-pc-btn-handler"))
        )
        driver.execute_script("arguments[0].click();", cookie_button)

        logger.info("Waiting for cookie settings panel")
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CLASS_NAME, "ot-pc-header"))
        )

        logger.info("Extracting consent information")
        consent_data["General Information"] = driver.find_element(By.CLASS_NAME, "ot-pc-header").text

        enabled_info = driver.find_element(By.ID, "ot-pc-desc").text
        if "If enabled:" in enabled_info and "If disabled:" in enabled_info:
            consent_data["If enabled"] = enabled_info.split("If enabled:")[1].split("If disabled:")[0].strip()
            consent_data["If disabled"] = enabled_info.split("If disabled:")[1].strip()
        else:
            logger.warning("Unable to find 'If enabled' and 'If disabled' sections")

    except Exception as e:
        logger.error(f"Error scraping Adobe consent: {str(e)}")
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