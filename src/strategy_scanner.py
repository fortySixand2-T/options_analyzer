"""
Strategy scanner — wraps chain scanner + regime detection + bias + dealer + strategy evaluation.

Pipeline: detect regime → detect bias → fetch dealer data → scan for signals →
          evaluate applicable strategies → return ranked StrategyResult list.

Options Analytics Team — 2026-04
"""

import logging
from typing import Dict, List, Optional

import pandas as pd

from scanner import OptionSignal, scan_watchlist
from scanner.providers import create_provider
from scanner.providers.flashalpha_client import (
    DealerData, fetch_gex, compute_dealer_data_from_chain,
)
from regime.detector import detect_regime, RegimeResult
from bias_detector import detect_bias, BiasResult
from strategies import StrategyDefinition, StrategyResult
from strategies.registry import STRATEGY_REGISTRY, for_regime

logger = logging.getLogger(__name__)


def scan_strategies(
    tickers: List[str],
    provider=None,
    scanner_config: Optional[Dict] = None,
    regime_result: Optional[RegimeResult] = None,
    bias_result: Optional[BiasResult] = None,
    dealer_data: Optional[DealerData] = None,
    strategy_filter: Optional[List[str]] = None,
    min_score: float = 30.0,
    top: int = 20,
) -> Dict:
    """Full strategy scan: regime → bias → dealer → signals → strategy evaluation.

    Parameters
    ----------
    tickers : List[str]
        Tickers to scan.
    provider : ChainProvider, optional
        Data provider (default: auto-detected).
    scanner_config : dict, optional
        Scanner config overrides.
    regime_result : RegimeResult, optional
        Pre-computed regime (default: detect live).
    bias_result : BiasResult, optional
        Pre-computed bias (default: detect from price data).
    dealer_data : DealerData, optional
        Pre-computed dealer positioning (default: fetch live).
    strategy_filter : List[str], optional
        Only evaluate these strategy names.
    min_score : float
        Minimum strategy score to include.
    top : int
        Max results to return.

    Returns
    -------
    dict with keys: regime, bias, dealer, strategies, signals_count
    """
    if provider is None:
        provider = create_provider()

    # 1. Detect regime
    if regime_result is None:
        regime_result = detect_regime()
    regime = regime_result.regime

    logger.info("Regime: %s — %s", regime.value, regime_result.rationale)

    # 2. Detect directional bias
    if bias_result is None:
        try:
            # Use first ticker for bias detection
            history = provider.get_history(tickers[0], days=60)
            if hasattr(history, 'closes') and len(history.closes) >= 26:
                df = pd.DataFrame({
                    "Close": history.closes,
                    "High": history.closes * 1.005,
                    "Low": history.closes * 0.995,
                    "Open": history.closes,
                    "Volume": [1_000_000] * len(history.closes),
                })
                bias_result = detect_bias(df)
            else:
                bias_result = BiasResult(label="NEUTRAL", score=0, atr_percentile=50.0)
        except Exception as e:
            logger.warning("Bias detection failed: %s", e)
            bias_result = BiasResult(label="NEUTRAL", score=0, atr_percentile=50.0)

    logger.info("Bias: %s (score %d)", bias_result.label, bias_result.score)

    # 3. Fetch dealer positioning
    if dealer_data is None:
        dealer_data = fetch_gex(tickers[0])
        # Fallback to chain-based computation if API unavailable
        if dealer_data is None:
            try:
                chain = provider.get_chain(tickers[0], min_dte=0, max_dte=14)
                if chain.contracts:
                    dealer_data = compute_dealer_data_from_chain(chain)
            except Exception as e:
                logger.warning("Dealer data unavailable: %s", e)

    if dealer_data:
        logger.info("Dealer: %s (net GEX %.0f)", dealer_data.dealer_regime, dealer_data.net_gex)

    # 4. Get strategies for this regime
    applicable = for_regime(regime)
    if strategy_filter:
        applicable = [s for s in applicable if s.name in strategy_filter]

    if not applicable:
        logger.info("No strategies applicable for regime %s", regime.value)
        return {
            "regime": regime_result,
            "bias": bias_result,
            "dealer": dealer_data,
            "strategies": [],
            "signals_count": 0,
        }

    # 5. Scan for signals
    signals = scan_watchlist(tickers, provider=provider, config=scanner_config)
    logger.info("Scanned %d signals across %d tickers", len(signals), len(tickers))

    # 6. Evaluate each signal against each applicable strategy
    results: List[StrategyResult] = []
    for signal in signals:
        for strategy in applicable:
            result = strategy.evaluate(signal, regime_result)
            if result and result.score >= min_score:
                results.append(result)

    # 7. Rank by score descending
    results.sort(key=lambda r: r.score, reverse=True)
    results = results[:top]

    return {
        "regime": regime_result,
        "bias": bias_result,
        "dealer": dealer_data,
        "strategies": results,
        "signals_count": len(signals),
    }
