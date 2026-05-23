"""
Integration tests for multi-agent orchestrator system.

Tests agent config loading, filtering, guardrails, conflict resolution,
risk ledger, and shadow_store agent_id migration.
"""

import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
import yaml

from agents.agent_config import AgentConfig, GuardrailConfig, OrchestratorConfig, load_config
from agents.orchestrator import (
    BEARISH_STRATEGIES,
    BULLISH_STRATEGIES,
    AgentProposal,
    CycleResult,
    Orchestrator,
)
from agents.risk_ledger import AgentRiskState, PortfolioRiskState, RiskLedger


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_guardrails():
    return GuardrailConfig()


@pytest.fixture
def default_agent():
    return AgentConfig(
        allowed_strategies=["butterfly", "short_put_spread", "long_call_spread", "long_put_spread"],
        min_confluence=65,
    )


@pytest.fixture
def conservative_agent():
    return AgentConfig(
        capital_pct=0.35,
        min_confluence=80,
        allowed_strategies=["butterfly", "short_put_spread"],
        max_positions=3,
        max_daily_loss_pct=0.01,
        drawdown_pause_pct=0.04,
        description="High-conviction credit + butterfly",
    )


@pytest.fixture
def momentum_agent():
    return AgentConfig(
        capital_pct=0.25,
        min_confluence=70,
        allowed_strategies=["long_call_spread", "long_put_spread"],
        required_bias_strength=3,
        max_positions=3,
    )


@pytest.fixture
def vol_harvester_agent():
    return AgentConfig(
        capital_pct=0.25,
        min_confluence=70,
        allowed_strategies=["short_put_spread", "butterfly"],
        required_regimes=["HIGH_IV"],
        min_iv_rv_edge_pct=5.0,
        max_positions=3,
    )


@dataclass
class MockTradeCandidate:
    symbol: str = "SPY"
    strategy: str = "butterfly"
    strategy_label: str = "Butterfly"
    confluence_score: float = 75.0
    regime: str = "MODERATE_IV"
    bias_label: str = "NEUTRAL"
    dealer_regime: str = "LONG_GAMMA"
    iv_rv_edge_pct: float = 3.0
    suggested_dte: int = 5
    is_credit: bool = False
    legs: list = field(default_factory=list)


@dataclass
class MockMarketState:
    symbol: str = "SPY"
    spot: float = 560.0
    bias_score: int = 0
    regime: str = "MODERATE_IV"
    bias_label: str = "NEUTRAL"


@dataclass
class MockRisk:
    open_positions: int = 0


def _make_proposal(agent_id, symbol="SPY", strategy="long_call_spread", score=75.0, direction="bullish"):
    tc = MockTradeCandidate(symbol=symbol, strategy=strategy, confluence_score=score)
    state = MockMarketState(symbol=symbol)
    return AgentProposal(agent_id=agent_id, trade_candidate=tc, market_state=state, direction=direction)


# ---------------------------------------------------------------------------
# Agent Config Tests
# ---------------------------------------------------------------------------

class TestAgentConfig:
    def test_defaults(self):
        cfg = AgentConfig()
        assert cfg.enabled is True
        assert cfg.capital_pct == 0.25
        assert cfg.min_confluence == 65
        assert cfg.max_positions == 3
        assert cfg.max_daily_loss_pct == 0.015
        assert cfg.drawdown_pause_pct == 0.05

    def test_capital_pct_bounds(self):
        with pytest.raises(Exception):
            AgentConfig(capital_pct=1.5)
        with pytest.raises(Exception):
            AgentConfig(capital_pct=-0.1)

    def test_min_confluence_bounds(self):
        with pytest.raises(Exception):
            AgentConfig(min_confluence=101)

    def test_custom_strategies(self):
        cfg = AgentConfig(allowed_strategies=["iron_condor"])
        assert cfg.allowed_strategies == ["iron_condor"]


