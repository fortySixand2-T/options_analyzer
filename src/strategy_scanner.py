"""
Strategy scanner — wraps chain scanner + regime detection + strategy evaluation.

Detects regime → scans for signals → evaluates applicable strategies →
returns ranked StrategyResult list.

Options Analytics Team — 2026-04
"""

import logging
from typing import Dict, List, Optional

from scanner import OptionSignal, scan_watchlist
from scanner.providers import create_provider
from scanner.scanner import OptionsScanner
from regime.detector import detect_regime, RegimeResult
from strategies import StrategyDefinition, StrategyResult
from strategies.registry import STRATEGY_REGISTRY, for_regime

logger = logging.getLogger(__name__)


def scan_strategies(
    tickers: List[str],
    provider=None,
    scanner_config: Optional[Dict] = None,
    regime_result: Optional[RegimeResult] = None,
    strategy_filter: Optional[List[str]] = None,
    min_score: float = 30.0,
    top: int = 20,
) -> Dict:
    """Full strategy scan: regime → signals → strategy evaluation.

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
    strategy_filter : List[str], optional
        Only evaluate these strategy names.
    min_score : float
        Minimum strategy score to include.
    top : int
        Max results to return.

    Returns
    -------
    dict with keys: regime, strategies, signals_count
    """
    # 1. Detect regime
    if regime_result is None:
        regime_result = detect_regime()
    regime = regime_result.regime

    logger.info("Regime: %s — %s", regime.value, regime_result.rationale)

    # 2. Get strategies for this regime
    applicable = for_regime(regime)
    if strategy_filter:
        applicable = [s for s in applicable if s.name in strategy_filter]

    if not applicable:
        logger.info("No strategies applicable for regime %s", regime.value)
        return {
            "regime": regime_result,
            "strategies": [],
            "signals_count": 0,
        }

    # 3. Scan for signals
    if provider is None:
        provider = create_provider()
    signals = scan_watchlist(tickers, provider=provider, config=scanner_config)

    logger.info("Scanned %d signals across %d tickers", len(signals), len(tickers))

    # 4. Evaluate each signal against each applicable strategy
    results: List[StrategyResult] = []
    for signal in signals:
        for strategy in applicable:
            result = strategy.evaluate(signal, regime_result)
            if result and result.score >= min_score:
                results.append(result)

    # 5. Rank by score descending
    results.sort(key=lambda r: r.score, reverse=True)
    results = results[:top]

    return {
        "regime": regime_result,
        "strategies": results,
        "signals_count": len(signals),
    }
