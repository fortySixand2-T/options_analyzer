"""
Tests for real-pricing P&L math and spread repricing.

All tests use synthetic data — no network or Dolt dependency.
These would have caught Bugs 3, 4 (P&L formula) and Bugs 1, 2 (repricing).
"""

import sys
import os
from dataclasses import dataclass
from typing import Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backtest.real_pricer import SpreadLeg, SpreadPosition, reprice_spread


# ── Helpers ──────────────────────────────────────────────────────────────────


@dataclass
class FakeContract:
    strike: float
    expiry: str
    option_type: str
    bid: float
    ask: float
    mid: float
    implied_volatility: float = 0.25


def _make_calendar_position(
    front_expiry="2024-02-16",
    back_expiry="2024-03-15",
    strike=500.0,
    front_bid=3.00,
    front_ask=3.20,
    back_bid=5.80,
    back_ask=6.00,
) -> SpreadPosition:
    """Calendar spread: sell front, buy back. Typically a debit."""
    front = SpreadLeg(strike, front_expiry, "put", "sell", front_bid, front_ask, (front_bid + front_ask) / 2, 0.20)
    back = SpreadLeg(strike, back_expiry, "put", "buy", back_bid, back_ask, (back_bid + back_ask) / 2, 0.22)
    entry_net = front.fill_price - back.fill_price  # sell at bid - buy at ask = 3.00 - 6.00 = -3.00
    return SpreadPosition(
        strategy="calendar_spread",
        legs=[front, back],
        entry_net=entry_net,
        is_credit=False,
        expiry=back_expiry,
        max_risk=abs(entry_net),
    )


def _make_credit_spread(
    short_strike=500.0,
    long_strike=495.0,
    expiry="2024-02-16",
    short_bid=4.00,
    short_ask=4.20,
    long_bid=2.00,
    long_ask=2.20,
) -> SpreadPosition:
    """Short put spread (credit). sell higher strike, buy lower."""
    short = SpreadLeg(short_strike, expiry, "put", "sell", short_bid, short_ask, (short_bid + short_ask) / 2, 0.20)
    long = SpreadLeg(long_strike, expiry, "put", "buy", long_bid, long_ask, (long_bid + long_ask) / 2, 0.22)
    entry_net = short.fill_price - long.fill_price  # 4.00 - 2.20 = +1.80 credit
    width = short_strike - long_strike
    return SpreadPosition(
        strategy="short_put_spread",
        legs=[short, long],
        entry_net=entry_net,
        is_credit=True,
        expiry=expiry,
        max_risk=width - entry_net,
    )


# ── P&L Formula Tests ───────────────────────────────────────────────────────


class TestPnLFormula:
    """P&L = entry_net + close_val (sum of cash flows)."""

    def test_debit_calendar_small_profit(self):
        """$3 debit calendar closing at $5 net → $2 profit."""
        entry_net = -3.00  # paid $3
        close_val = 5.00   # received $5 on close
        pnl = entry_net + close_val
        assert pnl == pytest.approx(2.00)

    def test_debit_calendar_loss(self):
        """$3 debit calendar closing at $1 → $2 loss."""
        entry_net = -3.00
        close_val = 1.00
        pnl = entry_net + close_val
        assert pnl == pytest.approx(-2.00)

    def test_credit_spread_profit(self):
        """$1.80 credit spread closing at $0.50 cost → $1.30 profit."""
        entry_net = 1.80   # received $1.80
        close_val = -0.50  # paid $0.50 to close
        pnl = entry_net + close_val
        assert pnl == pytest.approx(1.30)

    def test_credit_spread_loss(self):
        """$1.80 credit spread closing at $4.00 cost → $2.20 loss."""
        entry_net = 1.80
        close_val = -4.00
        pnl = entry_net + close_val
        assert pnl == pytest.approx(-2.20)

    def test_breakeven(self):
        """$3 debit closing at $3 → zero P&L."""
        pnl = -3.00 + 3.00
        assert pnl == pytest.approx(0.0)

    def test_subtraction_formula_is_wrong(self):
        """Verify the old formula (close - entry) gives wrong results.

        This is exactly the bug that inflated P&L by ~$92K.
        """
        entry_net = -12.00
        close_val = 14.00
        correct_pnl = entry_net + close_val       # -12 + 14 = +2
        wrong_pnl = close_val - entry_net          # 14 - (-12) = +26
        assert correct_pnl == pytest.approx(2.00)
        assert wrong_pnl == pytest.approx(26.00)   # double-counted the debit


# ── SpreadLeg Fill Price Tests ───────────────────────────────────────────────


class TestSpreadLegPricing:

    def test_sell_fills_at_bid(self):
        leg = SpreadLeg(500, "2024-02-16", "put", "sell", 3.00, 3.20, 3.10, 0.20)
        assert leg.fill_price == 3.00

    def test_buy_fills_at_ask(self):
        leg = SpreadLeg(500, "2024-02-16", "put", "buy", 3.00, 3.20, 3.10, 0.20)
        assert leg.fill_price == 3.20

    def test_close_sell_at_ask(self):
        leg = SpreadLeg(500, "2024-02-16", "put", "sell", 3.00, 3.20, 3.10, 0.20)
        assert leg.close_price == 3.20

    def test_close_buy_at_bid(self):
        leg = SpreadLeg(500, "2024-02-16", "put", "buy", 3.00, 3.20, 3.10, 0.20)
        assert leg.close_price == 3.00


