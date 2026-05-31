"""
signal_lib — point-in-time directional/volatility signals for IC research.

This is the "alpha layer" of the research stack (see ARCHITECTURE_EVOLUTION,
F-018). The thesis we are testing — desk-quant style — is that a tradeable edge
has two independent layers with very different data needs:

    1. SIGNAL  : does feature X predict the *underlying's* forward return?
                 → needs only cheap underlying OHLCV (decades, free).
    2. EXECUTION: can that move be harvested through options net of fills?
                 → needs scarce option BBO/OI (Dolt 2020-24, expensive).

F-017 found "no alpha" only because the two layers were always tested fused
together (bias_score → option P&L), which conflates a weak signal with option
mechanics and beta. This module isolates layer 1: each function maps daily
OHLCV (+ optional exogenous series) to a per-day signal score, computed
POINT-IN-TIME (every value uses only data available up to and including that
day — the trailing-window construction guarantees no lookahead). The forward
return is supplied later by the IC harness (signal_eval), never here.

The three signals below were chosen (F-018 agent survey) as the most
orthogonal, free/cheap, literature-backed candidates:

  - short_term_reversal : price-overreaction axis (Jegadeesh 1990, Lehmann 1990)
  - ts_momentum         : trend/underreaction axis (Moskowitz-Ooi-Pedersen 2012)
  - vix_term_structure  : implied-vol / fear axis  (Bollerslev-Tauchen-Zhou 2009)

Sign convention: each signal is oriented so that a POSITIVE value is the
hypothesised bullish reading. The IC test reports the realised sign regardless
— for the VIX term structure in particular the directional sign is genuinely
regime-dependent, so we do not hardcode a directional assumption, we measure it.
"""

from typing import Callable, Dict, Optional

import numpy as np
import pandas as pd


def _close(df: pd.DataFrame) -> pd.Series:
    """Return the close-price series, tolerating Title or lowercase columns."""
    return df["Close"] if "Close" in df.columns else df["close"]


def short_term_reversal(df: pd.DataFrame, aux: Optional[Dict] = None,
                        lookback: int = 5) -> pd.Series:
    """Short-term reversal: negate the trailing `lookback`-day return.

    Recent losers tend to bounce and recent winners to fade over the next few
    days (overreaction premium). Positive signal = recent loser = expect a
    rebound. Strongest at H=3-5 and on single names; near-zero on index ETFs.
    """
    c = _close(df)
    trailing = c / c.shift(lookback) - 1.0
    return -trailing


def ts_momentum(df: pd.DataFrame, aux: Optional[Dict] = None,
                lookback: int = 63, vol_window: int = 20) -> pd.Series:
    """Volatility-scaled time-series momentum (3-month trailing return / RV).

    An instrument's own trailing return positively predicts its near-term
    return (underreaction/trend). Scaling by realised volatility puts the
    signal on a comparable footing across regimes/symbols. Positive = uptrend.
    Best at H=10; vulnerable to momentum crashes (sharp post-selloff rebounds).
    """
    c = _close(df)
    mom = c / c.shift(lookback) - 1.0
    # Annualised realised vol from daily close-to-close returns.
    rv = c.pct_change().rolling(vol_window).std() * np.sqrt(252.0)
    rv = rv.replace(0.0, np.nan)
    return mom / rv


def vix_term_structure(df: pd.DataFrame, aux: Optional[Dict] = None,
                       z_window: int = 60) -> pd.Series:
    """VIX term-structure slope, z-scored: VIX/VIX3M − 1.

    Contango (VIX < VIX3M, slope < 0) = calm; backwardation (VIX > VIX3M,
    slope > 0) = stress. Whether stress predicts a bounce (contrarian, positive
    IC) or further weakness (positive slope → negative forward return) is
    regime-dependent, so we emit the raw z-scored slope (positive = stress) and
    let the IC test reveal the sign rather than baking one in.

    Requires aux['vix'] and aux['vix3m'] as date-indexed Series; they are
    reindexed onto `df` and forward-filled (both are known as-of the same
    close, so no extra lag is applied).
    """
    if not aux or "vix" not in aux or "vix3m" not in aux:
        raise ValueError("vix_term_structure requires aux['vix'] and aux['vix3m']")
    vix = aux["vix"].reindex(df.index).ffill()
    vix3m = aux["vix3m"].reindex(df.index).ffill()
    slope = vix / vix3m - 1.0
    mean = slope.rolling(z_window).mean()
    std = slope.rolling(z_window).std().replace(0.0, np.nan)
    return (slope - mean) / std


def conditioned_reversal(df: pd.DataFrame, aux: Optional[Dict] = None,
                         lookback: int = 63, vol_window: int = 20,
                         gate: str = "contango", pct_window: int = 252) -> pd.Series:
    """Calm-regime medium-horizon reversal — the F-018 lead, made tradeable.

    Signal = −(vol-scaled `lookback`-day return), emitted ONLY on calm days and
    NaN otherwise (so it never takes a position in stress). Positive value =
    recent medium-horizon loser in a calm tape = expected to revert UP, so a
    positive IC means the signal is predictive.

    The calm GATE is strictly point-in-time (no full-sample lookahead, unlike
    the median split that first surfaced the lead in the sweep):
      - "contango"  : VIX < VIX3M today (term structure upward sloping = calm).
      - "vix_pct"   : VIX below its trailing `pct_window`-day median (low vol).
    Both need aux['vix']; "contango" also needs aux['vix3m'].
    """
    if not aux or "vix" not in aux:
        raise ValueError("conditioned_reversal requires aux['vix']")
    c = _close(df)
    mom = c / c.shift(lookback) - 1.0
    rv = (c.pct_change().rolling(vol_window).std() * np.sqrt(252.0)).replace(0.0, np.nan)
    reversal = -(mom / rv)                       # positive = recent loser

    vix = aux["vix"].reindex(df.index).ffill()
    if gate == "contango":
        if "vix3m" not in aux:
            raise ValueError("gate='contango' requires aux['vix3m']")
        vix3m = aux["vix3m"].reindex(df.index).ffill()
        calm = vix < vix3m                       # point-in-time, no lookahead
    elif gate == "vix_pct":
        # Trailing median is known as-of each day → point-in-time.
        calm = vix < vix.rolling(pct_window, min_periods=60).median()
    else:
        raise ValueError(f"unknown gate {gate!r}")

    return reversal.where(calm)                  # NaN on non-calm days


# Registry of testable signals → (function, needs_vix_term_structure_aux?).
SIGNALS: Dict[str, Callable[..., pd.Series]] = {
    "short_term_reversal": short_term_reversal,
    "ts_momentum": ts_momentum,
    "vix_term_structure": vix_term_structure,
}

# Signals that require the VIX/VIX3M exogenous series in `aux`.
NEEDS_VIX = {"vix_term_structure"}
