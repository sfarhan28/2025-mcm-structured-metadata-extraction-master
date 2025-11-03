# File: generate_website_list.py
"""
Script to generate a randomized list of website URLs for GDPR scraping.
"""

import pandas as pd
import random

categories = {
    "E-commerce": [
        "https://www.zalando.de", "https://www.aboutyou.de", "https://www.otto.de",
        "https://www.mediamarkt.de", "https://www.saturn.de", "https://www.bol.com",
        "https://www.coolblue.nl", "https://www.wehkamp.nl", "https://www.alza.de",
        "https://www.notino.de", "https://www.manomano.de", "https://www.zooplus.de",
        "https://www.idealo.de", "https://www.galaxus.de", "https://www.conrad.de",
        "https://www.parfumdreams.de", "https://www.voelkner.de", "https://www.banggood.com",
        "https://www.etsy.com", "https://www.ebay.de", "https://www.amazon.de",
        "https://www.ebay-kleinanzeigen.de", "https://www.kaufland.de", "https://www.rewe.de",
        "https://www.lidl.de", "https://www.aldi.de", "https://www.metro.de",
        "https://www.mediamarkt.de", "https://www.saturn.de", "https://www.obi.de"
    ],
    "Media/News": [
        "https://www.spiegel.de", "https://www.bild.de", "https://www.faz.net",
        "https://www.zeit.de", "https://www.sueddeutsche.de", "https://www.tagesschau.de",
        "https://www.n-tv.de", "https://www.welt.de", "https://www.focus.de",
        "https://www.stern.de", "https://www.t-online.de", "https://www.handelsblatt.com",
        "https://www.wiwo.de", "https://www.nzz.ch", "https://www.theguardian.com",
        "https://www.bbc.com", "https://www.cnn.com", "https://www.nytimes.com",
        "https://www.washingtonpost.com", "https://www.reuters.com", "https://www.bloomberg.com",
        "https://www.aljazeera.com", "https://www.dw.com", "https://www.euronews.com",
        "https://www.politico.eu", "https://www.euractiv.com", "https://www.local.de",
        "https://www.morgenpost.de", "https://www.abendzeitung.de"
    ],
    # Additional categories (Banking, Healthcare, etc.) with similar URL lists
    # ... [truncated for brevity]
}

# Generate 30 URLs per category
urls = []
for category, sites in categories.items():
    urls += random.sample(sites, 30) if len(sites) > 30 else sites

pd.DataFrame({"url": urls}).to_csv("new-websites.csv", index=False)
