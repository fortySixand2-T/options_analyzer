"""
Multi-agent paper trading orchestrator.

Runs a single scan cycle: builds MarketState per ticker, generates
trade candidates via the existing L1→L2 pipeline, then filters each
candidate through every enabled agent's rules. Portfolio-level
guardrails and conflict resolution are applied before logging trades.

Entry only — shadow_monitor.py handles exits.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from agents.agent_config import AgentConfig, OrchestratorConfig
from agents.risk_ledger import RiskLedger

logger = logging.getLogger(__name__)

BULLISH_STRATEGIES = {"long_call_spread", "short_put_spread"}
BEARISH_STRATEGIES = {"long_put_spread", "short_call_spread"}
NEUTRAL_STRATEGIES = {"butterfly", "iron_condor"}


@dataclass
class AgentProposal:
    """A trade proposed by a specific agent."""
    agent_id: str
    trade_candidate: object
    market_state: object
    direction: str  # "bullish", "bearish", "neutral"

    @property
    def confluence_score(self) -> float:
        return self.trade_candidate.confluence_score

    @property
    def ticker(self) -> str:
        return self.trade_candidate.symbol

    @property
    def strategy(self) -> str:
        return self.trade_candidate.strategy


@dataclass
class CycleResult:
    """Summary of one orchestrator cycle."""
    tickers_scanned: int = 0
    candidates_generated: int = 0
    proposals_created: int = 0
    proposals_approved: int = 0
    trades_logged: int = 0
    agents_paused: List[str] = field(default_factory=list)
    portfolio_killed: bool = False
    kill_reason: str = ""
    errors: List[str] = field(default_factory=list)
    details: List[Dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tickers_scanned": self.tickers_scanned,
            "candidates_generated": self.candidates_generated,
            "proposals_created": self.proposals_created,
            "proposals_approved": self.proposals_approved,
            "trades_logged": self.trades_logged,
            "agents_paused": self.agents_paused,
            "portfolio_killed": self.portfolio_killed,
            "kill_reason": self.kill_reason,
            "errors": self.errors,
            "details": self.details,
        }


class Orchestrator:
    """Central coordinator for multi-agent paper trading."""

    def __init__(self, config: OrchestratorConfig):
        self.config = config
        self.ledger = RiskLedger(config.guardrails, config.portfolio_value)

    def run_cycle(
        self,
        tickers: Optional[List[str]] = None,
        dry_run: bool = False,
        agent_filter: Optional[str] = None,
    ) -> CycleResult:
        """Run one full scan cycle across all agents.

        Args:
            tickers: Override config tickers.
            dry_run: Preview without logging trades.
            agent_filter: Only run this specific agent.

        Returns:
            CycleResult with summary stats.
        """
        result = CycleResult()
        tickers = tickers or self.config.tickers

        # Check portfolio kill switch
        portfolio_risk = self.ledger.get_portfolio_risk()
        if portfolio_risk.is_killed:
            result.portfolio_killed = True
            result.kill_reason = portfolio_risk.kill_reason
            logger.warning("PORTFOLIO KILL SWITCH: %s", portfolio_risk.kill_reason)
            return result

        # Determine which agents to run
        agents = {}
        for name, agent_cfg in self.config.agents.items():
            if agent_filter and name != agent_filter:
                continue
            if not agent_cfg.enabled:
                result.agents_paused.append(name)
                continue
            agents[name] = agent_cfg

        # Build agent risk states
        agent_risks = {}
        for name, cfg in agents.items():
            risk = self.ledger.get_agent_risk(name, cfg)
            if risk.is_paused:
                result.agents_paused.append(name)
                logger.info("Agent '%s' paused: %s", name, risk.pause_reason)
                continue
            agent_risks[name] = risk

        active_agents = {k: v for k, v in agents.items() if k in agent_risks}
        if not active_agents:
            logger.info("No active agents, skipping cycle")
            return result

        # Scan each ticker
        all_proposals: List[AgentProposal] = []

        for ticker in tickers:
            result.tickers_scanned += 1

            try:
                state, candidates = self._build_candidates(ticker)
            except Exception as e:
                result.errors.append(f"{ticker}: {e}")
                logger.error("Failed to build candidates for %s: %s", ticker, e)
                continue

            result.candidates_generated += len(candidates)

            for name, cfg in active_agents.items():
                risk = agent_risks[name]
                filtered = self._filter_for_agent(name, cfg, risk, candidates, state)

                for tc in filtered:
                    direction = self._classify_direction(tc.strategy)
                    proposal = AgentProposal(
                        agent_id=name,
                        trade_candidate=tc,
                        market_state=state,
                        direction=direction,
                    )
                    all_proposals.append(proposal)
                    result.proposals_created += 1

        # Apply portfolio guardrails
        approved = self._apply_guardrails(all_proposals, portfolio_risk)
        result.proposals_approved = len(approved)

        # Resolve conflicts
        approved = self._resolve_conflicts(approved)

        # Log trades
        for proposal in approved:
            try:
                logged = self._log_proposal(proposal, dry_run=dry_run)
                if logged:
                    result.trades_logged += 1
                    result.details.append({
                        "agent": proposal.agent_id,
                        "ticker": proposal.ticker,
                        "strategy": proposal.strategy,
                        "score": round(proposal.confluence_score, 1),
                        "direction": proposal.direction,
                        "dry_run": dry_run,
                    })
            except Exception as e:
                result.errors.append(f"Log failed {proposal.ticker}/{proposal.strategy}: {e}")
                logger.error("Failed to log trade: %s", e)

        return result

    def _build_candidates(self, ticker: str) -> Tuple[object, list]:
        """Build MarketState and generate candidates for a ticker."""
        from market_state import build_market_state
        from trade_generator import generate_trades

        state = build_market_state(ticker)
        candidates = generate_trades(state)
        return state, candidates

    def _filter_for_agent(
        self,
        agent_id: str,
        cfg: AgentConfig,
        risk: object,
        candidates: list,
        state: object,
    ) -> list:
        """Filter trade candidates through agent-specific rules."""
        filtered = []

        for tc in candidates:
            # Strategy filter
            if tc.strategy not in cfg.allowed_strategies:
                continue

            # Confluence threshold
            if tc.confluence_score < cfg.min_confluence:
                continue

            # Regime filter
            if cfg.required_regimes and tc.regime not in cfg.required_regimes:
                continue

            # Bias strength filter
            if cfg.required_bias_strength > 0:
                bias_score = getattr(state, "bias_score", 0) or 0
                if abs(bias_score) < cfg.required_bias_strength:
                    continue

            # IV-RV edge filter
            if cfg.min_iv_rv_edge_pct > 0:
                if tc.iv_rv_edge_pct < cfg.min_iv_rv_edge_pct:
                    continue

            # Position count limit
            if risk.open_positions >= cfg.max_positions:
                logger.debug("Agent '%s' at max positions (%d)", agent_id, cfg.max_positions)
                break

            filtered.append(tc)

        return filtered

    def _classify_direction(self, strategy: str) -> str:
        if strategy in BULLISH_STRATEGIES:
            return "bullish"
        elif strategy in BEARISH_STRATEGIES:
            return "bearish"
        return "neutral"

    def _apply_guardrails(
        self,
        proposals: List[AgentProposal],
        portfolio_risk,
    ) -> List[AgentProposal]:
        """Enforce portfolio-level limits."""
        approved = []
        # Track running counts as we approve
        added_total = 0
        added_by_ticker: Dict[str, int] = {}

        # Sort by confluence score descending — best trades get priority
        proposals.sort(key=lambda p: p.confluence_score, reverse=True)

        current_total = portfolio_risk.total_open_positions
        max_total = self.config.guardrails.max_total_positions
        max_per_ticker = self.config.guardrails.max_positions_per_ticker

        for p in proposals:
            if current_total + added_total >= max_total:
                logger.info("Portfolio position limit reached (%d)", max_total)
                break

            ticker_count = (
                portfolio_risk.positions_by_ticker.get(p.ticker, 0)
                + added_by_ticker.get(p.ticker, 0)
            )
            if ticker_count >= max_per_ticker:
                logger.debug("Ticker %s at max positions (%d)", p.ticker, max_per_ticker)
                continue

            # Direction exposure check
            if p.direction != "neutral":
                if not self.ledger.check_direction_limit(
                    p.ticker, p.direction, portfolio_risk
                ):
                    logger.debug("Direction limit reached for %s %s", p.ticker, p.direction)
                    continue

            approved.append(p)
            added_total += 1
            added_by_ticker[p.ticker] = added_by_ticker.get(p.ticker, 0) + 1

        return approved

    def _resolve_conflicts(self, proposals: List[AgentProposal]) -> List[AgentProposal]:
        """Remove opposing-direction trades on the same ticker.

        When two agents want opposite directions on the same ticker,
        keep the one with higher confluence score.
        """
        by_ticker: Dict[str, List[AgentProposal]] = {}
        for p in proposals:
            by_ticker.setdefault(p.ticker, []).append(p)

        resolved = []
        for ticker, ticker_proposals in by_ticker.items():
            bullish = [p for p in ticker_proposals if p.direction == "bullish"]
            bearish = [p for p in ticker_proposals if p.direction == "bearish"]
            neutral = [p for p in ticker_proposals if p.direction == "neutral"]

            # Neutrals always pass
            resolved.extend(neutral)

            if bullish and bearish:
                best_bull = max(bullish, key=lambda p: p.confluence_score)
                best_bear = max(bearish, key=lambda p: p.confluence_score)

                if best_bull.confluence_score >= best_bear.confluence_score:
                    resolved.extend(bullish)
                    logger.info(
                        "Conflict on %s: bullish wins (%.1f vs %.1f)",
                        ticker, best_bull.confluence_score, best_bear.confluence_score,
                    )
                else:
                    resolved.extend(bearish)
                    logger.info(
                        "Conflict on %s: bearish wins (%.1f vs %.1f)",
                        ticker, best_bear.confluence_score, best_bull.confluence_score,
                    )
            else:
                resolved.extend(bullish)
                resolved.extend(bearish)

        return resolved

    def _log_proposal(self, proposal: AgentProposal, dry_run: bool = False) -> bool:
        """Resolve prices and log a trade via shadow_store."""
        import sys
        sys.path.insert(0, "scripts")

        from shadow_check import _resolve_entry_prices
        from data.shadow_store import log_shadow_trade

        tc = proposal.trade_candidate
        state = proposal.market_state

        entry_legs = _resolve_entry_prices(tc.symbol, tc, state.spot)

        if not all(lp.get("mid") for lp in entry_legs):
            missing = [lp["strike"] for lp in entry_legs if not lp.get("mid")]
            logger.warning(
                "Agent '%s': skipped %s %s — missing prices for strikes %s",
                proposal.agent_id, tc.symbol, tc.strategy, missing,
            )
            return False

        if dry_run:
            logger.info(
                "DRY RUN — Agent '%s': %s %s score=%.1f",
                proposal.agent_id, tc.symbol, tc.strategy_label, tc.confluence_score,
            )
            return True

        # Size using agent's capital allocation
        from sizing import compute_position_size
        agent_cfg = self.config.agents[proposal.agent_id]
        agent_capital = self.config.portfolio_value * agent_cfg.capital_pct

        # Estimate max loss from entry legs
        max_loss = self._estimate_max_loss(tc, entry_legs)

        size_result = compute_position_size(
            strategy=tc.strategy,
            portfolio_value=agent_capital,
            max_loss_per_contract=max_loss,
            confluence_score=tc.confluence_score,
        )
        contracts = max(1, size_result.contracts) if size_result.contracts > 0 else 1

        trade_id = log_shadow_trade(
            tc, entry_legs, state.spot,
            contracts=contracts,
            agent_id=proposal.agent_id,
        )

        if trade_id:
            logger.info(
                "Agent '%s': logged trade #%d — %s %s score=%.1f contracts=%d",
                proposal.agent_id, trade_id, tc.symbol,
                tc.strategy_label, tc.confluence_score, contracts,
            )
            return True
        return False

    def _estimate_max_loss(self, tc, entry_legs: list) -> float:
        """Estimate max loss per contract from leg structure."""
        if tc.is_credit:
            # Credit spread: max loss = spread width - credit received
            strikes = sorted(lp["strike"] for lp in entry_legs if lp.get("strike"))
            if len(strikes) >= 2:
                width = max(strikes) - min(strikes)
                credit = sum(
                    lp.get("mid", 0) for lp in entry_legs if lp.get("action") == "sell"
                ) - sum(
                    lp.get("mid", 0) for lp in entry_legs if lp.get("action") == "buy"
                )
                return max((width - credit) * 100, 50)
        else:
            # Debit spread: max loss = debit paid
            debit = sum(
                lp.get("mid", 0) for lp in entry_legs if lp.get("action") == "buy"
            ) - sum(
                lp.get("mid", 0) for lp in entry_legs if lp.get("action") == "sell"
            )
            return max(debit * 100, 50)
        return 200.0
