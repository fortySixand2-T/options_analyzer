"""
Local offline backtester using historical OHLCV + BS pricer.

Simulates strategy entries/exits by walking through historical price
data day-by-day, applying scanner logic at each step.

Options Analytics Team — 2026-04
"""

import logging
from datetime import date, timedelta
from typing import List, Optional

import numpy as np

from models.black_scholes import black_scholes_price
from config import RISK_FREE_RATE
from .models import BacktestRequest, BacktestResult, BacktestTrade
from .analyzer import (
    analyze_results, compute_regime_breakdown,
    compute_dte_breakdown, compute_pnl_distribution,
)
from .cache import get_cached, store_cached

logger = logging.getLogger(__name__)

# Strategy parameters: (is_credit, num_legs, wing_width_multiplier)
_STRATEGY_PARAMS = {
    "iron_condor":      {"is_credit": True,  "legs": 4, "wings": 2},
    "short_put_spread":  {"is_credit": True,  "legs": 2, "wings": 1},
    "short_call_spread": {"is_credit": True,  "legs": 2, "wings": 1},
    "short_strangle":    {"is_credit": True,  "legs": 2, "wings": 0},
    "long_call_spread":  {"is_credit": False, "legs": 2, "wings": 1},
    "long_put_spread":   {"is_credit": False, "legs": 2, "wings": 1},
    "long_straddle":     {"is_credit": False, "legs": 2, "wings": 0},
    "butterfly":         {"is_credit": False, "legs": 4, "wings": 1},
    "calendar_spread":   {"is_credit": False, "legs": 2, "wings": 0},
    "diagonal_spread":   {"is_credit": False, "legs": 2, "wings": 1},
    "naked_put_1dte":    {"is_credit": True,  "legs": 1, "wings": 0},
}


def run_local_backtest(request: BacktestRequest) -> BacktestResult:
    """Run a local backtest using historical price data + BS pricing.

    Uses yfinance to fetch historical OHLCV, then simulates strategy
    entries at regular intervals with BS-based pricing and exits based
    on the request's profit/loss/DTE targets.
    """
    # Check cache first
    cached = get_cached(request)
    if cached:
        return cached

    logger.info("Running local backtest: %s on %s (%s to %s)",
                request.strategy, request.symbol,
                request.start_date, request.end_date)

    # Fetch historical data
    closes, dates = _fetch_history(request.symbol, request.start_date, request.end_date)
    if len(closes) < 30:
        logger.warning("Insufficient history for %s", request.symbol)
        return BacktestResult(
            request=request,
            stats=analyze_results([]),
            source="local",
        )

    # Compute rolling vol for IV estimate
    returns = np.diff(np.log(closes))
    rolling_vol = _rolling_vol(returns, window=20)

    # Walk through dates and simulate trades
    params = _STRATEGY_PARAMS.get(request.strategy, {"is_credit": True, "legs": 2, "wings": 1})
    trades = _simulate_trades(
        closes=closes,
        dates=dates,
        rolling_vol=rolling_vol,
        request=request,
        params=params,
    )

    stats = analyze_results(trades)
    equity = [0.0]
    for t in trades:
        equity.append(equity[-1] + t.pnl)
    regime_breakdown = compute_regime_breakdown(trades)
    dte_breakdown = compute_dte_breakdown(trades)
    pnl_distribution = compute_pnl_distribution(trades)

    result = BacktestResult(
        request=request,
        stats=stats,
        trades=trades,
        equity_curve=equity,
        regime_breakdown=regime_breakdown,
        dte_breakdown=dte_breakdown,
        pnl_distribution=pnl_distribution,
        source="local",
    )

    # Cache result
    store_cached(request, result)

    return result


def _fetch_history(symbol: str, start: date, end: date):
    """Fetch historical closes from yfinance."""
    import yfinance as yf
    ticker = yf.Ticker(symbol)
    hist = ticker.history(start=start.isoformat(), end=end.isoformat())
    if hist.empty:
        return np.array([]), []
    closes = hist['Close'].values
    dates = [d.date() for d in hist.index]
    return closes, dates


