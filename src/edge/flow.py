"""Options flow signals: put-call parity deviations, OI changes, volume ratios.

Put-call parity deviations:
    Stocks with relatively expensive calls outperform those with expensive
    puts by ~50bp/week (Cremers & Weinbaum 2010). Persistent deviations
    indicate informed trading — options lead stock by 1-5 days.

OI flow signals:
    Large call OI increases predict higher equity returns (Pan & Poteshman 2006).
    Effect is strongest in single-name options at 30-90 DTE.

Volume ratios:
    Put/call volume ratio extremes are contrarian: very high P/C → bullish reversal
    (at 90th percentile), very low P/C → crowded longs, bearish.

References:
    Cremers & Weinbaum (2010), "Deviations from Put-Call Parity and Stock
        Return Predictability"
    Pan & Poteshman (2006), "The Information in Option Volume for Future
        Stock Prices"
    Easley, O'Hara & Srinivas (1998), "Option Volume and Stock Prices"
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class FlowSignal(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class PCPDeviation(str, Enum):
    CALLS_EXPENSIVE = "CALLS_EXPENSIVE"   # bullish — informed call buying
    PUTS_EXPENSIVE = "PUTS_EXPENSIVE"     # bearish — informed put buying
    PARITY = "PARITY"


@dataclass
class PutCallParitySignal:
    """Put-call parity deviation for a single expiry or bucket."""
    dte_bucket: str
    avg_deviation_pct: float    # positive = calls expensive relative to puts
    deviation_regime: PCPDeviation
    pair_count: int             # number of strike pairs measured

    def to_dict(self) -> dict:
        return {
            "dte_bucket": self.dte_bucket,
            "avg_deviation_pct": round(self.avg_deviation_pct, 4),
            "deviation_regime": self.deviation_regime.value,
            "pair_count": self.pair_count,
        }


@dataclass
class OIFlowSignal:
    """Open interest change signal."""
    call_oi_change: float       # net OI change in calls (contracts)
    put_oi_change: float        # net OI change in puts (contracts)
    call_oi_change_pct: float   # % change
    put_oi_change_pct: float
    net_signal: FlowSignal
    large_call_accumulation: bool   # > 2σ call OI increase
    large_put_accumulation: bool

    def to_dict(self) -> dict:
        return {
            "call_oi_change": round(self.call_oi_change, 0),
            "put_oi_change": round(self.put_oi_change, 0),
            "call_oi_change_pct": round(self.call_oi_change_pct, 2),
            "put_oi_change_pct": round(self.put_oi_change_pct, 2),
            "net_signal": self.net_signal.value,
            "large_call_accumulation": self.large_call_accumulation,
            "large_put_accumulation": self.large_put_accumulation,
        }


@dataclass
class VolumeRatioSignal:
    """Put/call volume ratio with contrarian interpretation."""
    put_volume: int
    call_volume: int
    pc_ratio: float
    pc_ratio_percentile: Optional[float]  # vs 20-day history
    signal: FlowSignal

    def to_dict(self) -> dict:
        return {
            "put_volume": self.put_volume,
            "call_volume": self.call_volume,
            "pc_ratio": round(self.pc_ratio, 3),
            "pc_ratio_percentile": round(self.pc_ratio_percentile, 1) if self.pc_ratio_percentile else None,
            "signal": self.signal.value,
        }


@dataclass
class FlowComposite:
    """Composite flow signal combining all sub-signals."""
    pcp_signals: List[PutCallParitySignal]
    oi_signal: Optional[OIFlowSignal]
    volume_signal: Optional[VolumeRatioSignal]
    composite: FlowSignal

    def to_dict(self) -> dict:
        return {
            "pcp_signals": [s.to_dict() for s in self.pcp_signals],
            "oi_signal": self.oi_signal.to_dict() if self.oi_signal else None,
            "volume_signal": self.volume_signal.to_dict() if self.volume_signal else None,
            "composite": self.composite.value,
        }


_PCP_THRESHOLD = 0.02   # 2% deviation from parity is significant
_PC_RATIO_HIGH = 0.90   # 90th percentile → contrarian bullish
_PC_RATIO_LOW = 0.10    # 10th percentile → contrarian bearish
_OI_ZSCORE_THRESHOLD = 2.0

_DTE_BUCKETS: List[Tuple[str, int, int]] = [
    ("14-30", 14, 30),
    ("30-60", 30, 60),
    ("60-90", 60, 90),
    ("90-180", 90, 180),
]


def compute_pcp_deviations(
    chain_pairs: Dict[int, List[Tuple[float, float, float, float]]],
    spot_price: float,
    risk_free_rate: float = 0.05,
) -> List[PutCallParitySignal]:
    """Compute put-call parity deviations across DTE buckets.

    Parameters
    ----------
    chain_pairs : dict
        DTE → [(strike, call_mid, put_mid, expiry_years), ...]
        Each tuple has matched call/put prices at the same strike.
    spot_price : float
        Current underlying price.
    risk_free_rate : float
        Annualized risk-free rate for PCP calculation.
    """
    signals: List[PutCallParitySignal] = []

    for label, min_dte, max_dte in _DTE_BUCKETS:
        deviations = []

        for dte, pairs in chain_pairs.items():
            if not (min_dte <= dte < max_dte):
                continue

            for strike, call_mid, put_mid, T in pairs:
                if call_mid <= 0 or put_mid <= 0 or T <= 0:
                    continue

                # C - P = S - K*exp(-rT) under PCP
                pv_strike = strike * np.exp(-risk_free_rate * T)
                theoretical_diff = spot_price - pv_strike
                actual_diff = call_mid - put_mid
                deviation = (actual_diff - theoretical_diff) / spot_price
                deviations.append(deviation)

        if not deviations:
            continue

        avg_dev = float(np.mean(deviations))

        if avg_dev > _PCP_THRESHOLD:
            regime = PCPDeviation.CALLS_EXPENSIVE
        elif avg_dev < -_PCP_THRESHOLD:
            regime = PCPDeviation.PUTS_EXPENSIVE
        else:
            regime = PCPDeviation.PARITY

        signals.append(PutCallParitySignal(
            dte_bucket=label,
            avg_deviation_pct=avg_dev,
            deviation_regime=regime,
            pair_count=len(deviations),
        ))

    return signals


def compute_oi_flow(
    current_call_oi: int,
    current_put_oi: int,
    prev_call_oi: int,
    prev_put_oi: int,
    historical_call_oi_changes: Optional[np.ndarray] = None,
    historical_put_oi_changes: Optional[np.ndarray] = None,
) -> OIFlowSignal:
    """Compute OI flow signal from day-over-day changes.

    Parameters
    ----------
    current/prev_call_oi, current/prev_put_oi : int
        Today's and yesterday's total OI.
    historical_*_oi_changes : np.ndarray, optional
        20+ days of OI changes for z-score computation.
    """
    call_change = current_call_oi - prev_call_oi
    put_change = current_put_oi - prev_put_oi
    call_pct = (call_change / prev_call_oi * 100) if prev_call_oi > 0 else 0.0
    put_pct = (put_change / prev_put_oi * 100) if prev_put_oi > 0 else 0.0

    large_call = False
    large_put = False

    if historical_call_oi_changes is not None and len(historical_call_oi_changes) >= 20:
        mean_c = float(np.mean(historical_call_oi_changes))
        std_c = float(np.std(historical_call_oi_changes, ddof=1))
        if std_c > 0:
            large_call = (call_change - mean_c) / std_c > _OI_ZSCORE_THRESHOLD

    if historical_put_oi_changes is not None and len(historical_put_oi_changes) >= 20:
        mean_p = float(np.mean(historical_put_oi_changes))
        std_p = float(np.std(historical_put_oi_changes, ddof=1))
        if std_p > 0:
            large_put = (put_change - mean_p) / std_p > _OI_ZSCORE_THRESHOLD

    if large_call and not large_put:
        signal = FlowSignal.BULLISH
    elif large_put and not large_call:
        signal = FlowSignal.BEARISH
    elif call_change > 0 and put_change <= 0:
        signal = FlowSignal.BULLISH
    elif put_change > 0 and call_change <= 0:
        signal = FlowSignal.BEARISH
    else:
        signal = FlowSignal.NEUTRAL

    return OIFlowSignal(
        call_oi_change=float(call_change),
        put_oi_change=float(put_change),
        call_oi_change_pct=call_pct,
        put_oi_change_pct=put_pct,
        net_signal=signal,
        large_call_accumulation=large_call,
        large_put_accumulation=large_put,
    )


def compute_volume_ratio(
    put_volume: int,
    call_volume: int,
    pc_ratio_history: Optional[np.ndarray] = None,
) -> VolumeRatioSignal:
    """Put/call volume ratio with contrarian interpretation.

    Parameters
    ----------
    put_volume, call_volume : int
        Today's total volume.
    pc_ratio_history : np.ndarray, optional
        20+ days of historical P/C ratios for percentile ranking.
    """
    pc_ratio = put_volume / call_volume if call_volume > 0 else 1.0

    percentile = None
    if pc_ratio_history is not None and len(pc_ratio_history) >= 10:
        percentile = float(np.mean(pc_ratio_history <= pc_ratio) * 100)

    # Contrarian: extreme put buying → bullish, extreme call buying → bearish
    if percentile is not None:
        if percentile >= _PC_RATIO_HIGH * 100:
            signal = FlowSignal.BULLISH
        elif percentile <= _PC_RATIO_LOW * 100:
            signal = FlowSignal.BEARISH
        else:
            signal = FlowSignal.NEUTRAL
    else:
        if pc_ratio > 1.5:
            signal = FlowSignal.BULLISH
        elif pc_ratio < 0.5:
            signal = FlowSignal.BEARISH
        else:
            signal = FlowSignal.NEUTRAL

    return VolumeRatioSignal(
        put_volume=put_volume,
        call_volume=call_volume,
        pc_ratio=pc_ratio,
        pc_ratio_percentile=percentile,
        signal=signal,
    )


def compute_flow_composite(
    pcp_signals: List[PutCallParitySignal],
    oi_signal: Optional[OIFlowSignal],
    volume_signal: Optional[VolumeRatioSignal],
) -> FlowComposite:
    """Combine all flow sub-signals into a composite directional signal.

    Weighting: PCP deviations (40%), OI flow (35%), volume ratio (25%).
    """
    score = 0.0
    weight_sum = 0.0

    if pcp_signals:
        pcp_score = 0.0
        for s in pcp_signals:
            if s.deviation_regime == PCPDeviation.CALLS_EXPENSIVE:
                pcp_score += 1.0
            elif s.deviation_regime == PCPDeviation.PUTS_EXPENSIVE:
                pcp_score -= 1.0
        pcp_score /= len(pcp_signals)
        score += 0.40 * pcp_score
        weight_sum += 0.40

    if oi_signal is not None:
        oi_score = 0.0
        if oi_signal.net_signal == FlowSignal.BULLISH:
            oi_score = 1.0
        elif oi_signal.net_signal == FlowSignal.BEARISH:
            oi_score = -1.0
        score += 0.35 * oi_score
        weight_sum += 0.35

    if volume_signal is not None:
        vol_score = 0.0
        if volume_signal.signal == FlowSignal.BULLISH:
            vol_score = 1.0
        elif volume_signal.signal == FlowSignal.BEARISH:
            vol_score = -1.0
        score += 0.25 * vol_score
        weight_sum += 0.25

    if weight_sum > 0:
        score /= weight_sum

    if score > 0.3:
        composite = FlowSignal.BULLISH
    elif score < -0.3:
        composite = FlowSignal.BEARISH
    else:
        composite = FlowSignal.NEUTRAL

    return FlowComposite(
        pcp_signals=pcp_signals,
        oi_signal=oi_signal,
        volume_signal=volume_signal,
        composite=composite,
    )
