"""
Macro event calendar — FOMC, CPI, and options expiration dates.

Used by the regime detector to flag SPIKE when a major
macro event is within N trading days.

Options Analytics Team — 2026-04
"""

from datetime import date, timedelta
from typing import List, Optional, Tuple

# FOMC meeting dates 2026 (announcement day)
FOMC_2026 = [
    date(2026, 1, 29),
    date(2026, 3, 18),
    date(2026, 5, 6),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 10, 28),
    date(2026, 12, 16),
]

# CPI release dates 2026 (8:30 AM ET)
CPI_2026 = [
    date(2026, 1, 14),
    date(2026, 2, 12),
    date(2026, 3, 11),
    date(2026, 4, 10),
    date(2026, 5, 13),
    date(2026, 6, 10),
    date(2026, 7, 14),
    date(2026, 8, 12),
    date(2026, 9, 10),
    date(2026, 10, 13),
    date(2026, 11, 12),
    date(2026, 12, 10),
]

# Monthly options expiration (3rd Friday of each month) 2026
OPEX_2026 = [
    date(2026, 1, 16),
    date(2026, 2, 20),
    date(2026, 3, 20),
    date(2026, 4, 17),
    date(2026, 5, 15),
    date(2026, 6, 19),
    date(2026, 7, 17),
    date(2026, 8, 21),
    date(2026, 9, 18),
    date(2026, 10, 16),
    date(2026, 11, 20),
    date(2026, 12, 18),
]


def days_to_next_event(ref_date: Optional[date] = None,
                       lookback_days: int = 5) -> Tuple[Optional[str], int]:
    """Find the nearest upcoming macro event.

    Parameters
    ----------
    ref_date : date, optional
        Reference date (default: today).
    lookback_days : int
        Also flag events within this many days in the past (post-event vol).

    Returns
    -------
    (event_type, days_away) or (None, 999)
        event_type: 'FOMC', 'CPI', 'OPEX', or None
        days_away: calendar days to event (negative = past)
    """
    if ref_date is None:
        ref_date = date.today()

    all_events: List[Tuple[str, date]] = []
    for d in FOMC_2026:
        all_events.append(('FOMC', d))
    for d in CPI_2026:
        all_events.append(('CPI', d))
    for d in OPEX_2026:
        all_events.append(('OPEX', d))

    best_type = None
    best_days = 999

    for event_type, event_date in all_events:
        delta = (event_date - ref_date).days
        # Consider events from -lookback_days to +30 days
        if -lookback_days <= delta <= 30:
            if abs(delta) < abs(best_days):
                best_type = event_type
                best_days = delta

    return best_type, best_days


def is_event_window(ref_date: Optional[date] = None,
                    days_before: int = 2,
                    days_after: int = 1) -> Tuple[bool, Optional[str], int]:
    """Check if we're in an event window (N days before/after a macro event).

    Returns (in_window, event_type, days_to_event).
    """
    if ref_date is None:
        ref_date = date.today()

    event_type, days_away = days_to_next_event(ref_date, lookback_days=days_after)

    if event_type is None:
        return False, None, 999

    in_window = -days_after <= days_away <= days_before
    return in_window, event_type, days_away
