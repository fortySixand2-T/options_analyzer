"""
NewsAPI.org provider.

Free tier: 100 requests/day, 1-month lookback.
Requires NEWSAPI_KEY environment variable.

Rate limiting is handled by the caller (scheduler or collector script).
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from ..models import Headline
from .base import NewsProvider

logger = logging.getLogger(__name__)


class NewsAPIProvider(NewsProvider):
    """Fetch financial headlines from NewsAPI.org."""

    BASE_URL = "https://newsapi.org/v2/everything"

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("NEWSAPI_KEY is required for NewsAPIProvider")
        self._api_key = api_key

    def fetch_headlines(
        self,
        ticker: str,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> List[Headline]:
        import requests

        if since is None:
            since = datetime.utcnow() - timedelta(hours=24)

        params = {
            "q": ticker,
            "from": since.strftime("%Y-%m-%dT%H:%M:%S"),
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": min(limit, 100),
            "apiKey": self._api_key,
            # Financial sources for higher signal-to-noise
            "domains": (
                "reuters.com,bloomberg.com,cnbc.com,wsj.com,"
                "marketwatch.com,finance.yahoo.com,barrons.com,"
                "seekingalpha.com,benzinga.com,thestreet.com"
            ),
        }

        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("NewsAPI request failed: %s", e)
            return []

        if data.get("status") != "ok":
            logger.error("NewsAPI error: %s", data.get("message", "unknown"))
            return []

        headlines = []
        for article in data.get("articles", []):
            title = (article.get("title") or "").strip()
            if not title or title == "[Removed]":
                continue

            pub_str = article.get("publishedAt", "")
            try:
                pub_dt = datetime.strptime(pub_str[:19], "%Y-%m-%dT%H:%M:%S")
            except (ValueError, IndexError):
                continue

            headlines.append(Headline(
                text=title,
                ticker=ticker.upper(),
                published_at=pub_dt,
                source="newsapi",
                url=article.get("url"),
            ))

        logger.info("NewsAPI: %d headlines for %s since %s",
                     len(headlines), ticker, since.isoformat())
        return sorted(headlines, key=lambda h: h.published_at, reverse=True)

    def fetch_macro_headlines(
        self,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> List[Headline]:
        import requests

        if since is None:
            since = datetime.utcnow() - timedelta(hours=24)

        params = {
            "q": "stock market OR federal reserve OR inflation OR S&P 500",
            "from": since.strftime("%Y-%m-%dT%H:%M:%S"),
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": min(limit, 100),
            "apiKey": self._api_key,
            "domains": (
                "reuters.com,bloomberg.com,cnbc.com,wsj.com,"
                "marketwatch.com,finance.yahoo.com"
            ),
        }

        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("NewsAPI macro request failed: %s", e)
            return []

        headlines = []
        for article in data.get("articles", []):
            title = (article.get("title") or "").strip()
            if not title or title == "[Removed]":
                continue

            pub_str = article.get("publishedAt", "")
            try:
                pub_dt = datetime.strptime(pub_str[:19], "%Y-%m-%dT%H:%M:%S")
            except (ValueError, IndexError):
                continue

            headlines.append(Headline(
                text=title,
                ticker="MACRO",
                published_at=pub_dt,
                source="newsapi",
                url=article.get("url"),
            ))

        return sorted(headlines, key=lambda h: h.published_at, reverse=True)[:limit]

    @property
    def source_name(self) -> str:
        return "newsapi"
