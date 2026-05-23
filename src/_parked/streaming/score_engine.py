"""
Live score recalculation engine.

Recomputes conviction scores and strategy evaluations in real-time
as streaming quote updates arrive from DXFeed.

Options Analytics Team — 2026-04
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from models.black_scholes import black_scholes_price, calculate_greeks
from config import RISK_FREE_RATE

logger = logging.getLogger(__name__)


@dataclass
class LiveScore:
    """Real-time scored position."""
    symbol: str
    strike: float
    option_type: str
    expiry: str
    dte: int

    # Live market data
    spot: float
    bid: float
    ask: float
    mid: float
    iv: float

    # Live greeks
    delta: float
    gamma: float
    theta: float
    vega: float

    # Computed
    theo_price: float       # BS price at current iv
    edge_pct: float         # (theo - mid) / mid * 100
    conviction: float       # 0-100

    updated_at: float       # epoch seconds


@dataclass
class LiveScoreEngine:
    """Recalculates scores when streaming quotes arrive.

    Maintains a dictionary of live scores keyed by streamer symbol.
    Call `on_quote_update()` with each streaming quote to trigger
    recalculation.
    """
    scores: Dict[str, LiveScore] = field(default_factory=dict)
    _r: float = RISK_FREE_RATE
    _callbacks: List[Callable] = field(default_factory=list)
    _update_count: int = 0

    def on_callback(self, fn: Callable):
        """Register a callback invoked on each score update."""
        self._callbacks.append(fn)

    def on_quote_update(self, update) -> Optional[LiveScore]:
        """Process a streaming quote update and recompute the score.

        Parameters
        ----------
        update : QuoteUpdate
            From DXFeedStreamer.

        Returns
        -------
        LiveScore or None if the update can't be scored.
        """
        if update.mid <= 0 or update.iv <= 0:
            return None

        # Parse symbol for strike/type/expiry (streamer symbols like .SPY260417C590)
        parsed = _parse_streamer_symbol(update.symbol)
        if not parsed:
            return None

        underlying, expiry, option_type, strike = parsed
        dte = _compute_dte(expiry)
        if dte <= 0:
            return None

        T = dte / 365.0
        spot = update.underlying if update.underlying > 0 else update.mid * 10  # fallback

        # Compute BS theoretical price
        try:
            theo = black_scholes_price(spot, strike, T, self._r, update.iv, option_type)
        except Exception:
            theo = 0.0

        # Edge
        edge_pct = ((theo - update.mid) / update.mid * 100) if update.mid > 0 else 0.0

        # Simple conviction score: blend of edge + IV level + liquidity proxy
        edge_score = min(abs(edge_pct) * 5, 40)  # max 40 from edge
        iv_score = min(update.iv * 100, 30)       # max 30 from IV level
        liquidity_score = min(update.volume / 100, 30) if update.volume > 0 else 5  # max 30
        conviction = min(edge_score + iv_score + liquidity_score, 100)

        score = LiveScore(
            symbol=update.symbol,
            strike=strike,
            option_type=option_type,
            expiry=expiry,
            dte=dte,
            spot=spot,
            bid=update.bid,
            ask=update.ask,
            mid=update.mid,
            iv=update.iv,
            delta=update.delta,
            gamma=update.gamma,
            theta=update.theta,
            vega=update.vega,
            theo_price=round(theo, 4),
            edge_pct=round(edge_pct, 2),
            conviction=round(conviction, 1),
            updated_at=time.time(),
        )

        self.scores[update.symbol] = score
        self._update_count += 1

        for cb in self._callbacks:
            try:
                cb(score)
            except Exception as e:
                logger.debug("Score callback error: %s", e)

        return score

    def get_top(self, n: int = 20) -> List[LiveScore]:
        """Get top N scores by conviction, descending."""
        ranked = sorted(self.scores.values(), key=lambda s: s.conviction, reverse=True)
        return ranked[:n]

    def get_by_underlying(self, underlying: str) -> List[LiveScore]:
        """Get all scores for a given underlying."""
        underlying = underlying.upper()
        return [s for s in self.scores.values()
                if s.symbol.upper().startswith(f".{underlying}")]

    @property
    def update_count(self) -> int:
        return self._update_count


def _parse_streamer_symbol(symbol: str):
    """Parse a DXFeed streamer symbol like .SPY260417C590.

    Returns (underlying, expiry_str, option_type, strike) or None.
    """
    if not symbol or not symbol.startswith('.'):
        return None

    s = symbol[1:]  # strip leading dot

    # Find the C or P that separates date from strike
    # Format: UNDERLYING YYMMDD C/P STRIKE
    # e.g.: SPY260417C590, NVDA260501P120
    cp_idx = -1
    for i in range(len(s) - 1, 5, -1):
        if s[i] in ('C', 'P') and s[i-1].isdigit() and (i + 1 < len(s) and s[i+1].isdigit()):
            cp_idx = i
            break

    if cp_idx < 0:
        return None

    try:
        option_type = 'call' if s[cp_idx] == 'C' else 'put'
        strike = float(s[cp_idx + 1:])
        date_part = s[cp_idx - 6:cp_idx]  # YYMMDD
        underlying = s[:cp_idx - 6]

        year = 2000 + int(date_part[:2])
        month = int(date_part[2:4])
        day = int(date_part[4:6])
        expiry = f"{year:04d}-{month:02d}-{day:02d}"

        return underlying, expiry, option_type, strike
    except (ValueError, IndexError):
        return None


def _compute_dte(expiry_str: str) -> int:
    """Compute days to expiration from YYYY-MM-DD string."""
    from datetime import datetime, date
    try:
        exp = date.fromisoformat(expiry_str)
        return (exp - date.today()).days
    except ValueError:
        return 0
