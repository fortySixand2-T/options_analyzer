"""
Standalone sentiment backtest runner.

Tests the hypothesis: does sentiment velocity predict next-session
directional moves in target indices?

Input:  historical headlines (CSV) + price data (yfinance)
Output: hit rate, avg return, Sharpe, correlation, drawdown

Zero imports from other src/ packages — fully standalone.
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .aggregator import SentimentAggregator
from .config import WINDOWS
from .models import SentimentSnapshot, SignalLabel
from .providers.csv_provider import CSVProvider
from .scorer_factory import create_scorer
from .signal import generate_signal
from .store import SentimentStore

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Full backtest output."""
    # Summary
    ticker: str
    start_date: str
    end_date: str
    total_days: int
    signal_days: int                  # days with actionable signal

    # Per-label breakdown
    label_stats: Dict[str, Dict] = field(default_factory=dict)
    # e.g. {"LEAN_POSITIVE": {"count": 30, "hit_rate": 0.63, "avg_return": 0.12, ...}}

    # Overall metrics
    hit_rate: float = 0.0             # fraction of correct direction predictions
    avg_return: float = 0.0           # mean next-day return when signal is active
    sharpe: float = 0.0               # annualized Sharpe of signal-following strategy
    max_drawdown: float = 0.0
    correlation: float = 0.0          # Pearson corr of sentiment score vs next-day return

    # Raw data for plotting
    daily_log: List[Dict] = field(default_factory=list)


