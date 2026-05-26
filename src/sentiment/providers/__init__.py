"""
News provider factory.

Usage:
    provider = create_news_provider()          # uses SENTIMENT_PROVIDER env var
    provider = create_news_provider("csv", csv_path="data/headlines.csv")
    provider = create_news_provider("newsapi")  # uses NEWSAPI_KEY env var
"""

from .base import NewsProvider


def create_news_provider(
    provider_type: str = None,
    **kwargs,
) -> NewsProvider:
    """Create a news provider instance.

    Parameters
    ----------
    provider_type : str, optional
        One of 'csv', 'newsapi', 'benzinga'. Defaults to SENTIMENT_PROVIDER env var.
    **kwargs
        Passed to the provider constructor.

    Returns
    -------
    NewsProvider
    """
    from ..config import NEWS_PROVIDER, NEWSAPI_KEY, BENZINGA_KEY, CSV_PATH

    ptype = (provider_type or NEWS_PROVIDER).lower()

    if ptype == "csv":
        from .csv_provider import CSVProvider
        csv_path = kwargs.get("csv_path", CSV_PATH)
        default_ticker = kwargs.get("default_ticker", "MACRO")
        return CSVProvider(csv_path=csv_path, default_ticker=default_ticker)

    if ptype == "newsapi":
        from .newsapi_provider import NewsAPIProvider
        api_key = kwargs.get("api_key", NEWSAPI_KEY)
        return NewsAPIProvider(api_key=api_key)

    if ptype == "benzinga":
        raise NotImplementedError(
            "Benzinga provider not yet implemented. "
            "Use 'newsapi' or 'csv' for now."
        )

    raise ValueError(f"Unknown news provider: {ptype!r}. Use 'csv', 'newsapi', or 'benzinga'.")


__all__ = ["NewsProvider", "create_news_provider"]