class TestGuardrailConfig:
    def test_defaults(self):
        g = GuardrailConfig()
        assert g.max_total_positions == 12
        assert g.max_positions_per_ticker == 4
        assert g.daily_drawdown_limit_pct == 0.03
        assert g.portfolio_kill_switch_pct == 0.08
        assert g.max_same_direction_exposure == 3

    def test_position_limit_bounds(self):
        with pytest.raises(Exception):
            GuardrailConfig(max_total_positions=0)
        with pytest.raises(Exception):
            GuardrailConfig(max_total_positions=51)


class TestOrchestratorConfig:
    def test_defaults(self):
        cfg = OrchestratorConfig()
        assert cfg.portfolio_value == 100000
        assert cfg.tickers == ["SPY", "QQQ", "IWM"]

    def test_capital_allocation_rejects_over_100pct(self):
        with pytest.raises(Exception):
            OrchestratorConfig(agents={
                "a": AgentConfig(capital_pct=0.6),
                "b": AgentConfig(capital_pct=0.5),
            })

    def test_capital_allocation_allows_100pct(self):
        cfg = OrchestratorConfig(agents={
            "a": AgentConfig(capital_pct=0.6),
            "b": AgentConfig(capital_pct=0.4),
        })
        assert len(cfg.agents) == 2

    def test_disabled_agents_excluded_from_capital_check(self):
        cfg = OrchestratorConfig(agents={
            "a": AgentConfig(capital_pct=0.8),
            "b": AgentConfig(capital_pct=0.8, enabled=False),
        })
        assert len(cfg.agents) == 2


class TestLoadConfig:
    def test_load_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({
                "orchestrator": {
                    "portfolio_value": 50000,
                    "tickers": ["SPY"],
                    "guardrails": {"max_total_positions": 6},
                },
                "agents": {
                    "test_agent": {
                        "capital_pct": 1.0,
                        "min_confluence": 70,
                        "allowed_strategies": ["butterfly"],
                    },
                },
            }, f)
            f.flush()
            cfg = load_config(f.name)
        os.unlink(f.name)

        assert cfg.portfolio_value == 50000
        assert cfg.tickers == ["SPY"]
        assert cfg.guardrails.max_total_positions == 6
        assert "test_agent" in cfg.agents
        assert cfg.agents["test_agent"].min_confluence == 70

    def test_load_real_config(self):
        cfg = load_config()
        assert "conservative" in cfg.agents
        assert "momentum" in cfg.agents
        assert "vol_harvester" in cfg.agents
        assert "opportunistic" in cfg.agents
        assert cfg.agents["conservative"].min_confluence == 80
        assert cfg.agents["vol_harvester"].required_regimes == ["HIGH_IV"]

    def test_rejects_bad_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({
                "agents": {
                    "bad": {"capital_pct": 2.0},
                },
            }, f)
            f.flush()
            with pytest.raises(Exception):
                load_config(f.name)
        os.unlink(f.name)


# ---------------------------------------------------------------------------
# Agent Filtering Tests
# ---------------------------------------------------------------------------

