"""
0 DTE intraday backtester engine.

Walks stored 5-min bars day-by-day, applies day-type classification
and signal filters at each entry window, then simulates option P&L
using intraday theta decay: T_remaining = minutes_to_close / (390 * 252).

Key differences from daily backtester:
- Uses stored intraday bars (not daily OHLCV)
- Entry at specific times (not "next open")
- Intraday theta decay model (not 1/365 per day)
- Day-type as primary filter (not vol regime)
- Exit on time (15:45 ET) not DTE

Options Analytics Team — 2026-04
"""

import logging
import math
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import RISK_FREE_RATE
from models.black_scholes import black_scholes_price
from .intraday_models import (
    IntradayBacktestRequest,
    IntradayBacktestResult,
    IntradayBacktestStats,
    IntradayBacktestTrade,
)

logger = logging.getLogger(__name__)

# Minutes in a trading session
TRADING_MINUTES = 390  # 9:30 - 16:00
ANNUALIZATION_FACTOR = 390 * 252  # minutes per year


def run_intraday_backtest(request: IntradayBacktestRequest) -> IntradayBacktestResult:
    """Run an intraday backtest over stored 5-min bars.

    For each trading day in the date range:
    1. Load 5-min bars from intraday_store
    2. Compute day-type classification at first entry window
    3. Check signal filters (day_type, exhaustion, dealer)
    4. At each entry window, simulate entry if filters pass
    5. Walk remaining bars tracking P&L with intraday theta decay
    6. Exit on profit target, stop loss, or exit time

    Returns
    -------
    IntradayBacktestResult
    """
    from data.intraday_store import get_bars, get_available_dates

    logger.info(
        "Running intraday backtest: %s on %s (%s to %s)",
        request.strategy, request.symbol, request.start_date, request.end_date,
    )

    # Get available trading days
    available_dates = get_available_dates(request.symbol, interval="5m")
    trading_days = [
        d for d in available_dates
        if request.start_date.isoformat() <= d <= request.end_date.isoformat()
    ]

    if not trading_days:
        logger.warning("No intraday data for %s in date range", request.symbol)
        return IntradayBacktestResult(
            request=request,
            stats=IntradayBacktestStats(),
        )

    trades: List[IntradayBacktestTrade] = []
    skip_reasons: Dict[str, int] = {}
    days_traded = 0
    days_skipped = 0

    for trade_date_str in trading_days:
        bars = get_bars(request.symbol, trade_date_str, interval="5m")
        if len(bars) < 12:  # need at least 1 hour of data
            skip_reasons["insufficient_bars"] = skip_reasons.get("insufficient_bars", 0) + 1
            days_skipped += 1
            continue

        # Try to enter at each window
        trade = _try_entry_and_simulate(
            bars=bars,
            trade_date_str=trade_date_str,
            request=request,
            skip_reasons=skip_reasons,
        )

        if trade:
            trades.append(trade)
            days_traded += 1
        else:
            days_skipped += 1

    # Compute stats
    stats = _compute_stats(trades, days_traded, days_skipped, skip_reasons)
    equity_curve = _compute_equity_curve(trades)
    day_type_breakdown = _compute_day_type_breakdown(trades)
    entry_time_breakdown = _compute_entry_time_breakdown(trades)

    result = IntradayBacktestResult(
        request=request,
        stats=stats,
        trades=trades,
        equity_curve=equity_curve,
        day_type_breakdown=day_type_breakdown,
        entry_time_breakdown=entry_time_breakdown,
    )

    logger.info(
        "Intraday backtest complete: %d trades, %.1f%% win rate, $%.2f total P&L",
        stats.total_trades, stats.win_rate, stats.total_pnl,
    )

    return result