def _rolling_vol(returns: np.ndarray, window: int = 20) -> np.ndarray:
    """Annualized rolling realized volatility."""
    if len(returns) < window:
        return np.full(len(returns) + 1, 0.20)
    vol = np.full(len(returns) + 1, 0.20)
    for i in range(window, len(returns) + 1):
        vol[i] = float(np.std(returns[i - window:i]) * np.sqrt(252))
    return vol


def _classify_regime(iv: float) -> str:
    """Classify market regime based on rolling IV."""
    if iv > 0.30:
        return "SPIKE"
    elif iv > 0.20:
        return "HIGH_IV"
    elif iv > 0.15:
        return "MODERATE_IV"
    else:
        return "LOW_IV"


def _check_entry_filters(request, regime: str) -> bool:
    """Check if signal filters allow entry. Returns True if entry is allowed."""
    if request.regime_filter:
        # Only enter when regime matches the strategy's ideal regime
        strategy_regimes = {
            "iron_condor": {"HIGH_IV"},
            "short_put_spread": {"HIGH_IV", "MODERATE_IV"},
            "short_call_spread": {"HIGH_IV", "MODERATE_IV"},
            "long_call_spread": {"LOW_IV", "MODERATE_IV"},
            "long_put_spread": {"LOW_IV", "MODERATE_IV"},
            "butterfly": {"LOW_IV", "MODERATE_IV"},
        }
        allowed = strategy_regimes.get(request.strategy, set())
        if regime not in allowed:
            return False

    # Note: bias_filter, dealer_filter, and edge_threshold cannot be
    # meaningfully applied in the local backtester since we don't have
    # historical dealer positioning or real-time bias signals.
    # They are included in the request model for the UI toggles and
    # future integration with historical signal data.

    return True


def _simulate_trades(closes, dates, rolling_vol, request, params) -> List[BacktestTrade]:
    """Walk through historical data and simulate strategy entries/exits."""
    trades = []
    in_trade = False
    entry_idx = 0
    entry_price = 0.0
    entry_spot = 0.0
    max_profit = 0.0
    max_loss = 0.0
    trade_dte = 0  # actual DTE at entry

    # Entry frequency: every entry_dte_min days
    entry_interval = max(request.entry_dte_min, 7)
    next_entry_idx = 0

    is_credit = params["is_credit"]
    use_profit_target = (request.exit_rule == "50pct")
    r = RISK_FREE_RATE

    for i in range(len(closes)):
        spot = closes[i]
        iv = rolling_vol[i] if i < len(rolling_vol) else 0.20

        if in_trade:
            # Check exit conditions
            days_held = i - entry_idx
            dte_remaining = trade_dte - days_held

            # Reprice the position
            T_remaining = max(dte_remaining / 365.0, 1 / 365.0)
            current_value = _price_strategy(
                spot, entry_spot, iv, T_remaining, r,
                request.strategy, is_credit,
            )

            if is_credit:
                pnl = entry_price - current_value
            else:
                pnl = current_value - entry_price

            # Check exit conditions
            exit_reason = None

            if use_profit_target:
                # Apply profit target and stop loss
                if is_credit and max_profit > 0:
                    if pnl >= max_profit * (request.exit_profit_pct / 100):
                        exit_reason = "profit_target"
                    elif pnl <= -max_profit * (request.exit_loss_pct / 100):
                        exit_reason = "stop_loss"
                elif not is_credit and entry_price > 0:
                    if pnl >= entry_price * (request.exit_profit_pct / 100):
                        exit_reason = "profit_target"
                    elif pnl <= -entry_price * (request.exit_loss_pct / 100):
                        exit_reason = "stop_loss"
            else:
                # Hold to expiry: only stop loss, no profit target
                if is_credit and max_profit > 0:
                    if pnl <= -max_profit * (request.exit_loss_pct / 100):
                        exit_reason = "stop_loss"
                elif not is_credit and entry_price > 0:
                    if pnl <= -entry_price * (request.exit_loss_pct / 100):
                        exit_reason = "stop_loss"

            if dte_remaining <= request.exit_dte:
                exit_reason = "dte_exit"

            if exit_reason:
                regime = _classify_regime(
                    rolling_vol[entry_idx] if entry_idx < len(rolling_vol) else 0.20
                )

                trade = BacktestTrade(
                    entry_date=dates[entry_idx],
                    exit_date=dates[i],
                    entry_price=round(entry_price, 2),
                    exit_price=round(current_value, 2),
                    pnl=round(pnl * 100, 2),  # per contract (x100 multiplier)
                    pnl_pct=round(pnl / max(abs(entry_price), 0.01) * 100, 1),
                    dte_at_entry=trade_dte,
                    dte_at_exit=max(dte_remaining, 0),
                    regime=regime,
                    win=pnl > 0,
                    exit_reason=exit_reason,
                )
                trades.append(trade)
                in_trade = False
                next_entry_idx = i + 5  # cool-off period

        elif i >= next_entry_idx:
            # Check signal filters before entering
            regime = _classify_regime(iv)
            if not _check_entry_filters(request, regime):
                next_entry_idx = i + 1  # try again next day
                continue

            # Randomize DTE within the allowed range for realistic entry spread
            dte_range = request.entry_dte_max - request.entry_dte_min
            if dte_range > 0:
                # Use a deterministic hash of the date index for reproducibility
                trade_dte = request.entry_dte_min + (i % (dte_range + 1))
            else:
                trade_dte = request.entry_dte_max

            T = trade_dte / 365.0
            entry_price = _price_strategy(spot, spot, iv, T, r, request.strategy, is_credit)

            if entry_price > 0.05:
                in_trade = True
                entry_idx = i
                entry_spot = spot
                if is_credit:
                    max_profit = entry_price
                    max_loss = entry_price * 2  # approximate for spreads
                else:
                    max_profit = entry_price * 2
                    max_loss = entry_price
                next_entry_idx = i + entry_interval

    return trades


