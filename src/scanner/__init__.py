"""
Options Chain Scanner — scans watchlists for high-conviction trade signals.

Public API:
    scan_watchlist(tickers, provider, config) -> List[OptionSignal]
    OptionSignal — scored trade signal dataclass

Options Analytics Team — 2026-04-02
"""

from dataclasses import dataclass


@dataclass
class OptionSignal:
    """Single scored options trade signal."""
    # Contract identity
    ticker: str
    strike: float
    expiry: str
    option_type: str               # 'call' / 'put'
    dte: int

    # Market data
    spot: float
    bid: float
    ask: float
    mid: float
    open_interest: int
    bid_ask_spread_pct: float      # (ask - bid) / mid * 100

    # IV context
    chain_iv: float                # IV from the chain
    iv_rank: float                 # 0–100
    iv_percentile: float           # 0–100
    iv_regime: str                 # LOW_IV / MODERATE_IV / HIGH_IV

    # Edge
    garch_vol: float               # GARCH-calibrated forward vol
    theo_price: float              # BS price using garch_vol
    edge_pct: float                # (theo - mid) / mid * 100
    direction: str                 # BUY (positive edge) / SELL (negative edge)

    # Greeks (BS, computed at chain IV)
    delta: float
    gamma: float
    theta: float
    vega: float

    # Conviction
    conviction: float              # 0–100, weighted composite


def scan_watchlist(tickers, provider=None, config=None):
    """Convenience wrapper: scan a list of tickers and return ranked signals.

    Parameters
    ----------
    tickers : List[str]
        Ticker symbols to scan.
    provider : ChainProvider, optional
        Data provider (default: cached YFinanceProvider).
    config : dict, optional
        Scanner config overrides.

    Returns
    -------
    List[OptionSignal]
        Ranked by conviction descending.
    """
    from .scanner import OptionsScanner
    from .providers import create_provider

    if provider is None:
        provider = create_provider()
    scanner = OptionsScanner(provider=provider, config=config)
    return scanner.scan_watchlist(tickers)


__all__ = ['OptionSignal', 'scan_watchlist']
