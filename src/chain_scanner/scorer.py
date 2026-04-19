"""
Conviction scorer for option signals.

Produces a 0–100 composite score from edge magnitude, IV rank alignment,
liquidity, and Greeks quality. Higher score = higher conviction.

Options Analytics Team — 2026-04-02
"""

from typing import List

# Default weight vector (must sum to 1.0)
DEFAULT_WEIGHTS = {
    'edge': 0.40,
    'iv_rank': 0.25,
    'liquidity': 0.20,
    'greeks': 0.15,
}


def score_signal(edge_pct: float,
                 iv_rank: float,
                 spread_pct: float,
                 open_interest: int,
                 theta: float,
                 vega: float,
                 direction: str,
                 weights: dict = None) -> float:
    """Compute a 0–100 conviction score for a single signal.

    Parameters
    ----------
    edge_pct : float
        Signed edge (positive = underpriced, negative = overpriced).
    iv_rank : float
        IV rank (0–100).
    spread_pct : float
        Bid-ask spread as % of mid.
    open_interest : int
        Open interest on the contract.
    theta : float
        Theta (per day, typically negative for long).
    vega : float
        Vega (per vol point).
    direction : str
        'BUY' or 'SELL'.
    weights : dict, optional
        Override default scoring weights.

    Returns
    -------
    float
        Conviction score in [0, 100].
    """
    w = weights or DEFAULT_WEIGHTS

    # --- Edge magnitude (0–100) ---
    # 20%+ absolute edge maps to max score
    edge_score = min(abs(edge_pct) / 20.0 * 100.0, 100.0)

    # --- IV rank alignment (0–100) ---
    # SELL when IV is HIGH → good; BUY when IV is LOW → good
    if direction == 'SELL':
        # Higher IV rank = better for selling premium
        iv_score = iv_rank
    else:
        # Lower IV rank = better for buying options
        iv_score = 100.0 - iv_rank

    # --- Liquidity (0–100) ---
    # Spread tightness: 0% spread = 100, 15%+ spread = 0
    spread_score = max(0.0, (1.0 - spread_pct / 15.0)) * 100.0
    # OI contribution: log-scaled, 10k+ OI = max
    import math
    oi_score = min(math.log10(max(open_interest, 1)) / 4.0 * 100.0, 100.0)
    liquidity_score = 0.6 * spread_score + 0.4 * oi_score

    # --- Greeks quality (0–100) ---
    if direction == 'SELL':
        # For selling: favor high |theta|/vega (time decay relative to vol risk)
        if abs(vega) > 1e-8:
            theta_vega_ratio = abs(theta) / abs(vega)
            greeks_score = min(theta_vega_ratio / 0.10 * 100.0, 100.0)
        else:
            greeks_score = 50.0
    else:
        # For buying: favor high vega/|theta| (vol exposure relative to bleed)
        if abs(theta) > 1e-8:
            vega_theta_ratio = abs(vega) / abs(theta)
            greeks_score = min(vega_theta_ratio / 15.0 * 100.0, 100.0)
        else:
            greeks_score = 50.0

    # --- Weighted composite ---
    conviction = (
        w['edge'] * edge_score +
        w['iv_rank'] * iv_score +
        w['liquidity'] * liquidity_score +
        w['greeks'] * greeks_score
    )

    return round(max(0.0, min(conviction, 100.0)), 2)


def rank_signals(signals: list) -> list:
    """Sort signals by conviction descending.

    Parameters
    ----------
    signals : List[OptionSignal]
        Unordered signals.

    Returns
    -------
    List[OptionSignal]
        Sorted by conviction (highest first).
    """
    return sorted(signals, key=lambda s: s.conviction, reverse=True)
