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


# ── vrp_proxy ────────────────────────────────────────────────────────────────

def test_vrp_proxy_requires_aux():
    """vrp_proxy must raise ValueError when aux is absent."""
    try:
        sl.vrp_proxy(_ohlcv([100.0] * 40))
        assert False, "expected ValueError without VIX aux"
    except ValueError:
        pass


def test_vrp_proxy_positive_when_iv_exceeds_rv():
    """High VIX relative to calm price action → large positive VRP (bullish)."""
    n = 60
    # Flat price series → RV ≈ 0; VIX = 25 → VRP ≈ +25.
    df = _ohlcv([100.0] * n)
    df.index = list(range(n))
    vix = pd.Series([25.0] * n, index=df.index)
    sig = sl.vrp_proxy(df, {"vix": vix})
    assert sig.iloc[-1] > 15.0   # large positive premium


def test_vrp_proxy_negative_when_rv_exceeds_iv():
    """High RV (volatile price) with low VIX → negative VRP (bearish / costly vol)."""
    n = 60
    rng = np.random.default_rng(42)
    # Highly volatile price series; VIX = 10 (low).
    pct = rng.normal(0, 0.03, n)       # ~3 % daily moves → ~47 % annualised RV
    prices = [100.0]
    for r in pct:
        prices.append(prices[-1] * (1 + r))
    df = _ohlcv(prices[:n])
    df.index = list(range(n))
    vix = pd.Series([10.0] * n, index=df.index)
    sig = sl.vrp_proxy(df, {"vix": vix})
    # Need at least rv_window=21 bars to have a non-NaN value.
    valid = sig.dropna()
    assert len(valid) > 0
    assert valid.iloc[-1] < 0   # RV >> VIX → negative VRP


def test_vrp_proxy_warmup_nan():
    """First rv_window bars should be NaN (rolling window not yet full)."""
    n = 50
    df = _ohlcv([100.0] * n)
    df.index = list(range(n))
    vix = pd.Series([20.0] * n, index=df.index)
    sig = sl.vrp_proxy(df, {"vix": vix}, rv_window=21)
    # Bars 0-20 should be NaN (pct_change NaN + rolling(21) NaN until bar 21).
    assert np.isnan(sig.iloc[10])


def test_vrp_proxy_pointintime():
    """Truncating future bars must not change a past VRP value."""
    n = 80
    rng = np.random.default_rng(7)
    prices = list(100.0 * np.cumprod(1 + rng.normal(0, 0.01, n)))
    df_full = _ohlcv(prices)
    df_full.index = list(range(n))
    df_trunc = _ohlcv(prices[:60])
    df_trunc.index = list(range(60))
    vix = pd.Series([20.0] * n)
    s_full = sl.vrp_proxy(df_full, {"vix": vix})
    s_trunc = sl.vrp_proxy(df_trunc, {"vix": vix.iloc[:60]})
    assert abs(float(s_full.iloc[55]) - float(s_trunc.iloc[55])) < 1e-9


# ── high52w_proximity ─────────────────────────────────────────────────────────

def test_high52w_at_new_high_equals_one():
    """When price is at its 252-day high, proximity should be exactly 1.0."""
    # Create a price series that ends AT the 252-day rolling max.
    prices = list(np.linspace(80, 100, 260))   # steadily rising
    df = _ohlcv(prices)
    df.index = list(range(len(prices)))
    sig = sl.high52w_proximity(df)
    # Last bar = highest price in any 252-day window starting from bar 0.
    assert abs(sig.iloc[-1] - 1.0) < 1e-9


def test_high52w_below_one_when_off_high():
    """When price is below its 252-day high, proximity should be < 1."""
    # Rise, then drop; last bar is below the window max.
    prices = list(np.linspace(80, 120, 260)) + [100.0] * 10
    df = _ohlcv(prices)
    df.index = list(range(len(prices)))
    sig = sl.high52w_proximity(df)
    assert sig.iloc[-1] < 1.0


def test_high52w_warmup_nan():
    """Bars before the 252nd observation should be NaN (min_periods=lookback)."""
    prices = list(np.linspace(100, 150, 300))
    df = _ohlcv(prices)
    df.index = list(range(len(prices)))
    sig = sl.high52w_proximity(df)
    assert np.isnan(sig.iloc[100])   # before lookback=252 is satisfied
    assert not np.isnan(sig.iloc[255])


def test_high52w_no_aux_needed():
    """high52w_proximity must work with aux=None (no exogenous data)."""
    prices = list(np.linspace(100, 150, 300))
    df = _ohlcv(prices)
    df.index = list(range(len(prices)))
    sig = sl.high52w_proximity(df, aux=None)   # must not raise
    assert sig.iloc[-1] > 0


