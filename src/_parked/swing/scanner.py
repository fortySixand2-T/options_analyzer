"""Strategy scanner for swing (14-60 DTE) and medium/long-term (30-180 DTE).

Same pipeline pattern as the short-DTE strategy_scanner.py:
    detect regime → detect swing bias → fetch dealer → compute edge signals →
    run decision matrix → evaluate applicable strategies → return ranked results.

Key differences from short-DTE scanner:
    - Uses swing bias (SMA 20/50/200) instead of short-term bias (EMA 9/21)
    - Adds VRP curve and term structure as primary edge inputs
    - Uses SWING_REGISTRY instead of STRATEGY_REGISTRY
    - DTE 14-60 filter
    - Persists all swing signals to SQLite for backtester replay

Medium/long-term (30-180 DTE) adds:
    - Yang-Zhang realized vol for VRP (~8x more efficient)
    - Volatility skew signal (25-delta put-call spread)
    - Cross-asset signals (VVIX, MOVE/VIX divergence)
    - Options flow signals (PCP deviations, OI changes, volume ratios)
    - Position sizing from VVIX regime
"""

import json
import logging
from datetime import date
from typing import Dict, List, Optional

import pandas as pd

from config import SWING_SCANNER_CONFIG
from regime.detector import detect_regime, RegimeResult
from scanner.providers import create_provider
from scanner.providers.flashalpha_client import (
    DealerData, fetch_gex, compute_dealer_data_from_chain,
)
from strategies import StrategyResult
from strategies.registry import SWING_REGISTRY, for_swing_regime

logger = logging.getLogger(__name__)


def scan_swing_strategies(
    tickers: List[str],
    provider=None,
    regime_result: Optional[RegimeResult] = None,
    dealer_data: Optional[DealerData] = None,
    strategy_filter: Optional[List[str]] = None,
    min_score: float = 30.0,
    top: int = 20,
    persist_signals: bool = True,
) -> Dict:
    """Full swing scan: regime → swing bias → dealer → VRP/term structure → decision matrix.

    Returns dict with keys: regime, swing_bias, dealer, vrp, term_structure,
    earnings, strategies, decision, signals_count
    """
    if provider is None:
        provider = create_provider()

    primary_ticker = tickers[0]

    # 1. Detect regime
    if regime_result is None:
        regime_result = detect_regime()
    regime = regime_result.regime

    logger.info("Swing scan — Regime: %s", regime.value)

    # 2. Detect swing bias (needs 200+ bars)
    swing_bias = _detect_swing_bias(provider, primary_ticker)
    logger.info("Swing bias: %s (score %d)", swing_bias.label, swing_bias.score)

    # 3. Fetch dealer positioning
    if dealer_data is None:
        dealer_data = _fetch_dealer(provider, primary_ticker)

    dealer_regime = dealer_data.dealer_regime if dealer_data else None

    # 4. Compute VRP
    vrp_data = _compute_vrp(provider, primary_ticker)

    # 5. Compute term structure
    ts_data = _compute_term_structure(provider, primary_ticker)

    # 6. Compute earnings info
    earnings_data = _compute_earnings(primary_ticker, vrp_data)

    # 7. Run decision matrix
    from swing.decision_matrix import map_swing_strategy
    recommendation = map_swing_strategy(
        regime=regime.value,
        swing_bias=swing_bias.label,
        dealer_regime=dealer_regime,
        vrp_rich=vrp_data.get("vrp_overall", 0) > 0,
        vrp_pct=vrp_data.get("vrp_overall_pct", 0),
        calendar_signal=ts_data.get("calendar_signal", 0),
        in_earnings_window=earnings_data.get("in_earnings_window", False),
        earnings_iv_inflation=earnings_data.get("earnings_iv_inflation", 0),
    )

    # 8. Scan signals with swing DTE range
    scan_config = {
        "filter": {
            "min_dte": SWING_SCANNER_CONFIG["filter"]["min_dte"],
            "max_dte": SWING_SCANNER_CONFIG["filter"]["max_dte"],
        },
    }

    from scanner import scan_watchlist
    signals = scan_watchlist(tickers, provider=provider, config=scan_config)
    logger.info("Swing scan: %d signals (DTE 14-60)", len(signals))

    # 9. Evaluate strategies
    applicable = for_swing_regime(regime)
    if strategy_filter:
        applicable = [s for s in applicable if s.name in strategy_filter]

    if recommendation:
        applicable = [s for s in applicable if s.name == recommendation.strategy] or applicable

    results: List[StrategyResult] = []
    for signal in signals:
        for strategy in applicable:
            result = strategy.evaluate(signal, regime_result)
            if result and result.score >= min_score:
                results.append(result)

    results.sort(key=lambda r: r.score, reverse=True)
    results = results[:top]

    # 10. Persist signals for backtester replay
    if persist_signals:
        _persist_signals(
            primary_ticker, swing_bias, vrp_data, ts_data,
            earnings_data, recommendation,
        )

    return {
        "regime": regime_result,
        "swing_bias": {
            "label": swing_bias.label,
            "score": swing_bias.score,
            "atr_percentile": swing_bias.atr_percentile,
            "detail": swing_bias.detail,
        },
        "dealer": dealer_data,
        "vrp": vrp_data,
        "term_structure": ts_data,
        "earnings": earnings_data,
        "decision": {
            "strategy": recommendation.strategy,
            "label": recommendation.strategy_label,
            "rationale": recommendation.rationale,
            "suggested_dte": recommendation.suggested_dte,
            "edge_source": recommendation.edge_source,
        } if recommendation else None,
        "strategies": results,
        "signals_count": len(signals),
    }


