"""
Pydantic v2 models for multi-agent orchestrator configuration.

Parses config/agents.yaml into validated, typed objects.
"""

import os
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, model_validator


class AgentConfig(BaseModel):
    """Per-agent filter and risk parameters."""

    enabled: bool = True
    capital_pct: float = Field(default=0.25, ge=0.0, le=1.0)
    min_confluence: float = Field(default=65, ge=0, le=100)
    allowed_strategies: List[str] = Field(
        default_factory=lambda: [
            "butterfly", "short_put_spread", "long_call_spread", "long_put_spread",
        ]
    )
    required_regimes: Optional[List[str]] = None
    required_bias_strength: float = Field(default=0, ge=0)
    min_iv_rv_edge_pct: float = Field(default=0, ge=0)
    max_positions: int = Field(default=3, ge=1, le=20)
    max_daily_loss_pct: float = Field(default=0.015, ge=0, le=1.0)
    drawdown_pause_pct: float = Field(default=0.05, ge=0, le=1.0)
    min_dte: int = Field(default=0, ge=0, le=180)
    dte_tier: str = Field(default="short_term", pattern=r"^(short_term|swing|medium_term|long_term)$")
    description: str = ""


class GuardrailConfig(BaseModel):
    """Portfolio-level safety limits."""

    max_total_positions: int = Field(default=12, ge=1, le=50)
    max_positions_per_ticker: int = Field(default=4, ge=1, le=20)
    max_notional_exposure_pct: float = Field(default=0.15, ge=0, le=1.0)
    daily_drawdown_limit_pct: float = Field(default=0.03, ge=0, le=1.0)
    weekly_drawdown_limit_pct: float = Field(default=0.05, ge=0, le=1.0)
    max_same_direction_exposure: int = Field(default=3, ge=1, le=20)
    portfolio_kill_switch_pct: float = Field(default=0.08, ge=0, le=1.0)


class OrchestratorConfig(BaseModel):
    """Top-level orchestrator configuration."""

    portfolio_value: float = Field(default=100000, ge=1000)
    tickers: List[str] = Field(default_factory=lambda: ["SPY", "QQQ", "IWM"])
    guardrails: GuardrailConfig = Field(default_factory=GuardrailConfig)
    agents: Dict[str, AgentConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_capital_allocation(self):
        enabled = {k: v for k, v in self.agents.items() if v.enabled}
        total = sum(a.capital_pct for a in enabled.values())
        if enabled and total > 1.01:
            raise ValueError(
                f"Enabled agents capital_pct sums to {total:.2f}, must be <= 1.0"
            )
        return self


_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "agents.yaml",
)


def load_config(path: Optional[str] = None) -> OrchestratorConfig:
    """Load and validate orchestrator config from YAML."""
    config_path = path or os.getenv("AGENTS_CONFIG", _DEFAULT_CONFIG_PATH)

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    orch_raw = raw.get("orchestrator", {})
    agents_raw = raw.get("agents", {})

    return OrchestratorConfig(
        portfolio_value=orch_raw.get("portfolio_value", 100000),
        tickers=orch_raw.get("tickers", ["SPY", "QQQ", "IWM"]),
        guardrails=GuardrailConfig(**orch_raw.get("guardrails", {})),
        agents={name: AgentConfig(**cfg) for name, cfg in agents_raw.items()},
    )
