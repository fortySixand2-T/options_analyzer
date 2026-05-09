"""
Risk ledger — per-agent and portfolio-level risk tracking.

Reads from shadow_trades (via shadow_store) to compute positions,
drawdown, daily P&L, and kill switch status. No separate tables.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from agents.agent_config import AgentConfig, GuardrailConfig

logger = logging.getLogger(__name__)

_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "orchestrator_state.json",
)


@dataclass
class AgentRiskState:
    """Current risk state for one agent."""
    agent_id: str
    open_positions: int
    open_by_ticker: Dict[str, int]
    daily_pnl: float
    cumulative_pnl: float
    max_drawdown: float
    is_paused: bool
    pause_reason: str = ""


@dataclass
class PortfolioRiskState:
    """Aggregate risk state across all agents."""
    total_open_positions: int
    positions_by_ticker: Dict[str, int]
    daily_pnl: float
    cumulative_pnl: float
    is_killed: bool
    kill_reason: str = ""


class RiskLedger:
    """Tracks risk across agents using shadow_store data."""

    def __init__(self, guardrails: GuardrailConfig, portfolio_value: float):
        self.guardrails = guardrails
        self.portfolio_value = portfolio_value
        self._paused_agents = self._load_paused()

    def _load_paused(self) -> Dict[str, str]:
        try:
            with open(_STATE_FILE) as f:
                state = json.load(f)
            return state.get("paused_agents", {})
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_paused(self):
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        try:
            with open(_STATE_FILE) as f:
                state = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            state = {}
        state["paused_agents"] = self._paused_agents
        state["updated_at"] = datetime.now().isoformat()
        with open(_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

    def pause_agent(self, agent_id: str, reason: str):
        self._paused_agents[agent_id] = reason
        self._save_paused()
        logger.warning("Agent '%s' paused: %s", agent_id, reason)

    def enable_agent(self, agent_id: str):
        self._paused_agents.pop(agent_id, None)
        self._save_paused()
        logger.info("Agent '%s' enabled", agent_id)

    def get_agent_risk(self, agent_id: str, agent_config: AgentConfig) -> AgentRiskState:
        from data.shadow_store import get_agent_positions, get_daily_pnl, get_cumulative_pnl

        positions = get_agent_positions(agent_id)
        open_count = len(positions)

        by_ticker: Dict[str, int] = {}
        for p in positions:
            sym = p["symbol"]
            by_ticker[sym] = by_ticker.get(sym, 0) + 1

        daily = get_daily_pnl(agent_id)
        cumulative = get_cumulative_pnl(agent_id)

        # Check auto-pause conditions
        agent_capital = self.portfolio_value * agent_config.capital_pct
        is_paused = agent_id in self._paused_agents
        pause_reason = self._paused_agents.get(agent_id, "")

        if not is_paused:
            daily_limit = agent_capital * agent_config.max_daily_loss_pct
            if daily < 0 and abs(daily) > daily_limit:
                pause_reason = f"Daily loss ${abs(daily):.0f} exceeds limit ${daily_limit:.0f}"
                self.pause_agent(agent_id, pause_reason)
                is_paused = True

            dd_limit = agent_capital * agent_config.drawdown_pause_pct
            if cumulative < 0 and abs(cumulative) > dd_limit:
                pause_reason = f"Drawdown ${abs(cumulative):.0f} exceeds limit ${dd_limit:.0f}"
                self.pause_agent(agent_id, pause_reason)
                is_paused = True

        from data.shadow_store import get_agent_stats
        stats = get_agent_stats(agent_id)

        return AgentRiskState(
            agent_id=agent_id,
            open_positions=open_count,
            open_by_ticker=by_ticker,
            daily_pnl=daily,
            cumulative_pnl=cumulative,
            max_drawdown=stats.get("max_drawdown", 0.0),
            is_paused=is_paused,
            pause_reason=pause_reason,
        )

    def get_portfolio_risk(self) -> PortfolioRiskState:
        from data.shadow_store import get_open_trades, get_daily_pnl, get_cumulative_pnl

        all_open = get_open_trades()
        total = len(all_open)

        by_ticker: Dict[str, int] = {}
        for t in all_open:
            sym = t["symbol"]
            by_ticker[sym] = by_ticker.get(sym, 0) + 1

        daily = get_daily_pnl()
        cumulative = get_cumulative_pnl()

        is_killed = False
        kill_reason = ""

        kill_limit = self.portfolio_value * self.guardrails.portfolio_kill_switch_pct
        if cumulative < 0 and abs(cumulative) > kill_limit:
            is_killed = True
            kill_reason = f"Portfolio drawdown ${abs(cumulative):.0f} exceeds kill switch ${kill_limit:.0f}"

        daily_limit = self.portfolio_value * self.guardrails.daily_drawdown_limit_pct
        if daily < 0 and abs(daily) > daily_limit:
            is_killed = True
            kill_reason = f"Daily loss ${abs(daily):.0f} exceeds portfolio limit ${daily_limit:.0f}"

        return PortfolioRiskState(
            total_open_positions=total,
            positions_by_ticker=by_ticker,
            daily_pnl=daily,
            cumulative_pnl=cumulative,
            is_killed=is_killed,
            kill_reason=kill_reason,
        )

    def can_add_position(self, ticker: str, portfolio_risk: PortfolioRiskState) -> bool:
        if portfolio_risk.total_open_positions >= self.guardrails.max_total_positions:
            return False
        ticker_count = portfolio_risk.positions_by_ticker.get(ticker, 0)
        if ticker_count >= self.guardrails.max_positions_per_ticker:
            return False
        return True

    def check_direction_limit(
        self, ticker: str, direction: str, portfolio_risk: PortfolioRiskState,
    ) -> bool:
        """Check if adding another same-direction trade on ticker is allowed."""
        from data.shadow_store import get_open_trades
        all_open = get_open_trades()
        same_dir = 0
        for t in all_open:
            if t["symbol"] != ticker:
                continue
            strat = t["strategy"]
            if direction == "bullish" and strat in ("long_call_spread", "short_put_spread"):
                same_dir += 1
            elif direction == "bearish" and strat in ("long_put_spread", "short_call_spread"):
                same_dir += 1
        return same_dir < self.guardrails.max_same_direction_exposure