def _detect_swing_bias(provider, ticker):
    from swing.bias import SwingBiasResult, detect_swing_bias
    try:
        history = provider.get_history(ticker, days=300)
        if hasattr(history, 'closes') and len(history.closes) >= 50:
            df = pd.DataFrame({
                "Close": history.closes,
                "High": history.highs if hasattr(history, 'highs') else history.closes * 1.005,
                "Low": history.lows if hasattr(history, 'lows') else history.closes * 0.995,
                "Open": history.opens if hasattr(history, 'opens') else history.closes,
                "Volume": history.volumes if hasattr(history, 'volumes') else [1_000_000] * len(history.closes),
            })
            return detect_swing_bias(df)
    except Exception as e:
        logger.warning("Swing bias detection failed: %s", e)
    return SwingBiasResult(label="NEUTRAL", score=0, atr_percentile=50.0)


def _fetch_dealer(provider, ticker):
    dealer = fetch_gex(ticker)
    if dealer is None:
        try:
            chain = provider.get_chain(ticker, min_dte=0, max_dte=60)
            if chain.contracts:
                dealer = compute_dealer_data_from_chain(chain)
        except Exception as e:
            logger.warning("Swing dealer data unavailable: %s", e)
    return dealer


def _compute_vrp(provider, ticker, max_dte=60):
    try:
        from edge.vrp import compute_vrp_by_dte, extract_chain_iv_by_dte
        import numpy as np

        chain = provider.get_chain(ticker, min_dte=0, max_dte=max_dte)
        if not chain.contracts:
            return {}

        iv_by_dte = extract_chain_iv_by_dte(chain)
        history = provider.get_history(ticker, days=120)
        if not hasattr(history, 'closes') or len(history.closes) < 20:
            return {}

        ohlc = None
        if all(hasattr(history, a) for a in ('opens', 'highs', 'lows', 'closes')):
            ohlc = {
                "opens": np.array(history.opens),
                "highs": np.array(history.highs),
                "lows": np.array(history.lows),
                "closes": np.array(history.closes),
            }

        vrp_curve = compute_vrp_by_dte(
            iv_by_dte, np.array(history.closes), ohlc=ohlc,
        )
        return vrp_curve.to_dict()
    except Exception as e:
        logger.warning("VRP computation failed: %s", e)
        return {}


def _compute_term_structure(provider, ticker):
    try:
        from edge.term_structure import compute_iv_term_structure
        chain = provider.get_chain(ticker, min_dte=0, max_dte=60)
        if not chain.contracts:
            return {}

        ts = compute_iv_term_structure(chain, chain.spot)
        return ts.to_dict()
    except Exception as e:
        logger.warning("Term structure computation failed: %s", e)
        return {}


def _compute_earnings(ticker, vrp_data):
    try:
        from edge.earnings import compute_earnings_info
        baseline_iv = vrp_data.get("overall_vrp", 0) + 0.15 if vrp_data else 0.15
        info = compute_earnings_info(ticker, current_iv=0.20, baseline_iv=baseline_iv)
        if info is None:
            return {"earnings_days": None, "in_earnings_window": False,
                    "earnings_iv_inflation": 0.0, "expected_move_pct": 0.0}
        return {
            "earnings_days": info.days_to_earnings,
            "in_earnings_window": info.in_earnings_window,
            "earnings_iv_inflation": info.iv_inflation_score,
            "expected_move_pct": info.expected_move_pct,
            "earnings_date": info.earnings_date,
        }
    except Exception as e:
        logger.warning("Earnings computation failed: %s", e)
        return {"earnings_days": None, "in_earnings_window": False,
                "earnings_iv_inflation": 0.0, "expected_move_pct": 0.0}


