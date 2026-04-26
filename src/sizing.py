"""
Execution & Sizing — Layer 3 of the trading system.

Takes TradeCandidate (L2) and produces sized, fill-adjusted trade orders.

Responsibilities:
    1. Kelly criterion position sizing (half-Kelly, capped)
    2. Slippage and fill modeling
    3. Spread cost analysis
    4. Go/no-go execution check

The Kelly fractions are derived from backtest win rates per strategy.
Negative Kelly = no edge — those strategies are blocked.

Options Analytics Team — 2026-04
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Backtest-derived stats per strategy ───────────────────────────────────────
# Updated 2026-04-26 from 6 validation backtests: SPY 2022-2026, 3% slippage,
# per-strategy exit rules, with optimal filter configurations.
#
# Key finding: strategy viability depends heavily on filter + exit rule combo.
# Stats below use each strategy's best validated configuration:
#   - butterfly:          strategy exits, no filters needed      (Sharpe 2.09)
#   - long_put_spread:    strategy exits + GARCH edge > 5%       (Sharpe 3.38)
#   - long_call_spread:   strategy exits + regime filter         (Sharpe 2.07)
#   - short_put_spread:   strategy exits + GARCH edge > 5%       (Sharpe 1.14)
#   - iron_condor:        negative in all configs                (Sharpe -2.39)
#   - short_call_spread:  negative in all configs                (Sharpe -0.81)

@dataclass(frozen=True)
class StrategyStats:
    """Historical performance stats for Kelly sizing."""
    win_rate: float         # 0-1
    avg_win: float          # dollars per contract
    avg_loss: float         # dollars per contract (positive number)
    kelly: float            # raw Kelly fraction
    tradeable: bool         # is the edge positive?

STRATEGY_STATS: Dict[str, StrategyStats] = {
    "iron_condor": StrategyStats(
        win_rate=0.422, avg_win=85, avg_loss=197,
        kelly=-0.47, tradeable=False,
    ),
    "short_put_spread": StrategyStats(
        win_rate=0.804, avg_win=77, avg_loss=212,
        kelly=0.26, tradeable=True,   # requires GARCH edge > 5%
    ),
    "short_call_spread": StrategyStats(
        win_rate=0.667, avg_win=80, avg_loss=237,
        kelly=-0.09, tradeable=False,
    ),
    "long_call_spread": StrategyStats(
        win_rate=0.598, avg_win=176, avg_loss=140,
        kelly=0.28, tradeable=True,   # benefits from regime filter
    ),
    "long_put_spread": StrategyStats(
        win_rate=0.625, avg_win=206, avg_loss=127,
        kelly=0.39, tradeable=True,   # requires GARCH edge > 5%
    ),
    "butterfly": StrategyStats(
        win_rate=0.506, avg_win=869, avg_loss=354,
        kelly=0.30, tradeable=True,
    ),
}


# ── Kelly sizing ──────────────────────────────────────────────────────────────

def kelly_fraction(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
) -> float:
    """Compute Kelly criterion fraction.

    f* = (p * b - q) / b
    where p = win_rate, q = 1-p, b = avg_win / avg_loss

    Returns raw Kelly fraction (can be negative = no edge).
    """
    if avg_loss <= 0 or avg_win <= 0:
        return 0.0
    b = avg_win / avg_loss
    p = win_rate
    q = 1.0 - p
    return (p * b - q) / b


def compute_position_size(
    strategy: str,
    portfolio_value: float,
    max_loss_per_contract: float,
    confluence_score: float = 70.0,
    max_risk_pct: float = 0.02,
) -> "SizeResult":
    """Compute position size using half-Kelly, capped at max risk.

    Parameters
    ----------
    strategy : str
        Strategy name for stats lookup.
    portfolio_value : float
        Total portfolio value.
    max_loss_per_contract : float
        Max loss per single contract of this spread.
    confluence_score : float
        L2 confluence score (0-100). Scales sizing linearly.
    max_risk_pct : float
        Hard cap on portfolio risk per trade (default 2%).

    Returns
    -------
    SizeResult with contracts, risk_dollars, kelly details.
    """
    stats = STRATEGY_STATS.get(strategy)
    if stats is None:
        return SizeResult(
            contracts=0, reason="Unknown strategy",
            kelly_raw=0, kelly_half=0, risk_pct=0, risk_dollars=0,
        )

    if not stats.tradeable:
        return SizeResult(
            contracts=0, reason=f"Negative expectancy (Kelly={stats.kelly:.2f})",
            kelly_raw=stats.kelly, kelly_half=0, risk_pct=0, risk_dollars=0,
        )

    # Raw Kelly from backtest stats
    k = kelly_fraction(stats.win_rate, stats.avg_win, stats.avg_loss)
    if k <= 0:
        return SizeResult(
            contracts=0, reason=f"No edge (Kelly={k:.2f})",
            kelly_raw=k, kelly_half=0, risk_pct=0, risk_dollars=0,
        )

    # Half-Kelly (standard practice — accounts for estimation error)
    half_k = k / 2.0

    # Scale by confluence score (higher conviction → closer to half-Kelly)
    # Score 60 = minimum, 100 = full half-Kelly
    score_scale = max(0.0, min(1.0, (confluence_score - 60) / 40.0))
    adjusted_k = half_k * score_scale

    # Cap at max risk
    risk_pct = min(adjusted_k, max_risk_pct)

    # Convert to dollar risk and contracts
    risk_dollars = portfolio_value * risk_pct
    if max_loss_per_contract <= 0:
        contracts = 0
    else:
        contracts = max(1, int(risk_dollars / max_loss_per_contract))

    # Double-check: actual risk shouldn't exceed cap
    actual_risk = contracts * max_loss_per_contract
    if actual_risk > portfolio_value * max_risk_pct:
        contracts = max(1, int(portfolio_value * max_risk_pct / max_loss_per_contract))

    return SizeResult(
        contracts=contracts,
        reason="ok",
        kelly_raw=round(k, 4),
        kelly_half=round(half_k, 4),
        risk_pct=round(risk_pct, 4),
        risk_dollars=round(contracts * max_loss_per_contract, 2),
    )


@dataclass
class SizeResult:
    """Position sizing output."""
    contracts: int
    reason: str
    kelly_raw: float = 0.0
    kelly_half: float = 0.0
    risk_pct: float = 0.0
    risk_dollars: float = 0.0

    def to_dict(self) -> dict:
        return {
            "contracts": self.contracts,
            "reason": self.reason,
            "kelly_raw": self.kelly_raw,
            "kelly_half": self.kelly_half,
            "risk_pct": self.risk_pct,
            "risk_dollars": self.risk_dollars,
        }


# ── Execution / slippage model ────────────────────────────────────────────────

@dataclass
class ExecutionModel:
    """Models fill quality and spread cost for options trades.

    At short DTE, spread cost is a huge fraction of premium.
    A $5-wide SPY credit spread at 7 DTE might have mid $1.20.
    Natural fill = $1.15 (give up $0.05). That's 4% of premium.
    """
    slippage_pct: float = 0.03       # 3% of premium (conservative)
    tick_size: float = 0.01          # penny increments
    max_spread_pct: float = 0.10     # reject if bid-ask > 10% of mid

    def adjusted_entry(self, mid: float, is_credit: bool) -> float:
        """Compute fill price after slippage.

        Credit: collect less (mid - slippage).
        Debit: pay more (mid + slippage).
        """
        slip = abs(mid) * self.slippage_pct
        slip = max(slip, self.tick_size)  # at least 1 tick

        if is_credit:
            return round(mid - slip, 2)
        else:
            return round(mid + slip, 2)

    def spread_cost(self, bid: float, ask: float) -> float:
        """Compute spread cost as fraction of mid."""
        mid = (bid + ask) / 2.0
        if mid <= 0:
            return float('inf')
        return (ask - bid) / mid

    def is_executable(self, bid: float, ask: float) -> Tuple[bool, str]:
        """Check if the spread is tight enough to execute."""
        if bid <= 0:
            return False, "no bid"
        cost = self.spread_cost(bid, ask)
        if cost > self.max_spread_pct:
            return False, f"spread too wide ({cost:.1%} > {self.max_spread_pct:.0%})"
        return True, "ok"


# ── Execution check ──────────────────────────────────────────────────────────

@dataclass
class ExecutionResult:
    """Full execution assessment for a trade candidate."""
    executable: bool
    reason: str
    size: SizeResult
    adjusted_entry: Optional[float] = None
    slippage_cost: float = 0.0
    spread_cost_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            "executable": self.executable,
            "reason": self.reason,
            "size": self.size.to_dict(),
            "adjusted_entry": self.adjusted_entry,
            "slippage_cost": round(self.slippage_cost, 4),
            "spread_cost_pct": round(self.spread_cost_pct, 4),
        }


def assess_execution(
    trade_candidate,
    portfolio_value: float = 100_000.0,
    max_risk_pct: float = 0.02,
    execution_model: Optional[ExecutionModel] = None,
    mid_price: Optional[float] = None,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
) -> ExecutionResult:
    """Assess whether a trade candidate should be executed and at what size.

    Combines:
        1. Strategy-level Kelly sizing
        2. Spread cost check
        3. Fill-adjusted entry price

    Parameters
    ----------
    trade_candidate : TradeCandidate
        From L2 trade generator.
    portfolio_value : float
        Total portfolio value for sizing.
    max_risk_pct : float
        Max portfolio risk per trade.
    execution_model : ExecutionModel, optional
        Custom execution params (default: standard model).
    mid_price : float, optional
        Net mid price for the spread. If None, uses approximate from legs.
    bid, ask : float, optional
        Bid/ask for spread cost check.

    Returns
    -------
    ExecutionResult
    """
    if execution_model is None:
        execution_model = ExecutionModel()

    strategy = trade_candidate.strategy
    is_credit = trade_candidate.is_credit

    # 1. Check executability from spread width
    spread_cost_pct = 0.0
    if bid is not None and ask is not None:
        ok, reason = execution_model.is_executable(bid, ask)
        if not ok:
            return ExecutionResult(
                executable=False, reason=reason,
                size=SizeResult(contracts=0, reason=reason),
                spread_cost_pct=execution_model.spread_cost(bid, ask),
            )
        spread_cost_pct = execution_model.spread_cost(bid, ask)

    # 2. Compute position size
    # Estimate max loss from spread width
    legs = trade_candidate.legs
    strikes = [leg["strike"] for leg in legs]
    if len(strikes) >= 2:
        width = max(strikes) - min(strikes)
        max_loss_per_contract = width * 100  # standard multiplier
    else:
        max_loss_per_contract = 500  # fallback

    size = compute_position_size(
        strategy=strategy,
        portfolio_value=portfolio_value,
        max_loss_per_contract=max_loss_per_contract,
        confluence_score=trade_candidate.confluence_score,
        max_risk_pct=max_risk_pct,
    )

    if size.contracts == 0:
        return ExecutionResult(
            executable=False, reason=size.reason,
            size=size, spread_cost_pct=spread_cost_pct,
        )

    # 3. Compute fill-adjusted entry
    adjusted = None
    slippage = 0.0
    if mid_price is not None:
        adjusted = execution_model.adjusted_entry(mid_price, is_credit)
        slippage = abs(mid_price - adjusted)

    return ExecutionResult(
        executable=True,
        reason="ok",
        size=size,
        adjusted_entry=adjusted,
        slippage_cost=slippage,
        spread_cost_pct=spread_cost_pct,
    )
