"""
Tests for CSVProvider — Phase 1 validation.

Run: pytest tests/test_csv_provider.py -v
"""

import os
import tempfile
from datetime import datetime, timedelta

import pytest

from sentiment.providers.csv_provider import CSVProvider


@pytest.fixture
def sample_csv(tmp_path):
    """Create a sample financial news CSV."""
    csv_path = tmp_path / "test_headlines.csv"
    csv_path.write_text(
        "date,ticker,headline,source,url\n"
        "2024-06-01 09:30:00,SPY,S&P 500 opens higher on tech gains,reuters,https://example.com/1\n"
        "2024-06-01 10:15:00,SPY,Markets rally as inflation cools,cnbc,https://example.com/2\n"
        "2024-06-01 11:00:00,QQQ,Nasdaq hits record high amid AI boom,bloomberg,https://example.com/3\n"
        "2024-06-01 14:30:00,SPY,Stocks pull back on profit taking,wsj,https://example.com/4\n"
        "2024-06-02 09:00:00,SPY,Futures point to lower open after jobs data,reuters,https://example.com/5\n"
        "2024-06-02 10:00:00,MACRO,Fed officials hint at rate pause,cnbc,https://example.com/6\n"
        "2024-06-02 11:30:00,QQQ,Tech stocks slide on regulatory concerns,bloomberg,https://example.com/7\n"
    )
    return str(csv_path)


@pytest.fixture
def alt_format_csv(tmp_path):
    """CSV with alternative column names and date format."""
    csv_path = tmp_path / "alt_headlines.csv"
    csv_path.write_text(
        "datetime,title,symbol\n"
        "2024-01-15T14:30:00,Market surges on Fed pivot hopes,SPY\n"
        "2024-01-15T15:00:00,Oil prices drop amid demand fears,USO\n"
        "2024-01-16T09:30:00,Jobs report beats expectations,MACRO\n"
    )
    return str(csv_path)


@pytest.fixture
def no_ticker_csv(tmp_path):
    """CSV without a ticker column — should default to MACRO."""
    csv_path = tmp_path / "macro_headlines.csv"
    csv_path.write_text(
        "date,headline\n"
        "2024-03-01,Global markets react to tariff news\n"
        "2024-03-02,Inflation data surprises to the upside\n"
        "2024-03-03,Central banks signal coordinated easing\n"
    )
    return str(csv_path)


class TestCSVLoading:
    def test_loads_standard_csv(self, sample_csv):
        provider = CSVProvider(sample_csv)
        all_headlines = provider.fetch_headlines("SPY", limit=999)
        assert len(all_headlines) == 4  # 4 SPY headlines

    def test_loads_alt_format(self, alt_format_csv):
        provider = CSVProvider(alt_format_csv)
        all_headlines = provider.fetch_headlines("SPY", limit=999)
        assert len(all_headlines) == 1

    def test_loads_no_ticker(self, no_ticker_csv):
        provider = CSVProvider(no_ticker_csv, default_ticker="MACRO")
        all_headlines = provider.fetch_headlines("MACRO", limit=999)
        assert len(all_headlines) == 3

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            provider = CSVProvider("/nonexistent/path.csv")
            provider.fetch_headlines("SPY")

    def test_lazy_loading(self, sample_csv):
        provider = CSVProvider(sample_csv)
        assert provider._loaded is False
        provider.fetch_headlines("SPY")
        assert provider._loaded is True


class TestFiltering:
    def test_filter_by_ticker(self, sample_csv):
        provider = CSVProvider(sample_csv)
        spy = provider.fetch_headlines("SPY", limit=999)
        qqq = provider.fetch_headlines("QQQ", limit=999)
        assert len(spy) == 4
        assert len(qqq) == 2

    def test_filter_by_since(self, sample_csv):
        provider = CSVProvider(sample_csv)
        since = datetime(2024, 6, 2, 0, 0, 0)
        results = provider.fetch_headlines("SPY", since=since, limit=999)
        assert len(results) == 1  # only June 2 SPY headline

    def test_limit(self, sample_csv):
        provider = CSVProvider(sample_csv)
        results = provider.fetch_headlines("SPY", limit=2)
        assert len(results) == 2

    def test_newest_first(self, sample_csv):
        provider = CSVProvider(sample_csv)
        results = provider.fetch_headlines("SPY", limit=999)
        dates = [h.published_at for h in results]
        assert dates == sorted(dates, reverse=True)

    def test_nonexistent_ticker(self, sample_csv):
        provider = CSVProvider(sample_csv)
        results = provider.fetch_headlines("AAPL", limit=999)
        assert len(results) == 0


class TestMacroHeadlines:
    def test_fetch_macro(self, sample_csv):
        provider = CSVProvider(sample_csv)
        results = provider.fetch_macro_headlines(limit=999)
        # Should match MACRO ticker + any headline with macro keywords
        assert len(results) >= 1
        assert any(h.ticker == "MACRO" for h in results)

    def test_macro_keyword_matching(self, sample_csv):
        provider = CSVProvider(sample_csv)
        results = provider.fetch_macro_headlines(limit=999)
        # "Fed officials hint at rate pause" should match
        texts = [h.text for h in results]
        assert any("Fed" in t for t in texts)


class TestBacktestHelpers:
    def test_date_range(self, sample_csv):
        provider = CSVProvider(sample_csv)
        start, end = provider.get_date_range()
        assert start is not None
        assert end is not None
        assert start < end

    def test_get_tickers(self, sample_csv):
        provider = CSVProvider(sample_csv)
        tickers = provider.get_tickers()
        assert "SPY" in tickers
        assert "QQQ" in tickers

    def test_fetch_window(self, sample_csv):
        provider = CSVProvider(sample_csv)
        start = datetime(2024, 6, 1, 10, 0, 0)
        end = datetime(2024, 6, 1, 15, 0, 0)
        results = provider.fetch_window("SPY", start, end)
        assert len(results) == 2  # 10:15 and 14:30
        for h in results:
            assert start <= h.published_at < end


class TestSourceName:
    def test_source_name(self, sample_csv):
        provider = CSVProvider(sample_csv)
        assert provider.source_name == "csv"
