"""
Trade Generator — Layer 2 of the trading system.

Takes a MarketState (L1) and produces ranked TradeCandidate objects.

Responsibilities:
    1. Signal confluence scoring — weighted probability estimate, not a checklist
    2. Per-strategy exit rules — from SIGNALS.md exit table
    3. Strike selection using vol surface and dealer walls
    4. DTE selection within strategy-allowed range

The confluence score replaces the old 60% checklist + 40% conviction formula.
Each signal component contributes a continuous 0-1 sub-score, weighted per
config.CHAIN_SCANNER_CONFIG['scoring_weights'].

Options Analytics Team — 2026-04
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Exit rules per strategy (from SIGNALS.md) ────────────────────────────────

@dataclass(frozen=True)
class ExitRule:
    """Per-strategy exit parameters."""
    profit_target_pct: float    # % of credit/debit to take profit
    stop_loss_pct: float        # % of credit/debit to stop out
    time_exit_dte: int          # close at this many DTE remaining
    hold_to_expiry: bool = False

EXIT_RULES: Dict[str, ExitRule] = {
    "iron_condor":      ExitRule(profit_target_pct=50, stop_loss_pct=200, time_exit_dte=1),
    "short_put_spread": ExitRule(profit_target_pct=50, stop_loss_pct=200, time_exit_dte=1),
    "short_call_spread":ExitRule(profit_target_pct=50, stop_loss_pct=200, time_exit_dte=1),
    "long_call_spread": ExitRule(profit_target_pct=75, stop_loss_pct=100, time_exit_dte=2),
    "long_put_spread":  ExitRule(profit_target_pct=75, stop_loss_pct=100, time_exit_dte=2),
    "butterfly":        ExitRule(profit_target_pct=100, stop_loss_pct=100, time_exit_dte=0,
                                 hold_to_expiry=True),
}

# Credit vs debit classification
CREDIT_STRATEGIES = {"iron_condor", "short_put_spread", "short_call_spread"}
DEBIT_STRATEGIES = {"long_call_spread", "long_put_spread", "butterfly"}


# ── Trade candidate output ────────────────────────────────────────────────────

@dataclass
class TradeCandidate:
    """A fully-specified trade candidate ready for sizing (L3)."""
    # Identity
    symbol: str
    strategy: str
    strategy_label: str

    # Structure
    legs: List[Dict]            # [{action, option_type, strike, iv_at_strike}, ...]
    is_credit: bool
    suggested_dte: int
    expiry: Optional[str] = None

    # Confluence scoring (0-100)
    confluence_score: float = 0.0
    score_breakdown: Dict[str, float] = field(default_factory=dict)

    # Edge metrics (from MarketState)
    iv_rv_edge_pct: float = 0.0
    skew_edge: float = 0.0      # skew contribution to edge

    # Exit management
    exit_rule: ExitRule = field(default_factory=lambda: ExitRule(50, 200, 1))

    # Timing
    entry_window: Optional[Tuple[str, str]] = None  # (start_time, end_time) ET

    # Context for display
    rationale: str = ""
    regime: str = ""
    bias_label: str = ""
    dealer_regime: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "strategy": self.strategy,
            "strategy_label": self.strategy_label,
            "legs": self.legs,
            "is_credit": self.is_credit,
            "suggested_dte": self.suggested_dte,
            "expiry": self.expiry,
            "confluence_score": round(self.confluence_score, 1),
            "score_breakdown": {k: round(v, 1) for k, v in self.score_breakdown.items()},
            "iv_rv_edge_pct": round(self.iv_rv_edge_pct, 1),
            "skew_edge": round(self.skew_edge, 3),
            "exit_rule": {
                "profit_target_pct": self.exit_rule.profit_target_pct,
                "stop_loss_pct": self.exit_rule.stop_loss_pct,
                "time_exit_dte": self.exit_rule.time_exit_dte,
                "hold_to_expiry": self.exit_rule.hold_to_expiry,
            },
            "entry_window": self.entry_window,
            "rationale": self.rationale,
            "regime": self.regime,
            "bias_label": self.bias_label,
            "dealer_regime": self.dealer_regime,
        }


# ── Confluence scoring ────────────────────────────────────────────────────────

def _edge_sub_score(market_state, strategy: str) -> float:
    """Score the IV-RV edge signal (0-1).

    This IS the edge. A spread of 5% is the minimum; 15%+ is strong.
    Credit strategies want positive spread; debit want negative.
    """
    edge = market_state.iv_rv_edge_pct
    if strategy in CREDIT_STRATEGIES:
        # Positive edge = IV rich vs realized
        if edge <= 0:
            return 0.0
        return min(1.0, edge / 20.0)  # 20% edge = max score
    else:
        # Negative edge = IV cheap vs realized
        if edge >= 0:
            return 0.0
        return min(1.0, abs(edge) / 20.0)


def _regime_sub_score(market_state, strategy: str) -> float:
    """Score regime alignment (0-1).

    HIGH_IV + credit = good. LOW_IV + debit = good.
    SPIKE penalizes credit heavily.
    """
    regime = market_state.regime
    if strategy in CREDIT_STRATEGIES:
        if regime == "HIGH_IV":
            return 1.0
        if regime == "MODERATE_IV":
            return 0.4
        if regime == "SPIKE":
            return 0.0  # never sell in a spike
        return 0.1  # LOW_IV — wrong environment
    else:
        if regime == "LOW_IV":
            return 1.0
        if regime == "MODERATE_IV":
            return 0.7
        if regime == "SPIKE":
            return 0.5  # debit is ok in spike (small size)
        return 0.2  # HIGH_IV — IV is rich, buying is expensive


def _dealer_sub_score(market_state, strategy: str) -> float:
    """Score dealer positioning alignment (0-1).

    LONG_GAMMA = range-bound → good for credit/butterfly.
    SHORT_GAMMA = trending → good for directional debit.
    """
    dealer = market_state.dealer_regime
    if dealer is None:
        return 0.5  # no data, neutral

    if strategy == "iron_condor":
        return 1.0 if dealer == "LONG_GAMMA" else 0.0  # hard override
    if strategy in CREDIT_STRATEGIES:
        return 0.8 if dealer == "LONG_GAMMA" else 0.3
    if strategy == "butterfly":
        return 0.9 if dealer == "LONG_GAMMA" else 0.4
    # Debit directional
    return 0.7 if dealer == "SHORT_GAMMA" else 0.4


def _bias_sub_score(market_state, strategy: str) -> float:
    """Score directional bias alignment (0-1).

    Directional strategies need bias to agree. Neutral strategies need
    the bias to be neutral.
    """
    score = market_state.bias_score
    label = market_state.bias_label

    if strategy == "iron_condor" or strategy == "butterfly":
        # Neutral is ideal; strong directional is bad
        return max(0.0, 1.0 - abs(score) / 5.0)

    if strategy in ("short_put_spread", "long_call_spread"):
        # Bullish is good
        if score >= 4:
            return 1.0
        if score >= 2:
            return 0.7
        if score >= 0:
            return 0.3
        return 0.0  # bearish bias, wrong direction

    if strategy in ("short_call_spread", "long_put_spread"):
        # Bearish is good
        if score <= -4:
            return 1.0
        if score <= -2:
            return 0.7
        if score <= 0:
            return 0.3
        return 0.0  # bullish bias, wrong direction

    return 0.5


def _skew_sub_score(market_state, strategy: str) -> float:
    """Score vol surface skew alignment (0-1).

    Steep put skew = puts are expensive. Good for selling puts, bad for buying.
    Flat/inverted skew = calls are relatively expensive. Good for selling calls.
    """
    skew = market_state.vol_surface.skew_25d  # put_25d - atm (positive = normal)

    if strategy in ("short_put_spread",):
        # Selling puts: steeper skew = more premium to collect
        if skew > 0.05:
            return 1.0
        if skew > 0.02:
            return 0.7
        return 0.4

    if strategy in ("short_call_spread",):
        # Selling calls: flat/inverted call skew is better
        rr = market_state.vol_surface.skew_rr  # call - put (negative = put skew)
        if rr and rr > -0.01:
            return 0.8  # call skew elevated
        return 0.5

    if strategy in ("long_put_spread",):
        # Buying puts: less skew = cheaper puts
        if skew < 0.02:
            return 0.8
        if skew < 0.04:
            return 0.5
        return 0.3  # puts are expensive due to skew

    if strategy in ("long_call_spread",):
        # Buying calls: normal (calls cheap relative to puts)
        if skew > 0.03:
            return 0.7  # puts skewed, calls relatively cheap
        return 0.5

    # Iron condor / butterfly: moderate skew is fine
    if abs(skew) < 0.06:
        return 0.7
    return 0.4


def _timing_sub_score(market_state, strategy: str) -> float:
    """Score intraday timing quality (0-1).

    Based on current time relative to optimal entry windows.
    If no timestamp or outside market hours, return neutral.
    """
    ts = market_state.timestamp
    if ts is None:
        return 0.5

    hour = ts.hour
    minute = ts.minute
    t = hour + minute / 60.0

    if strategy in CREDIT_STRATEGIES:
        # Best: 10:00-11:00 ET (IV elevated from open, spreads tightening)
        if 10.0 <= t <= 11.0:
            return 1.0
        if 9.5 <= t < 10.0 or 11.0 < t <= 12.0:
            return 0.7
        if 12.0 < t <= 15.0:
            return 0.5
        return 0.3  # late day or pre-market
    else:
        # Best: 15:00-15:45 ET (minimize overnight theta)
        if 15.0 <= t <= 15.75:
            return 1.0
        if 14.0 <= t < 15.0:
            return 0.7
        if 10.0 <= t < 14.0:
            return 0.5
        return 0.3


def compute_confluence_score(market_state, strategy: str) -> Tuple[float, Dict[str, float]]:
    """Compute weighted confluence score for a strategy given market state.

    Returns (score_0_to_100, breakdown_dict).

    Weights from SIGNALS.md conviction table (config.py scoring_weights):
        vol_regime=20%, directional=20%, dealer_regime=20%, garch_edge=15%,
        iv_rank=10%, liquidity=10%, greeks=5%

    Remapped for L2:
        edge=25%, regime=20%, dealer=20%, bias=15%, skew=10%, timing=10%
    """
    from config import CHAIN_SCANNER_CONFIG

    subs = {
        "edge": _edge_sub_score(market_state, strategy),
        "regime": _regime_sub_score(market_state, strategy),
        "dealer": _dealer_sub_score(market_state, strategy),
        "bias": _bias_sub_score(market_state, strategy),
        "skew": _skew_sub_score(market_state, strategy),
        "timing": _timing_sub_score(market_state, strategy),
    }

    # L2 weights — edge is the primary signal
    weights = {
        "edge": 0.25,
        "regime": 0.20,
        "dealer": 0.20,
        "bias": 0.15,
        "skew": 0.10,
        "timing": 0.10,
    }

    raw = sum(subs[k] * weights[k] for k in subs)
    score = round(raw * 100, 1)

    # Breakdown as percentage contribution
    breakdown = {k: round(subs[k] * weights[k] * 100, 1) for k in subs}

    return score, breakdown


# ── Strike selection ──────────────────────────────────────────────────────────

def _strike_increment(spot: float) -> float:
    """Standard strike width for the price level."""
    if spot >= 100:
        return 5.0
    if spot >= 50:
        return 2.5
    return 1.0


def _snap_strike(value: float, inc: float) -> float:
    """Snap a price to the nearest valid strike."""
    return round(value / inc) * inc


def _select_short_strike_from_surface(
    spot: float,
    target_delta: float,
    option_type: str,
    vol_surface,
    dealer_wall: Optional[float] = None,
) -> float:
    """Select short strike using vol surface IV at each strike.

    If dealer wall data is available, anchor to the wall.
    Otherwise, find the strike whose IV-adjusted delta is closest to target.
    """
    inc = _strike_increment(spot)
    iv_by_strike = vol_surface.iv_by_strike

    # If dealer wall is available and within reasonable range, use it
    if dealer_wall is not None:
        moneyness = dealer_wall / spot
        if 0.90 <= moneyness <= 1.10:
            return _snap_strike(dealer_wall, inc)

    # Otherwise, find strike where approximate delta matches target
    # Using simplified BS delta: delta ~ N(d1) where d1 depends on strike IV
    best_strike = _snap_strike(spot, inc)
    best_diff = float('inf')

    for strike, iv in iv_by_strike.items():
        if iv <= 0 or math.isnan(iv):
            continue
        moneyness = strike / spot
        if option_type == "put":
            if moneyness > 1.0:
                continue  # skip ITM puts for short strike
            # Approximate put delta magnitude increases as strike approaches spot
            approx_delta = max(0.01, 1.0 - moneyness) * (1 + iv)
        else:  # call
            if moneyness < 1.0:
                continue  # skip ITM calls for short strike
            approx_delta = max(0.01, moneyness - 1.0) * (1 + iv)

        # Rough mapping: OTM distance / (iv * sqrt(T)) approximates delta region
        diff = abs(approx_delta - target_delta)
        if diff < best_diff:
            best_diff = diff
            best_strike = strike

    return _snap_strike(best_strike, inc)


def build_legs(
    strategy: str,
    spot: float,
    vol_surface=None,
    call_wall: Optional[float] = None,
    put_wall: Optional[float] = None,
    max_pain: Optional[float] = None,
) -> List[Dict]:
    """Build concrete trade legs using vol surface and dealer data.

    Uses dealer walls for short strike anchoring when available.
    Falls back to ATM +/- width otherwise.
    """
    inc = _strike_increment(spot)
    atm = _snap_strike(spot, inc)

    if strategy == "iron_condor":
        # Short call at call wall or ATM + 1 width
        short_call = atm + inc
        if call_wall and 1.0 < call_wall / spot <= 1.08:
            short_call = _snap_strike(call_wall, inc)
        # Short put at put wall or ATM - 1 width
        short_put = atm - inc
        if put_wall and 0.92 <= put_wall / spot < 1.0:
            short_put = _snap_strike(put_wall, inc)
        return [
            {"action": "sell", "option_type": "call", "strike": short_call},
            {"action": "buy", "option_type": "call", "strike": short_call + inc},
            {"action": "sell", "option_type": "put", "strike": short_put},
            {"action": "buy", "option_type": "put", "strike": short_put - inc},
        ]

    if strategy == "short_put_spread":
        short_put = atm - inc
        if put_wall and 0.92 <= put_wall / spot < 1.0:
            short_put = _snap_strike(put_wall, inc)
        return [
            {"action": "sell", "option_type": "put", "strike": short_put},
            {"action": "buy", "option_type": "put", "strike": short_put - inc},
        ]

    if strategy == "short_call_spread":
        short_call = atm + inc
        if call_wall and 1.0 < call_wall / spot <= 1.08:
            short_call = _snap_strike(call_wall, inc)
        return [
            {"action": "sell", "option_type": "call", "strike": short_call},
            {"action": "buy", "option_type": "call", "strike": short_call + inc},
        ]

    if strategy == "long_call_spread":
        # Buy ATM or slightly ITM, sell one width above
        long_strike = atm
        return [
            {"action": "buy", "option_type": "call", "strike": long_strike},
            {"action": "sell", "option_type": "call", "strike": long_strike + inc},
        ]

    if strategy == "long_put_spread":
        long_strike = atm
        return [
            {"action": "buy", "option_type": "put", "strike": long_strike},
            {"action": "sell", "option_type": "put", "strike": long_strike - inc},
        ]

    if strategy == "butterfly":
        # Center at max pain if available, otherwise ATM
        center = atm
        if max_pain is not None:
            mp_moneyness = max_pain / spot
            if 0.95 <= mp_moneyness <= 1.05:
                center = _snap_strike(max_pain, inc)
        return [
            {"action": "buy", "option_type": "call", "strike": center - inc},
            {"action": "sell", "option_type": "call", "strike": center},
            {"action": "sell", "option_type": "call", "strike": center},
            {"action": "buy", "option_type": "call", "strike": center + inc},
        ]

    return []


# ── DTE selection ─────────────────────────────────────────────────────────────

DTE_RANGES = {
    "iron_condor": (7, 14),
    "short_put_spread": (3, 10),
    "short_call_spread": (3, 10),
    "long_call_spread": (3, 14),
    "long_put_spread": (3, 14),
    "butterfly": (0, 7),
}


def select_dte(strategy: str, market_state) -> int:
    """Select optimal DTE within the strategy's allowed range.

    Higher IV → shorter DTE (theta decay faster, capture more).
    Lower IV → longer DTE (need time for move).
    Strong bias → shorter DTE (conviction trade).
    """
    min_dte, max_dte = DTE_RANGES.get(strategy, (3, 14))

    iv_rank = market_state.iv_rank
    bias_strength = abs(market_state.bias_score)

    if strategy in CREDIT_STRATEGIES:
        # High IV rank → shorter DTE to capture rapid theta decay
        if iv_rank > 70:
            dte = min_dte + 1
        elif iv_rank > 50:
            dte = (min_dte + max_dte) // 2
        else:
            dte = max_dte - 1
    elif strategy == "butterfly":
        # Pin plays need time but not too much
        dte = min(5, max_dte)
    else:
        # Debit: strong bias → shorter (momentum), weak → longer (time)
        if bias_strength >= 4:
            dte = min_dte + 1
        elif bias_strength >= 2:
            dte = (min_dte + max_dte) // 2
        else:
            dte = max_dte - 1

    return max(min_dte, min(dte, max_dte))


# ── Entry window ──────────────────────────────────────────────────────────────

def optimal_entry_window(strategy: str, market_state) -> Tuple[str, str]:
    """Return optimal entry window as (start, end) time strings in ET.

    Credit: 10:00-11:00 (IV still elevated, spreads tightening after open).
    Debit: 15:00-15:45 (minimize overnight theta bleed).
    Spike: wait for 10:30-11:30 (let initial panic subside).
    """
    if market_state.regime == "SPIKE":
        return ("10:30", "11:30")

    if strategy in CREDIT_STRATEGIES:
        atr_pctl = market_state.atr_percentile
        if atr_pctl > 60:
            # Trending day — wait for vol to settle
            return ("10:30", "11:30")
        return ("10:00", "11:00")
    else:
        return ("15:00", "15:45")


# ── Main generator ────────────────────────────────────────────────────────────

def generate_trades(market_state) -> List[TradeCandidate]:
    """Generate ranked trade candidates from a MarketState snapshot.

    Pipeline:
        1. Get strategy candidates from MarketState (regime + bias + dealer)
        2. For each candidate, check edge gate (has_edge)
        3. Compute confluence score
        4. Build legs using vol surface + dealer walls
        5. Select DTE and entry window
        6. Rank by confluence score, filter >= 60

    Parameters
    ----------
    market_state : MarketState
        Complete L1 market state snapshot.

    Returns
    -------
    List[TradeCandidate]
        Ranked by confluence score descending. Only includes score >= 60.
    """
    candidates = market_state.strategy_candidates()
    if not candidates:
        logger.info("No strategy candidates for %s (regime=%s, bias=%s)",
                     market_state.symbol, market_state.regime, market_state.bias_label)
        return []

    results = []
    for strategy in candidates:
        # Edge gate — primary filter
        if not market_state.has_edge(strategy):
            logger.debug("No edge for %s/%s (spread=%.4f, edge_pct=%.1f%%)",
                         market_state.symbol, strategy,
                         market_state.iv_rv_spread, market_state.iv_rv_edge_pct)
            continue

        # Confluence score
        score, breakdown = compute_confluence_score(market_state, strategy)

        # Build legs
        legs = build_legs(
            strategy=strategy,
            spot=market_state.spot,
            vol_surface=market_state.vol_surface,
            call_wall=market_state.call_wall,
            put_wall=market_state.put_wall,
            max_pain=market_state.max_pain,
        )

        if not legs:
            continue

        # DTE and timing
        dte = select_dte(strategy, market_state)
        window = optimal_entry_window(strategy, market_state)

        # Exit rule
        exit_rule = EXIT_RULES.get(strategy, ExitRule(50, 200, 1))

        # Skew edge contribution
        skew = market_state.vol_surface.skew_25d

        # Strategy label
        labels = {
            "iron_condor": "Iron Condor",
            "short_put_spread": "Short Put Spread",
            "short_call_spread": "Short Call Spread",
            "long_call_spread": "Long Call Spread",
            "long_put_spread": "Long Put Spread",
            "butterfly": "Butterfly",
        }

        tc = TradeCandidate(
            symbol=market_state.symbol,
            strategy=strategy,
            strategy_label=labels.get(strategy, strategy),
            legs=legs,
            is_credit=strategy in CREDIT_STRATEGIES,
            suggested_dte=dte,
            confluence_score=score,
            score_breakdown=breakdown,
            iv_rv_edge_pct=market_state.iv_rv_edge_pct,
            skew_edge=skew,
            exit_rule=exit_rule,
            entry_window=window,
            rationale=_build_rationale(market_state, strategy, score, breakdown),
            regime=market_state.regime,
            bias_label=market_state.bias_label,
            dealer_regime=market_state.dealer_regime,
        )
        results.append(tc)

    # Rank by confluence score
    results.sort(key=lambda tc: tc.confluence_score, reverse=True)

    # Filter: show if >= 60
    results = [tc for tc in results if tc.confluence_score >= 60]

    return results


def _build_rationale(market_state, strategy: str, score: float,
                     breakdown: Dict[str, float]) -> str:
    """Build human-readable rationale for a trade candidate."""
    top_factors = sorted(breakdown.items(), key=lambda x: x[1], reverse=True)[:3]
    factors_str = ", ".join(f"{k}={v:.0f}" for k, v in top_factors)

    edge_dir = "rich" if market_state.iv_rv_spread > 0 else "cheap"
    return (
        f"{strategy.replace('_', ' ').title()}: "
        f"IV {edge_dir} by {abs(market_state.iv_rv_edge_pct):.0f}% vs GARCH. "
        f"Score {score:.0f} ({factors_str}). "
        f"Regime {market_state.regime}, bias {market_state.bias_label}."
    )
