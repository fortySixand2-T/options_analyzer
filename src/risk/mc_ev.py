"""
MC-based expected value calculator for multi-leg option positions.

Uses the existing monte_carlo/ engine to simulate underlying paths,
then computes P&L for each leg at expiry to get probability of profit,
expected value, and risk metrics for the full position.

Options Analytics Team — 2026-04
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from models.black_scholes import black_scholes_price
from monte_carlo.gbm_simulator import simulate_gbm_paths, simulate_garch_paths
from monte_carlo.risk_metrics import compute_var, compute_cvar, compute_distribution_stats
from config import RISK_FREE_RATE, MC_NUM_PATHS, MC_NUM_STEPS, MC_SEED

logger = logging.getLogger(__name__)


@dataclass
class LegSpec:
    """Single leg specification for a multi-leg position."""
    action: str         # "buy" or "sell"
    option_type: str    # "call" or "put"
    strike: float
    quantity: int = 1


@dataclass
class PositionEV:
    """MC-based expected value result for a multi-leg position."""
    expected_value: float       # mean P&L per contract group
    prob_profit: float          # probability of profit (0-1)
    prob_max_profit: float      # probability of achieving max profit
    max_profit: float           # theoretical max profit
    max_loss: float             # theoretical max loss
    var_95: float               # 95% VaR
    cvar_95: float              # 95% CVaR (Expected Shortfall)
    percentiles: Dict[str, float]
    breakevens: List[float]     # breakeven underlying prices
    pnl_distribution: Optional[np.ndarray] = None  # raw P&L array


def compute_multi_leg_ev(
    spot: float,
    legs: List[LegSpec],
    iv: float,
    dte: int,
    entry_net: float,
    is_credit: bool,
    r: Optional[float] = None,
    num_paths: Optional[int] = None,
    num_steps: Optional[int] = None,
    seed: Optional[int] = None,
    use_garch: bool = False,
    historical_returns: Optional[np.ndarray] = None,
) -> PositionEV:
    """Compute expected value for a multi-leg option position via MC simulation.

    Parameters
    ----------
    spot : float
        Current underlying price.
    legs : List[LegSpec]
        Legs of the position.
    iv : float
        Implied volatility (annualized).
    dte : int
        Days to expiration.
    entry_net : float
        Net premium at entry (positive = credit received, for credit strategies).
    is_credit : bool
        True if this is a credit strategy (premium received at entry).
    r : float, optional
        Risk-free rate (default: from config).
    num_paths, num_steps, seed : int, optional
        MC simulation parameters (defaults from config).
    use_garch : bool
        Use GARCH vol paths instead of constant vol.
    historical_returns : np.ndarray, optional
        Required if use_garch=True.

    Returns
    -------
    PositionEV
    """
    r = r if r is not None else RISK_FREE_RATE
    num_paths = num_paths or MC_NUM_PATHS
    num_steps = num_steps or MC_NUM_STEPS
    seed = seed if seed is not None else MC_SEED

    T = max(dte / 365.0, 1 / 365.0)

    # Simulate underlying price paths
    if use_garch and historical_returns is not None and len(historical_returns) >= 30:
        from monte_carlo.garch_vol import fit_garch11
        garch = fit_garch11(historical_returns)
        paths = simulate_garch_paths(
            spot, r,
            garch["omega"], garch["alpha"], garch["beta"], garch["sigma0"],
            T, num_paths, num_steps, seed,
        )
    else:
        paths = simulate_gbm_paths(spot, r, iv, T, num_paths, num_steps, seed)

    # Terminal underlying prices
    S_T = paths[:, -1]

    # Compute payoff at expiry for each leg
    position_payoff = np.zeros(num_paths)
    for leg in legs:
        sign = 1.0 if leg.action == "buy" else -1.0
        qty = leg.quantity

        if leg.option_type == "call":
            leg_payoff = np.maximum(S_T - leg.strike, 0.0)
        else:
            leg_payoff = np.maximum(leg.strike - S_T, 0.0)

        position_payoff += sign * qty * leg_payoff

    # P&L = payoff at expiry - entry cost (or + credit received)
    # For credit: entry_net is positive (premium received), P&L = entry_net - payoff_cost
    # For debit: entry_net is the debit paid, P&L = payoff - entry_net
    if is_credit:
        pnl = entry_net + position_payoff  # position_payoff is net payoff (sell legs negative)
    else:
        pnl = position_payoff - entry_net

    # Per-contract P&L (multiply by 100 for standard equity options)
    pnl_per_contract = pnl * 100

    ev = float(np.mean(pnl_per_contract))
    prob_profit = float(np.mean(pnl_per_contract > 0))

    # Max profit/loss (theoretical)
    max_profit_theoretical = float(np.max(pnl_per_contract))
    max_loss_theoretical = float(np.min(pnl_per_contract))

    # Probability of achieving near-max profit (within 90% of max)
    if max_profit_theoretical > 0:
        prob_max = float(np.mean(pnl_per_contract >= 0.9 * max_profit_theoretical))
    else:
        prob_max = 0.0

    # Risk metrics
    var_95 = compute_var(pnl_per_contract, 0.95)
    cvar_95 = compute_cvar(pnl_per_contract, 0.95)
    percentiles = compute_distribution_stats(pnl_per_contract)

    # Breakevens: find where P&L crosses zero
    breakevens = _find_breakevens(legs, entry_net, is_credit, spot)

    return PositionEV(
        expected_value=round(ev, 2),
        prob_profit=round(prob_profit, 4),
        prob_max_profit=round(prob_max, 4),
        max_profit=round(max_profit_theoretical, 2),
        max_loss=round(max_loss_theoretical, 2),
        var_95=round(var_95, 2),
        cvar_95=round(cvar_95, 2),
        percentiles=percentiles,
        breakevens=[round(b, 2) for b in breakevens],
        pnl_distribution=pnl_per_contract,
    )


def _find_breakevens(
    legs: List[LegSpec],
    entry_net: float,
    is_credit: bool,
    spot: float,
) -> List[float]:
    """Find approximate breakeven prices by scanning a range.

    Evaluates the position payoff across a grid of underlying prices
    and finds zero-crossings.
    """
    strikes = [leg.strike for leg in legs]
    low = min(strikes) * 0.85
    high = max(strikes) * 1.15
    prices = np.linspace(low, high, 1000)

    payoffs = np.zeros_like(prices)
    for leg in legs:
        sign = 1.0 if leg.action == "buy" else -1.0
        qty = leg.quantity
        if leg.option_type == "call":
            payoffs += sign * qty * np.maximum(prices - leg.strike, 0.0)
        else:
            payoffs += sign * qty * np.maximum(leg.strike - prices, 0.0)

    if is_credit:
        pnl = entry_net + payoffs
    else:
        pnl = payoffs - entry_net

    # Find zero crossings
    breakevens = []
    for i in range(len(pnl) - 1):
        if pnl[i] * pnl[i + 1] < 0:
            # Linear interpolation
            frac = abs(pnl[i]) / (abs(pnl[i]) + abs(pnl[i + 1]))
            be = prices[i] + frac * (prices[i + 1] - prices[i])
            breakevens.append(float(be))

    return breakevens


def compute_strategy_ev(
    strategy_result,
    spot: float,
    iv: float,
    r: Optional[float] = None,
    num_paths: Optional[int] = None,
    use_garch: bool = False,
    historical_returns: Optional[np.ndarray] = None,
) -> Optional[PositionEV]:
    """Compute MC-based EV for a StrategyResult.

    Convenience wrapper that converts StrategyResult.legs into LegSpec list
    and calls compute_multi_leg_ev.

    Parameters
    ----------
    strategy_result : StrategyResult
        Evaluated strategy with legs.
    spot : float
        Current underlying price.
    iv : float
        Implied vol.
    r, num_paths, use_garch, historical_returns:
        Passed through to compute_multi_leg_ev.

    Returns
    -------
    PositionEV or None if legs can't be parsed.
    """
    if not strategy_result.legs:
        return None

    legs = []
    for leg_dict in strategy_result.legs:
        try:
            legs.append(LegSpec(
                action=leg_dict.get("action", "buy"),
                option_type=leg_dict.get("option_type", "call"),
                strike=float(leg_dict.get("strike", 0)),
                quantity=int(leg_dict.get("quantity", 1)),
            ))
        except (ValueError, TypeError):
            continue

    if not legs:
        return None

    return compute_multi_leg_ev(
        spot=spot,
        legs=legs,
        iv=iv,
        dte=strategy_result.suggested_dte,
        entry_net=abs(strategy_result.entry),
        is_credit=strategy_result.is_credit,
        r=r,
        num_paths=num_paths,
        use_garch=use_garch,
        historical_returns=historical_returns,
    )
