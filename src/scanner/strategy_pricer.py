"""
Strategy pricer for chain scanner recommendations.

Resolves abstract legs to concrete strikes, prices via BS, computes
net premium/Greeks/stops/targets, and runs MC for probability of profit.

Options Analytics Team — 2026-04
"""

import logging
from typing import List, Optional

import numpy as np

from models.black_scholes import black_scholes_price, calculate_greeks
from monte_carlo.gbm_simulator import run_monte_carlo

from config import (
    MC_NUM_PATHS, MC_NUM_STEPS, MC_SEED, RISK_FREE_RATE,
)
from . import OptionSignal
from .strategy_mapper import StrategyRecommendation
from .providers.flashalpha_client import DealerData

logger = logging.getLogger(__name__)

# Credit strategies: sell for a net credit
_CREDIT_STRATEGIES = {"short_put_spread", "short_call_spread", "iron_condor"}


def _round_strike(price: float) -> float:
    """Round to the nearest standard strike increment."""
    if price >= 100:
        return round(price / 5) * 5
    if price >= 50:
        return round(price / 2.5) * 2.5
    return round(price)


def _strike_increment(spot: float) -> float:
    """Standard strike increment based on underlying price."""
    if spot >= 100:
        return 5.0
    if spot >= 50:
        return 2.5
    return 1.0


def _classify_credit(strategy: str) -> bool:
    """Return True if the strategy receives a net credit."""
    return strategy in _CREDIT_STRATEGIES


def _resolve_strikes(
    signal: OptionSignal,
    recommendation: StrategyRecommendation,
    dealer_data: Optional[DealerData] = None,
) -> List[dict]:
    """Convert abstract strike_method references to concrete leg dicts.

    Uses GEX walls (call_wall/put_wall) and max_pain from dealer_data
    for intelligent strike placement when available:
    - call_wall → upper bound for short call strikes
    - put_wall → lower bound for short put strikes
    - max_pain → center for butterfly strategies
    """
    width = _strike_increment(signal.spot)
    atm = _round_strike(signal.spot)

    # Use dealer data for strike anchoring when available
    call_wall = _round_strike(dealer_data.call_wall) if dealer_data and dealer_data.call_wall else None
    put_wall = _round_strike(dealer_data.put_wall) if dealer_data and dealer_data.put_wall else None
    max_pain = _round_strike(dealer_data.max_pain) if dealer_data and dealer_data.max_pain else None

    legs = []

    for leg_template in recommendation.legs:
        method = leg_template["strike_method"]
        action = leg_template["action"]
        opt_type = leg_template["option_type"]

        if method == "signal_strike":
            strike = signal.strike
        elif method == "atm":
            # For butterfly: use max pain as center if available
            if recommendation.strategy == "butterfly" and max_pain:
                strike = max_pain
            else:
                strike = atm
        elif method == "otm_1":
            if opt_type == "call":
                # Use call wall if available and it's beyond ATM+width
                if call_wall and call_wall > atm and action == "sell":
                    strike = call_wall
                else:
                    strike = atm + width
            else:
                # Use put wall if available and it's below ATM-width
                if put_wall and put_wall < atm and action == "sell":
                    strike = put_wall
                else:
                    strike = atm - width
        elif method == "otm_2":
            if opt_type == "call":
                if call_wall and call_wall > atm and action == "buy":
                    strike = call_wall + width
                else:
                    strike = atm + 2 * width
            else:
                if put_wall and put_wall < atm and action == "buy":
                    strike = put_wall - width
                else:
                    strike = atm - 2 * width
        elif method == "signal_strike - width":
            strike = signal.strike - width
        elif method == "signal_strike + width":
            strike = signal.strike + width
        else:
            strike = signal.strike

        legs.append({
            "action": action,
            "option_type": opt_type,
            "strike": round(strike, 2),
        })

    return legs