def test_high52w_pointintime():
    """Truncating future bars must not change a past proximity value."""
    prices = list(np.linspace(80, 130, 320)) + list(np.linspace(130, 95, 40))
    n_full = len(prices)
    df_full = _ohlcv(prices)
    df_full.index = list(range(n_full))
    df_trunc = _ohlcv(prices[:300])
    df_trunc.index = list(range(300))
    s_full = sl.high52w_proximity(df_full)
    s_trunc = sl.high52w_proximity(df_trunc)
    # Value at bar 280 (inside both series, past 252-bar warmup) must be equal.
    assert abs(float(s_full.iloc[280]) - float(s_trunc.iloc[280])) < 1e-9


def test_high52w_not_in_needs_vix():
    """high52w_proximity must NOT appear in NEEDS_VIX (no exogenous data)."""
    assert "high52w_proximity" not in sl.NEEDS_VIX


def test_vrp_proxy_in_needs_vix():
    """vrp_proxy requires VIX and must appear in NEEDS_VIX."""
    assert "vrp_proxy" in sl.NEEDS_VIX


# ── regression / registry ─────────────────────────────────────────────────────

def test_signals_registry_contains_new_signals():
    """Both new signals must appear in the SIGNALS registry."""
    assert "vrp_proxy" in sl.SIGNALS
    assert "high52w_proximity" in sl.SIGNALS


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


def test_cache_key_covers_vrp_and_swing_bias_filters():
    """Phase 3 regression: vrp_filter, vrp_threshold, swing_bias_filter must be
    in the cache key — they were absent (F-005-class latent bug, noted in F-019)."""
    from backtest.cache import _cache_key
    from backtest.models import BacktestRequest
    from datetime import date as _date
    base = dict(strategy="iron_condor", symbol="SPY",
                start_date=_date(2020, 1, 1), end_date=_date(2024, 12, 31))
    k_base = _cache_key(BacktestRequest(**base))
    k_vrp_on = _cache_key(BacktestRequest(**base, vrp_filter=True))
    k_vrp_thresh = _cache_key(BacktestRequest(**base, vrp_filter=True, vrp_threshold=5.0))
    k_swing = _cache_key(BacktestRequest(**base, swing_bias_filter=True))
    assert k_base != k_vrp_on, "vrp_filter=True must change cache key"
    assert k_vrp_on != k_vrp_thresh, "vrp_threshold must change cache key"
    assert k_base != k_swing, "swing_bias_filter=True must change cache key"


def test_cache_key_covers_option_style_and_min_score():
    """Phase 3: option_style and min_score were missing from the cache key."""
    from backtest.cache import _cache_key
    from backtest.models import BacktestRequest
    from datetime import date as _date
    base = dict(strategy="long_put_spread", symbol="SPY",
                start_date=_date(2020, 1, 1), end_date=_date(2024, 12, 31))
    k_euro = _cache_key(BacktestRequest(**base, option_style="european"))
    k_amer = _cache_key(BacktestRequest(**base, option_style="american"))
    k_score = _cache_key(BacktestRequest(**base, min_score=50.0))
    assert k_euro != k_amer, "option_style must change cache key"
    assert k_euro != k_score, "min_score must change cache key"


def test_cache_key_sentinel_all_result_affecting_fields_present():
    """Sentinel: every field in RESULT_AFFECTING_FIELDS must exist on BacktestRequest.

    If you add a new result-affecting field to BacktestRequest and forget to add
    it to RESULT_AFFECTING_FIELDS (and thus to _cache_key), this test fails
    immediately — catching the F-005-class bug before it silently corrupts results.

    To pass: add the new field to cache.RESULT_AFFECTING_FIELDS AND to _cache_key.
    """
    from backtest.cache import RESULT_AFFECTING_FIELDS
    from backtest.models import BacktestRequest
    import dataclasses, inspect
    # Collect all field names on BacktestRequest (pydantic or dataclass).
    try:
        req_fields = set(BacktestRequest.model_fields.keys())
    except AttributeError:
        req_fields = {f.name for f in dataclasses.fields(BacktestRequest)}
    # Every field in our allow-list must actually exist on the model.
    missing_from_model = RESULT_AFFECTING_FIELDS - req_fields
    assert not missing_from_model, (
        f"RESULT_AFFECTING_FIELDS references fields not on BacktestRequest: "
        f"{missing_from_model}. Remove stale entries from the allow-list."
    )