class TestAgentFiltering:
    def _make_orchestrator(self, agents=None, guardrails=None):
        cfg = OrchestratorConfig(
            agents=agents or {},
            guardrails=guardrails or GuardrailConfig(),
        )
        return Orchestrator(cfg)

    def test_strategy_filter(self, conservative_agent):
        orch = self._make_orchestrator({"cons": conservative_agent})
        risk = MockRisk()

        tc_allowed = MockTradeCandidate(strategy="butterfly", confluence_score=85)
        tc_blocked = MockTradeCandidate(strategy="long_call_spread", confluence_score=85)

        result = orch._filter_for_agent("cons", conservative_agent, risk, [tc_allowed, tc_blocked], MockMarketState())
        assert len(result) == 1
        assert result[0].strategy == "butterfly"

    def test_confluence_threshold(self, conservative_agent):
        orch = self._make_orchestrator({"cons": conservative_agent})
        risk = MockRisk()

        tc_high = MockTradeCandidate(strategy="butterfly", confluence_score=85)
        tc_low = MockTradeCandidate(strategy="butterfly", confluence_score=70)

        result = orch._filter_for_agent("cons", conservative_agent, risk, [tc_high, tc_low], MockMarketState())
        assert len(result) == 1
        assert result[0].confluence_score == 85

    def test_regime_filter(self, vol_harvester_agent):
        orch = self._make_orchestrator({"vh": vol_harvester_agent})
        risk = MockRisk()

        tc_high = MockTradeCandidate(strategy="short_put_spread", confluence_score=75, regime="HIGH_IV", iv_rv_edge_pct=6.0)
        tc_low = MockTradeCandidate(strategy="short_put_spread", confluence_score=75, regime="LOW_IV", iv_rv_edge_pct=6.0)

        result = orch._filter_for_agent("vh", vol_harvester_agent, risk, [tc_high, tc_low], MockMarketState())
        assert len(result) == 1
        assert result[0].regime == "HIGH_IV"

    def test_bias_strength_filter(self, momentum_agent):
        orch = self._make_orchestrator({"mom": momentum_agent})
        risk = MockRisk()

        state_strong = MockMarketState(bias_score=4)
        state_weak = MockMarketState(bias_score=2)

        tc = MockTradeCandidate(strategy="long_call_spread", confluence_score=75)

        result_strong = orch._filter_for_agent("mom", momentum_agent, risk, [tc], state_strong)
        result_weak = orch._filter_for_agent("mom", momentum_agent, risk, [tc], state_weak)

        assert len(result_strong) == 1
        assert len(result_weak) == 0

    def test_iv_rv_edge_filter(self, vol_harvester_agent):
        orch = self._make_orchestrator({"vh": vol_harvester_agent})
        risk = MockRisk()

        tc_edge = MockTradeCandidate(strategy="short_put_spread", confluence_score=75, regime="HIGH_IV", iv_rv_edge_pct=7.0)
        tc_no_edge = MockTradeCandidate(strategy="short_put_spread", confluence_score=75, regime="HIGH_IV", iv_rv_edge_pct=3.0)

        result = orch._filter_for_agent("vh", vol_harvester_agent, risk, [tc_edge, tc_no_edge], MockMarketState())
        assert len(result) == 1
        assert result[0].iv_rv_edge_pct == 7.0

    def test_max_positions_breaks(self):
        agent = AgentConfig(max_positions=1, allowed_strategies=["butterfly"])
        orch = self._make_orchestrator({"a": agent})
        risk = MockRisk(open_positions=1)

        tc = MockTradeCandidate(strategy="butterfly", confluence_score=75)
        result = orch._filter_for_agent("a", agent, risk, [tc], MockMarketState())
        assert len(result) == 0

    def test_all_filters_pass(self):
        agent = AgentConfig(
            min_confluence=70,
            allowed_strategies=["short_put_spread"],
            required_regimes=["HIGH_IV"],
            min_iv_rv_edge_pct=5.0,
            required_bias_strength=2,
        )
        orch = self._make_orchestrator({"a": agent})
        risk = MockRisk()
        state = MockMarketState(bias_score=3)

        tc = MockTradeCandidate(strategy="short_put_spread", confluence_score=80, regime="HIGH_IV", iv_rv_edge_pct=6.0)
        result = orch._filter_for_agent("a", agent, risk, [tc], state)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Direction Classification Tests
# ---------------------------------------------------------------------------

class TestDirectionClassification:
    def test_bullish(self):
        orch = Orchestrator(OrchestratorConfig())
        assert orch._classify_direction("long_call_spread") == "bullish"
        assert orch._classify_direction("short_put_spread") == "bullish"

    def test_bearish(self):
        orch = Orchestrator(OrchestratorConfig())
        assert orch._classify_direction("long_put_spread") == "bearish"
        assert orch._classify_direction("short_call_spread") == "bearish"

    def test_neutral(self):
        orch = Orchestrator(OrchestratorConfig())
        assert orch._classify_direction("butterfly") == "neutral"
        assert orch._classify_direction("iron_condor") == "neutral"


# ---------------------------------------------------------------------------
# Guardrails Tests
# ---------------------------------------------------------------------------