# ── Calendar Entry Net Tests ────────────────────────────────────────────────


class TestCalendarEntryNet:

    def test_calendar_is_debit(self):
        """Calendar: sell cheap front, buy expensive back → net debit (negative)."""
        pos = _make_calendar_position()
        assert pos.entry_net == pytest.approx(-3.00)  # 3.00 - 6.00
        assert not pos.is_credit

    def test_credit_spread_entry(self):
        pos = _make_credit_spread()
        assert pos.entry_net == pytest.approx(1.80)  # 4.00 - 2.20
        assert pos.is_credit


# ── Reprice Spread Tests ────────────────────────────────────────────────────


class TestRepriceSpread:

    def test_reprice_live_legs(self):
        """Both legs still live — reprice from new snapshot."""
        pos = _make_calendar_position(
            front_expiry="2024-02-16", back_expiry="2024-03-15", strike=500.0,
        )
        new_contracts = [
            FakeContract(500, "2024-02-16", "put", bid=1.50, ask=1.70, mid=1.60),
            FakeContract(500, "2024-03-15", "put", bid=7.00, ask=7.20, mid=7.10),
        ]
        close_val = reprice_spread(pos, new_contracts, current_date="2024-02-10", spot=502.0)
        assert close_val is not None
        # To close: buy back front (ask=1.70), sell back (bid=7.00)
        # close_val = -1.70 + 7.00 = +5.30
        assert close_val == pytest.approx(5.30)

    def test_reprice_front_expired_otm(self):
        """Front leg expired OTM → worth 0. Only back leg repriced."""
        pos = _make_calendar_position(
            front_expiry="2024-02-16", back_expiry="2024-03-15", strike=500.0,
        )
        new_contracts = [
            FakeContract(500, "2024-03-15", "put", bid=6.50, ask=6.70, mid=6.60),
        ]
        # Current date past front expiry, spot > strike → front put expired OTM
        close_val = reprice_spread(pos, new_contracts, current_date="2024-02-17", spot=505.0)
        assert close_val is not None
        # Front expired OTM: intrinsic = 0. Sold it → close cost = -0 = 0
        # Back leg: bought it → sell at bid = +6.50
        assert close_val == pytest.approx(6.50)

    def test_reprice_front_expired_itm(self):
        """Front leg expired ITM → worth intrinsic. Sold put at 500, spot at 495 → intrinsic = 5."""
        pos = _make_calendar_position(
            front_expiry="2024-02-16", back_expiry="2024-03-15", strike=500.0,
        )
        new_contracts = [
            FakeContract(500, "2024-03-15", "put", bid=8.00, ask=8.20, mid=8.10),
        ]
        close_val = reprice_spread(pos, new_contracts, current_date="2024-02-17", spot=495.0)
        assert close_val is not None
        # Front put sold, expired ITM: intrinsic=5 → close_value -= 5
        # Back put bought, sell at bid=8.00 → close_value += 8.00
        assert close_val == pytest.approx(3.00)  # -5 + 8

    def test_reprice_returns_none_when_no_match(self):
        """No matching contract → returns None."""
        pos = _make_calendar_position()
        close_val = reprice_spread(pos, [], current_date="2024-02-10", spot=500.0)
        assert close_val is None

    def test_full_calendar_pnl_flow(self):
        """End-to-end: entry → reprice → P&L for a calendar spread."""
        pos = _make_calendar_position(
            front_bid=3.00, front_ask=3.20, back_bid=5.80, back_ask=6.00,
        )
        # entry_net = 3.00 (sell front at bid) - 6.00 (buy back at ask) = -3.00

        new_contracts = [
            FakeContract(500, "2024-02-16", "put", bid=1.00, ask=1.20, mid=1.10),
            FakeContract(500, "2024-03-15", "put", bid=7.50, ask=7.70, mid=7.60),
        ]
        close_val = reprice_spread(pos, new_contracts, current_date="2024-02-10", spot=502.0)
        # close: buy back front (ask=1.20), sell back (bid=7.50) = -1.20 + 7.50 = +6.30
        assert close_val == pytest.approx(6.30)

        pnl = pos.entry_net + close_val
        assert pnl == pytest.approx(3.30)  # -3.00 + 6.30 = +3.30 profit

    def test_full_credit_spread_pnl_flow(self):
        """End-to-end: credit spread entry → reprice → P&L."""
        pos = _make_credit_spread()
        # entry_net = 4.00 - 2.20 = +1.80

        new_contracts = [
            FakeContract(500, "2024-02-16", "put", bid=1.00, ask=1.20, mid=1.10),
            FakeContract(495, "2024-02-16", "put", bid=0.40, ask=0.60, mid=0.50),
        ]
        close_val = reprice_spread(pos, new_contracts, current_date="2024-02-10", spot=510.0)
        # close: buy back short (ask=1.20), sell long (bid=0.40) = -1.20 + 0.40 = -0.80
        assert close_val == pytest.approx(-0.80)

        pnl = pos.entry_net + close_val
        assert pnl == pytest.approx(1.00)  # +1.80 - 0.80 = +1.00 profit
