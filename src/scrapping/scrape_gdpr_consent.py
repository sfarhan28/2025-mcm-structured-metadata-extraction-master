"""
Simple GDPR consent banner scraper using Selenium.
"""

import pandas as pd
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

# List of button keywords to look for
BUTTON_KEYWORDS = [
    "cookie settings", "manage preferences", "manage my preferences",
    "customize", "customise", "privacy settings", "show details"
]

def find_banner_elements(driver):
    # Try to find consent banner and relevant buttons/links
    banner = None
    buttons = []
    try:
        # Look for common banner containers
        banners = driver.find_elements(By.XPATH, "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'cookie')]")
        if banners:
            banner = banners[0]
        # Find all clickable elements with relevant keywords
        for keyword in BUTTON_KEYWORDS:
            elements = driver.find_elements(By.XPATH, f"//*[self::button or self::a][contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{keyword}')]")
            for el in elements:
                buttons.append((keyword, el.text.strip()))
    except Exception as e:
        pass
    return banner, buttons

def scrape_website(url):
    result = {
        "url": url,
        "initial_banner_found": False,
        "settings_button_present": False,
        "settings_button_text": "",
        "error_log": "",
    }
    try:
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        driver = webdriver.Chrome(options=options)
        driver.get(url)
        time.sleep(5)  # Wait for banner to load

        banner, buttons = find_banner_elements(driver)
        result["initial_banner_found"] = bool(banner)
        if buttons:
            result["settings_button_present"] = True
            result["settings_button_text"] = "; ".join([b[1] for b in buttons])
        driver.quit()
    except Exception as e:
        result["error_log"] = str(e)
    return result

def main():
    input_csv = "websites.csv"
    output_csv = "gdpr_consent_scraped.csv"
    df = pd.read_csv(input_csv)
    results = []
    for url in df['url']:
        print(f"Scraping: {url}")
        row = scrape_website(url)
        results.append(row)
    pd.DataFrame(results).to_csv(output_csv, index=False)
    print(f"Done. Results saved to {output_csv}")

if __name__ == "__main__":
    main()