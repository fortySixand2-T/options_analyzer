"""Advanced Greeks endpoints — Monte Carlo forward simulation and multi-leg payoff diagrams."""

import numpy as np
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.auth.dependencies import get_current_user

router = APIRouter(prefix="/api/greeks", tags=["greeks"])


class MonteCarloRequest(BaseModel):
    spot: float
    iv: float
    r: float = 0.05
    days_forward: int = 30
    num_paths: int = 5000
    percentiles: List[float] = [5, 25, 50, 75, 95]


class PayoffLeg(BaseModel):
    strike: float
    option_type: str  # call or put
    position: str  # long or short
    premium: float = 0.0
    contracts: int = 1


class PayoffRequest(BaseModel):
    spot: float
    legs: List[PayoffLeg]
    price_range_pct: float = 15.0
    num_points: int = 100


@router.post("/monte-carlo-forward")
def monte_carlo_forward(req: MonteCarloRequest, _user: dict = Depends(get_current_user)):
    """Simulate forward price distribution using GBM paths.

    Returns percentile fan data for charting (price cones at various confidence levels).
    """
    from monte_carlo.gbm_simulator import simulate_gbm_paths
    from monte_carlo.risk_metrics import compute_var

    T = req.days_forward / 365.0
    num_steps = max(req.days_forward, 30)

    paths = simulate_gbm_paths(
        S0=req.spot, r=req.r, sigma=req.iv,
        T=T, num_paths=req.num_paths, num_steps=num_steps, seed=42,
    )

    # Build fan chart data: for each time step, compute percentiles
    step_size = max(1, num_steps // 30)  # ~30 points for the chart
    fan = []
    for step in range(0, num_steps + 1, step_size):
        day = round(step / num_steps * req.days_forward)
        prices_at_step = paths[:, min(step, paths.shape[1] - 1)]
        point = {"day": day}
        for pct in req.percentiles:
            point[f"p{int(pct)}"] = round(float(np.percentile(prices_at_step, pct)), 2)
        fan.append(point)

    # Terminal distribution stats
    terminal = paths[:, -1]
    var_95 = compute_var(terminal - req.spot, confidence=0.95)

    return {
        "fan": fan,
        "terminal": {
            "mean": round(float(np.mean(terminal)), 2),
            "median": round(float(np.median(terminal)), 2),
            "std": round(float(np.std(terminal)), 2),
            "min": round(float(np.min(terminal)), 2),
            "max": round(float(np.max(terminal)), 2),
            "var_95": round(float(var_95), 2),
        },
        "inputs": {
            "spot": req.spot,
            "iv": req.iv,
            "days": req.days_forward,
            "paths": req.num_paths,
        },
    }


@router.post("/payoff-diagram")
def payoff_diagram(req: PayoffRequest, _user: dict = Depends(get_current_user)):
    """Compute multi-leg option payoff diagram at expiration.

    Returns array of {price, pnl} points for charting.
    """
    low = req.spot * (1 - req.price_range_pct / 100)
    high = req.spot * (1 + req.price_range_pct / 100)
    prices = np.linspace(low, high, req.num_points)

    payoffs = np.zeros(req.num_points)

    for leg in req.legs:
        mult = leg.contracts * 100
        sign = 1 if leg.position == "long" else -1

        for i, price in enumerate(prices):
            if leg.option_type == "call":
                intrinsic = max(price - leg.strike, 0)
            else:
                intrinsic = max(leg.strike - price, 0)

            leg_pnl = sign * (intrinsic - leg.premium) * mult
            payoffs[i] += leg_pnl

    # Find breakevens
    breakevens = []
    for i in range(len(payoffs) - 1):
        if payoffs[i] * payoffs[i + 1] < 0:
            # Linear interpolation
            ratio = abs(payoffs[i]) / (abs(payoffs[i]) + abs(payoffs[i + 1]))
            be_price = prices[i] + ratio * (prices[i + 1] - prices[i])
            breakevens.append(round(float(be_price), 2))

    max_profit = float(np.max(payoffs))
    max_loss = float(np.min(payoffs))

    points = [
        {"price": round(float(p), 2), "pnl": round(float(pnl), 2)}
        for p, pnl in zip(prices, payoffs)
    ]

    return {
        "points": points,
        "breakevens": breakevens,
        "max_profit": round(max_profit, 2),
        "max_loss": round(max_loss, 2),
        "spot": req.spot,
    }
