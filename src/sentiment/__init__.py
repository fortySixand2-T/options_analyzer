"""
Sentiment Analysis Module — standalone, pluggable news-sentiment pipeline.

Public API:
    get_sentiment(ticker)     → SentimentSignal
    SentimentSignal           — final output dataclass (label, score, velocity)
    SignalLabel               — enum: STRONG_POSITIVE → STRONG_NEGATIVE

For backtesting:
    run_backtest(csv_path)    → BacktestResult

This module has zero imports from other src/ packages.
See DESIGN.md for architecture details.
"""

from .models import (
    Headline,
    ScoredHeadline,
    SentimentLabel,
    SentimentSignal,
    SentimentSnapshot,
    SignalLabel,
)


def get_sentiment(
    ticker: str,
    provider_type: str = None,
    primary_window: str = "6h",
    velocity_window: str = "1h",
    **provider_kwargs,
) -> SentimentSignal:
    """Get the current sentiment signal for a ticker.

    This is the main entry point for external systems. It:
    1. Fetches recent headlines from the configured provider
    2. Scores them with FinBERT
    3. Aggregates into rolling windows
    4. Returns a single SentimentSignal

    Parameters
    ----------
    ticker : str
        Ticker symbol (e.g. 'SPY') or 'MACRO' for index-level sentiment.
    provider_type : str, optional
        News provider: 'newsapi', 'benzinga', or 'csv'.
        Defaults to SENTIMENT_PROVIDER env var.
    primary_window : str
        Window for composite level (default '6h').
    velocity_window : str
        Window for velocity (default '1h').
    **provider_kwargs
        Passed to the provider constructor.

    Returns
    -------
    SentimentSignal
        Contains .label (SignalLabel), .score (float), .velocity (float),
        .confidence (float), .headline_count (int), .is_actionable (bool).

    Example
    -------
    >>> from sentiment import get_sentiment
    >>> sig = get_sentiment("SPY", provider_type="newsapi")
    >>> print(sig.label, sig.score, sig.velocity)
    LEAN_POSITIVE 0.23 0.08
    >>> if sig.is_actionable:
    ...     print("Signal has enough data to act on")
    """
    from .aggregator import SentimentAggregator
    from .providers import create_news_provider
    from .scorer import SentimentScorer
    from .signal import generate_signal
    from .store import SentimentStore

    # 1. Fetch headlines
    provider = create_news_provider(provider_type, **provider_kwargs)
    headlines = provider.fetch_headlines(ticker)

    if not headlines:
        return SentimentSignal(
            ticker=ticker,
            label=SignalLabel.NEUTRAL,
            score=0.0,
            velocity=0.0,
            confidence=0.0,
            headline_count=0,
            detail={"reason": "no headlines available"},
        )

    # 2. Score with FinBERT
    scorer = SentimentScorer()
    scored = scorer.score_batch(headlines)

    # 3. Persist
    store = SentimentStore()
    store.save_scored(scored)

    # 4. Aggregate
    aggregator = SentimentAggregator(store=store)
    snapshots = aggregator.aggregate(ticker)

    # 5. Generate signal
    signal = generate_signal(
        ticker=ticker,
        snapshots=snapshots,
        primary_window=primary_window,
        velocity_window=velocity_window,
    )

    store.close()
    return signal


__all__ = [
    "get_sentiment",
    "Headline",
    "ScoredHeadline",
    "SentimentLabel",
    "SentimentSignal",
    "SentimentSnapshot",
    "SignalLabel",
]