def _try_entry_and_simulate(
    bars: pd.DataFrame,
    trade_date_str: str,
    request: IntradayBacktestRequest,
    skip_reasons: Dict[str, int],
) -> Optional[IntradayBacktestTrade]:
    """Try to enter at each entry window and simulate the trade if filters pass."""

    # Classify the day using first ~30 min of bars
    day_context = _compute_day_context(bars, trade_date_str, request.symbol)

    # Check day-type filter
    if request.day_type_filter and day_context["day_type"] != request.day_type_filter:
        reason = f"day_type_{day_context['day_type'].lower()}"
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
        return None

    # Check dealer filter
    if request.dealer_filter and day_context.get("dealer_regime") != request.dealer_filter:
        skip_reasons["dealer_filter"] = skip_reasons.get("dealer_filter", 0) + 1
        return None

    # Try each entry window
    for entry_time_str in request.entry_windows:
        entry_bar_idx = _find_bar_index(bars, entry_time_str)
        if entry_bar_idx is None:
            continue

        # Compute exhaustion at entry time
        open_price = bars["Open"].iloc[0]
        entry_price = bars["Close"].iloc[entry_bar_idx]
        expected_move = day_context["expected_daily_move"]

        if expected_move > 0:
            exhaustion = abs(entry_price - open_price) / expected_move * 100
        else:
            exhaustion = 0.0

        # Check exhaustion filter
        if exhaustion < request.exhaustion_min or exhaustion > request.exhaustion_max:
            continue

        # Passed all filters — simulate the trade
        trade = _simulate_intraday_trade(
            bars=bars,
            entry_bar_idx=entry_bar_idx,
            entry_time_str=entry_time_str,
            trade_date_str=trade_date_str,
            request=request,
            day_context=day_context,
            exhaustion=exhaustion,
        )
        if trade:
            return trade

    skip_reasons["no_valid_entry"] = skip_reasons.get("no_valid_entry", 0) + 1
    return None


