"""
Scrapy spider for generalized GDPR consent banner detection and MongoDB storage.
"""

import scrapy
from scrapy_splash import SplashRequest
from pymongo import MongoClient
import time
import random
import json
import logging

class GeneralizedConsentSpider(scrapy.Spider):
    name = 'generalized_consent_scraper'
    
    # --- Heuristic Detection Keywords ---
    # These keywords are used to find banners when specific selectors fail.
    BANNER_TEXT_KEYWORDS = [
        'cookie', 'consent', 'privacy', 'gdpr', 'data protection', 
        'personal data', 'we use cookies'
    ]
    ACTION_BUTTON_KEYWORDS = [
        'accept', 'agree', 'allow', 'ok', 'got it', 'continue to site',
        'reject', 'decline', 'manage', 'options', 'settings', 'preferences'
    ]

    def __init__(self, *args, **kwargs):
        super(GeneralizedConsentSpider, self).__init__(*args, **kwargs)
        self.client = MongoClient('mongodb://localhost:27017/')
        self.db = self.client['gdpr_consent_research']
        self.collection = self.db['consent_banners']
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        ]
        
    def start_requests(self):
        urls = self.load_target_websites()
        for url in urls:
            yield SplashRequest(
                url=url,
                callback=self.parse,
                args={'wait': 10, 'html': 1, 'png': 1, 'timeout': 90},
                headers={'User-Agent': random.choice(self.user_agents)}
            )
            time.sleep(random.uniform(2, 4)) # Be respectful to servers

    def parse(self, response):
        """
        Main parsing function that orchestrates the detection process.
        """
        self.logger.info(f"Processing URL: {response.url}")
        
        banner_element, detection_method, vendor = self.find_consent_banner(response)
        
        banner_data = {
            'url': response.url,
            'timestamp': time.time(),
            'detected': False,
            'detection_method': 'none',
            'cmp_vendor': None,
            'banner_text': None,
            'buttons': [],
            'html_snippet': None,
            'screenshot': response.data.get('png')
        }

        if banner_element:
            self.logger.info(f"SUCCESS: Found consent banner on {response.url} using method: {detection_method}")
            
            banner_data.update({
                'detected': True,
                'detection_method': detection_method,
                'cmp_vendor': vendor,
                'banner_text': ' '.join(banner_element.css('::text').getall()).strip(),
                'buttons': self.extract_buttons(banner_element),
                'html_snippet': banner_element.get()
            })
        else:
            self.logger.warning(f"FAILURE: No consent banner found on {response.url}")

        self.collection.insert_one(banner_data)
        yield banner_data

    def find_consent_banner(self, response):
        """
        Tries multiple methods to find the consent banner element.
        Returns (banner_element, detection_method, vendor_name) or (None, None, None).
        """
        # Method 1: Known CMP Vendors (Most Reliable)
        vendor_selectors = {
            'quantcast': 'div[data-qc-cmp-ui]',
            'onetrust': '#onetrust-consent-sdk',
            'cookiebot': '#CybotCookiebotDialog',
            'trustarc': '#truste-consent-track'
        }
        for vendor, selector in vendor_selectors.items():
            element = response.css(selector)
            if element:
                return element, 'vendor_selector', vendor

        # Method 2: General Keyword Selectors
        keyword_selectors = ['[id*="cookie"]', '[class*="cookie"]', '[id*="consent"]', '[class*="consent"]', '[id*="gdpr"]', '[class*="gdpr"]']
        for selector in keyword_selectors:
            element = response.css(selector)
            # Find the most likely candidate (often a top-level banner div)
            for el in element:
                text_content = ''.join(el.css('::text').getall()).lower()
                if any(kw in text_content for kw in self.BANNER_TEXT_KEYWORDS):
                    return el, 'keyword_selector', 'generic'

        # Method 3: Heuristic Text-Based Search (Most General)
        # Find an element containing banner-like text, then return its parent.
        for keyword in self.BANNER_TEXT_KEYWORDS:
            # XPath is powerful for finding text content anywhere in the document
            elements_with_text = response.xpath(f'//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{keyword}")]/..')
            if elements_with_text:
                # We assume the first one found is our best candidate
                return elements_with_text[0], 'heuristic_text_search', 'generic_heuristic'

        return None, None, None

    def extract_buttons(self, banner_element):
        """
        Finds all buttons or links within the banner element.
        """
        buttons = []
        # Look for <button> tags and <a> tags with role="button"
        for btn in banner_element.css('button, a[role="button"]'):
            btn_text = ' '.join(btn.css('::text').getall()).strip()
            if btn_text:
                buttons.append(btn_text)
        return buttons

    def load_target_websites(self):
        """
        Load a diverse set of target websites for scraping.
        """
        # Use a more diverse list for testing the generalized approach
        return [
            'https://www.theguardian.com/international',
            'https://www.reuters.com/',
            'https://www.nytimes.com/',
            'https://www.forbes.com/',
            'https://edition.cnn.com/',
            'https://www.instructables.com/', # Known to have a simple banner
            'https://www.techradar.com/'
        ]

# --- Main execution block with CORRECT settings ---
if __name__ == "__main__":
    from scrapy.crawler import CrawlerProcess
    
    process = CrawlerProcess({
        'USER_AGENT': 'GDPR Research Bot/1.0 (+http://your-research-project.com/about)',
        'ROBOTSTXT_OBEY': True,
        'DOWNLOAD_DELAY': 2,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'CONCURRENT_REQUESTS': 1,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
        'SPLASH_URL': 'http://localhost:8050',
        'LOG_LEVEL': 'INFO', # Set log level to see more output
        
        'DOWNLOADER_MIDDLEWARES': {
            'scrapy_splash.SplashCookiesMiddleware': 723,
            'scrapy_splash.SplashMiddleware': 725,
            'scrapy.downloadermiddlewares.httpcompression.HttpCompressionMiddleware': 810,
        },
        'SPIDER_MIDDLEWARES': {
            'scrapy_splash.SplashDeduplicateArgsMiddleware': 100,
        },
        'DUPEFILTER_CLASS': 'scrapy_splash.SplashAwareDupeFilter',
        'HTTPCACHE_STORAGE': 'scrapy_splash.SplashAwareFSCacheStorage',
    })
    
    process.crawl(GeneralizedConsentSpider)
    process.start()