class TestGuardrails:
    def _make_orchestrator(self, max_total=12, max_per_ticker=4):
        cfg = OrchestratorConfig(
            guardrails=GuardrailConfig(
                max_total_positions=max_total,
                max_positions_per_ticker=max_per_ticker,
            ),
        )
        return Orchestrator(cfg)

    def _make_portfolio_risk(self, total=0, by_ticker=None):
        return PortfolioRiskState(
            total_open_positions=total,
            positions_by_ticker=by_ticker or {},
            daily_pnl=0.0,
            cumulative_pnl=0.0,
            is_killed=False,
        )

    def test_total_position_limit(self):
        orch = self._make_orchestrator(max_total=2)
        risk = self._make_portfolio_risk(total=0)

        proposals = [
            _make_proposal("a", "SPY", score=80),
            _make_proposal("b", "QQQ", score=70),
            _make_proposal("c", "IWM", score=60),
        ]

        with patch.object(orch.ledger, 'check_direction_limit', return_value=True):
            approved = orch._apply_guardrails(proposals, risk)
        assert len(approved) == 2

    def test_existing_positions_counted(self):
        orch = self._make_orchestrator(max_total=3)
        risk = self._make_portfolio_risk(total=2)

        proposals = [
            _make_proposal("a", "SPY", score=80),
            _make_proposal("b", "QQQ", score=70),
        ]

        with patch.object(orch.ledger, 'check_direction_limit', return_value=True):
            approved = orch._apply_guardrails(proposals, risk)
        assert len(approved) == 1

    def test_per_ticker_limit(self):
        orch = self._make_orchestrator(max_per_ticker=1)
        risk = self._make_portfolio_risk(total=0, by_ticker={"SPY": 1})

        proposals = [
            _make_proposal("a", "SPY", score=80),
            _make_proposal("b", "QQQ", score=70),
        ]

        with patch.object(orch.ledger, 'check_direction_limit', return_value=True):
            approved = orch._apply_guardrails(proposals, risk)
        assert len(approved) == 1
        assert approved[0].ticker == "QQQ"

    def test_highest_score_prioritized(self):
        orch = self._make_orchestrator(max_total=1)
        risk = self._make_portfolio_risk(total=0)

        proposals = [
            _make_proposal("a", "SPY", score=60),
            _make_proposal("b", "QQQ", score=90),
        ]

        with patch.object(orch.ledger, 'check_direction_limit', return_value=True):
            approved = orch._apply_guardrails(proposals, risk)
        assert len(approved) == 1
        assert approved[0].confluence_score == 90

    def test_neutrals_bypass_direction_check(self):
        orch = self._make_orchestrator()
        risk = self._make_portfolio_risk(total=0)

        proposal = _make_proposal("a", "SPY", strategy="butterfly", direction="neutral", score=75)
        approved = orch._apply_guardrails([proposal], risk)
        assert len(approved) == 1


# ---------------------------------------------------------------------------
# Conflict Resolution Tests
# ---------------------------------------------------------------------------

class TestConflictResolution:
    def test_opposing_directions_higher_score_wins(self):
        orch = Orchestrator(OrchestratorConfig())

        proposals = [
            _make_proposal("bull_agent", "SPY", strategy="long_call_spread", direction="bullish", score=80),
            _make_proposal("bear_agent", "SPY", strategy="long_put_spread", direction="bearish", score=70),
        ]

        resolved = orch._resolve_conflicts(proposals)
        directions = {p.direction for p in resolved}
        assert "bearish" not in directions
        assert any(p.direction == "bullish" for p in resolved)

    def test_bearish_wins_when_higher(self):
        orch = Orchestrator(OrchestratorConfig())

        proposals = [
            _make_proposal("bull_agent", "SPY", strategy="long_call_spread", direction="bullish", score=60),
            _make_proposal("bear_agent", "SPY", strategy="long_put_spread", direction="bearish", score=85),
        ]

        resolved = orch._resolve_conflicts(proposals)
        directions = {p.direction for p in resolved}
        assert "bullish" not in directions

    def test_neutrals_always_pass(self):
        orch = Orchestrator(OrchestratorConfig())

        proposals = [
            _make_proposal("a", "SPY", strategy="butterfly", direction="neutral", score=50),
            _make_proposal("b", "SPY", strategy="long_call_spread", direction="bullish", score=80),
            _make_proposal("c", "SPY", strategy="long_put_spread", direction="bearish", score=70),
        ]

        resolved = orch._resolve_conflicts(proposals)
        neutral_count = sum(1 for p in resolved if p.direction == "neutral")
        assert neutral_count == 1

    def test_no_conflict_both_pass(self):
        orch = Orchestrator(OrchestratorConfig())

        proposals = [
            _make_proposal("a", "SPY", strategy="long_call_spread", direction="bullish", score=80),
            _make_proposal("b", "QQQ", strategy="long_put_spread", direction="bearish", score=70),
        ]

        resolved = orch._resolve_conflicts(proposals)
        assert len(resolved) == 2

    def test_same_direction_no_conflict(self):
        orch = Orchestrator(OrchestratorConfig())

        proposals = [
            _make_proposal("a", "SPY", strategy="long_call_spread", direction="bullish", score=80),
            _make_proposal("b", "SPY", strategy="short_put_spread", direction="bullish", score=70),
        ]

        resolved = orch._resolve_conflicts(proposals)
        assert len(resolved) == 2


