"""
Collect real financial headlines for sentiment backtesting.

Sources:
1. yfinance Ticker.news — per-ticker headlines from Yahoo Finance
2. RSS feeds — broad market/macro headlines from free feeds

Output: data/headlines_real.csv (date, headline, source, ticker)
"""

import csv
import hashlib
import logging
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import List, Dict
from urllib.request import urlopen, Request
from urllib.error import URLError

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

TICKERS = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA"]

RSS_FEEDS = [
    ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY&region=US&lang=en-US", "yahoo", "SPY"),
    ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=QQQ&region=US&lang=en-US", "yahoo", "QQQ"),
    ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL&region=US&lang=en-US", "yahoo", "AAPL"),
    ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=NVDA&region=US&lang=en-US", "yahoo", "NVDA"),
    ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US", "yahoo", "MACRO"),
    ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EVIX&region=US&lang=en-US", "yahoo", "MACRO"),
]

USER_AGENT = "Mozilla/5.0 (compatible; OptionScanner/1.0)"


def _dedup_key(headline: str, date: str) -> str:
    return hashlib.md5(f"{headline.strip().lower()}|{date[:10]}".encode()).hexdigest()


def collect_from_yfinance() -> List[Dict]:
    """Pull headlines via yfinance Ticker.news."""
    import yfinance as yf

    all_headlines = []
    for ticker in TICKERS:
        try:
            t = yf.Ticker(ticker)
            news = t.news or []
            logger.info("yfinance %s: %d items", ticker, len(news))

            for item in news:
                content = item.get("content", item)
                title = content.get("title", "") if isinstance(content, dict) else item.get("title", "")
                if not title:
                    continue

                pub_ts = None
                if isinstance(content, dict):
                    pub_date = content.get("pubDate")
                    if pub_date:
                        try:
                            pub_ts = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                        except (ValueError, TypeError):
                            pass

                if pub_ts is None:
                    pub_epoch = item.get("providerPublishTime") or item.get("publish_time")
                    if pub_epoch and isinstance(pub_epoch, (int, float)):
                        pub_ts = datetime.fromtimestamp(pub_epoch, tz=timezone.utc)

                if pub_ts is None:
                    continue

                source = "yahoo"
                if isinstance(content, dict):
                    provider = content.get("provider", {})
                    if isinstance(provider, dict):
                        source = provider.get("displayName", "yahoo").lower()

                all_headlines.append({
                    "date": pub_ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "headline": title.strip(),
                    "source": source,
                    "ticker": ticker,
                })
        except Exception as e:
            logger.warning("yfinance %s failed: %s", ticker, e)

    return all_headlines


def collect_from_rss() -> List[Dict]:
    """Pull headlines from RSS feeds."""
    all_headlines = []

    for url, source, ticker in RSS_FEEDS:
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=15) as resp:
                xml_data = resp.read()

            root = ET.fromstring(xml_data)
            items = root.findall(".//item")
            logger.info("RSS %s (%s): %d items", ticker, source, len(items))

            for item in items:
                title_el = item.find("title")
                pub_el = item.find("pubDate")
                if title_el is None or not title_el.text:
                    continue

                pub_ts = None
                if pub_el is not None and pub_el.text:
                    try:
                        from email.utils import parsedate_to_datetime
                        pub_ts = parsedate_to_datetime(pub_el.text)
                    except Exception:
                        pass

                if pub_ts is None:
                    pub_ts = datetime.now(timezone.utc)

                all_headlines.append({
                    "date": pub_ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "headline": title_el.text.strip(),
                    "source": source,
                    "ticker": ticker,
                })
        except (URLError, ET.ParseError) as e:
            logger.warning("RSS %s failed: %s", url, e)
        except Exception as e:
            logger.warning("RSS %s unexpected error: %s", url, e)

    return all_headlines


def main():
    output_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "headlines_real.csv",
    )

    logger.info("Collecting headlines from yfinance...")
    yf_headlines = collect_from_yfinance()

    logger.info("Collecting headlines from RSS feeds...")
    rss_headlines = collect_from_rss()

    all_headlines = yf_headlines + rss_headlines

    # Deduplicate
    seen = set()
    unique = []
    for h in all_headlines:
        key = _dedup_key(h["headline"], h["date"])
        if key not in seen:
            seen.add(key)
            unique.append(h)

    # Sort by date
    unique.sort(key=lambda h: h["date"])

    # Merge with existing if file exists
    existing = []
    if os.path.isfile(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = _dedup_key(row.get("headline", ""), row.get("date", ""))
                if key not in seen:
                    seen.add(key)
                    existing.append(row)
        logger.info("Merged with %d existing headlines", len(existing))

    all_final = existing + unique
    all_final.sort(key=lambda h: h.get("date", ""))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "headline", "source", "ticker"])
        writer.writeheader()
        writer.writerows(all_final)

    logger.info("Wrote %d headlines to %s", len(all_final), output_path)

    # Stats
    tickers = {}
    for h in all_final:
        t = h.get("ticker", "UNKNOWN")
        tickers[t] = tickers.get(t, 0) + 1

    dates = [h["date"][:10] for h in all_final]
    if dates:
        logger.info("Date range: %s to %s", min(dates), max(dates))

    for t, count in sorted(tickers.items(), key=lambda x: -x[1]):
        logger.info("  %s: %d headlines", t, count)


if __name__ == "__main__":
    main()
