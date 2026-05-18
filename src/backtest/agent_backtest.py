"""
Agent backtester — replay historical chain snapshots through agent filters.

Loads backfilled ChainSnapshots from chain_store, builds MarketState
for each date, generates TradeCandidate via the L1→L2 pipeline, then
filters through each agent's rules. Tracks virtual P&L per agent using
BS repricing for exits.

Reuses:
    - build_market_state(symbol, chain_snapshot=...) from market_state.py
    - generate_trades(state) from trade_generator.py
    - Orchestrator._filter_for_agent logic from agents/orchestrator.py
    - analyze_results() from backtest/analyzer.py
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from agents.agent_config import AgentConfig, GuardrailConfig, OrchestratorConfig, load_config
from backtest.analyzer import analyze_results
from backtest.models import BacktestStats, BacktestTrade

logger = logging.getLogger(__name__)

BULLISH_STRATEGIES = {"long_call_spread", "short_put_spread"}
BEARISH_STRATEGIES = {"long_put_spread", "short_call_spread"}
CREDIT_STRATEGIES = {"iron_condor", "short_put_spread", "short_call_spread"}
SWING_CREDIT = {"calendar_spread", "diagonal_spread", "iron_butterfly"}
MEDIUM_TERM_CREDIT = {"mt_calendar_spread", "mt_diagonal_spread", "mt_iron_butterfly"}
LONG_TERM_CREDIT = {"lt_calendar_spread", "lt_diagonal_spread"}


@dataclass
class AgentTrade:
    """An open trade being tracked for an agent."""
    agent_id: str
    ticker: str
    strategy: str
    entry_date: str
    entry_spot: float
    entry_price: float
    entry_iv: float
    dte_at_entry: int
    confluence_score: float
    regime: str
    bias_label: str
    is_credit: bool
    legs: List[Dict]
    entry_regime: str = ""
    edge_source: str = ""


@dataclass
class AgentBacktestResult:
    """Results for one agent."""
    agent_id: str
    config: AgentConfig
    stats: BacktestStats
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    entries_attempted: int = 0
    entries_filtered: int = 0

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "description": self.config.description,
            "capital_pct": self.config.capital_pct,
            "stats": self.stats.model_dump(),
            "trade_count": len(self.trades),
            "entries_attempted": self.entries_attempted,
            "entries_filtered": self.entries_filtered,
            "equity_curve_final": self.equity_curve[-1] if self.equity_curve else 0.0,
        }


@dataclass
class AgentBacktestSummary:
    """Combined results across all agents."""
    tickers: List[str]
    date_range: Tuple[str, str]
    dates_processed: int
    agent_results: Dict[str, AgentBacktestResult]

    def to_dict(self) -> dict:
        return {
            "tickers": self.tickers,
            "date_range": list(self.date_range),
            "dates_processed": self.dates_processed,
            "agents": {k: v.to_dict() for k, v in self.agent_results.items()},
        }


def _get_exit_rules(strategy: str, dte_at_entry: int = 14) -> dict:
    # Short-term rules (0-14 DTE)
    _short_rules = {
        "iron_condor":       {"profit_pct": 50, "loss_pct": 200, "exit_dte": 1},
        "short_put_spread":  {"profit_pct": 50, "loss_pct": 200, "exit_dte": 1},
        "short_call_spread": {"profit_pct": 50, "loss_pct": 200, "exit_dte": 1},
        "long_call_spread":  {"profit_pct": 75, "loss_pct": 100, "exit_dte": 2},
        "long_put_spread":   {"profit_pct": 75, "loss_pct": 100, "exit_dte": 2},
        "butterfly":         {"profit_pct": 100, "loss_pct": 100, "exit_dte": 0},
    }

    # Swing rules (14-60 DTE): moderate targets, 7 DTE time exit
    _swing_rules = {
        "calendar_spread":      {"profit_pct": 30, "loss_pct": 100, "exit_dte": 7},
        "diagonal_spread":      {"profit_pct": 35, "loss_pct": 100, "exit_dte": 7},
        "iron_butterfly":       {"profit_pct": 40, "loss_pct": 150, "exit_dte": 7},
        "long_straddle":        {"profit_pct": 50, "loss_pct": 50,  "exit_dte": 10},
    }

    # Medium/long-term rules (30-180 DTE): wider targets, earlier time exit
    _medium_rules = {
        "mt_calendar_spread":   {"profit_pct": 35, "loss_pct": 100, "exit_dte": 14},
        "mt_diagonal_spread":   {"profit_pct": 40, "loss_pct": 100, "exit_dte": 14},
        "mt_iron_butterfly":    {"profit_pct": 50, "loss_pct": 150, "exit_dte": 14},
        "mt_long_straddle":     {"profit_pct": 50, "loss_pct": 50,  "exit_dte": 21},
        # Long-term (90-180 DTE): wider stops, earlier time exit
        "lt_calendar_spread":   {"profit_pct": 30, "loss_pct": 80,  "exit_dte": 21},
        "lt_diagonal_spread":   {"profit_pct": 35, "loss_pct": 80,  "exit_dte": 21},
        "lt_long_straddle":     {"profit_pct": 50, "loss_pct": 50,  "exit_dte": 30},
    }

    if dte_at_entry >= 30 and strategy in _medium_rules:
        return _medium_rules[strategy]

    if 14 <= dte_at_entry < 30 and strategy in _swing_rules:
        return _swing_rules[strategy]

    if strategy in _short_rules:
        return _short_rules[strategy]

    if strategy in _swing_rules:
        return _swing_rules[strategy]

    if strategy in _medium_rules:
        return _medium_rules[strategy]

    return {"profit_pct": 50, "loss_pct": 200, "exit_dte": 1}


def _price_position(spot: float, entry_spot: float, iv: float,
                     dte_remaining: int, strategy: str, is_credit: bool) -> float:
    from models.black_scholes import black_scholes_price
    from config import RISK_FREE_RATE

    T = max(dte_remaining / 365.0, 1 / 365.0)
    r = RISK_FREE_RATE

    inc = 5.0 if entry_spot >= 100 else (2.5 if entry_spot >= 50 else 1.0)
    atm = round(entry_spot / inc) * inc

    try:
        if strategy == "iron_condor":
            sc = black_scholes_price(spot, atm + inc, T, r, iv, "call")
            bc = black_scholes_price(spot, atm + 2 * inc, T, r, iv, "call")
            sp = black_scholes_price(spot, atm - inc, T, r, iv, "put")
            bp = black_scholes_price(spot, atm - 2 * inc, T, r, iv, "put")
            return (sc - bc) + (sp - bp)
        elif strategy == "short_put_spread":
            s = black_scholes_price(spot, atm - inc, T, r, iv, "put")
            b = black_scholes_price(spot, atm - 2 * inc, T, r, iv, "put")
            return s - b
        elif strategy == "short_call_spread":
            s = black_scholes_price(spot, atm + inc, T, r, iv, "call")
            b = black_scholes_price(spot, atm + 2 * inc, T, r, iv, "call")
            return s - b
        elif strategy == "long_call_spread":
            b = black_scholes_price(spot, atm, T, r, iv, "call")
            s = black_scholes_price(spot, atm + inc, T, r, iv, "call")
            return b - s
        elif strategy == "long_put_spread":
            b = black_scholes_price(spot, atm, T, r, iv, "put")
            s = black_scholes_price(spot, atm - inc, T, r, iv, "put")
            return b - s
        elif strategy == "butterfly":
            bc_lo = black_scholes_price(spot, atm - inc, T, r, iv, "call")
            sc_2 = black_scholes_price(spot, atm, T, r, iv, "call") * 2
            bc_hi = black_scholes_price(spot, atm + inc, T, r, iv, "call")
            return bc_lo - sc_2 + bc_hi
        elif strategy in ("calendar_spread", "diagonal_spread",
                          "mt_calendar_spread", "mt_diagonal_spread",
                          "lt_calendar_spread", "lt_diagonal_spread"):
            front_T = max(T * 0.4, 1 / 365.0)
            back = black_scholes_price(spot, atm, T, r, iv, "call")
            front = black_scholes_price(spot, atm, front_T, r, iv, "call")
            return back - front
        elif strategy in ("iron_butterfly", "mt_iron_butterfly"):
            sc = black_scholes_price(spot, atm, T, r, iv, "call")
            sp = black_scholes_price(spot, atm, T, r, iv, "put")
            bc = black_scholes_price(spot, atm + 2 * inc, T, r, iv, "call")
            bp = black_scholes_price(spot, atm - 2 * inc, T, r, iv, "put")
            return (sc + sp) - (bc + bp)
        elif strategy in ("long_straddle", "mt_long_straddle", "lt_long_straddle"):
            c = black_scholes_price(spot, atm, T, r, iv, "call")
            p = black_scholes_price(spot, atm, T, r, iv, "put")
            return c + p
        else:
            return black_scholes_price(spot, atm, T, r, iv, "call")
    except Exception:
        return 0.0


@dataclass
class _SyntheticCandidate:
    """Lightweight trade candidate built from persisted swing_signals."""
    symbol: str
    strategy: str
    strategy_label: str
    confluence_score: float
    regime: str
    bias_label: str
    suggested_dte: int
    iv_rv_edge_pct: float
    legs: List[Dict] = field(default_factory=list)
    is_credit: bool = False
    edge_source: str = ""


def _build_candidates_from_signals(
    ticker: str, date_str: str, dte_tier: str,
) -> Tuple[Optional[Dict], List[_SyntheticCandidate]]:
    """Build trade candidates from persisted swing_signals for medium/long-term tiers.

    Replays the decision matrix using stored signal values instead of live data.
    Returns (signal_state_dict, list_of_candidates).
    """
    from data.chain_store import get_swing_signals

    signals = get_swing_signals(ticker, start_date=date_str, end_date=date_str)
    if not signals:
        return None, []

    sig = signals[0]
    vrp_pct = sig.get("vrp_overall_pct") or 0
    vrp_regime = sig.get("vrp_regime") or "NEUTRAL"
    skew_regime = sig.get("skew_regime") or "NORMAL"
    bias_label = sig.get("swing_bias_label") or "NEUTRAL"
    cross_signal = sig.get("move_vix_signal") or "ALIGNED"
    flow_signal = sig.get("flow_composite") or "NEUTRAL"
    vvix_size = sig.get("vvix_size_factor") or 1.0
    calendar_signal = sig.get("calendar_signal") or 0
    correlation_premium = sig.get("correlation_premium")
    chain_iv = sig.get("front_iv") or 0.20

    # Determine regime from VRP context
    regime = "HIGH_IV" if vrp_pct > 0 else "MODERATE_IV"

    state = {
        "spot": 0,
        "chain_iv": chain_iv,
        "regime": regime,
        "bias_label": bias_label,
        "vrp_regime": vrp_regime,
        "skew_regime": skew_regime,
        "cross_signal": cross_signal,
        "flow_signal": flow_signal,
        "vvix_size_factor": vvix_size,
        "cross_asset": {"position_size_factor": vvix_size},
    }

    candidates = []

    if dte_tier == "swing":
        from swing.decision_matrix import map_swing_strategy
        rec = map_swing_strategy(
            regime=regime, swing_bias=bias_label, dealer_regime=None,
            vrp_rich=vrp_pct > 0, vrp_pct=vrp_pct,
            calendar_signal=calendar_signal,
            in_earnings_window=bool(sig.get("in_earnings_window")),
            earnings_iv_inflation=sig.get("earnings_iv_inflation") or 0,
        )
        dte_range = (14, 60)
    elif dte_tier == "medium_term":
        from swing.decision_matrix import map_medium_term_strategy
        rec = map_medium_term_strategy(
            regime=regime, swing_bias=bias_label, dealer_regime=None,
            vrp_regime=vrp_regime, vrp_pct=vrp_pct,
            calendar_signal=calendar_signal, skew_regime=skew_regime,
            cross_asset_signal=cross_signal, flow_signal=flow_signal,
            vvix_size_factor=vvix_size,
            in_earnings_window=bool(sig.get("in_earnings_window")),
            earnings_iv_inflation=sig.get("earnings_iv_inflation") or 0,
        )
        dte_range = (30, 90)
    else:
        from swing.decision_matrix import map_long_term_strategy
        rec = map_long_term_strategy(
            regime=regime, swing_bias=bias_label,
            vrp_regime=vrp_regime, vrp_pct=vrp_pct,
            skew_regime=skew_regime, cross_asset_signal=cross_signal,
            flow_signal=flow_signal, vvix_size_factor=vvix_size,
            correlation_premium=correlation_premium,
        )
        dte_range = (90, 180)

    if rec:
        score = getattr(rec, "score", 70)
        edge_source = getattr(rec, "edge_source", "")
        suggested_dte = getattr(rec, "suggested_dte", sum(dte_range) // 2)
        is_credit = rec.strategy in SWING_CREDIT or rec.strategy in MEDIUM_TERM_CREDIT or rec.strategy in LONG_TERM_CREDIT

        tc = _SyntheticCandidate(
            symbol=ticker,
            strategy=rec.strategy,
            strategy_label=getattr(rec, "strategy_label", rec.strategy),
            confluence_score=score,
            regime=regime,
            bias_label=bias_label,
            suggested_dte=suggested_dte,
            iv_rv_edge_pct=vrp_pct,
            is_credit=is_credit,
            edge_source=edge_source,
        )
        candidates.append(tc)

    return state, candidates


_SW_REMAP = {
    "butterfly": "iron_butterfly",
    "short_put_spread": "calendar_spread",
    "short_call_spread": "diagonal_spread",
    "iron_condor": "iron_butterfly",
    "long_call_spread": "long_straddle",
    "long_put_spread": "long_straddle",
}

_MT_REMAP = {
    "butterfly": "mt_iron_butterfly",
    "short_put_spread": "mt_calendar_spread",
    "short_call_spread": "mt_diagonal_spread",
    "iron_condor": "mt_iron_butterfly",
    "long_call_spread": "mt_long_straddle",
    "long_put_spread": "mt_long_straddle",
}

_LT_REMAP = {
    "butterfly": "lt_calendar_spread",
    "short_put_spread": "lt_calendar_spread",
    "short_call_spread": "lt_diagonal_spread",
    "iron_condor": "lt_calendar_spread",
    "long_call_spread": "lt_long_straddle",
    "long_put_spread": "lt_long_straddle",
}


def _remap_candidates(raw_candidates: list, dte_tier: str) -> List[_SyntheticCandidate]:
    """Remap short-term trade candidates to swing/medium/long-term strategy names."""
    if dte_tier == "swing":
        remap = _SW_REMAP
    elif dte_tier == "medium_term":
        remap = _MT_REMAP
    else:
        remap = _LT_REMAP
    dte_default = {"swing": 35, "medium_term": 60, "long_term": 120}.get(dte_tier, 60)

    result = []
    seen = set()
    for tc in raw_candidates:
        new_strat = remap.get(tc.strategy)
        if not new_strat or new_strat in seen:
            continue
        seen.add(new_strat)

        is_credit = new_strat in SWING_CREDIT or new_strat in MEDIUM_TERM_CREDIT or new_strat in LONG_TERM_CREDIT
        result.append(_SyntheticCandidate(
            symbol=tc.symbol,
            strategy=new_strat,
            strategy_label=new_strat.replace("_", " ").title(),
            confluence_score=tc.confluence_score,
            regime=tc.regime,
            bias_label=tc.bias_label,
            suggested_dte=dte_default,
            iv_rv_edge_pct=getattr(tc, "iv_rv_edge_pct", 0),
            is_credit=is_credit,
        ))
    return result


def _filter_candidate(cfg: AgentConfig, tc, state) -> bool:
    if tc.strategy not in cfg.allowed_strategies:
        return False
    if tc.confluence_score < cfg.min_confluence:
        return False
    if cfg.required_regimes and tc.regime not in cfg.required_regimes:
        return False
    if cfg.required_bias_strength > 0:
        bias_score = getattr(state, "bias_score", 0) or 0
        if abs(bias_score) < cfg.required_bias_strength:
            return False
    if cfg.min_iv_rv_edge_pct > 0:
        if tc.iv_rv_edge_pct < cfg.min_iv_rv_edge_pct:
            return False
    if cfg.min_dte > 0:
        dte = getattr(tc, "suggested_dte", 0) or 0
        if dte < cfg.min_dte:
            return False
    return True


def _check_exits(
    enabled_agents, agent_open, agent_trades, cooldowns,
    ticker, date_str, spot, chain_iv, slippage_pct,
    current_regime: str = "",
):
    """Check exit conditions for all open trades on this ticker/date."""
    for agent_id in enabled_agents:
        still_open = []
        for ot in agent_open[agent_id]:
            if ot.ticker != ticker:
                still_open.append(ot)
                continue

            entry_dt = datetime.strptime(ot.entry_date, "%Y-%m-%d")
            current_dt = datetime.strptime(date_str, "%Y-%m-%d")
            days_held = (current_dt - entry_dt).days
            dte_remaining = ot.dte_at_entry - days_held

            current_value = _price_position(
                spot, ot.entry_spot, chain_iv,
                dte_remaining, ot.strategy, ot.is_credit,
            )

            if ot.is_credit:
                pnl = ot.entry_price - current_value
            else:
                pnl = current_value - ot.entry_price

            rules = _get_exit_rules(ot.strategy, ot.dte_at_entry)
            exit_reason = None

            if ot.is_credit and ot.entry_price > 0:
                if pnl >= ot.entry_price * (rules["profit_pct"] / 100):
                    exit_reason = "profit_target"
                elif pnl <= -ot.entry_price * (rules["loss_pct"] / 100):
                    exit_reason = "stop_loss"
            elif not ot.is_credit and ot.entry_price > 0:
                if pnl >= ot.entry_price * (rules["profit_pct"] / 100):
                    exit_reason = "profit_target"
                elif pnl <= -ot.entry_price * (rules["loss_pct"] / 100):
                    exit_reason = "stop_loss"

            if dte_remaining <= rules["exit_dte"]:
                exit_reason = "dte_exit"

            # Regime-transition exit: close credit positions if regime → SPIKE
            if (
                not exit_reason
                and current_regime == "SPIKE"
                and ot.entry_regime
                and ot.entry_regime != "SPIKE"
                and ot.is_credit
            ):
                exit_reason = "regime_spike"
                logger.info(
                    "Regime exit: %s %s entered in %s, now SPIKE",
                    ot.ticker, ot.strategy, ot.entry_regime,
                )

            if exit_reason:
                slip = abs(current_value) * (slippage_pct / 100.0)
                if ot.is_credit:
                    final_pnl = ot.entry_price - (current_value + slip)
                else:
                    final_pnl = (current_value - slip) - ot.entry_price

                entry_d = datetime.strptime(ot.entry_date, "%Y-%m-%d").date()
                exit_d = datetime.strptime(date_str, "%Y-%m-%d").date()

                trade = BacktestTrade(
                    entry_date=entry_d,
                    exit_date=exit_d,
                    entry_price=round(ot.entry_price, 2),
                    exit_price=round(current_value, 2),
                    pnl=round(final_pnl * 100, 2),
                    pnl_pct=round(final_pnl / max(abs(ot.entry_price), 0.01) * 100, 1),
                    dte_at_entry=ot.dte_at_entry,
                    dte_at_exit=max(dte_remaining, 0),
                    regime=ot.regime,
                    score=ot.confluence_score,
                    win=final_pnl > 0,
                    exit_reason=exit_reason,
                    bias_label=ot.bias_label,
                    iv_at_entry=round(ot.entry_iv, 4),
                )
                agent_trades[agent_id].append(trade)
                cooldowns[agent_id][ticker] = date_str
            else:
                still_open.append(ot)

        agent_open[agent_id] = still_open


def _try_entries(
    enabled_agents, agent_open, cooldowns,
    agent_entries_attempted, agent_entries_filtered,
    candidates, state, ticker, date_str, spot, chain_iv,
    slippage_pct,
):
    """Try new entries for each agent on this ticker/date."""
    # Extract regime for entry_regime tracking
    if isinstance(state, dict):
        current_regime = state.get("regime", "")
        edge_source = ""
    else:
        current_regime = getattr(state, "regime", "")
        edge_source = ""

    for agent_id, cfg in enabled_agents.items():
        open_count = len(agent_open[agent_id])
        if open_count >= cfg.max_positions:
            continue

        last_exit = cooldowns[agent_id].get(ticker)
        if last_exit:
            last_dt = datetime.strptime(last_exit, "%Y-%m-%d")
            curr_dt = datetime.strptime(date_str, "%Y-%m-%d")
            if (curr_dt - last_dt).days < 5:
                continue

        ticker_positions = sum(
            1 for ot in agent_open[agent_id] if ot.ticker == ticker
        )
        if ticker_positions > 0:
            continue

        for tc in candidates:
            agent_entries_attempted[agent_id] += 1

            if not _filter_candidate(cfg, tc, state):
                agent_entries_filtered[agent_id] += 1
                continue

            if len(agent_open[agent_id]) >= cfg.max_positions:
                break

            is_credit = tc.strategy in (CREDIT_STRATEGIES | SWING_CREDIT | MEDIUM_TERM_CREDIT | LONG_TERM_CREDIT)
            dte = tc.suggested_dte if tc.suggested_dte > 0 else 7

            raw_price = _price_position(
                spot, spot, chain_iv, dte,
                tc.strategy, is_credit,
            )
            if raw_price <= 0.05:
                continue

            slip = abs(raw_price) * (slippage_pct / 100.0)
            if is_credit:
                entry_price = raw_price - slip
            else:
                entry_price = raw_price + slip

            if entry_price <= 0.01:
                continue

            tc_edge = getattr(tc, "edge_source", edge_source)

            ot = AgentTrade(
                agent_id=agent_id,
                ticker=ticker,
                strategy=tc.strategy,
                entry_date=date_str,
                entry_spot=spot,
                entry_price=entry_price,
                entry_iv=chain_iv,
                dte_at_entry=dte,
                confluence_score=tc.confluence_score,
                regime=tc.regime,
                bias_label=tc.bias_label,
                is_credit=is_credit,
                legs=getattr(tc, "legs", []),
                entry_regime=current_regime if isinstance(current_regime, str) else "",
                edge_source=tc_edge,
            )
            agent_open[agent_id].append(ot)
            break


def run_agent_backtest(
    tickers: List[str],
    start_date: str,
    end_date: str,
    config: Optional[OrchestratorConfig] = None,
    label: str = "backfill",
    slippage_pct: float = 3.0,
    source: str = "chain_store",
    dte_tier: Optional[str] = None,
) -> AgentBacktestSummary:
    """Replay historical chain snapshots through all agent filters.

    Args:
        tickers: Symbols to backtest.
        start_date: Start date "YYYY-MM-DD".
        end_date: End date "YYYY-MM-DD".
        config: Orchestrator config (loaded from agents.yaml if None).
        label: chain_store snapshot label to use.
        slippage_pct: Slippage as % of premium.
        source: Data source — "chain_store" (local snapshots) or "dolt" (DoltHub options DB).
        dte_tier: Filter to only run agents matching this tier (short_term, swing, medium_term, long_term).

    Returns:
        AgentBacktestSummary with per-agent results.
    """
    if source == "dolt":
        from data.dolt_provider import get_available_dates as _dolt_dates
        from data.dolt_provider import get_snapshot as _dolt_snap
        _get_dates = lambda t: _dolt_dates(t, start_date, end_date)
        _get_snap = lambda t, d: _dolt_snap(t, d)
    else:
        from data.chain_store import get_available_dates, get_snapshot
        _get_dates = lambda t: get_available_dates(t, label=label)
        _get_snap = lambda t, d: get_snapshot(t, d, label=label)

    if config is None:
        config = load_config()

    enabled_agents = {
        name: cfg for name, cfg in config.agents.items()
        if cfg.enabled and (dte_tier is None or cfg.dte_tier == dte_tier)
    }

    # Per-agent state
    agent_trades: Dict[str, List[BacktestTrade]] = {a: [] for a in enabled_agents}
    agent_open: Dict[str, List[AgentTrade]] = {a: [] for a in enabled_agents}
    agent_entries_attempted: Dict[str, int] = {a: 0 for a in enabled_agents}
    agent_entries_filtered: Dict[str, int] = {a: 0 for a in enabled_agents}
    cooldowns: Dict[str, Dict[str, str]] = {a: {} for a in enabled_agents}

    dates_processed = 0
    all_dates = set()

    is_mt_lt = dte_tier in ("swing", "medium_term", "long_term")

    if is_mt_lt:
        from data.chain_store import get_swing_signals

        for ticker in tickers:
            # Try signal replay first; fall back to chain snapshots
            signals = get_swing_signals(ticker, start_date=start_date, end_date=end_date)
            signal_dates = {s["snapshot_date"]: s for s in signals}

            available = _get_dates(ticker)
            ticker_dates = sorted(set(
                [d for d in available if start_date <= d <= end_date]
                + list(signal_dates.keys())
            ))
            all_dates.update(ticker_dates)

            logger.info(
                "Backtesting %s (%s): %d dates (%d from signals, %d from snapshots)",
                ticker, dte_tier, len(ticker_dates),
                len(signal_dates), len(available),
            )

            for date_str in ticker_dates:
                # Get spot + chain_iv from chain snapshot
                snapshot = _get_snap(ticker, date_str)
                if snapshot and snapshot.contracts:
                    try:
                        from market_state import build_market_state
                        ms = build_market_state(ticker, chain_snapshot=snapshot)
                        spot = ms.spot
                        chain_iv = ms.chain_iv if not math.isnan(ms.chain_iv) else 0.20
                    except Exception:
                        continue
                else:
                    continue

                if spot <= 0:
                    continue

                # Build candidates: prefer persisted signals, fall back to on-the-fly
                if date_str in signal_dates:
                    sig_state, candidates = _build_candidates_from_signals(
                        ticker, date_str, dte_tier,
                    )
                    if sig_state:
                        sig_state["spot"] = spot
                    else:
                        sig_state = {"spot": spot, "chain_iv": chain_iv, "regime": "MODERATE_IV"}
                        candidates = []
                else:
                    # On-the-fly: use short-term pipeline, remap to mt/lt strategies
                    try:
                        from trade_generator import generate_trades
                        raw_candidates = generate_trades(ms)
                        candidates = _remap_candidates(raw_candidates, dte_tier)
                        sig_state = {
                            "spot": spot, "chain_iv": chain_iv,
                            "regime": getattr(ms, "regime", "MODERATE_IV"),
                        }
                    except Exception:
                        continue

                current_regime = sig_state.get("regime", "")

                _check_exits(
                    enabled_agents, agent_open, agent_trades, cooldowns,
                    ticker, date_str, spot, chain_iv, slippage_pct,
                    current_regime=current_regime,
                )

                _try_entries(
                    enabled_agents, agent_open, cooldowns,
                    agent_entries_attempted, agent_entries_filtered,
                    candidates, sig_state, ticker, date_str, spot, chain_iv,
                    slippage_pct,
                )
    else:
        for ticker in tickers:
            available = _get_dates(ticker)
            ticker_dates = [d for d in available if start_date <= d <= end_date]
            all_dates.update(ticker_dates)

            logger.info(
                "Backtesting %s: %d dates available (%s to %s)",
                ticker, len(ticker_dates),
                ticker_dates[0] if ticker_dates else "none",
                ticker_dates[-1] if ticker_dates else "none",
            )

            for date_str in ticker_dates:
                snapshot = _get_snap(ticker, date_str)
                if not snapshot or not snapshot.contracts:
                    continue

                try:
                    from market_state import build_market_state
                    state = build_market_state(ticker, chain_snapshot=snapshot)
                except Exception as e:
                    logger.warning("MarketState failed for %s %s: %s", ticker, date_str, e)
                    continue

                try:
                    from trade_generator import generate_trades
                    candidates = generate_trades(state)
                except Exception as e:
                    logger.warning("TradeGen failed for %s %s: %s", ticker, date_str, e)
                    continue

                spot = state.spot
                chain_iv = state.chain_iv if not math.isnan(state.chain_iv) else 0.20

                _check_exits(
                    enabled_agents, agent_open, agent_trades, cooldowns,
                    ticker, date_str, spot, chain_iv, slippage_pct,
                )

                _try_entries(
                    enabled_agents, agent_open, cooldowns,
                    agent_entries_attempted, agent_entries_filtered,
                    candidates, state, ticker, date_str, spot, chain_iv,
                    slippage_pct,
                )

    dates_processed = len(all_dates)

    # Build results
    agent_results = {}
    for agent_id, cfg in enabled_agents.items():
        trades = agent_trades[agent_id]
        stats = analyze_results(trades)

        equity = [0.0]
        for t in trades:
            equity.append(equity[-1] + t.pnl)

        agent_results[agent_id] = AgentBacktestResult(
            agent_id=agent_id,
            config=cfg,
            stats=stats,
            trades=trades,
            equity_curve=equity,
            entries_attempted=agent_entries_attempted[agent_id],
            entries_filtered=agent_entries_filtered[agent_id],
        )

    return AgentBacktestSummary(
        tickers=tickers,
        date_range=(start_date, end_date),
        dates_processed=dates_processed,
        agent_results=agent_results,
    )