class SentimentBacktester:
    """Run sentiment backtest over historical data.

    Workflow:
    1. Load headlines from CSV
    2. Score all headlines with FinBERT (batch)
    3. For each trading day:
       a. Aggregate sentiment from prior-session headlines
       b. Generate signal
       c. Record next-day return
    4. Compute metrics
    """

    def __init__(
        self,
        csv_path: str,
        ticker: str = "MACRO",
        price_ticker: str = "SPY",
        db_path: str = None,
        prefer_finbert: bool = True,
    ):
        self.csv_path = csv_path
        self.ticker = ticker
        self.price_ticker = price_ticker

        if db_path is None:
            db_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "data", "sentiment_backtest.db",
            )
        self.store = SentimentStore(db_path=db_path)
        self.provider = CSVProvider(csv_path=csv_path, default_ticker=ticker)
        self.scorer = create_scorer(prefer_finbert=prefer_finbert)
        self.aggregator = SentimentAggregator(store=self.store)

    def run(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        primary_window: str = "24h",
        velocity_window: str = "6h",
    ) -> BacktestResult:
        """Execute the backtest.

        Parameters
        ----------
        start_date : str, optional
            YYYY-MM-DD start (default: earliest in CSV).
        end_date : str, optional
            YYYY-MM-DD end (default: latest in CSV).
        primary_window : str
            Window for composite sentiment level.
        velocity_window : str
            Window for velocity computation.

        Returns
        -------
        BacktestResult
        """
        # Step 1: Load and score all headlines
        logger.info("Step 1: Loading headlines from %s", self.csv_path)
        date_range = self.provider.get_date_range()
        if date_range[0] is None:
            raise ValueError("CSV has no headlines")

        all_headlines = self.provider.fetch_headlines(
            self.ticker, limit=999_999
        )
        if not all_headlines:
            all_headlines = self.provider.fetch_macro_headlines(limit=999_999)

        # For market-level backtests, include all tickers' headlines for density
        if len(all_headlines) < 200:
            logger.info("Only %d headlines for %s, loading all tickers", len(all_headlines), self.ticker)
            all_tickers = self.provider.get_tickers()
            seen_texts = {h.text for h in all_headlines}
            for t in all_tickers:
                if t == self.ticker:
                    continue
                extras = self.provider.fetch_headlines(t, limit=999_999)
                for h in extras:
                    if h.text not in seen_texts:
                        seen_texts.add(h.text)
                        from .models import Headline
                        all_headlines.append(Headline(
                            text=h.text,
                            ticker=self.ticker,
                            published_at=h.published_at,
                            source=h.source,
                            url=h.url,
                            collected_at=h.collected_at,
                        ))

        logger.info("Loaded %d headlines", len(all_headlines))

        logger.info("Step 2: Scoring with FinBERT (this may take a while)...")
        scored = self.scorer.score_batch(all_headlines)
        self.store.save_scored(scored)
        logger.info("Scored and stored %d headlines", len(scored))

        # Step 3: Get price data
        logger.info("Step 3: Fetching price data for %s", self.price_ticker)
        prices = self._fetch_prices(start_date, end_date)
        if prices.empty:
            raise ValueError(f"No price data for {self.price_ticker}")

        trading_days = prices.index.tolist()
        logger.info("Price data: %d trading days (%s to %s)",
                     len(trading_days),
                     trading_days[0].strftime("%Y-%m-%d"),
                     trading_days[-1].strftime("%Y-%m-%d"))

        # Step 4: Walk through each trading day
        logger.info("Step 4: Running day-by-day simulation...")
        daily_log = []

        for i in range(len(trading_days) - 1):
            today = trading_days[i]
            tomorrow = trading_days[i + 1]

            # Aggregate sentiment as of market close today
            as_of = datetime(today.year, today.month, today.day, 16, 0, 0)

            snapshots = self.aggregator.aggregate(
                ticker=self.ticker,
                as_of=as_of,
            )

            signal = generate_signal(
                ticker=self.ticker,
                snapshots=snapshots,
                primary_window=primary_window,
                velocity_window=velocity_window,
            )

            # Next-day return (close-to-close)
            today_close = float(prices.loc[today, "Close"])
            tomorrow_close = float(prices.loc[tomorrow, "Close"])
            next_day_return = (tomorrow_close - today_close) / today_close

            daily_log.append({
                "date": today.strftime("%Y-%m-%d"),
                "signal_label": signal.label.value,
                "signal_score": signal.score,
                "velocity": signal.velocity,
                "headline_count": signal.headline_count,
                "is_actionable": signal.is_actionable,
                "next_day_return": round(next_day_return, 6),
                "today_close": today_close,
                "tomorrow_close": tomorrow_close,
            })

        # Step 5: Compute metrics
        logger.info("Step 5: Computing backtest metrics...")
        result = self._compute_metrics(
            daily_log=daily_log,
            ticker=self.ticker,
            start_date=trading_days[0].strftime("%Y-%m-%d"),
            end_date=trading_days[-1].strftime("%Y-%m-%d"),
        )

        self.store.close()
        return result

    def _fetch_prices(
        self,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> pd.DataFrame:
        """Fetch daily OHLCV from yfinance."""
        import yfinance as yf

        date_range = self.provider.get_date_range()
        start = start_date or date_range[0].strftime("%Y-%m-%d")
        end = end_date or date_range[1].strftime("%Y-%m-%d")

        # Add buffer for next-day returns
        end_dt = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=7)
        end_buffered = end_dt.strftime("%Y-%m-%d")

        df = yf.download(self.price_ticker, start=start, end=end_buffered, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        return df

    @staticmethod
    def _compute_metrics(
        daily_log: List[Dict],
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> BacktestResult:
        """Compute backtest metrics from daily log."""
        df = pd.DataFrame(daily_log)

        if df.empty:
            return BacktestResult(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                total_days=0,
                signal_days=0,
            )

        total_days = len(df)
        # A day is actionable if it has a directional signal with enough headlines
        actionable = df[
            (df["headline_count"] >= 3) &
            (df["signal_label"] != "NEUTRAL")
        ]
        signal_days = len(actionable)

        # Overall hit rate (direction prediction)
        if signal_days > 0:
            correct = actionable.apply(
                lambda r: (
                    (r["signal_score"] > 0 and r["next_day_return"] > 0) or
                    (r["signal_score"] < 0 and r["next_day_return"] < 0) or
                    (r["signal_score"] == 0)  # neutral doesn't count as wrong
                ),
                axis=1,
            )
            hit_rate = correct.sum() / signal_days
            avg_return = actionable["next_day_return"].mean()

            # Sharpe (annualized)
            returns = actionable["next_day_return"]
            if returns.std() > 0:
                sharpe = (returns.mean() / returns.std()) * (252 ** 0.5)
            else:
                sharpe = 0.0

            # Max drawdown
            cumulative = (1 + returns).cumprod()
            peak = cumulative.expanding().max()
            drawdown = (cumulative - peak) / peak
            max_drawdown = drawdown.min()

            # Correlation
            correlation = actionable["signal_score"].corr(actionable["next_day_return"])
        else:
            hit_rate = 0.0
            avg_return = 0.0
            sharpe = 0.0
            max_drawdown = 0.0
            correlation = 0.0

        # Per-label stats
        label_stats = {}
        for label in SignalLabel:
            subset = actionable[actionable["signal_label"] == label.value]
            if len(subset) == 0:
                continue
            label_correct = subset.apply(
                lambda r: (
                    (r["signal_score"] > 0 and r["next_day_return"] > 0) or
                    (r["signal_score"] < 0 and r["next_day_return"] < 0)
                ),
                axis=1,
            )
            label_stats[label.value] = {
                "count": len(subset),
                "hit_rate": round(label_correct.sum() / len(subset), 4),
                "avg_return": round(subset["next_day_return"].mean(), 6),
                "total_return": round(subset["next_day_return"].sum(), 6),
                "avg_score": round(subset["signal_score"].mean(), 4),
                "avg_velocity": round(subset["velocity"].mean(), 4),
            }

        return BacktestResult(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            total_days=total_days,
            signal_days=signal_days,
            label_stats=label_stats,
            hit_rate=round(hit_rate, 4),
            avg_return=round(avg_return, 6),
            sharpe=round(sharpe, 4),
            max_drawdown=round(max_drawdown, 4),
            correlation=round(correlation if not np.isnan(correlation) else 0.0, 4),
            daily_log=daily_log,
        )


def run_backtest(
    csv_path: str,
    ticker: str = "MACRO",
    price_ticker: str = "SPY",
    start_date: str = None,
    end_date: str = None,
    primary_window: str = "24h",
    velocity_window: str = "6h",
    db_path: str = None,
    prefer_finbert: bool = True,
) -> BacktestResult:
    """Convenience function to run a sentiment backtest.

    Usage:
        from sentiment.backtest import run_backtest
        result = run_backtest("data/headlines.csv", price_ticker="SPY")
        print(f"Hit rate: {result.hit_rate:.1%}")
        print(f"Sharpe: {result.sharpe:.2f}")
    """
    bt = SentimentBacktester(
        csv_path=csv_path,
        ticker=ticker,
        price_ticker=price_ticker,
        db_path=db_path,
        prefer_finbert=prefer_finbert,
    )
    return bt.run(
        start_date=start_date,
        end_date=end_date,
        primary_window=primary_window,
        velocity_window=velocity_window,
    )
