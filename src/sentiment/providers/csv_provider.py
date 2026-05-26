"""
CSV-based news provider for backtesting.

Loads historical headlines from a CSV file with columns:
    date, time (optional), ticker, headline, source (optional), url (optional)

Supports common Kaggle financial news datasets.
Handles multiple date formats gracefully.
"""

import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from ..models import Headline
from .base import NewsProvider

logger = logging.getLogger(__name__)

# Common date formats in financial news CSVs
_DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y",
]


def _parse_datetime(text: str) -> Optional[datetime]:
    """Try multiple date formats, return None on failure."""
    text = text.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


class CSVProvider(NewsProvider):
    """Replay headlines from a CSV file.

    Expected CSV columns (case-insensitive, flexible matching):
        Required: date/datetime/published_at, headline/title/text
        Optional: ticker/symbol, source, url

    If no ticker column exists, all headlines are assigned to a default ticker.
    """

    def __init__(self, csv_path: str, default_ticker: str = "MACRO"):
        self._path = Path(csv_path)
        self._default_ticker = default_ticker
        self._headlines: List[Headline] = []
        self._loaded = False

    def _ensure_loaded(self):
        """Lazy-load CSV on first access."""
        if self._loaded:
            return

        if not self._path.exists():
            raise FileNotFoundError(f"CSV not found: {self._path}")

        logger.info("Loading headlines from %s", self._path)

        # Detect column mapping
        with open(self._path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise ValueError("CSV has no header row")

            # Normalize column names
            col_lower = {c.lower().strip(): c for c in reader.fieldnames}

            # Find date column
            date_col = None
            for candidate in ["published_at", "datetime", "date", "timestamp", "time"]:
                if candidate in col_lower:
                    date_col = col_lower[candidate]
                    break
            if date_col is None:
                raise ValueError(
                    f"No date column found. Columns: {list(reader.fieldnames)}"
                )

            # Find text column
            text_col = None
            for candidate in ["headline", "title", "text", "news", "content", "description"]:
                if candidate in col_lower:
                    text_col = col_lower[candidate]
                    break
            if text_col is None:
                raise ValueError(
                    f"No headline column found. Columns: {list(reader.fieldnames)}"
                )

            # Optional columns
            ticker_col = None
            for candidate in ["ticker", "symbol", "stock"]:
                if candidate in col_lower:
                    ticker_col = col_lower[candidate]
                    break

            source_col = col_lower.get("source")
            url_col = col_lower.get("url")

            # Handle 'time' column separate from 'date' column
            time_col = None
            if date_col.lower() == "date" and "time" in col_lower:
                time_col = col_lower["time"]

            headlines = []
            skipped = 0
            for row in reader:
                text = (row.get(text_col) or "").strip()
                if not text:
                    skipped += 1
                    continue

                # Parse date
                date_str = (row.get(date_col) or "").strip()
                if time_col:
                    time_str = (row.get(time_col) or "").strip()
                    if time_str:
                        date_str = f"{date_str} {time_str}"

                pub_dt = _parse_datetime(date_str)
                if pub_dt is None:
                    skipped += 1
                    continue

                ticker = (
                    (row.get(ticker_col) or "").strip().upper()
                    if ticker_col
                    else self._default_ticker
                )
                if not ticker:
                    ticker = self._default_ticker

                headlines.append(Headline(
                    text=text,
                    ticker=ticker,
                    published_at=pub_dt,
                    source=row.get(source_col, "csv") if source_col else "csv",
                    url=row.get(url_col) if url_col else None,
                    collected_at=pub_dt,  # historical — use publish time
                ))

            self._headlines = sorted(headlines, key=lambda h: h.published_at)
            self._loaded = True
            logger.info(
                "Loaded %d headlines (%d skipped) spanning %s to %s",
                len(self._headlines),
                skipped,
                self._headlines[0].published_at.date() if self._headlines else "N/A",
                self._headlines[-1].published_at.date() if self._headlines else "N/A",
            )

    def fetch_headlines(
        self,
        ticker: str,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> List[Headline]:
        self._ensure_loaded()

        results = [
            h for h in self._headlines
            if h.ticker == ticker.upper()
            and (since is None or h.published_at >= since)
        ]
        # Return newest first, capped at limit
        return sorted(results, key=lambda h: h.published_at, reverse=True)[:limit]

    def fetch_macro_headlines(
        self,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> List[Headline]:
        self._ensure_loaded()

        from ..config import MACRO_KEYWORDS

        results = []
        for h in self._headlines:
            if since and h.published_at < since:
                continue
            # Match if ticker is MACRO or headline contains macro keywords
            if h.ticker == "MACRO" or any(
                kw in h.text.lower() for kw in MACRO_KEYWORDS
            ):
                results.append(h)

        return sorted(results, key=lambda h: h.published_at, reverse=True)[:limit]

    @property
    def source_name(self) -> str:
        return "csv"

    # ── Backtest helpers ───────────────────────────────────────────────────

    def get_date_range(self) -> tuple:
        """Return (earliest, latest) datetime in the dataset."""
        self._ensure_loaded()
        if not self._headlines:
            return (None, None)
        return (self._headlines[0].published_at, self._headlines[-1].published_at)

    def get_tickers(self) -> List[str]:
        """Return all unique tickers in the dataset."""
        self._ensure_loaded()
        return sorted(set(h.ticker for h in self._headlines))

    def fetch_window(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
    ) -> List[Headline]:
        """Fetch all headlines for a ticker within a time window.

        Used by the backtester to replay a specific day's headlines.
        """
        self._ensure_loaded()
        return [
            h for h in self._headlines
            if h.ticker == ticker.upper()
            and start <= h.published_at < end
        ]
