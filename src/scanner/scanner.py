"""
OptionsScanner — orchestrator for the full scanning pipeline.

Takes a ChainProvider and config, runs the pipeline for each ticker:
fetch chain → compute IV rank → fit GARCH → filter contracts →
compute edge → score → return ranked OptionSignal list.

Options Analytics Team — 2026-04-02
"""

import json
import logging
import math
import os
import sys
from datetime import datetime
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from monte_carlo.garch_vol import fit_garch11

from . import OptionSignal
from .providers.base import ChainProvider
from .iv_rank import compute_iv_metrics
from .contract_filter import filter_contracts
from .edge import compute_edge
from .scorer import score_signal, rank_signals

logger = logging.getLogger(__name__)

DEFAULT_SCANNER_CONFIG = {
    'filter': {
        'min_dte': 20,
        'max_dte': 60,
        'min_delta': 0.15,
        'max_delta': 0.50,
        'min_open_interest': 100,
        'max_spread_pct': 15.0,
        'moneyness_range': [0.85, 1.15],
    },
    'garch': {
        'history_days': 120,
        'min_returns': 30,
    },
    'scoring_weights': {
        'edge': 0.40,
        'iv_rank': 0.25,
        'liquidity': 0.20,
        'greeks': 0.15,
    },
}


class OptionsScanner:
    """Orchestrates the full option scanning pipeline."""

    def __init__(self, provider: ChainProvider, config: dict = None):
        self.provider = provider
        self.config = config or DEFAULT_SCANNER_CONFIG

    def scan_ticker(self, ticker: str) -> List[OptionSignal]:
        """Full pipeline for one ticker.

        Steps:
          1. Fetch chain + history
          2. Compute IV rank/percentile
          3. Fit GARCH to recent returns
          4. Filter contracts
          5. Compute edge for each surviving contract
          6. Score and return signals
        """
        fc = self.config.get('filter', DEFAULT_SCANNER_CONFIG['filter'])
        gc = self.config.get('garch', DEFAULT_SCANNER_CONFIG['garch'])
        weights = self.config.get('scoring_weights',
                                  DEFAULT_SCANNER_CONFIG['scoring_weights'])

        # 1. Fetch chain + history
        min_dte = fc.get('min_dte', 20)
        max_dte = fc.get('max_dte', 60)
        snapshot = self.provider.get_chain(ticker, min_dte=7, max_dte=max_dte + 10)
        history = self.provider.get_history(ticker, days=gc.get('history_days', 120))
        rfr = self.provider.get_risk_free_rate()
        spot = snapshot.spot

        if math.isnan(spot) or spot <= 0:
            logger.warning("Invalid spot for %s, skipping", ticker)
            return []

        if not snapshot.contracts:
            logger.warning("No contracts found for %s, skipping", ticker)
            return []

        # 2. IV rank — use ATM call IV as the "current IV"
        atm_iv = self._get_atm_iv(snapshot)
        iv_metrics = compute_iv_metrics(atm_iv, history)

        # 3. Fit GARCH
        garch_vol = atm_iv  # fallback
        if len(history.returns) >= gc.get('min_returns', 30):
            try:
                garch_params = fit_garch11(history.returns)
                if garch_params.get('converged', False):
                    garch_vol = garch_params['sigma0']
                    logger.info("%s GARCH sigma0=%.4f, long_run=%.4f",
                                ticker, garch_vol, garch_params['long_run_vol'])
                else:
                    logger.warning("%s GARCH did not converge, using ATM IV", ticker)
            except Exception as e:
                logger.warning("%s GARCH fit failed: %s, using ATM IV", ticker, e)

        # 4. Filter contracts
        filtered = filter_contracts(
            contracts=snapshot.contracts,
            spot=spot,
            risk_free_rate=rfr,
            min_dte=min_dte,
            max_dte=max_dte,
            min_delta=fc.get('min_delta', 0.15),
            max_delta=fc.get('max_delta', 0.50),
            min_oi=fc.get('min_open_interest', 100),
            max_spread_pct=fc.get('max_spread_pct', 15.0),
            moneyness_range=tuple(fc.get('moneyness_range', [0.85, 1.15])),
        )

        if not filtered:
            logger.info("%s: no contracts passed filter", ticker)
            return []

        # 5 & 6. Edge + score for each contract
        signals = []
        now = datetime.now()
        for c in filtered:
            exp_dt = datetime.strptime(c.expiry, '%Y-%m-%d')
            dte = (exp_dt - now).days

            edge_result = compute_edge(c, spot, garch_vol, rfr, dte)

            spread_pct = (c.ask - c.bid) / c.mid * 100 if c.mid > 0 else 100.0

            conviction = score_signal(
                edge_pct=edge_result['edge_pct'],
                iv_rank=iv_metrics['iv_rank'],
                spread_pct=spread_pct,
                open_interest=c.open_interest,
                theta=edge_result['theta'],
                vega=edge_result['vega'],
                direction=edge_result['direction'],
                weights=weights,
            )

            signals.append(OptionSignal(
                ticker=ticker,
                strike=c.strike,
                expiry=c.expiry,
                option_type=c.option_type,
                dte=dte,
                spot=spot,
                bid=c.bid,
                ask=c.ask,
                mid=c.mid,
                open_interest=c.open_interest,
                bid_ask_spread_pct=round(spread_pct, 2),
                chain_iv=c.implied_volatility,
                iv_rank=iv_metrics['iv_rank'],
                iv_percentile=iv_metrics['iv_percentile'],
                iv_regime=iv_metrics['iv_regime'],
                garch_vol=garch_vol,
                theo_price=edge_result['theo_price'],
                edge_pct=round(edge_result['edge_pct'], 2),
                direction=edge_result['direction'],
                delta=round(edge_result['delta'], 4),
                gamma=round(edge_result['gamma'], 6),
                theta=round(edge_result['theta'], 4),
                vega=round(edge_result['vega'], 4),
                conviction=conviction,
            ))

        logger.info("%s: %d signals generated", ticker, len(signals))
        return signals

    def scan_watchlist(self, tickers: List[str]) -> List[OptionSignal]:
        """Scan all tickers, merge and rank signals globally."""
        all_signals = []
        for ticker in tickers:
            try:
                signals = self.scan_ticker(ticker)
                all_signals.extend(signals)
            except Exception as e:
                logger.warning("Failed to scan %s: %s", ticker, e)
                continue
        return rank_signals(all_signals)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_atm_iv(snapshot) -> float:
        """Extract ATM implied vol from the nearest-to-spot call."""
        spot = snapshot.spot
        calls = [c for c in snapshot.contracts
                 if c.option_type == 'call'
                 and not math.isnan(c.implied_volatility)
                 and c.implied_volatility > 0]
        if not calls:
            return 0.25  # fallback
        atm = min(calls, key=lambda c: abs(c.strike - spot))
        return atm.implied_volatility