def _price_strategy(spot, entry_spot, iv, T, r, strategy, is_credit) -> float:
    """Simplified BS pricing for a strategy position."""
    if T <= 0:
        return 0.0

    inc = 5.0 if spot >= 100 else (2.5 if spot >= 50 else 1.0)
    atm = round(entry_spot / inc) * inc

    try:
        if strategy in ("iron_condor",):
            # Sell call spread + sell put spread
            sell_call = black_scholes_price(spot, atm + inc, T, r, iv, "call")
            buy_call = black_scholes_price(spot, atm + 2 * inc, T, r, iv, "call")
            sell_put = black_scholes_price(spot, atm - inc, T, r, iv, "put")
            buy_put = black_scholes_price(spot, atm - 2 * inc, T, r, iv, "put")
            return (sell_call - buy_call) + (sell_put - buy_put)

        elif strategy in ("short_put_spread",):
            sell = black_scholes_price(spot, atm - inc, T, r, iv, "put")
            buy = black_scholes_price(spot, atm - 2 * inc, T, r, iv, "put")
            return sell - buy

        elif strategy in ("short_call_spread",):
            sell = black_scholes_price(spot, atm + inc, T, r, iv, "call")
            buy = black_scholes_price(spot, atm + 2 * inc, T, r, iv, "call")
            return sell - buy

        elif strategy in ("short_strangle",):
            sell_call = black_scholes_price(spot, atm + inc, T, r, iv, "call")
            sell_put = black_scholes_price(spot, atm - inc, T, r, iv, "put")
            return sell_call + sell_put

        elif strategy in ("long_call_spread",):
            buy = black_scholes_price(spot, atm, T, r, iv, "call")
            sell = black_scholes_price(spot, atm + inc, T, r, iv, "call")
            return buy - sell

        elif strategy in ("long_put_spread",):
            buy = black_scholes_price(spot, atm, T, r, iv, "put")
            sell = black_scholes_price(spot, atm - inc, T, r, iv, "put")
            return buy - sell

        elif strategy in ("long_straddle",):
            call = black_scholes_price(spot, atm, T, r, iv, "call")
            put = black_scholes_price(spot, atm, T, r, iv, "put")
            return call + put

        elif strategy in ("naked_put_1dte",):
            return black_scholes_price(spot, atm - inc, T, r, iv, "put")

        else:
            # Default: single option
            return black_scholes_price(spot, atm, T, r, iv, "call")

    except Exception:
        return 0.0