def price_recommendation(
    signal: OptionSignal,
    recommendation: StrategyRecommendation,
    dealer_data: Optional[DealerData] = None,
) -> Optional[dict]:
    """Resolve abstract legs to concrete strikes, price via BS,
    compute net premium, Greeks, stops, targets, and P(profit).

    Uses GEX walls and max pain from dealer_data for strike placement
    when available.

    Returns None if pricing fails or entry < $0.05.
    """
    T = signal.dte / 365.0
    if T <= 0:
        return None

    iv = signal.chain_iv
    spot = signal.spot
    r = RISK_FREE_RATE
    is_credit = _classify_credit(recommendation.strategy)

    # 1. Resolve strikes (using GEX walls/max pain when available)
    resolved_legs = _resolve_strikes(signal, recommendation, dealer_data)

    # 2. Price each leg
    priced_legs = []
    net_premium = 0.0
    net_delta = 0.0
    net_gamma = 0.0
    net_theta = 0.0
    net_vega = 0.0

    for leg in resolved_legs:
        try:
            bs = black_scholes_price(
                S=spot, K=leg["strike"], T=T, r=r,
                sigma=iv, option_type=leg["option_type"],
            )
            greeks = calculate_greeks(
                S=spot, K=leg["strike"], T=T, r=r,
                sigma=iv, option_type=leg["option_type"],
            )
        except Exception as e:
            logger.warning("BS pricing failed for leg %s: %s", leg, e)
            return None

        price = float(bs)
        sign = 1.0 if leg["action"] == "sell" else -1.0

        net_premium += sign * price
        net_delta += sign * greeks["Delta"]
        net_gamma += sign * greeks["Gamma"]
        net_theta += sign * greeks["Theta"]
        net_vega += sign * greeks["Vega"]

        priced_legs.append({
            "action": leg["action"],
            "option_type": leg["option_type"],
            "strike": leg["strike"],
            "iv": round(iv * 100, 1),
            "price": round(price, 2),
            "delta": round(greeks["Delta"], 4),
            "theta": round(greeks["Theta"], 4),
        })

    # 3. Entry
    entry = round(abs(net_premium), 2)
    if entry < 0.05:
        return None

    # 4. Spread width (for spread strategies)
    spread_width = None
    if recommendation.strategy in ("short_put_spread", "short_call_spread"):
        strikes = [l["strike"] for l in priced_legs]
        spread_width = round(abs(strikes[0] - strikes[1]), 2)
    elif recommendation.strategy == "iron_condor":
        call_strikes = [l["strike"] for l in priced_legs if l["option_type"] == "call"]
        put_strikes = [l["strike"] for l in priced_legs if l["option_type"] == "put"]
        if call_strikes and put_strikes:
            call_width = abs(max(call_strikes) - min(call_strikes))
            put_width = abs(max(put_strikes) - min(put_strikes))
            spread_width = round(max(call_width, put_width), 2)

    # 5. Max profit / max loss
    if is_credit:
        max_profit = entry
        max_loss = round(spread_width - entry, 2) if spread_width else None
    else:
        max_loss = entry
        if spread_width:
            max_profit = round(spread_width - entry, 2)
        else:
            max_profit = None  # unlimited for single long calls, large for puts

    # 6. Exit target
    if is_credit:
        exit_target = round(entry * 0.5, 2)   # buy back at 50% of credit
        exit_pct = 50.0
    else:
        exit_target = round(entry * 1.5, 2)    # sell at 150% of debit (50% profit)
        exit_pct = 50.0

    # 7. Stop
    if is_credit:
        option_stop = round(entry * 2.0, 2)    # 2x credit
    else:
        option_stop = round(entry * 0.5, 2)    # 50% of premium paid

    # 8. Risk/reward string
    if max_profit and max_loss and max_profit > 0:
        ratio = max_loss / max_profit
        risk_reward = f"1:{ratio:.2f}"
    else:
        risk_reward = "N/A"

    # 9. MC for probability of profit
    prob_profit = _compute_prob_profit(signal, priced_legs, is_credit, entry)

    return {
        "strategy": recommendation.strategy,
        "strategy_label": recommendation.strategy_label,
        "is_credit": is_credit,
        "legs": priced_legs,
        "spread_width": spread_width,
        "entry": entry,
        "exit_target": exit_target,
        "exit_pct": exit_pct,
        "option_stop": option_stop,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "net_delta": round(net_delta, 4),
        "net_gamma": round(net_gamma, 6),
        "net_theta": round(net_theta, 4),
        "net_vega": round(net_vega, 4),
        "prob_profit": prob_profit,
        "risk_reward": risk_reward,
        "edge_source": recommendation.edge_source,
        "rationale": recommendation.rationale,
    }


def _compute_prob_profit(signal, priced_legs, is_credit, entry):
    """Run MC on the primary leg to estimate probability of profit."""
    primary = priced_legs[0]
    mc_config = {
        "current_price": signal.spot,
        "strike_price": primary["strike"],
        "implied_volatility": signal.chain_iv,
        "expiration_date": signal.expiry,
        "option_type": primary["option_type"],
        "risk_free_rate": RISK_FREE_RATE,
    }

    try:
        mc_result = run_monte_carlo(
            config=mc_config,
            num_paths=MC_NUM_PATHS,
            num_steps=MC_NUM_STEPS,
            seed=MC_SEED,
            antithetic=True,
            use_jumps=True,
            jump_params={"lam": 0.1, "mu_J": -0.05, "sigma_J": 0.15},
        )
        payoffs = mc_result.get("payoffs", np.array([]))
        if len(payoffs) == 0:
            return 50.0

        if is_credit:
            # Credit: profit if payoff < entry (option expires worthless enough)
            prob = float(np.mean(payoffs < entry) * 100)
        else:
            # Debit: profit if payoff > entry
            prob = float(np.mean(payoffs > entry) * 100)

        return round(max(0.0, min(prob, 100.0)), 1)
    except Exception as e:
        logger.warning("MC prob_profit failed: %s", e)
        return 50.0
