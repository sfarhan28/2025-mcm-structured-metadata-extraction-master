from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import WebDriverException, TimeoutException
import time
import logging

# Suppress WebDriverManager logs
logging.getLogger('webdriver_manager').setLevel(logging.ERROR)

def get_dynamic_html_content(url, wait_time=5):
    """Fetches dynamic HTML content from a URL using Selenium."""
    options = Options()
    options.add_argument("--headless")  # Run browser in background
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080") # Set consistent window size
    options.add_argument("--disable-gpu") # For Windows OS
    options.add_argument("--log-level=3") # Suppress Chrome console logs

    try:
        # Setup chromedriver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        driver.set_page_load_timeout(30) # Set page load timeout
        driver.get(url)
        time.sleep(wait_time)  # Wait for dynamic content
        html_content = driver.page_source
        driver.quit()
        return html_content
    except TimeoutException:
        print(f"Page load timed out for {url}")
        if driver:
            driver.quit()
        return None
    except WebDriverException as e:
        print(f"WebDriver error for {url}: {e}")
        if driver:
            driver.quit()
        return None
    except Exception as e:
        print(f"An unexpected error occurred during scraping {url}: {e}")
        if driver:
            driver.quit()
        return None

if __name__ == "__main__":    # Example usage for testing    test_url = "https://www.example.com" # Replace with a real URL for testing dynamic content    print(f"Attempting to scrape: {test_url}")    html = get_dynamic_html_content(test_url)    if html:        print(f"Successfully scraped HTML content (first 500 chars):\n{html[:500]}...")    else:        print("Failed to scrape content.")