def _gather_all_signals(provider, primary_ticker, max_dte, regime_result):
    """Shared signal computation for both medium-term and long-term scanners."""
    if provider is None:
        provider = create_provider()

    if regime_result is None:
        regime_result = detect_regime()

    return {
        "regime_result": regime_result,
        "swing_bias": _detect_swing_bias(provider, primary_ticker),
        "dealer_data": _fetch_dealer(provider, primary_ticker),
        "vrp_data": _compute_vrp(provider, primary_ticker, max_dte=max_dte),
        "ts_data": _compute_term_structure(provider, primary_ticker),
        "earnings_data": _compute_earnings(primary_ticker, {}),
        "skew_data": _compute_skew(provider, primary_ticker),
        "cross_asset_data": _compute_cross_asset(),
        "flow_data": _compute_flow(provider, primary_ticker),
    }


def _extract_signal_state(signals: Dict) -> Dict:
    """Pull scalar signal values used by decision matrices."""
    vrp_data = signals["vrp_data"]
    ts_data = signals["ts_data"]
    skew_data = signals["skew_data"]
    cross_asset_data = signals["cross_asset_data"]
    flow_data = signals["flow_data"]
    return {
        "vrp_regime": vrp_data.get("overall_regime", "NEUTRAL"),
        "vrp_pct": vrp_data.get("overall_vrp_pct", 0),
        "calendar_signal": ts_data.get("calendar_signal", 0),
        "skew_regime": skew_data.get("overall_regime", "NORMAL"),
        "cross_signal": cross_asset_data.get("move_vix_signal", "ALIGNED"),
        "flow_signal": flow_data.get("composite", "NEUTRAL"),
        "vvix_size": cross_asset_data.get("position_size_factor", 1.0),
        "correlation_premium": cross_asset_data.get("correlation_premium"),
    }


def _rec_dict(rec):
    if rec is None:
        return None
    return {
        "strategy": rec.strategy,
        "label": rec.strategy_label,
        "rationale": rec.rationale,
        "suggested_dte": rec.suggested_dte,
        "edge_source": rec.edge_source,
        "position_size_factor": rec.position_size_factor,
    }


# ── Medium-term scanner (30-90 DTE) ──────────────────────────────────


def scan_medium_term(
    tickers: List[str],
    provider=None,
    regime_result: Optional[RegimeResult] = None,
    persist_signals: bool = True,
) -> Dict:
    """Scan 30-90 DTE tier.  VRP + skew + term structure dominate.

    Uses MEDIUM_TERM_SCANNER_CONFIG weights and MEDIUM_TERM_REGISTRY strategies.
    """
    from config import MEDIUM_TERM_SCANNER_CONFIG
    from swing.decision_matrix import map_medium_term_strategy

    if provider is None:
        provider = create_provider()
    primary_ticker = tickers[0]
    cfg = MEDIUM_TERM_SCANNER_CONFIG

    sig = _gather_all_signals(provider, primary_ticker, max_dte=90, regime_result=regime_result)
    state = _extract_signal_state(sig)
    regime = sig["regime_result"].regime
    swing_bias = sig["swing_bias"]
    dealer_data = sig["dealer_data"]
    dealer_regime = dealer_data.dealer_regime if dealer_data else None

    rec = map_medium_term_strategy(
        regime=regime.value,
        swing_bias=swing_bias.label,
        dealer_regime=dealer_regime,
        vrp_regime=state["vrp_regime"],
        vrp_pct=state["vrp_pct"],
        calendar_signal=state["calendar_signal"],
        skew_regime=state["skew_regime"],
        cross_asset_signal=state["cross_signal"],
        flow_signal=state["flow_signal"],
        vvix_size_factor=state["vvix_size"],
        in_earnings_window=sig["earnings_data"].get("in_earnings_window", False),
        earnings_iv_inflation=sig["earnings_data"].get("earnings_iv_inflation", 0),
    )

    if persist_signals:
        _persist_signals(
            primary_ticker, swing_bias,
            sig["vrp_data"], sig["ts_data"], sig["earnings_data"], rec,
            skew_data=sig["skew_data"],
            cross_asset_data=sig["cross_asset_data"],
            flow_data=sig["flow_data"],
        )

    return {
        "dte_tier": "medium_term",
        "config": cfg,
        "regime": sig["regime_result"],
        "swing_bias": {"label": swing_bias.label, "score": swing_bias.score,
                       "atr_percentile": swing_bias.atr_percentile},
        "dealer": dealer_data,
        "vrp": sig["vrp_data"],
        "term_structure": sig["ts_data"],
        "earnings": sig["earnings_data"],
        "skew": sig["skew_data"],
        "cross_asset": sig["cross_asset_data"],
        "flow": sig["flow_data"],
        "decision": _rec_dict(rec),
    }


