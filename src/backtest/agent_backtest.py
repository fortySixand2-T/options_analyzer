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


def _get_exit_rules(strategy: str) -> dict:
    rules = {
        "iron_condor":       {"profit_pct": 50, "loss_pct": 200, "exit_dte": 1},
        "short_put_spread":  {"profit_pct": 50, "loss_pct": 200, "exit_dte": 1},
        "short_call_spread": {"profit_pct": 50, "loss_pct": 200, "exit_dte": 1},
        "long_call_spread":  {"profit_pct": 75, "loss_pct": 100, "exit_dte": 2},
        "long_put_spread":   {"profit_pct": 75, "loss_pct": 100, "exit_dte": 2},
        "butterfly":         {"profit_pct": 100, "loss_pct": 100, "exit_dte": 0},
    }
    return rules.get(strategy, {"profit_pct": 50, "loss_pct": 200, "exit_dte": 1})


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
        else:
            return black_scholes_price(spot, atm, T, r, iv, "call")
    except Exception:
        return 0.0


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
    return True


def run_agent_backtest(
    tickers: List[str],
    start_date: str,
    end_date: str,
    config: Optional[OrchestratorConfig] = None,
    label: str = "backfill",
    slippage_pct: float = 3.0,
    source: str = "chain_store",
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
        name: cfg for name, cfg in config.agents.items() if cfg.enabled
    }

    # Per-agent state
    agent_trades: Dict[str, List[BacktestTrade]] = {a: [] for a in enabled_agents}
    agent_open: Dict[str, List[AgentTrade]] = {a: [] for a in enabled_agents}
    agent_entries_attempted: Dict[str, int] = {a: 0 for a in enabled_agents}
    agent_entries_filtered: Dict[str, int] = {a: 0 for a in enabled_agents}
    cooldowns: Dict[str, Dict[str, str]] = {a: {} for a in enabled_agents}

    dates_processed = 0
    all_dates = set()

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

            # Build MarketState from stored snapshot
            try:
                from market_state import build_market_state
                state = build_market_state(ticker, chain_snapshot=snapshot)
            except Exception as e:
                logger.warning("MarketState failed for %s %s: %s", ticker, date_str, e)
                continue

            # Generate trade candidates
            try:
                from trade_generator import generate_trades
                candidates = generate_trades(state)
            except Exception as e:
                logger.warning("TradeGen failed for %s %s: %s", ticker, date_str, e)
                continue

            spot = state.spot
            chain_iv = state.chain_iv if not math.isnan(state.chain_iv) else 0.20

            # Check exits for open trades
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

                    rules = _get_exit_rules(ot.strategy)
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

                    if exit_reason:
                        # Apply slippage to exit
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

            # Try new entries for each agent
            for agent_id, cfg in enabled_agents.items():
                open_count = len(agent_open[agent_id])
                if open_count >= cfg.max_positions:
                    continue

                # Cooldown: 5 days after last exit on same ticker
                last_exit = cooldowns[agent_id].get(ticker)
                if last_exit:
                    last_dt = datetime.strptime(last_exit, "%Y-%m-%d")
                    curr_dt = datetime.strptime(date_str, "%Y-%m-%d")
                    if (curr_dt - last_dt).days < 5:
                        continue

                # Already has a position in this ticker?
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

                    is_credit = tc.strategy in CREDIT_STRATEGIES
                    dte = tc.suggested_dte if tc.suggested_dte > 0 else 7

                    raw_price = _price_position(
                        spot, spot, chain_iv, dte,
                        tc.strategy, is_credit,
                    )
                    if raw_price <= 0.05:
                        continue

                    # Apply entry slippage
                    slip = abs(raw_price) * (slippage_pct / 100.0)
                    if is_credit:
                        entry_price = raw_price - slip
                    else:
                        entry_price = raw_price + slip

                    if entry_price <= 0.01:
                        continue

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
                        legs=tc.legs,
                    )
                    agent_open[agent_id].append(ot)
                    break  # one entry per ticker per day per agent

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
