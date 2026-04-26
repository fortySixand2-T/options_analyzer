"""
Portfolio Engine — Layer 4 of the trading system.

Manages concurrent positions with portfolio-level constraints:
    1. Position limits (total and per-symbol)
    2. Greeks limits (delta, gamma, theta, vega)
    3. Correlation-aware risk aggregation
    4. Dynamic hedge triggers

The difference between a screener and a trading system.

Options Analytics Team — 2026-04
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Position ──────────────────────────────────────────────────────────────────

@dataclass
class Position:
    """A single open position in the portfolio."""
    position_id: str
    symbol: str
    strategy: str
    contracts: int
    entry_price: float          # net premium per contract
    is_credit: bool
    max_loss: float             # max loss for entire position
    entry_time: datetime

    # Current Greeks (per contract, scaled by contracts)
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0

    # Current P&L
    current_price: float = 0.0
    unrealized_pnl: float = 0.0

    # Exit parameters
    profit_target: float = 0.0
    stop_loss: float = 0.0
    dte_remaining: int = 0

    def update_greeks(self, delta: float, gamma: float,
                      theta: float, vega: float):
        """Update position Greeks (total for all contracts)."""
        self.delta = delta * self.contracts
        self.gamma = gamma * self.contracts
        self.theta = theta * self.contracts
        self.vega = vega * self.contracts

    def update_pnl(self, current_price: float):
        """Update unrealized P&L from current mid price."""
        self.current_price = current_price
        if self.is_credit:
            # Credit: profit = entry - current (collected premium erodes)
            self.unrealized_pnl = (self.entry_price - current_price) * self.contracts * 100
        else:
            # Debit: profit = current - entry
            self.unrealized_pnl = (current_price - self.entry_price) * self.contracts * 100

    def to_dict(self) -> dict:
        return {
            "position_id": self.position_id,
            "symbol": self.symbol,
            "strategy": self.strategy,
            "contracts": self.contracts,
            "entry_price": round(self.entry_price, 2),
            "is_credit": self.is_credit,
            "max_loss": round(self.max_loss, 2),
            "entry_time": self.entry_time.isoformat(),
            "delta": round(self.delta, 2),
            "gamma": round(self.gamma, 4),
            "theta": round(self.theta, 2),
            "vega": round(self.vega, 2),
            "current_price": round(self.current_price, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "dte_remaining": self.dte_remaining,
        }


# ── Portfolio limits ──────────────────────────────────────────────────────────

@dataclass
class PortfolioLimits:
    """Configurable portfolio-level constraints."""
    max_positions: int = 5
    max_per_symbol: int = 2
    max_delta: float = 50.0         # absolute portfolio delta
    max_gamma: float = 20.0         # absolute portfolio gamma
    max_theta: float = -200.0       # minimum daily theta (most negative allowed)
    max_vega: float = 300.0         # max absolute vega exposure
    max_risk: float = 10_000.0      # max capital at risk across all positions
    max_risk_pct: float = 0.10      # max % of portfolio at risk


# ── Portfolio ─────────────────────────────────────────────────────────────────

@dataclass
class Portfolio:
    """Portfolio engine — tracks positions and enforces constraints."""
    limits: PortfolioLimits = field(default_factory=PortfolioLimits)
    positions: List[Position] = field(default_factory=list)
    portfolio_value: float = 100_000.0

    # ── Aggregate metrics ─────────────────────────────────────────────────

    @property
    def net_delta(self) -> float:
        return sum(p.delta for p in self.positions)

    @property
    def net_gamma(self) -> float:
        return sum(p.gamma for p in self.positions)

    @property
    def net_theta(self) -> float:
        return sum(p.theta for p in self.positions)

    @property
    def net_vega(self) -> float:
        return sum(p.vega for p in self.positions)

    @property
    def total_risk(self) -> float:
        return sum(p.max_loss for p in self.positions)

    @property
    def total_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.positions)

    @property
    def position_count(self) -> int:
        return len(self.positions)

    def positions_for_symbol(self, symbol: str) -> List[Position]:
        return [p for p in self.positions if p.symbol == symbol]

    # ── Constraint checking ───────────────────────────────────────────────

    def can_add(self, symbol: str, strategy: str, max_loss: float,
                delta: float = 0.0, gamma: float = 0.0,
                theta: float = 0.0, vega: float = 0.0) -> Tuple[bool, str]:
        """Check if adding a position would violate any portfolio constraint.

        Returns (ok, reason).
        """
        if self.position_count >= self.limits.max_positions:
            return False, f"max positions ({self.limits.max_positions}) reached"

        sym_count = len(self.positions_for_symbol(symbol))
        if sym_count >= self.limits.max_per_symbol:
            return False, f"max positions for {symbol} ({self.limits.max_per_symbol})"

        new_delta = self.net_delta + delta
        if abs(new_delta) > self.limits.max_delta:
            return False, f"delta would be {new_delta:+.0f} (limit {self.limits.max_delta})"

        new_gamma = self.net_gamma + gamma
        if abs(new_gamma) > self.limits.max_gamma:
            return False, f"gamma would be {new_gamma:+.1f} (limit {self.limits.max_gamma})"

        new_theta = self.net_theta + theta
        if new_theta < self.limits.max_theta:
            return False, f"theta would be {new_theta:+.0f} (limit {self.limits.max_theta})"

        new_vega = self.net_vega + vega
        if abs(new_vega) > self.limits.max_vega:
            return False, f"vega would be {new_vega:+.0f} (limit {self.limits.max_vega})"

        new_risk = self.total_risk + max_loss
        if new_risk > self.limits.max_risk:
            return False, f"total risk would be ${new_risk:,.0f} (limit ${self.limits.max_risk:,.0f})"

        risk_pct = new_risk / self.portfolio_value if self.portfolio_value > 0 else 1.0
        if risk_pct > self.limits.max_risk_pct:
            return False, f"risk would be {risk_pct:.1%} of portfolio (limit {self.limits.max_risk_pct:.0%})"

        return True, "ok"

    # ── Position management ───────────────────────────────────────────────

    def add_position(self, position: Position) -> Tuple[bool, str]:
        """Add a position after constraint check."""
        ok, reason = self.can_add(
            symbol=position.symbol,
            strategy=position.strategy,
            max_loss=position.max_loss,
            delta=position.delta,
            gamma=position.gamma,
            theta=position.theta,
            vega=position.vega,
        )
        if not ok:
            return False, reason
        self.positions.append(position)
        return True, "ok"

    def remove_position(self, position_id: str) -> Optional[Position]:
        """Remove a position by ID. Returns the removed position or None."""
        for i, p in enumerate(self.positions):
            if p.position_id == position_id:
                return self.positions.pop(i)
        return None

    # ── Correlation-aware risk ────────────────────────────────────────────

    def correlated_risk(self, correlation: float = 0.7) -> float:
        """Worst-case portfolio loss accounting for correlation.

        SPY/QQQ/IWM average correlation is ~0.7.
        3 independent $1000 risks = $1732 correlated risk (sqrt of sum of squares).
        3 correlated $1000 risks = $2510 correlated risk.
        """
        risks = [p.max_loss for p in self.positions]
        if not risks:
            return 0.0

        n = len(risks)
        # Variance = sum(r_i^2) + 2*rho * sum(r_i * r_j for i<j)
        var = sum(r ** 2 for r in risks)
        cross = sum(
            risks[i] * risks[j]
            for i in range(n) for j in range(i + 1, n)
        )
        var += 2 * correlation * cross
        return math.sqrt(max(0, var))

    # ── Hedge triggers ────────────────────────────────────────────────────

    def hedge_triggers(self) -> List[Dict]:
        """Check portfolio Greeks against limits and suggest hedges.

        Returns list of {trigger, action, urgency} dicts.
        """
        triggers = []
        delta = self.net_delta

        if delta > 30:
            triggers.append({
                "trigger": f"Portfolio delta {delta:+.0f} > +30",
                "action": "Buy put spread or sell call spread to reduce delta",
                "urgency": "high" if delta > 40 else "medium",
            })
        elif delta < -30:
            triggers.append({
                "trigger": f"Portfolio delta {delta:+.0f} < -30",
                "action": "Buy call spread or sell put spread to reduce delta",
                "urgency": "high" if delta < -40 else "medium",
            })

        vega = self.net_vega
        if abs(vega) > 150:
            triggers.append({
                "trigger": f"Portfolio vega {vega:+.0f} exceeds 150",
                "action": "Reduce long premium positions" if vega > 0
                          else "Reduce short premium positions",
                "urgency": "medium",
            })

        theta = self.net_theta
        if theta < -150:
            triggers.append({
                "trigger": f"Portfolio theta {theta:+.0f} below -150",
                "action": "Reduce time-decaying positions or add theta-positive trades",
                "urgency": "medium",
            })

        return triggers

    # ── Serialization ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        corr_risk = self.correlated_risk()
        return {
            "positions": [p.to_dict() for p in self.positions],
            "position_count": self.position_count,
            "portfolio_value": round(self.portfolio_value, 2),
            "greeks": {
                "net_delta": round(self.net_delta, 2),
                "net_gamma": round(self.net_gamma, 4),
                "net_theta": round(self.net_theta, 2),
                "net_vega": round(self.net_vega, 2),
            },
            "risk": {
                "total_risk": round(self.total_risk, 2),
                "correlated_risk": round(corr_risk, 2),
                "risk_pct": round(self.total_risk / self.portfolio_value * 100, 1)
                            if self.portfolio_value > 0 else 0,
                "available_risk": round(
                    max(0, self.limits.max_risk - self.total_risk), 2
                ),
            },
            "pnl": {
                "total_unrealized": round(self.total_pnl, 2),
            },
            "limits": {
                "max_positions": self.limits.max_positions,
                "max_per_symbol": self.limits.max_per_symbol,
                "max_delta": self.limits.max_delta,
                "max_risk": self.limits.max_risk,
            },
            "hedge_triggers": self.hedge_triggers(),
        }