# ---------------------------------------------------------------------------
# Risk Ledger Tests
# ---------------------------------------------------------------------------

class TestRiskLedger:
    @pytest.fixture
    def tmp_state_file(self, tmp_path):
        return str(tmp_path / "orchestrator_state.json")

    def _make_ledger(self, guardrails=None, portfolio_value=100000, state_file=None):
        g = guardrails or GuardrailConfig()
        ledger = RiskLedger(g, portfolio_value)
        if state_file:
            import agents.risk_ledger as rl_mod
            rl_mod._STATE_FILE = state_file
            ledger._paused_agents = ledger._load_paused()
        return ledger

    def test_pause_and_enable_agent(self, tmp_state_file):
        import agents.risk_ledger as rl_mod
        rl_mod._STATE_FILE = tmp_state_file

        ledger = self._make_ledger(state_file=tmp_state_file)
        ledger.pause_agent("momentum", "Daily loss exceeded")
        assert "momentum" in ledger._paused_agents

        ledger.enable_agent("momentum")
        assert "momentum" not in ledger._paused_agents

    def test_pause_persists_to_file(self, tmp_state_file):
        import agents.risk_ledger as rl_mod
        rl_mod._STATE_FILE = tmp_state_file

        ledger1 = self._make_ledger(state_file=tmp_state_file)
        ledger1.pause_agent("vol_harvester", "Drawdown limit")

        ledger2 = self._make_ledger(state_file=tmp_state_file)
        assert "vol_harvester" in ledger2._paused_agents

    def test_portfolio_kill_switch_cumulative(self):
        g = GuardrailConfig(portfolio_kill_switch_pct=0.08)
        ledger = self._make_ledger(guardrails=g, portfolio_value=100000)

        with patch("data.shadow_store.get_open_trades", return_value=[]):
            with patch("data.shadow_store.get_daily_pnl", return_value=0.0):
                with patch("data.shadow_store.get_cumulative_pnl", return_value=-9000.0):
                    risk = ledger.get_portfolio_risk()
                    assert risk.is_killed is True
                    assert "kill switch" in risk.kill_reason.lower()

    def test_portfolio_kill_switch_daily(self):
        g = GuardrailConfig(daily_drawdown_limit_pct=0.03)
        ledger = self._make_ledger(guardrails=g, portfolio_value=100000)

        with patch("data.shadow_store.get_open_trades", return_value=[]):
            with patch("data.shadow_store.get_daily_pnl", return_value=-4000.0):
                with patch("data.shadow_store.get_cumulative_pnl", return_value=-4000.0):
                    risk = ledger.get_portfolio_risk()
                    assert risk.is_killed is True

    def test_portfolio_not_killed_within_limits(self):
        g = GuardrailConfig(portfolio_kill_switch_pct=0.08, daily_drawdown_limit_pct=0.03)
        ledger = self._make_ledger(guardrails=g, portfolio_value=100000)

        with patch("data.shadow_store.get_open_trades", return_value=[]):
            with patch("data.shadow_store.get_daily_pnl", return_value=-1000.0):
                with patch("data.shadow_store.get_cumulative_pnl", return_value=-5000.0):
                    risk = ledger.get_portfolio_risk()
                    assert risk.is_killed is False

    def test_agent_daily_loss_auto_pause(self, tmp_state_file):
        import agents.risk_ledger as rl_mod
        rl_mod._STATE_FILE = tmp_state_file

        g = GuardrailConfig()
        ledger = self._make_ledger(guardrails=g, portfolio_value=100000, state_file=tmp_state_file)
        agent_cfg = AgentConfig(capital_pct=0.25, max_daily_loss_pct=0.015)

        with patch("data.shadow_store.get_agent_positions", return_value=[]):
            with patch("data.shadow_store.get_daily_pnl", return_value=-500.0):
                with patch("data.shadow_store.get_cumulative_pnl", return_value=-500.0):
                    with patch("data.shadow_store.get_agent_stats", return_value={"max_drawdown": 0}):
                        risk = ledger.get_agent_risk("test_agent", agent_cfg)
                        assert risk.is_paused is True
                        assert "daily loss" in risk.pause_reason.lower()

    def test_agent_drawdown_auto_pause(self, tmp_state_file):
        import agents.risk_ledger as rl_mod
        rl_mod._STATE_FILE = tmp_state_file

        g = GuardrailConfig()
        ledger = self._make_ledger(guardrails=g, portfolio_value=100000, state_file=tmp_state_file)
        agent_cfg = AgentConfig(capital_pct=0.25, drawdown_pause_pct=0.05)

        with patch("data.shadow_store.get_agent_positions", return_value=[]):
            with patch("data.shadow_store.get_daily_pnl", return_value=0.0):
                with patch("data.shadow_store.get_cumulative_pnl", return_value=-1500.0):
                    with patch("data.shadow_store.get_agent_stats", return_value={"max_drawdown": 0}):
                        risk = ledger.get_agent_risk("test_agent", agent_cfg)
                        assert risk.is_paused is True
                        assert "drawdown" in risk.pause_reason.lower()

    def test_agent_not_paused_within_limits(self, tmp_state_file):
        import agents.risk_ledger as rl_mod
        rl_mod._STATE_FILE = tmp_state_file

        g = GuardrailConfig()
        ledger = self._make_ledger(guardrails=g, portfolio_value=100000, state_file=tmp_state_file)
        agent_cfg = AgentConfig(capital_pct=0.25, max_daily_loss_pct=0.015, drawdown_pause_pct=0.05)

        with patch("data.shadow_store.get_agent_positions", return_value=[]):
            with patch("data.shadow_store.get_daily_pnl", return_value=-100.0):
                with patch("data.shadow_store.get_cumulative_pnl", return_value=-500.0):
                    with patch("data.shadow_store.get_agent_stats", return_value={"max_drawdown": 0}):
                        risk = ledger.get_agent_risk("test_agent", agent_cfg)
                        assert risk.is_paused is False

    def test_can_add_position_total_limit(self):
        g = GuardrailConfig(max_total_positions=5)
        ledger = self._make_ledger(guardrails=g)

        risk_under = PortfolioRiskState(total_open_positions=4, positions_by_ticker={}, daily_pnl=0, cumulative_pnl=0, is_killed=False)
        risk_at = PortfolioRiskState(total_open_positions=5, positions_by_ticker={}, daily_pnl=0, cumulative_pnl=0, is_killed=False)

        assert ledger.can_add_position("SPY", risk_under) is True
        assert ledger.can_add_position("SPY", risk_at) is False

    def test_can_add_position_ticker_limit(self):
        g = GuardrailConfig(max_positions_per_ticker=2)
        ledger = self._make_ledger(guardrails=g)

        risk = PortfolioRiskState(total_open_positions=2, positions_by_ticker={"SPY": 2}, daily_pnl=0, cumulative_pnl=0, is_killed=False)

        assert ledger.can_add_position("SPY", risk) is False
        assert ledger.can_add_position("QQQ", risk) is True

    def test_direction_limit(self):
        g = GuardrailConfig(max_same_direction_exposure=2)
        ledger = self._make_ledger(guardrails=g)

        mock_trades = [
            {"symbol": "SPY", "strategy": "long_call_spread"},
            {"symbol": "SPY", "strategy": "short_put_spread"},
        ]
        risk = PortfolioRiskState(total_open_positions=2, positions_by_ticker={"SPY": 2}, daily_pnl=0, cumulative_pnl=0, is_killed=False)

        with patch("data.shadow_store.get_open_trades", return_value=mock_trades):
            assert ledger.check_direction_limit("SPY", "bullish", risk) is False
            assert ledger.check_direction_limit("SPY", "bearish", risk) is True
            assert ledger.check_direction_limit("QQQ", "bullish", risk) is True


