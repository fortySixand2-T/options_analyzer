"""
Tests for the IC-first signal research stack (F-018):
  - signal_lib point-in-time signals (orientation + no-lookahead),
  - signal_eval generic IC engine (forward returns, IC, fold/regime stability,
    and the strict graduation gate).

All pure/synthetic — no network. We construct data with a KNOWN relationship so
the IC engine's sign and the graduation gate can be asserted deterministically.
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backtest import signal_lib as sl
from backtest.signal_eval import (
    forward_returns, ic_at_horizon, ic_table, fold_ic_signs, regime_ic_signs,
    graduate, _sign,
)


def _ohlcv(closes):
    """Minimal OHLCV frame from a close series (Title-cased columns)."""
    c = pd.Series(closes, dtype=float)
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c,
                         "Volume": np.ones(len(c))})


# ── signal_lib: orientation & causality ──────────────────────────────────────

def test_short_term_reversal_sign():
    # A 5-day run-up → negative reversal signal (expect fade); run-down → positive.
    up = _ohlcv([100, 101, 102, 103, 104, 105])
    s = sl.short_term_reversal(up)
    assert s.iloc[-1] < 0          # recent winner → negative (bearish) signal
    down = _ohlcv([105, 104, 103, 102, 101, 100])
    assert sl.short_term_reversal(down).iloc[-1] > 0


def test_ts_momentum_sign_and_warmup():
    closes = list(np.linspace(100, 200, 80))   # steady uptrend
    s = sl.ts_momentum(_ohlcv(closes))
    assert np.isnan(s.iloc[10])                 # warmup region undefined
    assert s.iloc[-1] > 0                       # uptrend → positive momentum


def test_signals_are_pointintime():
    # Truncating future bars must NOT change a past signal value (no lookahead).
    closes = list(np.linspace(100, 130, 90)) + list(np.linspace(130, 90, 30))
    full = sl.ts_momentum(_ohlcv(closes))
    trunc = sl.ts_momentum(_ohlcv(closes[:90]))
    assert abs(float(full.iloc[80]) - float(trunc.iloc[80])) < 1e-9


def test_vix_term_structure_requires_aux():
    try:
        sl.vix_term_structure(_ohlcv([100] * 80))
        assert False, "expected ValueError without VIX aux"
    except ValueError:
        pass


def test_conditioned_reversal_requires_vix():
    try:
        sl.conditioned_reversal(_ohlcv([100] * 80))
        assert False, "expected ValueError without VIX aux"
    except ValueError:
        pass


def test_conditioned_reversal_gates_out_stress():
    # Backwardation (VIX > VIX3M) ⇒ signal NaN (no position taken in stress).
    n = 90
    df = _ohlcv(list(np.linspace(100, 80, n)))   # steady decline → a "laggard"
    df.index = list(range(n))
    vix = pd.Series([30.0] * n, index=df.index)   # always > vix3m
    vix3m = pd.Series([18.0] * n, index=df.index)
    s = sl.conditioned_reversal(df, {"vix": vix, "vix3m": vix3m}, gate="contango")
    assert np.isnan(s.iloc[-1])                    # backwardation → gated out


def test_conditioned_reversal_calm_laggard_positive():
    # Calm (contango) + recent medium-horizon loser ⇒ positive (revert-up) signal.
    n = 90
    df = _ohlcv(list(np.linspace(100, 80, n)))
    df.index = list(range(n))
    vix = pd.Series([14.0] * n, index=df.index)    # < vix3m → calm
    vix3m = pd.Series([18.0] * n, index=df.index)
    s = sl.conditioned_reversal(df, {"vix": vix, "vix3m": vix3m}, gate="contango")
    assert s.iloc[-1] > 0


def test_conditioned_reversal_pointintime():
    closes = list(np.linspace(100, 130, 90)) + list(np.linspace(130, 95, 30))
    n = len(closes)
    vix = pd.Series([14.0] * n)
    vix3m = pd.Series([18.0] * n)
    df = _ohlcv(closes); df.index = list(range(n))
    full = sl.conditioned_reversal(df, {"vix": vix, "vix3m": vix3m}, gate="contango")
    dft = _ohlcv(closes[:90]); dft.index = list(range(90))
    trunc = sl.conditioned_reversal(dft, {"vix": vix.iloc[:90], "vix3m": vix3m.iloc[:90]},
                                    gate="contango")
    assert abs(float(full.iloc[80]) - float(trunc.iloc[80])) < 1e-9


def test_vix_term_structure_backwardation_positive():
    n = 90
    idx = list(range(n))
    df = _ohlcv([100] * n)
    df.index = idx
    # Backwardation at the end (VIX > VIX3M) → positive raw slope → positive z.
    vix = pd.Series([15.0] * (n - 5) + [30.0] * 5, index=idx)
    vix3m = pd.Series([18.0] * n, index=idx)
    s = sl.vix_term_structure(df, {"vix": vix, "vix3m": vix3m})
    assert s.iloc[-1] > 0


# ── signal_eval: IC engine ───────────────────────────────────────────────────

def test_forward_returns():
    fwd = forward_returns([100, 110, 121], 1)
    assert abs(fwd[0] - 0.10) < 1e-9 and abs(fwd[1] - 0.10) < 1e-9
    assert np.isnan(fwd[2])         # last h days undefined


def test_ic_positive_when_signal_predicts():
    # Build closes so that a high signal precedes a high 1-day forward return.
    rng = np.random.default_rng(0)
    n = 300
    sig = rng.normal(size=n)
    rets = 0.4 * sig + rng.normal(scale=0.5, size=n)   # signal predicts next ret
    closes = [100.0]
    for r in rets:
        closes.append(closes[-1] * (1 + r / 100.0))
    closes = closes[:n]                                 # align lengths
    r = ic_at_horizon(sig, closes, 1)
    assert r["spearman"] > 0.2 and r["spearman_p"] < 0.01


def test_ic_insufficient_sample():
    assert "note" in ic_at_horizon([1, 2, 3], [100, 101, 102], 1)


def test_graduate_passes_strong_stable_signal():
    table = {3: {"spearman": 0.05, "spearman_p": 0.001, "n": 500},
             5: {"spearman": 0.02, "spearman_p": 0.20, "n": 500}}
    folds = {3: [1, 1, 1], 5: [1, -1, 1]}
    regimes = {3: {"low": {"sign": 1}, "high": {"sign": 1}}}
    v = graduate(table, folds, regimes)
    assert v["graduates"] is True and v["best_horizon"] == 3
    assert v["direction"] == "bullish"


def test_graduate_rejects_time_unstable():
    table = {5: {"spearman": 0.06, "spearman_p": 0.001, "n": 500}}
    v = graduate(table, {5: [1, -1, 1]}, {5: {"low": {"sign": 1}, "high": {"sign": 1}}})
    assert v["graduates"] is False and "time-unstable" in v["reason"]


def test_graduate_rejects_regime_unstable():
    table = {5: {"spearman": 0.06, "spearman_p": 0.001, "n": 500}}
    v = graduate(table, {5: [1, 1, 1]}, {5: {"low": {"sign": 1}, "high": {"sign": -1}}})
    assert v["graduates"] is False and "regime-unstable" in v["reason"]


def test_graduate_rejects_insignificant():
    table = {5: {"spearman": 0.10, "spearman_p": 0.30, "n": 500}}
    v = graduate(table, {5: [1, 1, 1]}, {})
    assert v["graduates"] is False and "not significant" in v["reason"]


def test_graduate_inverted_direction():
    table = {5: {"spearman": -0.05, "spearman_p": 0.001, "n": 500}}
    v = graduate(table, {5: [-1, -1, -1]}, {5: {"low": {"sign": -1}, "high": {"sign": -1}}})
    assert v["graduates"] is True and v["direction"] == "inverted"


def test_cache_key_includes_signal_filter():
    # F-019 regression: toggling the signal filter MUST change the cache key,
    # else the gated run silently returns the cached unconditional result.
    from backtest.cache import _cache_key
    from backtest.models import BacktestRequest
    from datetime import date as _date
    base = dict(strategy="long_call_spread", symbol="SPY",
                start_date=_date(2020, 1, 1), end_date=_date(2024, 12, 31))
    k_off = _cache_key(BacktestRequest(**base, signal_filter=False))
    k_on = _cache_key(BacktestRequest(**base, signal_filter=True))
    k_gate = _cache_key(BacktestRequest(**base, signal_filter=True, signal_gate="contango"))
    assert k_off != k_on != k_gate and k_off != k_gate
