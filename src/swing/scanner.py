"""Swing-timeframe strategy scanner (14-60 DTE).

Same pipeline pattern as the short-DTE strategy_scanner.py:
    detect regime → detect swing bias → fetch dealer → compute edge signals →
    run decision matrix → evaluate applicable strategies → return ranked results.

Key differences from short-DTE scanner:
    - Uses swing bias (SMA 20/50/200) instead of short-term bias (EMA 9/21)
    - Adds VRP curve and term structure as primary edge inputs
    - Uses SWING_REGISTRY instead of STRATEGY_REGISTRY
    - DTE 14-60 filter
    - Persists all swing signals to SQLite for backtester replay
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


def _compute_vrp(provider, ticker):
    try:
        from edge.vrp import compute_vrp_curve, extract_chain_iv_by_dte
        chain = provider.get_chain(ticker, min_dte=0, max_dte=60)
        if not chain.contracts:
            return {}

        iv_by_dte = extract_chain_iv_by_dte(chain)
        history = provider.get_history(ticker, days=30)
        if not hasattr(history, 'closes') or len(history.closes) < 20:
            return {}

        import numpy as np
        returns = np.diff(np.log(history.closes))
        realized_vol = float(np.std(returns) * np.sqrt(252))

        vrp_curve = compute_vrp_curve(iv_by_dte, realized_vol)
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


def _persist_signals(ticker, swing_bias, vrp_data, ts_data, earnings_data, recommendation):
    try:
        from data.chain_store import store_swing_signals
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
            recommended_strategy=recommendation.strategy if recommendation else None,
            recommendation_rationale=recommendation.rationale if recommendation else None,
        )
    except Exception as e:
        logger.warning("Failed to persist swing signals: %s", e)
