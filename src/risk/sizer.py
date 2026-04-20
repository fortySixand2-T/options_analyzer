"""
Position sizing — Kelly criterion and fixed-fractional sizing.

Computes the number of contracts to trade based on account size,
max risk per trade, and expected edge.

Options Analytics Team — 2026-04
"""

import logging
import math
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PositionSize:
    """Position sizing result."""
    contracts: int          # number of contracts to trade
    capital_at_risk: float  # total $ at risk for this position
    risk_pct: float         # % of fund at risk
    method: str             # "kelly" or "fixed_fractional"
    kelly_fraction: Optional[float] = None  # raw Kelly f* (before half-kelly)


def kelly_size(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    fund_size: Optional[float] = None,
    max_loss_per_contract: Optional[float] = None,
    half_kelly: bool = True,
) -> PositionSize:
    """Kelly criterion position sizing.

    Kelly fraction f* = (p * b - q) / b
    where p = win rate, q = 1 - p, b = avg_win / avg_loss ratio.

    Parameters
    ----------
    win_rate : float
        Historical win probability (0 to 1).
    avg_win : float
        Average winning trade P&L (positive).
    avg_loss : float
        Average losing trade P&L (positive magnitude, e.g. 100 not -100).
    fund_size : float, optional
        Total fund size. Reads from OPTIONS_FUND_SIZE env var if not given.
    max_loss_per_contract : float, optional
        Max loss per contract (used to convert dollar allocation to contracts).
    half_kelly : bool
        If True (default), use half-Kelly for safety margin.

    Returns
    -------
    PositionSize
    """
    fund = fund_size or float(os.getenv("OPTIONS_FUND_SIZE", "10000"))
    avg_loss = abs(avg_loss)

    if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
        return PositionSize(
            contracts=0, capital_at_risk=0.0, risk_pct=0.0,
            method="kelly", kelly_fraction=0.0,
        )

    p = win_rate
    q = 1.0 - p
    b = avg_win / avg_loss

    # Kelly fraction
    f_star = (p * b - q) / b

    if f_star <= 0:
        return PositionSize(
            contracts=0, capital_at_risk=0.0, risk_pct=0.0,
            method="kelly", kelly_fraction=f_star,
        )

    if half_kelly:
        f_star *= 0.5

    # Dollar allocation
    allocation = fund * f_star

    # Convert to contracts
    if max_loss_per_contract and max_loss_per_contract > 0:
        contracts = max(1, int(allocation / max_loss_per_contract))
        capital_at_risk = contracts * max_loss_per_contract
    else:
        contracts = 1
        capital_at_risk = allocation

    risk_pct = capital_at_risk / fund * 100 if fund > 0 else 0.0

    return PositionSize(
        contracts=contracts,
        capital_at_risk=round(capital_at_risk, 2),
        risk_pct=round(risk_pct, 2),
        method="kelly",
        kelly_fraction=round(f_star, 4),
    )


def fixed_fractional_size(
    max_risk_pct: Optional[float] = None,
    fund_size: Optional[float] = None,
    max_loss_per_contract: float = 100.0,
) -> PositionSize:
    """Fixed-fractional position sizing.

    Risks a fixed percentage of the fund on each trade.

    Parameters
    ----------
    max_risk_pct : float, optional
        Max risk per trade as a fraction (e.g. 0.02 for 2%).
        Reads from OPTIONS_MAX_RISK_PCT env var if not given.
    fund_size : float, optional
        Total fund size. Reads from OPTIONS_FUND_SIZE env var if not given.
    max_loss_per_contract : float
        Max loss per contract in dollars.

    Returns
    -------
    PositionSize
    """
    fund = fund_size or float(os.getenv("OPTIONS_FUND_SIZE", "10000"))
    risk_pct = max_risk_pct or float(os.getenv("OPTIONS_MAX_RISK_PCT", "0.02"))

    risk_dollars = fund * risk_pct

    if max_loss_per_contract <= 0:
        return PositionSize(
            contracts=0, capital_at_risk=0.0, risk_pct=0.0,
            method="fixed_fractional",
        )

    contracts = max(1, int(risk_dollars / max_loss_per_contract))
    capital_at_risk = contracts * max_loss_per_contract
    actual_risk_pct = capital_at_risk / fund * 100 if fund > 0 else 0.0

    return PositionSize(
        contracts=contracts,
        capital_at_risk=round(capital_at_risk, 2),
        risk_pct=round(actual_risk_pct, 2),
        method="fixed_fractional",
    )


def compute_position_size(
    strategy_result=None,
    backtest_stats=None,
    max_loss_per_contract: Optional[float] = None,
    fund_size: Optional[float] = None,
    method: str = "auto",
) -> PositionSize:
    """Compute position size using the best available method.

    If backtest stats are available with sufficient trades, uses Kelly.
    Otherwise falls back to fixed-fractional.

    Parameters
    ----------
    strategy_result : StrategyResult, optional
        Strategy evaluation result (used for max_loss estimate).
    backtest_stats : BacktestStats, optional
        Historical backtest stats (win_rate, avg_win, avg_loss).
    max_loss_per_contract : float, optional
        Override max loss per contract. If None, derived from strategy_result.
    fund_size : float, optional
        Override fund size.
    method : str
        "kelly", "fixed", or "auto" (default).

    Returns
    -------
    PositionSize
    """
    fund = fund_size or float(os.getenv("OPTIONS_FUND_SIZE", "10000"))

    # Derive max loss from strategy if available
    if max_loss_per_contract is None and strategy_result is not None:
        if strategy_result.max_loss is not None:
            max_loss_per_contract = abs(strategy_result.max_loss)
        elif strategy_result.entry > 0:
            # For credit strategies, max loss ≈ spread width - credit
            # For debit strategies, max loss = debit paid
            max_loss_per_contract = strategy_result.entry * 100  # per contract
    if max_loss_per_contract is None:
        max_loss_per_contract = 100.0  # conservative default

    use_kelly = method == "kelly" or (
        method == "auto"
        and backtest_stats is not None
        and backtest_stats.total_trades >= 30
        and backtest_stats.win_rate > 0
    )

    if use_kelly and backtest_stats is not None:
        return kelly_size(
            win_rate=backtest_stats.win_rate / 100.0,
            avg_win=abs(backtest_stats.avg_win),
            avg_loss=abs(backtest_stats.avg_loss),
            fund_size=fund,
            max_loss_per_contract=max_loss_per_contract,
        )

    return fixed_fractional_size(
        fund_size=fund,
        max_loss_per_contract=max_loss_per_contract,
    )