# ---------------------------------------------------------------------------
# Shadow Store Migration Tests
# ---------------------------------------------------------------------------

class TestShadowStoreMigration:
    def test_agent_id_column_created(self, tmp_path):
        db_path = str(tmp_path / "test_shadow.db")
        with patch.dict(os.environ, {"SHADOW_DB": db_path}):
            from data.shadow_store import _get_conn
            conn = _get_conn()
            cols = [row[1] for row in conn.execute("PRAGMA table_info(shadow_trades)").fetchall()]
            conn.close()
            assert "agent_id" in cols

    def test_agent_id_default_value(self, tmp_path):
        db_path = str(tmp_path / "test_shadow2.db")
        with patch.dict(os.environ, {"SHADOW_DB": db_path}):
            from data.shadow_store import _get_conn
            conn = _get_conn()
            conn.execute(
                "INSERT INTO shadow_trades (symbol, strategy, strategy_label, legs_json, is_credit, "
                "entry_date, entry_net_price, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("SPY", "butterfly", "Butterfly", "[]", 0, "2025-01-01", 1.50, "open"),
            )
            conn.commit()
            row = conn.execute("SELECT agent_id FROM shadow_trades WHERE symbol='SPY'").fetchone()
            conn.close()
            assert row[0] == "legacy"

    def test_agent_id_filter_queries(self, tmp_path):
        db_path = str(tmp_path / "test_shadow3.db")
        with patch.dict(os.environ, {"SHADOW_DB": db_path}):
            from data.shadow_store import _get_conn, get_open_trades
            conn = _get_conn()
            for agent in ["conservative", "momentum", "legacy"]:
                conn.execute(
                    "INSERT INTO shadow_trades (symbol, strategy, strategy_label, legs_json, is_credit, "
                    "entry_date, entry_net_price, agent_id, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("SPY", "butterfly", "Butterfly", "[]", 0, "2025-01-01", 1.50, agent, "open"),
                )
            conn.commit()
            conn.close()

            all_open = get_open_trades()
            assert len(all_open) == 3

            cons_open = get_open_trades(agent_id="conservative")
            assert len(cons_open) == 1
            assert cons_open[0]["agent_id"] == "conservative"

    def test_migration_idempotent(self, tmp_path):
        db_path = str(tmp_path / "test_shadow4.db")
        with patch.dict(os.environ, {"SHADOW_DB": db_path}):
            from data.shadow_store import _get_conn
            conn1 = _get_conn()
            conn1.close()
            conn2 = _get_conn()
            cols = [row[1] for row in conn2.execute("PRAGMA table_info(shadow_trades)").fetchall()]
            conn2.close()
            assert cols.count("agent_id") == 1


# ---------------------------------------------------------------------------
# CycleResult Tests
# ---------------------------------------------------------------------------

class TestCycleResult:
    def test_to_dict(self):
        result = CycleResult(
            tickers_scanned=3,
            candidates_generated=10,
            proposals_created=5,
            proposals_approved=3,
            trades_logged=2,
        )
        d = result.to_dict()
        assert d["tickers_scanned"] == 3
        assert d["trades_logged"] == 2
        assert d["portfolio_killed"] is False

    def test_killed_state(self):
        result = CycleResult(portfolio_killed=True, kill_reason="drawdown")
        d = result.to_dict()
        assert d["portfolio_killed"] is True
        assert d["kill_reason"] == "drawdown"