# ── Long-term scanner (90-180 DTE) ───────────────────────────────────


def scan_long_term(
    tickers: List[str],
    provider=None,
    regime_result: Optional[RegimeResult] = None,
    persist_signals: bool = True,
) -> Dict:
    """Scan 90-180 DTE tier.  Cross-asset + correlation premium dominate.

    Uses LONG_TERM_SCANNER_CONFIG weights and LONG_TERM_REGISTRY strategies.
    """
    from config import LONG_TERM_SCANNER_CONFIG
    from swing.decision_matrix import map_long_term_strategy

    if provider is None:
        provider = create_provider()
    primary_ticker = tickers[0]
    cfg = LONG_TERM_SCANNER_CONFIG

    sig = _gather_all_signals(provider, primary_ticker, max_dte=180, regime_result=regime_result)
    state = _extract_signal_state(sig)
    regime = sig["regime_result"].regime
    swing_bias = sig["swing_bias"]

    rec = map_long_term_strategy(
        regime=regime.value,
        swing_bias=swing_bias.label,
        vrp_regime=state["vrp_regime"],
        vrp_pct=state["vrp_pct"],
        skew_regime=state["skew_regime"],
        cross_asset_signal=state["cross_signal"],
        flow_signal=state["flow_signal"],
        vvix_size_factor=state["vvix_size"],
        correlation_premium=state["correlation_premium"],
    )

    if persist_signals:
        _persist_signals(
            primary_ticker, swing_bias,
            sig["vrp_data"], sig["ts_data"], sig["earnings_data"], rec,
            skew_data=sig["skew_data"],
            cross_asset_data=sig["cross_asset_data"],
            flow_data=sig["flow_data"],
        )

    return {
        "dte_tier": "long_term",
        "config": cfg,
        "regime": sig["regime_result"],
        "swing_bias": {"label": swing_bias.label, "score": swing_bias.score,
                       "atr_percentile": swing_bias.atr_percentile},
        "dealer": sig["dealer_data"],
        "vrp": sig["vrp_data"],
        "term_structure": sig["ts_data"],
        "earnings": sig["earnings_data"],
        "skew": sig["skew_data"],
        "cross_asset": sig["cross_asset_data"],
        "flow": sig["flow_data"],
        "decision": _rec_dict(rec),
    }