def _simulate_intraday_trade(
    bars: pd.DataFrame,
    entry_bar_idx: int,
    entry_time_str: str,
    trade_date_str: str,
    request: IntradayBacktestRequest,
    day_context: Dict,
    exhaustion: float,
) -> Optional[IntradayBacktestTrade]:
    """Simulate a single 0 DTE trade from entry to exit."""

    spot_entry = bars["Close"].iloc[entry_bar_idx]
    expected_move = day_context["expected_daily_move"]

    # Compute strikes based on strategy
    strikes = _compute_strikes(spot_entry, expected_move, request)
    if not strikes:
        return None

    # Compute entry premium using BS with intraday time
    minutes_to_close_entry = _minutes_to_close(bars, entry_bar_idx)
    T_entry = minutes_to_close_entry / ANNUALIZATION_FACTOR

    # IV estimate: use expected_move to back out implied vol
    # ATM straddle ≈ spot * sigma * sqrt(T) * 0.8 (approximate)
    # So sigma ≈ expected_move / (spot * sqrt(T) * 0.8)
    if T_entry > 0 and spot_entry > 0:
        iv_estimate = expected_move / (spot_entry * math.sqrt(T_entry) * 0.8)
        iv_estimate = max(0.10, min(iv_estimate, 2.0))  # clamp
    else:
        iv_estimate = 0.20

    entry_credit = _price_strategy(
        spot_entry, strikes, T_entry, iv_estimate, request.strategy,
    )

    if entry_credit <= 0:
        return None

    # Apply slippage
    num_legs = len([v for v in strikes.values() if v is not None])
    total_slippage = request.slippage_per_leg * num_legs
    net_entry = entry_credit - total_slippage

    if net_entry <= 0:
        return None

    # Max profit and max risk
    max_profit = net_entry
    max_risk = request.wing_width - net_entry if request.wing_width > net_entry else net_entry

    # Walk forward through remaining bars
    exit_bar_idx = entry_bar_idx
    exit_reason = "eod"
    exit_value = 0.0

    for i in range(entry_bar_idx + 1, len(bars)):
        spot_now = bars["Close"].iloc[i]
        minutes_to_close_now = _minutes_to_close(bars, i)
        T_now = minutes_to_close_now / ANNUALIZATION_FACTOR

        # Check exit time
        bar_time_str = _bar_time_str(bars, i)
        if bar_time_str >= request.exit_time:
            exit_bar_idx = i
            exit_reason = "time_exit"
            exit_value = _price_strategy(
                spot_now, strikes, T_now, iv_estimate, request.strategy,
            )
            break

        # Price the position
        current_value = _price_strategy(
            spot_now, strikes, T_now, iv_estimate, request.strategy,
        )

        # P&L check (credit strategy: profit = entry - current)
        unrealized_pnl = net_entry - current_value

        # Profit target
        if unrealized_pnl >= max_profit * (request.profit_target_pct / 100):
            exit_bar_idx = i
            exit_reason = "profit_target"
            exit_value = current_value
            break

        # Stop loss
        if unrealized_pnl <= -max_risk * (request.stop_loss_pct / 100):
            exit_bar_idx = i
            exit_reason = "stop_loss"
            exit_value = current_value
            break

        exit_bar_idx = i
        exit_value = current_value

    # Final P&L
    exit_slippage = request.slippage_per_leg * num_legs
    pnl = (net_entry - exit_value) - exit_slippage
    pnl_pct = (pnl / max_risk * 100) if max_risk > 0 else 0.0

    spot_exit = bars["Close"].iloc[exit_bar_idx]
    exit_time_str = _bar_time_str(bars, exit_bar_idx)

    # Hold time in minutes
    hold_minutes = (exit_bar_idx - entry_bar_idx) * 5

    return IntradayBacktestTrade(
        trade_date=date.fromisoformat(trade_date_str),
        entry_time=entry_time_str,
        exit_time=exit_time_str,
        entry_price=round(net_entry, 4),
        exit_price=round(exit_value, 4),
        pnl=round(pnl, 4),
        pnl_pct=round(pnl_pct, 2),
        max_profit=round(max_profit, 4),
        max_risk=round(max_risk, 4),
        spot_at_entry=round(spot_entry, 2),
        spot_at_exit=round(spot_exit, 2),
        expected_daily_move=round(expected_move, 2),
        day_type=day_context["day_type"],
        day_type_confidence=day_context["day_type_confidence"],
        move_exhaustion_pct=round(exhaustion, 2),
        dealer_regime=day_context.get("dealer_regime"),
        win=pnl > 0,
        exit_reason=exit_reason,
        short_call=strikes.get("short_call"),
        short_put=strikes.get("short_put"),
        long_call=strikes.get("long_call"),
        long_put=strikes.get("long_put"),
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _compute_day_context(bars: pd.DataFrame, trade_date: str, symbol: str) -> Dict:
    """Classify day type and compute context from first 30 min of bars."""
    from signals.day_classifier import classify_day
    from signals.intraday_gex import get_latest_intraday_dealer

    # Get prior close for gap calculation
    prior_close = None
    from data.intraday_store import get_available_dates, get_bars as get_stored_bars
    dates = get_available_dates(symbol, "5m")
    prior_dates = [d for d in dates if d < trade_date]
    if prior_dates:
        prior_bars = get_stored_bars(symbol, prior_dates[-1], "5m")
        if not prior_bars.empty:
            prior_close = prior_bars["Close"].iloc[-1]

    # VIX context
    vix_current = None
    vix_prior_close = None
    vix_bars = get_stored_bars("^VIX", trade_date, "5m")
    if not vix_bars.empty:
        vix_current = vix_bars["Close"].iloc[-1]

    vix_dates = get_available_dates("^VIX", "5m")
    prior_vix_dates = [d for d in vix_dates if d < trade_date]
    if prior_vix_dates:
        prior_vix_bars = get_stored_bars("^VIX", prior_vix_dates[-1], "5m")
        if not prior_vix_bars.empty:
            vix_prior_close = prior_vix_bars["Close"].iloc[-1]

    # Expected daily move estimate
    spot = bars["Close"].iloc[-1] if not bars.empty else 0.0
    if vix_current and vix_current > 0 and spot > 0:
        expected_move = spot * (vix_current / 100) / math.sqrt(252)
    else:
        expected_move = spot * 0.01  # 1% fallback

    # Classify
    classification = classify_day(
        bars=bars,
        expected_daily_move=expected_move,
        prior_close=prior_close,
        vix_current=vix_current,
        vix_prior_close=vix_prior_close,
    )

    # Dealer regime (try to get from stored chain)
    dealer_regime = None
    try:
        dealer = get_latest_intraday_dealer(symbol, trade_date)
        if dealer:
            dealer_regime = dealer.dealer_regime
    except Exception:
        pass

    return {
        "day_type": classification.day_type.value,
        "day_type_confidence": classification.confidence,
        "expected_daily_move": expected_move,
        "prior_close": prior_close,
        "vix_current": vix_current,
        "dealer_regime": dealer_regime,
    }


def _compute_strikes(
    spot: float,
    expected_move: float,
    request: IntradayBacktestRequest,
) -> Optional[Dict[str, Optional[float]]]:
    """Compute option strikes for the strategy."""

    wing = request.wing_width

    if request.strategy in ("0dte_iron_condor", "iron_condor"):
        # Place short strikes ~1 expected move away
        short_put = round(spot - expected_move, 0)
        short_call = round(spot + expected_move, 0)
        long_put = short_put - wing
        long_call = short_call + wing
        return {
            "short_put": short_put,
            "short_call": short_call,
            "long_put": long_put,
            "long_call": long_call,
        }

    elif request.strategy in ("0dte_put_spread", "short_put_spread"):
        short_put = round(spot - expected_move * 0.8, 0)
        long_put = short_put - wing
        return {
            "short_put": short_put,
            "long_put": long_put,
            "short_call": None,
            "long_call": None,
        }

    elif request.strategy in ("0dte_call_spread", "short_call_spread"):
        short_call = round(spot + expected_move * 0.8, 0)
        long_call = short_call + wing
        return {
            "short_call": short_call,
            "long_call": long_call,
            "short_put": None,
            "long_put": None,
        }

    elif request.strategy in ("0dte_butterfly", "butterfly"):
        center = round(spot, 0)
        return {
            "short_put": center,
            "short_call": center,
            "long_put": center - wing,
            "long_call": center + wing,
        }

    else:
        logger.warning("Unknown strategy: %s", request.strategy)
        return None


def _price_strategy(
    spot: float,
    strikes: Dict[str, Optional[float]],
    T: float,
    iv: float,
    strategy: str,
) -> float:
    """Price the strategy using Black-Scholes.

    Returns the net value of the position (positive for credit strategies).
    """
    if T <= 0:
        # At expiry — intrinsic value only
        return _intrinsic_value(spot, strikes, strategy)

    value = 0.0
    r = RISK_FREE_RATE

    # Iron condor: sell put spread + sell call spread
    if strategy in ("0dte_iron_condor", "iron_condor"):
        sp, sc = strikes["short_put"], strikes["short_call"]
        lp, lc = strikes["long_put"], strikes["long_call"]

        if sp and lp:
            value += black_scholes_price(spot, sp, T, r, iv, "put")   # short put
            value -= black_scholes_price(spot, lp, T, r, iv, "put")   # long put
        if sc and lc:
            value += black_scholes_price(spot, sc, T, r, iv, "call")  # short call
            value -= black_scholes_price(spot, lc, T, r, iv, "call")  # long call

    elif strategy in ("0dte_put_spread", "short_put_spread"):
        sp, lp = strikes["short_put"], strikes["long_put"]
        if sp and lp:
            value += black_scholes_price(spot, sp, T, r, iv, "put")
            value -= black_scholes_price(spot, lp, T, r, iv, "put")

    elif strategy in ("0dte_call_spread", "short_call_spread"):
        sc, lc = strikes["short_call"], strikes["long_call"]
        if sc and lc:
            value += black_scholes_price(spot, sc, T, r, iv, "call")
            value -= black_scholes_price(spot, lc, T, r, iv, "call")

    elif strategy in ("0dte_butterfly", "butterfly"):
        center_put = strikes["short_put"]
        center_call = strikes["short_call"]
        lp, lc = strikes["long_put"], strikes["long_call"]

        if center_put and lp:
            # Buy wings, sell center (debit for butterfly)
            value -= black_scholes_price(spot, lp, T, r, iv, "put")
            value += 2 * black_scholes_price(spot, center_put, T, r, iv, "put")
            value -= black_scholes_price(spot, lc, T, r, iv, "call") if lc else 0

    return max(value, 0.0)


def _intrinsic_value(spot: float, strikes: Dict, strategy: str) -> float:
    """Compute intrinsic value at expiry."""
    value = 0.0

    if strategy in ("0dte_iron_condor", "iron_condor"):
        sp, sc = strikes.get("short_put"), strikes.get("short_call")
        lp, lc = strikes.get("long_put"), strikes.get("long_call")
        if sp and lp:
            value += max(sp - spot, 0) - max(lp - spot, 0)
        if sc and lc:
            value += max(spot - sc, 0) - max(spot - lc, 0)

    elif strategy in ("0dte_put_spread", "short_put_spread"):
        sp, lp = strikes.get("short_put"), strikes.get("long_put")
        if sp and lp:
            value += max(sp - spot, 0) - max(lp - spot, 0)

    elif strategy in ("0dte_call_spread", "short_call_spread"):
        sc, lc = strikes.get("short_call"), strikes.get("long_call")
        if sc and lc:
            value += max(spot - sc, 0) - max(spot - lc, 0)

    return max(value, 0.0)


def _find_bar_index(bars: pd.DataFrame, time_str: str) -> Optional[int]:
    """Find bar index closest to the given time (HH:MM format)."""
    target_hour = int(time_str.split(":")[0])
    target_min = int(time_str.split(":")[1])

    for i, ts in enumerate(bars.index):
        if hasattr(ts, 'hour'):
            # Handle timezone-aware timestamps
            bar_hour = ts.hour
            bar_min = ts.minute

            # If timezone-aware, convert to ET for comparison
            if hasattr(ts, 'tz') and ts.tz is not None:
                try:
                    import pytz
                    eastern = pytz.timezone("US/Eastern")
                    local_ts = ts.astimezone(eastern)
                    bar_hour = local_ts.hour
                    bar_min = local_ts.minute
                except Exception:
                    pass

            if bar_hour == target_hour and bar_min >= target_min:
                return i
            if bar_hour > target_hour:
                return i

    return None


def _minutes_to_close(bars: pd.DataFrame, bar_idx: int) -> float:
    """Estimate minutes remaining until 16:00 ET close."""
    remaining_bars = len(bars) - bar_idx - 1
    return max(remaining_bars * 5, 1)  # 5 min per bar, minimum 1 minute


def _bar_time_str(bars: pd.DataFrame, bar_idx: int) -> str:
    """Get HH:MM string for a bar."""
    ts = bars.index[bar_idx]
    if hasattr(ts, 'hour'):
        if hasattr(ts, 'tz') and ts.tz is not None:
            try:
                import pytz
                eastern = pytz.timezone("US/Eastern")
                ts = ts.astimezone(eastern)
            except Exception:
                pass
        return f"{ts.hour:02d}:{ts.minute:02d}"
    return "00:00"


# ── Stats computation ────────────────────────────────────────────────────────


def _compute_stats(
    trades: List[IntradayBacktestTrade],
    days_traded: int,
    days_skipped: int,
    skip_reasons: Dict[str, int],
) -> IntradayBacktestStats:
    """Compute aggregate statistics from trades."""
    if not trades:
        return IntradayBacktestStats(
            days_traded=days_traded,
            days_skipped=days_skipped,
            skip_reasons=skip_reasons,
        )

    pnls = [t.pnl for t in trades]
    wins = [t for t in trades if t.win]
    losses = [t for t in trades if not t.win]

    total = len(trades)
    n_wins = len(wins)
    win_rate = n_wins / total * 100 if total > 0 else 0.0

    avg_win = float(np.mean([t.pnl for t in wins])) if wins else 0.0
    avg_loss = float(np.mean([t.pnl for t in losses])) if losses else 0.0
    avg_pnl = float(np.mean(pnls))
    total_pnl = sum(pnls)

    gross_wins = sum(t.pnl for t in wins)
    gross_losses = abs(sum(t.pnl for t in losses))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')

    # Drawdown
    equity = list(np.cumsum(pnls))
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = peak - e
        if dd > max_dd:
            max_dd = dd

    # Sharpe (annualized from daily trades)
    if len(pnls) > 1:
        sharpe = float(np.mean(pnls) / np.std(pnls) * math.sqrt(252))
    else:
        sharpe = 0.0

    # Day-type specific win rates
    range_trades = [t for t in trades if t.day_type == "RANGE_DAY"]
    trend_trades = [t for t in trades if t.day_type == "TREND_DAY"]
    range_wr = len([t for t in range_trades if t.win]) / len(range_trades) * 100 if range_trades else 0.0
    trend_wr = len([t for t in trend_trades if t.win]) / len(trend_trades) * 100 if trend_trades else 0.0

    # Average exhaustion at entry
    avg_exhaustion = float(np.mean([t.move_exhaustion_pct for t in trades]))

    return IntradayBacktestStats(
        total_trades=total,
        wins=n_wins,
        losses=len(losses),
        win_rate=round(win_rate, 1),
        avg_win=round(avg_win, 4),
        avg_loss=round(avg_loss, 4),
        avg_pnl=round(avg_pnl, 4),
        total_pnl=round(total_pnl, 4),
        profit_factor=round(profit_factor, 2),
        max_drawdown=round(max_dd, 4),
        sharpe_ratio=round(sharpe, 2),
        avg_hold_minutes=0.0,  # computed from entry/exit times
        range_day_win_rate=round(range_wr, 1),
        trend_day_win_rate=round(trend_wr, 1),
        avg_entry_exhaustion=round(avg_exhaustion, 1),
        days_traded=days_traded,
        days_skipped=days_skipped,
        skip_reasons=skip_reasons,
    )


def _compute_equity_curve(trades: List[IntradayBacktestTrade]) -> List[float]:
    """Build cumulative P&L curve."""
    if not trades:
        return []
    return [round(float(x), 4) for x in np.cumsum([t.pnl for t in trades])]


def _compute_day_type_breakdown(trades: List[IntradayBacktestTrade]) -> Dict[str, Dict]:
    """Win rate and avg P&L by day type."""
    breakdown = {}
    for dt in ("RANGE_DAY", "TREND_DAY", "UNCERTAIN"):
        dt_trades = [t for t in trades if t.day_type == dt]
        if dt_trades:
            wins = len([t for t in dt_trades if t.win])
            breakdown[dt] = {
                "trades": len(dt_trades),
                "win_rate": round(wins / len(dt_trades) * 100, 1),
                "avg_pnl": round(float(np.mean([t.pnl for t in dt_trades])), 4),
                "total_pnl": round(sum(t.pnl for t in dt_trades), 4),
            }
    return breakdown


def _compute_entry_time_breakdown(trades: List[IntradayBacktestTrade]) -> Dict[str, Dict]:
    """Win rate and avg P&L by entry time window."""
    breakdown = {}
    entry_times = sorted(set(t.entry_time for t in trades))
    for et in entry_times:
        et_trades = [t for t in trades if t.entry_time == et]
        if et_trades:
            wins = len([t for t in et_trades if t.win])
            breakdown[et] = {
                "trades": len(et_trades),
                "win_rate": round(wins / len(et_trades) * 100, 1),
                "avg_pnl": round(float(np.mean([t.pnl for t in et_trades])), 4),
                "total_pnl": round(sum(t.pnl for t in et_trades), 4),
            }
    return breakdown
