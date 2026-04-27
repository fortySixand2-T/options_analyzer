"""
Move exhaustion signal for 0 DTE options.

Tracks how much of the expected daily move has been consumed:
- Below 50%: move has room to run — "safe" to enter premium-selling
- 50-80%: meaningful move consumed — "caution", tighter risk
- 80-120%: move largely done — "exhausted", premium selling is safer
- Above 120%: overextended — "overextended", avoid new entries

The intuition: if SPY's expected daily move is $3 and it's already
moved $2.50 from open, 83% of the move is "used up." Further movement
is less likely, making premium selling more attractive — but reversal
risk is also elevated.

Options Analytics Team — 2026-04
"""

import logging

from data.intraday_models import MoveExhaustion

logger = logging.getLogger(__name__)

# ── Exhaustion thresholds ────────────────────────────────────────────────────
SAFE_THRESHOLD = 50.0        # Below → move has room, safe entry
CAUTION_THRESHOLD = 80.0     # 50-80 → proceed with tighter risk
EXHAUSTED_THRESHOLD = 120.0  # 80-120 → move done, premium selling safer
# Above 120 → overextended, avoid new entries


def compute_move_exhaustion(
    current_price: float,
    open_price: float,
    expected_daily_move: float,
) -> MoveExhaustion:
    """Compute how much of the expected daily move has been consumed.

    Parameters
    ----------
    current_price : float
        Current spot price.
    open_price : float
        Today's opening price.
    expected_daily_move : float
        ATM 0DTE straddle price (from day_classifier.get_expected_daily_move_from_chain).

    Returns
    -------
    MoveExhaustion
    """
    intraday_move = current_price - open_price
    abs_move = abs(intraday_move)

    if expected_daily_move <= 0:
        return MoveExhaustion(
            exhaustion_pct=0.0,
            intraday_move=round(intraday_move, 4),
            expected_daily_move=0.0,
            signal="caution",
            detail="No expected move data — cannot compute exhaustion",
        )

    exhaustion_pct = abs_move / expected_daily_move * 100

    if exhaustion_pct < SAFE_THRESHOLD:
        signal = "safe"
        detail = (
            f"Move {abs_move:.2f} is {exhaustion_pct:.0f}% of expected {expected_daily_move:.2f} — "
            f"room to run, safe for new entries"
        )
    elif exhaustion_pct < CAUTION_THRESHOLD:
        signal = "caution"
        detail = (
            f"Move {abs_move:.2f} is {exhaustion_pct:.0f}% of expected {expected_daily_move:.2f} — "
            f"meaningful move consumed, use tighter risk"
        )
    elif exhaustion_pct < EXHAUSTED_THRESHOLD:
        signal = "exhausted"
        detail = (
            f"Move {abs_move:.2f} is {exhaustion_pct:.0f}% of expected {expected_daily_move:.2f} — "
            f"move largely done, premium selling safer"
        )
    else:
        signal = "overextended"
        detail = (
            f"Move {abs_move:.2f} is {exhaustion_pct:.0f}% of expected {expected_daily_move:.2f} — "
            f"overextended, avoid new entries (reversal or continuation risk)"
        )

    logger.info("Move exhaustion: %s", detail)

    return MoveExhaustion(
        exhaustion_pct=round(exhaustion_pct, 2),
        intraday_move=round(intraday_move, 4),
        expected_daily_move=round(expected_daily_move, 4),
        signal=signal,
        detail=detail,
    )