def _compute_skew(provider, ticker):
    try:
        from edge.skew import compute_skew_from_chain
        chain = provider.get_chain(ticker, min_dte=14, max_dte=180)
        if not chain.contracts:
            return {}

        chain_data = {}
        from datetime import date as date_cls, datetime
        today = date_cls.today()

        for c in chain.contracts:
            if c.implied_volatility is None or c.implied_volatility <= 0:
                continue
            try:
                expiry_date = datetime.strptime(c.expiry, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            dte = (expiry_date - today).days
            if dte < 0:
                continue

            if dte not in chain_data:
                chain_data[dte] = {"puts": [], "calls": []}

            side = "puts" if c.option_type == "put" else "calls"
            chain_data[dte][side].append((c.strike, c.implied_volatility))

        skew_curve = compute_skew_from_chain(chain_data, chain.spot)
        return skew_curve.to_dict()
    except Exception as e:
        logger.warning("Skew computation failed: %s", e)
        return {}


def _compute_cross_asset():
    try:
        import yfinance as yf
        from edge.cross_asset import compute_vvix_signal, compute_move_vix_signal
        import numpy as np

        vix_data = yf.Ticker("^VIX").history(period="3mo")
        vvix_data = yf.Ticker("^VVIX").history(period="3mo")

        if vix_data.empty:
            return {}

        vix = float(vix_data["Close"].iloc[-1])
        result = {"vix": round(vix, 2)}

        if not vvix_data.empty:
            vvix = float(vvix_data["Close"].iloc[-1])
            vvix_hist = np.array(vvix_data["Close"].values[-60:])
            vvix_sig = compute_vvix_signal(vvix, vix, vvix_history=vvix_hist)
            result.update(vvix_sig.to_dict())
            result["position_size_factor"] = vvix_sig.position_size_factor

        # MOVE index (^MOVE) may not be available via yfinance
        try:
            move_data = yf.Ticker("^MOVE").history(period="3mo")
            if not move_data.empty:
                move = float(move_data["Close"].iloc[-1])
                vix_hist = np.array(vix_data["Close"].values[-60:])
                move_hist = np.array(move_data["Close"].values[-60:])
                move_sig = compute_move_vix_signal(move, vix, move_hist, vix_hist)
                result["move_vix_signal"] = move_sig.signal.value
                result["move_vix_divergence"] = move_sig.divergence
        except Exception:
            pass

        return result
    except Exception as e:
        logger.warning("Cross-asset computation failed: %s", e)
        return {}


def _compute_flow(provider, ticker):
    try:
        from edge.flow import compute_volume_ratio, compute_flow_composite
        chain = provider.get_chain(ticker, min_dte=14, max_dte=180)
        if not chain.contracts:
            return {}

        put_vol = sum(c.volume or 0 for c in chain.contracts if c.option_type == "put")
        call_vol = sum(c.volume or 0 for c in chain.contracts if c.option_type == "call")

        vol_sig = compute_volume_ratio(put_vol, call_vol)
        composite = compute_flow_composite([], None, vol_sig)
        return composite.to_dict()
    except Exception as e:
        logger.warning("Flow computation failed: %s", e)
        return {}


def _persist_signals(
    ticker, swing_bias, vrp_data, ts_data, earnings_data, recommendation,
    skew_data=None, cross_asset_data=None, flow_data=None,
):
    try:
        from data.chain_store import store_swing_signals
        skew_data = skew_data or {}
        cross_asset_data = cross_asset_data or {}
        flow_data = flow_data or {}

        store_swing_signals(
            ticker=ticker,
            snapshot_date=date.today().isoformat(),
            vrp_overall=vrp_data.get("overall_vrp"),
            vrp_overall_pct=vrp_data.get("overall_vrp_pct"),
            vrp_richest_bucket=vrp_data.get("richest_bucket"),
            vrp_buckets_json=json.dumps(vrp_data.get("buckets", [])),
            term_structure_slope=ts_data.get("slope"),
            term_structure_slope_per_dte=ts_data.get("slope_per_dte"),
            calendar_signal=ts_data.get("calendar_signal"),
            kink_expiry=ts_data.get("kink_expiry"),
            kink_magnitude=ts_data.get("kink_magnitude"),
            contango=ts_data.get("contango"),
            front_iv=ts_data.get("front_iv"),
            back_iv=ts_data.get("back_iv"),
            swing_bias_label=swing_bias.label,
            swing_bias_score=swing_bias.score,
            swing_atr_percentile=swing_bias.atr_percentile,
            earnings_days=earnings_data.get("earnings_days"),
            earnings_iv_inflation=earnings_data.get("earnings_iv_inflation"),
            expected_move_pct=earnings_data.get("expected_move_pct"),
            in_earnings_window=earnings_data.get("in_earnings_window"),
            skew_25d=skew_data.get("mean_skew_normalized"),
            skew_zscore=skew_data.get("skew_z_score"),
            skew_regime=skew_data.get("overall_regime"),
            vrp_regime=vrp_data.get("overall_regime"),
            vvix_regime=cross_asset_data.get("regime"),
            vvix_ratio=cross_asset_data.get("ratio"),
            vvix_size_factor=cross_asset_data.get("position_size_factor"),
            move_vix_signal=cross_asset_data.get("move_vix_signal"),
            move_vix_divergence=cross_asset_data.get("move_vix_divergence"),
            flow_composite=flow_data.get("composite"),
            correlation_premium=cross_asset_data.get("correlation_premium"),
            recommended_strategy=recommendation.strategy if recommendation else None,
            recommendation_rationale=recommendation.rationale if recommendation else None,
        )
    except Exception as e:
        logger.warning("Failed to persist swing signals: %s", e)
