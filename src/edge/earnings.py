"""Earnings calendar and IV inflation scoring.

IV inflates 5-10 days before earnings and crushes after.
This module detects upcoming earnings and scores how inflated
IV is relative to a baseline — the primary signal for event-driven
straddle/strangle entries and credit spread avoidance.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class EarningsInfo:
    """Earnings proximity and IV inflation data for a ticker."""
    has_earnings: bool = False
    earnings_date: Optional[str] = None     # YYYY-MM-DD
    days_to_earnings: Optional[int] = None  # calendar days (negative = past)
    iv_inflation: float = 0.0               # 0-1 score of how inflated IV is
    expected_move_pct: float = 0.0          # market-implied move as % of spot
    in_earnings_window: bool = False        # within actionable window (2-10 days before)
    post_earnings: bool = False             # within 2 days after earnings

    def to_dict(self) -> dict:
        return {
            "has_earnings": self.has_earnings,
            "earnings_date": self.earnings_date,
            "days_to_earnings": self.days_to_earnings,
            "iv_inflation": round(self.iv_inflation, 3),
            "expected_move_pct": round(self.expected_move_pct, 2),
            "in_earnings_window": self.in_earnings_window,
            "post_earnings": self.post_earnings,
        }


def get_earnings_date(ticker: str) -> Optional[str]:
    """Get next earnings date for a ticker via yfinance.

    Returns YYYY-MM-DD string or None if unavailable.
    Index tickers (^SPX, ^NDX, SPY, QQQ, IWM) don't have earnings.
    """
    index_tickers = {"^SPX", "^NDX", "^GSPC", "^DJI", "^RUT",
                     "SPY", "QQQ", "IWM", "DIA", "XLF", "XLK"}
    if ticker.upper() in index_tickers:
        return None

    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is None or cal.empty:
            return None
        if "Earnings Date" in cal.index:
            dates = cal.loc["Earnings Date"]
            if hasattr(dates, "iloc") and len(dates) > 0:
                next_date = dates.iloc[0]
                if hasattr(next_date, "strftime"):
                    return next_date.strftime("%Y-%m-%d")
                return str(next_date)[:10]
        if hasattr(cal, "columns") and len(cal.columns) > 0:
            first_col = cal.columns[0]
            if hasattr(first_col, "strftime"):
                return first_col.strftime("%Y-%m-%d")
    except Exception as e:
        logger.debug("Failed to fetch earnings for %s: %s", ticker, e)

    return None


def compute_earnings_info(
    ticker: str,
    current_iv: float,
    baseline_iv: float,
    spot: float = 0.0,
    atm_straddle_price: float = 0.0,
    ref_date: Optional[date] = None,
    earnings_date_str: Optional[str] = None,
) -> EarningsInfo:
    """Build full earnings info for a ticker.

    Parameters
    ----------
    ticker : str
        Ticker symbol.
    current_iv : float
        Current ATM IV.
    baseline_iv : float
        Baseline IV (e.g. HV30 or recent non-event IV).
    spot : float
        Current spot price (for expected move calc).
    atm_straddle_price : float
        ATM straddle price (for expected move calc). If 0, estimated from IV.
    ref_date : date, optional
        Reference date (default: today).
    earnings_date_str : str, optional
        Pre-fetched earnings date. If None, fetched via yfinance.
    """
    if ref_date is None:
        ref_date = date.today()

    if earnings_date_str is None:
        earnings_date_str = get_earnings_date(ticker)

    if earnings_date_str is None:
        return EarningsInfo()

    try:
        earnings_date = datetime.strptime(earnings_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return EarningsInfo()

    days = (earnings_date - ref_date).days

    iv_inflation = compute_iv_inflation(current_iv, baseline_iv)

    # Actionable window: 2-10 days before earnings
    in_window = 2 <= days <= 10

    # Post-earnings: within 2 days after
    post = -2 <= days < 0

    # Expected move
    exp_move_pct = 0.0
    if spot > 0 and days is not None and days > 0:
        if atm_straddle_price > 0:
            exp_move_pct = (atm_straddle_price / spot) * 100
        elif current_iv > 0:
            # Estimate: IV * sqrt(days/365) * spot, as % of spot
            exp_move_pct = current_iv * (days / 365) ** 0.5 * 100

    return EarningsInfo(
        has_earnings=True,
        earnings_date=earnings_date_str,
        days_to_earnings=days,
        iv_inflation=iv_inflation,
        expected_move_pct=exp_move_pct,
        in_earnings_window=in_window,
        post_earnings=post,
    )


def compute_iv_inflation(current_iv: float, baseline_iv: float) -> float:
    """Score how inflated IV is relative to baseline.

    Returns 0-1 where:
    - 0.0 = IV at or below baseline (no inflation)
    - 0.5 = IV ~25% above baseline (moderate inflation)
    - 1.0 = IV 50%+ above baseline (heavy pre-earnings inflation)
    """
    if baseline_iv <= 0 or current_iv <= 0:
        return 0.0

    inflation_ratio = (current_iv - baseline_iv) / baseline_iv

    if inflation_ratio <= 0:
        return 0.0

    # Map 0-50% inflation to 0-1 score
    return min(inflation_ratio / 0.50, 1.0)


def expected_move_from_straddle(straddle_price: float, spot: float) -> float:
    """Market-implied expected move from ATM straddle price.

    The straddle price approximates the market's expected move
    through the earnings event (±straddle / spot).
    """
    if spot <= 0:
        return 0.0
    return (straddle_price / spot) * 100
