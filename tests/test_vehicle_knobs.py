"""
Tests for the Phase-2 (F-023) vehicle knobs in chain_replay._select_strikes:
debit_itm_pct (deeper-ITM long leg) and debit_width_pct (spread width), plus the
guarantee that defaults reproduce the legacy narrow-ATM spread exactly.

Pure/synthetic — builds a single-expiry chain around spot=100 and inspects the
selected legs. No DB, no network.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backtest.chain_replay import _select_strikes


def _chain(spot=100.0, expiry="2020-01-31", snap="2020-01-15"):
    """Calls + puts at every integer strike 80..120 for one expiry."""
    out = []
    for k in range(80, 121):
        for ot in ("call", "put"):
            out.append({"option_type": ot, "strike": float(k), "expiry": expiry,
                        "_snap_date": snap, "bid": 1.0, "ask": 1.1, "mid": 1.05,
                        "implied_volatility": 0.2, "open_interest": 0})
    return out


def _legs(pos):
    """Return (buy_strike, sell_strike) for a 2-leg debit spread."""
    buy = next(l["contract"]["strike"] for l in pos["legs"] if l["side"] == "buy")
    sell = next(l["contract"]["strike"] for l in pos["legs"] if l["side"] == "sell")
    return buy, sell


def test_long_call_default_is_atm_adjacent():
    # itm=0, width=0 → buy ATM (100), sell the adjacent strike (101). Legacy behaviour.
    pos = _select_strikes(_chain(), 100.0, "long_call_spread", 0.20)
    buy, sell = _legs(pos)
    assert buy == 100.0 and sell == 101.0
    assert pos["is_credit"] is False


def test_long_call_itm_deepens_long_leg():
    # 6% ITM → long call strike ≈ 94 (below spot = in the money for a call).
    pos = _select_strikes(_chain(), 100.0, "long_call_spread", 0.20, itm_pct=0.06)
    buy, _ = _legs(pos)
    assert buy == 94.0


def test_long_call_width_sets_short_leg():
    # 5%-of-spot width → short strike ≈ buy + 5 = 105.
    pos = _select_strikes(_chain(), 100.0, "long_call_spread", 0.20, width_pct=0.05)
    buy, sell = _legs(pos)
    assert buy == 100.0 and sell == 105.0


def test_long_call_itm_and_width_combine():
    pos = _select_strikes(_chain(), 100.0, "long_call_spread", 0.20,
                          itm_pct=0.04, width_pct=0.05)
    buy, sell = _legs(pos)
    assert buy == 96.0 and sell == 101.0      # 96 long, +5 = 101 short


def test_long_put_default_is_atm_adjacent():
    pos = _select_strikes(_chain(), 100.0, "long_put_spread", 0.20)
    buy, sell = _legs(pos)
    assert buy == 100.0 and sell == 99.0      # buy ATM put, sell adjacent below


def test_long_put_itm_and_width():
    # ITM put is ABOVE spot; width sets short leg below the long strike.
    pos = _select_strikes(_chain(), 100.0, "long_put_spread", 0.20,
                          itm_pct=0.05, width_pct=0.05)
    buy, sell = _legs(pos)
    assert buy == 105.0 and sell == 100.0     # 105 long, -5 = 100 short
