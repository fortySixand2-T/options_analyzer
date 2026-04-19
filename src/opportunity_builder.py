"""
Builds a fully-priced opportunity dict for one (ticker, outlook) pair.

All legs of multi-leg strategies (iron condor, spreads) are individually
priced and summed to a net credit or net debit. Exit and stop levels are
computed at the position level, not the single-leg level.
"""
import logging
from datetime import date
from typing import Any, Dict, List, Optional

import numpy as np

from config import OPTION_STOP_PCT, OUTLOOKS, RISK_FREE_RATE
from pricer import price_bs, price_mc, reprice_at
from bias_detector import detect_bias
from strategy_selector import (
    CREDIT_STRATEGIES,
    OUTLOOK_ORDER,
    STRATEGY_MAP,
    find_expiry,
    get_iv_for_strike,
    get_primary_leg,
    select_strikes,
)

logger = logging.getLogger(__name__)


def _prob_profit(payoffs: np.ndarray, entry: float) -> float:
    if len(payoffs) == 0:
        return 0.45
    return float(np.mean(payoffs > entry))


def _price_all_legs(
    legs: List[Dict],
    current_price: float,
    T: float,
    expiry: str,
    hist_vol: float,
    vol_surface_df,
) -> tuple:
    """
    Price every leg with BS. Return (priced_legs, net_premium, net_greeks).

    net_premium > 0 means net credit received.
    net_premium < 0 means net debit paid.
    """
    priced_legs = []
    net_premium = 0.0
    net_delta   = 0.0
    net_gamma   = 0.0
    net_theta   = 0.0
    net_vega    = 0.0

    for leg in legs:
        iv  = get_iv_for_strike(vol_surface_df, expiry, leg["strike"], leg["option_type"], hist_vol)
        bs  = price_bs(current_price, leg["strike"], T, iv, leg["option_type"])
        prc = bs["price"]
        grk = bs["greeks"]

        sign = 1 if leg["action"] == "sell" else -1

        net_premium += sign * prc
        net_delta   += sign * grk.get("Delta", 0)
        net_gamma   += sign * grk.get("Gamma", 0)
        net_theta   += sign * grk.get("Theta", 0)
        net_vega    += sign * grk.get("Vega",  0)

        priced_legs.append({
            "action":      leg["action"],
            "option_type": leg["option_type"],
            "strike":      leg["strike"],
            "iv":          round(iv * 100, 1),
            "price":       round(prc, 2),
            "delta":       round(sign * grk.get("Delta", 0), 3),
            "theta":       round(sign * grk.get("Theta", 0), 3),
        })

    net_greeks = {
        "Delta": net_delta,
        "Gamma": net_gamma,
        "Theta": net_theta,
        "Vega":  net_vega,
    }
    return priced_legs, net_premium, net_greeks


def _reprice_net_at(
    legs: List[Dict],
    S_target: float,
    T_remaining: float,
    hist_vol: float,
    vol_surface_df,
    expiry: str,
) -> float:
    """Reprice all legs at a target underlying price and return net value."""
    total = 0.0
    for leg in legs:
        iv  = get_iv_for_strike(vol_surface_df, expiry, leg["strike"], leg["option_type"], hist_vol)
        prc = reprice_at(S_target, leg["strike"], T_remaining, iv, leg["option_type"])
        sign = 1 if leg["action"] == "sell" else -1
        total += sign * prc
    return total


def build_opportunity(
    ticker: str,
    signals: Dict[str, Any],
    vol_surface_df,
    historical_returns: np.ndarray,
    outlook: str,
) -> Optional[Dict[str, Any]]:
    """Build one fully-priced opportunity dict. Returns None if no valid setup."""
    today         = date.today()
    trend         = signals["trend"]
    vol           = signals["volatility"]
    sr            = signals["support_resistance"]
    current_price = float(trend["current_price"])
    hist_vol      = float(vol["hist_vol"])

    bias, score, _ = detect_bias(signals)
    strategy = STRATEGY_MAP.get((bias, outlook))
    if not strategy:
        return None

    # ── Expiry ────────────────────────────────────────────────────────────
    dte_cfg = OUTLOOKS[outlook]
    expiry, T = find_expiry(vol_surface_df, dte_cfg["min_dte"], dte_cfg["max_dte"], today)
    if T <= 1 / 365:
        return None

    # ── Legs & strikes ────────────────────────────────────────────────────
    leg_spec     = select_strikes(strategy, current_price, sr)
    legs         = leg_spec["legs"]
    target_price = leg_spec["target_price"]
    spread_width = leg_spec["spread_width"]

    # ── Price all legs ────────────────────────────────────────────────────
    priced_legs, net_premium, net_greeks = _price_all_legs(
        legs, current_price, T, expiry, hist_vol, vol_surface_df
    )

    is_credit = strategy in CREDIT_STRATEGIES
    entry     = round(abs(net_premium), 2)

    if entry < 0.05:
        return None

    # ── Max profit / max loss ─────────────────────────────────────────────
    if is_credit:
        max_profit = entry
        max_loss   = (round(spread_width - entry, 2) if spread_width else None)
    else:
        max_loss   = entry
        max_profit = (round(spread_width - entry, 2) if spread_width else None)

    # ── Exit target ───────────────────────────────────────────────────────
    T_at_target = max(T * 0.40, 2 / 365)

    if is_credit:
        exit_price        = round(entry * 0.50, 2)
        exit_pct          = 50.0
        target_underlying = None
    elif target_price:
        net_at_target     = _reprice_net_at(legs, target_price, T_at_target, hist_vol, vol_surface_df, expiry)
        exit_price        = round(abs(net_at_target), 2)
        exit_pct          = (exit_price - entry) / entry * 100 if entry > 0 else 0
        target_underlying = target_price
    else:
        exit_price        = round(entry * 1.50, 2)
        exit_pct          = 50.0
        target_underlying = None

    # ── Stops ─────────────────────────────────────────────────────────────
    if is_credit:
        option_stop = round(entry * 2.0, 2)
    else:
        option_stop = round(entry * (1 - OPTION_STOP_PCT), 2)

    primary = get_primary_leg(legs)
    underlying_stop = (
        sr["nearest_support"]    if primary["option_type"] == "call"
        else sr["nearest_resistance"]
    )

    # ── IV context (use primary leg IV) ──────────────────────────────────
    primary_iv = next(
        (pl["iv"] / 100 for pl in priced_legs if pl["strike"] == primary["strike"]),
        hist_vol
    )
    iv_vs_hv = (primary_iv - hist_vol) / hist_vol * 100 if hist_vol > 0 else 0

    # ── MC on primary leg only (indicative for multi-leg) ────────────────
    mc_config = {
        "ticker":             ticker,
        "current_price":      current_price,
        "strike_price":       primary["strike"],
        "expiration_date":    expiry,
        "option_type":        primary["option_type"],
        "implied_volatility": primary_iv,
        "risk_free_rate":     RISK_FREE_RATE,
    }
    am_style = "american" if primary["option_type"] == "put" else "european"
    mc       = price_mc(mc_config, historical_returns, use_jumps=True, option_style=am_style)

    payoffs         = mc.get("payoffs", np.array([]))
    prob_profit     = _prob_profit(payoffs, entry)
    expected_payoff = float(np.mean(payoffs)) if len(payoffs) > 0 else entry
    am_price        = mc.get("american_price")
    early_ex_prem   = float(mc.get("early_exercise_premium", 0) or 0)

    return {
        "ticker":       ticker,
        "outlook":      outlook,
        "dte":          int(T * 365),
        "expiry":       expiry,
        "strategy":     strategy,
        "is_credit":    is_credit,
        "bias":         bias,
        "bias_score":   score,
        "legs":         priced_legs,
        "spread_width": spread_width,
        "current_price":   round(current_price, 2),
        "hist_vol":        round(hist_vol * 100, 1),
        "iv_vs_hv":        round(iv_vs_hv, 1),
        "atr":             round(vol["atr"] or 0, 2),
        "atr_pct":         round(vol["atr_pct"] or 0, 2),
        "entry":              entry,
        "exit_target":        exit_price,
        "exit_pct":           round(exit_pct, 1),
        "target_underlying":  round(target_underlying, 2) if target_underlying else None,
        "option_stop":        option_stop,
        "underlying_stop":    round(underlying_stop, 2),
        "max_profit":         max_profit,
        "max_loss":           max_loss,
        "delta": round(net_greeks["Delta"], 3),
        "gamma": round(net_greeks["Gamma"], 4),
        "theta": round(net_greeks["Theta"], 3),
        "vega":  round(net_greeks["Vega"],  3),
        "prob_profit":            round(prob_profit * 100, 1),
        "expected_payoff":        round(expected_payoff, 2),
        "american_price":         round(am_price, 2) if am_price is not None else None,
        "early_exercise_premium": round(early_ex_prem, 2),
        "nearest_resistance": round(sr["nearest_resistance"], 2),
        "nearest_support":    round(sr["nearest_support"],    2),
    }


def build_all_opportunities(
    ticker: str,
    signals: Dict[str, Any],
    vol_surface_df,
    historical_returns: np.ndarray,
) -> List[Dict[str, Any]]:
    """Build opportunities for all three outlooks."""
    results = []
    for outlook in OUTLOOK_ORDER:
        try:
            opp = build_opportunity(ticker, signals, vol_surface_df, historical_returns, outlook)
            if opp:
                results.append(opp)
        except Exception as exc:
            logger.warning(f"Opportunity build failed ({ticker}, {outlook}): {exc}")
    return results
