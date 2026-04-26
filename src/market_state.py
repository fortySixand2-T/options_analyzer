"""
Market State — Layer 1 of the trading system.

Aggregates all signal layers into a single snapshot that answers:
"Is there a tradeable edge right now, and what kind?"

Combines:
    - Vol regime (V1-V5): regime classification + IV-RV spread
    - Vol surface skew: 25-delta put IV vs ATM IV
    - Directional bias (D1-D8): from bias_detector
    - Dealer positioning (F1-F7): from GEX/chain data
    - Chain quality: bid-ask spreads, OI depth

The IV-RV spread (GARCH forward vol vs chain IV) is the primary edge
signal. Everything else is a filter or sizing input.

Options Analytics Team — 2026-04
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Credit strategies: positive IV-RV spread = edge
CREDIT_STRATEGIES = {"iron_condor", "short_put_spread", "short_call_spread"}
# Debit strategies: negative IV-RV spread = edge
DEBIT_STRATEGIES = {"long_call_spread", "long_put_spread", "butterfly"}


@dataclass
class VolSurface:
    """Vol surface metrics from the options chain."""
    atm_iv: float                       # ATM implied vol (annualized decimal)
    put_25d_iv: Optional[float] = None  # 25-delta put IV
    call_25d_iv: Optional[float] = None # 25-delta call IV
    skew_25d: float = 0.0              # put_25d_iv - atm_iv (positive = normal skew)
    skew_rr: float = 0.0               # 25d risk reversal: call_25d - put_25d (negative = put skew)
    iv_by_strike: Dict[float, float] = field(default_factory=dict)


@dataclass
class ChainQuality:
    """Bid-ask spread and liquidity metrics from the chain."""
    avg_spread_pct: float = 0.0         # avg (ask-bid)/mid across near-term ATM
    median_spread_pct: float = 0.0      # median spread
    total_oi: int = 0                   # total open interest
    avg_oi_per_strike: float = 0.0      # average OI per strike
    liquid_strikes: int = 0             # strikes with OI > 100 and spread < 10%
    quality_score: float = 0.0          # 0-1, higher = better to trade


@dataclass
class MarketState:
    """Complete market state snapshot for trade decisions.

    This is the single object that flows into the trade generation layer.
    Everything needed to decide "should I trade, and what?" is here.
    """
    # Identity
    symbol: str
    spot: float
    timestamp: datetime

    # Vol regime (Layer 1 of SIGNALS.md)
    regime: str                         # HIGH_IV, MODERATE_IV, LOW_IV, SPIKE
    regime_rationale: str
    iv_rank: float                      # 0-100
    vix: float
    vix_term_slope: float               # (VIX3M - VIX) / VIX * 100

    # The edge: IV vs realized vol
    chain_iv: float                     # current ATM IV from chain
    garch_vol: float                    # GARCH forward vol estimate
    iv_rv_spread: float                 # chain_iv - garch_vol (positive = IV rich)
    iv_rv_edge_pct: float               # spread / chain_iv * 100
    hv20: float                         # 20-day historical vol (annualized)

    # Vol surface
    vol_surface: VolSurface

    # Chain quality
    chain_quality: ChainQuality

    # Directional bias (Layer 2)
    bias_label: str                     # STRONG_BULLISH to STRONG_BEARISH
    bias_score: int                     # raw weighted score
    atr_percentile: float               # trending vs ranging

    # Dealer positioning (Layer 3)
    dealer_regime: Optional[str] = None # LONG_GAMMA or SHORT_GAMMA
    net_gex: float = 0.0
    gamma_flip: float = 0.0
    gamma_flip_distance_pct: float = 0.0  # (spot - gamma_flip) / spot * 100
    call_wall: Optional[float] = None
    put_wall: Optional[float] = None
    max_pain: Optional[float] = None
    put_call_ratio: Optional[float] = None

    # Event risk
    event_active: bool = False
    event_type: Optional[str] = None
    event_days: int = 0

    def has_edge(self, strategy: str) -> bool:
        """Does the current state present a tradeable edge for this strategy?

        Primary gate: IV-RV spread must be meaningful.
        Secondary: chain must be liquid enough to execute.

        Backtested edge requirements (SPY 2022-2026, 3% slippage):
        - Credit strategies: IV must be rich (edge > 5%) — validated for short_put_spread
        - Long put spread: IV must be cheap (edge > 5%) — Sharpe 3.38 with filter
        - Long call spread: directional momentum > IV cheapness — no edge gate needed
          (edge filter drops Sharpe from 1.74 to -0.87; regime filter helps instead)
        - Butterfly: no edge gate needed — structure profits from pin, not IV direction
        """
        if self.chain_quality.quality_score < 0.3:
            return False  # chain too illiquid

        if strategy in CREDIT_STRATEGIES:
            # Selling premium: need IV to be rich vs realized
            return self.iv_rv_spread > 0.01 and self.iv_rv_edge_pct > 5.0
        elif strategy == "long_put_spread":
            # Buying put spreads: need IV cheap — backtested edge > 5% required
            return self.iv_rv_spread < -0.01 and self.iv_rv_edge_pct < -5.0
        elif strategy == "long_call_spread":
            # Directional: edge filter hurts this strategy (kills momentum trades)
            # Regime filter is the right gate (handled in strategy_candidates)
            return True
        elif strategy == "butterfly":
            # Pin strategy: profits from price convergence, not IV direction
            return True
        return False

    def edge_magnitude(self) -> float:
        """Absolute edge magnitude for sizing decisions."""
        return abs(self.iv_rv_edge_pct)

    def strategy_candidates(self) -> List[str]:
        """Which strategies are viable in this state?

        Based on regime + bias + dealer, returns strategies worth evaluating.
        Does NOT check edge — that's a separate gate.
        """
        candidates = []

        if self.regime == "SPIKE":
            # Small debit only or stand aside
            if self.bias_score >= 2:
                candidates.append("long_call_spread")
            elif self.bias_score <= -2:
                candidates.append("long_put_spread")
            return candidates

        if self.regime == "HIGH_IV":
            if self.bias_label == "NEUTRAL" and self.dealer_regime == "LONG_GAMMA":
                candidates.append("iron_condor")
            if self.bias_score >= 2:
                candidates.append("short_put_spread")
            if self.bias_score <= -2:
                candidates.append("short_call_spread")

        if self.regime in ("MODERATE_IV", "LOW_IV"):
            if self.bias_label == "NEUTRAL":
                candidates.append("butterfly")
            if self.bias_score >= 2:
                candidates.append("long_call_spread")
            if self.bias_score <= -2:
                candidates.append("long_put_spread")
            if self.bias_score >= 4:
                candidates.append("long_call_spread")  # tight, 3-5 DTE
            if self.bias_score <= -4:
                candidates.append("long_put_spread")   # tight, 3-5 DTE

        return list(dict.fromkeys(candidates))  # dedupe preserving order

    def to_dict(self) -> dict:
        """Serialize for API response."""
        return {
            "symbol": self.symbol,
            "spot": self.spot,
            "timestamp": self.timestamp.isoformat(),
            "regime": self.regime,
            "regime_rationale": self.regime_rationale,
            "iv_rank": round(self.iv_rank, 1),
            "vix": round(self.vix, 2),
            "vix_term_slope": round(self.vix_term_slope, 2),
            "chain_iv": round(self.chain_iv, 4),
            "garch_vol": round(self.garch_vol, 4),
            "iv_rv_spread": round(self.iv_rv_spread, 4),
            "iv_rv_edge_pct": round(self.iv_rv_edge_pct, 1),
            "hv20": round(self.hv20, 4),
            "vol_surface": {
                "atm_iv": round(self.vol_surface.atm_iv, 4),
                "put_25d_iv": round(self.vol_surface.put_25d_iv, 4) if self.vol_surface.put_25d_iv else None,
                "call_25d_iv": round(self.vol_surface.call_25d_iv, 4) if self.vol_surface.call_25d_iv else None,
                "skew_25d": round(self.vol_surface.skew_25d, 4),
                "skew_rr": round(self.vol_surface.skew_rr, 4),
            },
            "chain_quality": {
                "avg_spread_pct": round(self.chain_quality.avg_spread_pct, 2),
                "median_spread_pct": round(self.chain_quality.median_spread_pct, 2),
                "total_oi": self.chain_quality.total_oi,
                "liquid_strikes": self.chain_quality.liquid_strikes,
                "quality_score": round(self.chain_quality.quality_score, 2),
            },
            "bias": {
                "label": self.bias_label,
                "score": self.bias_score,
                "atr_percentile": round(self.atr_percentile, 1),
            },
            "dealer": {
                "regime": self.dealer_regime,
                "net_gex": round(self.net_gex, 4),
                "gamma_flip": round(self.gamma_flip, 2),
                "gamma_flip_distance_pct": round(self.gamma_flip_distance_pct, 2),
                "call_wall": self.call_wall,
                "put_wall": self.put_wall,
                "max_pain": self.max_pain,
                "put_call_ratio": round(self.put_call_ratio, 3) if self.put_call_ratio else None,
            },
            "event": {
                "active": self.event_active,
                "type": self.event_type,
                "days": self.event_days,
            },
            "edge": {
                "has_credit_edge": self.has_edge("iron_condor"),
                "has_debit_edge": self.has_edge("long_call_spread"),
                "magnitude": round(self.edge_magnitude(), 1),
                "candidates": self.strategy_candidates(),
            },
        }


# ── Builder ─────────────────────────────────────────────────────────────────


def compute_vol_surface(chain_snapshot, spot: float) -> VolSurface:
    """Extract vol surface metrics from an options chain.

    Finds ATM IV, 25-delta put/call IV, and computes skew measures.
    Uses the nearest expiry with sufficient data.
    """
    from models.black_scholes import calculate_greeks
    from config import RISK_FREE_RATE

    contracts = chain_snapshot.contracts
    if not contracts:
        return VolSurface(atm_iv=0.20)

    now = datetime.now()

    # Group by expiry, pick nearest with enough contracts
    by_expiry = {}
    for c in contracts:
        by_expiry.setdefault(c.expiry, []).append(c)

    # Sort expiries, pick the first with >= 6 contracts
    sorted_expiries = sorted(by_expiry.keys())
    target_contracts = []
    target_expiry = None
    for exp in sorted_expiries:
        if len(by_expiry[exp]) >= 6:
            target_contracts = by_expiry[exp]
            target_expiry = exp
            break

    if not target_contracts:
        target_contracts = contracts
        target_expiry = sorted_expiries[0] if sorted_expiries else None

    # Compute T for this expiry
    T = 7.0 / 365.0  # fallback
    if target_expiry:
        try:
            exp_dt = datetime.strptime(target_expiry, '%Y-%m-%d')
            T = max((exp_dt - now).days / 365.0, 1 / 365.0)
        except (ValueError, TypeError):
            pass

    # Find ATM IV: contract with strike closest to spot
    calls = [c for c in target_contracts if c.option_type == "call"]
    puts = [c for c in target_contracts if c.option_type == "put"]

    atm_iv = 0.20
    if calls:
        atm_call = min(calls, key=lambda c: abs(c.strike - spot))
        iv = atm_call.implied_volatility
        if iv == iv and iv > 0:  # not NaN
            atm_iv = iv

    # Find 25-delta strikes using BS greeks
    put_25d_iv = None
    call_25d_iv = None

    for c in puts:
        iv = c.implied_volatility
        if iv != iv or iv <= 0:
            continue
        try:
            greeks = calculate_greeks(
                S=spot, K=c.strike, T=T, r=RISK_FREE_RATE,
                sigma=iv, option_type="put",
            )
            delta = abs(greeks["Delta"])
            if 0.20 <= delta <= 0.30:
                # Closest to 25-delta
                if put_25d_iv is None or abs(delta - 0.25) < abs(_prev_delta - 0.25):
                    put_25d_iv = iv
                    _prev_delta = delta
        except Exception:
            continue
    _prev_delta = 1.0  # reset

    for c in calls:
        iv = c.implied_volatility
        if iv != iv or iv <= 0:
            continue
        try:
            greeks = calculate_greeks(
                S=spot, K=c.strike, T=T, r=RISK_FREE_RATE,
                sigma=iv, option_type="call",
            )
            delta = abs(greeks["Delta"])
            if 0.20 <= delta <= 0.30:
                if call_25d_iv is None or abs(delta - 0.25) < abs(_prev_delta - 0.25):
                    call_25d_iv = iv
                    _prev_delta = delta
        except Exception:
            continue

    # Skew measures
    skew_25d = (put_25d_iv - atm_iv) if put_25d_iv else 0.0
    skew_rr = 0.0
    if call_25d_iv and put_25d_iv:
        skew_rr = call_25d_iv - put_25d_iv  # negative = put skew (normal)

    # IV by strike for the target expiry
    iv_by_strike = {}
    for c in target_contracts:
        iv = c.implied_volatility
        if iv == iv and iv > 0:
            iv_by_strike[c.strike] = iv

    return VolSurface(
        atm_iv=atm_iv,
        put_25d_iv=put_25d_iv,
        call_25d_iv=call_25d_iv,
        skew_25d=skew_25d,
        skew_rr=skew_rr,
        iv_by_strike=iv_by_strike,
    )


def compute_chain_quality(chain_snapshot, spot: float) -> ChainQuality:
    """Compute liquidity and bid-ask quality metrics from the chain.

    Focuses on near-the-money contracts (0.85-1.15 moneyness) which
    are the tradeable region.
    """
    contracts = chain_snapshot.contracts
    if not contracts:
        return ChainQuality()

    spreads = []
    total_oi = 0
    liquid_count = 0

    for c in contracts:
        # Focus on near-the-money
        moneyness = c.strike / spot if spot > 0 else 1.0
        if moneyness < 0.85 or moneyness > 1.15:
            continue

        oi = getattr(c, 'open_interest', 0) or 0
        total_oi += oi

        mid = c.mid
        if mid > 0:
            spread_pct = (c.ask - c.bid) / mid * 100
            spreads.append(spread_pct)
            if oi > 100 and spread_pct < 10:
                liquid_count += 1

    if not spreads:
        return ChainQuality()

    avg_spread = float(np.mean(spreads))
    median_spread = float(np.median(spreads))
    n_strikes = len(spreads)
    avg_oi = total_oi / n_strikes if n_strikes > 0 else 0

    # Quality score: 0-1
    # Good: tight spreads (<5%), deep OI (>500 avg), many liquid strikes (>10)
    spread_score = max(0, 1.0 - avg_spread / 10.0)  # 0% spread = 1.0, 10% = 0
    oi_score = min(1.0, avg_oi / 500.0)              # 500 avg OI = 1.0
    liquid_score = min(1.0, liquid_count / 10.0)      # 10 liquid strikes = 1.0
    quality_score = 0.4 * spread_score + 0.3 * oi_score + 0.3 * liquid_score

    return ChainQuality(
        avg_spread_pct=avg_spread,
        median_spread_pct=median_spread,
        total_oi=total_oi,
        avg_oi_per_strike=avg_oi,
        liquid_strikes=liquid_count,
        quality_score=quality_score,
    )


def build_market_state(
    symbol: str,
    chain_snapshot=None,
    history_data=None,
    regime_result=None,
    bias_result=None,
    dealer_data=None,
) -> MarketState:
    """Build a complete MarketState from available data sources.

    This is the main entry point. It fetches any missing data and
    assembles the full state snapshot.

    Parameters
    ----------
    symbol : str
        Ticker symbol.
    chain_snapshot : ChainSnapshot, optional
        Options chain. Fetched from yfinance if not provided.
    history_data : HistoryData, optional
        Historical prices. Fetched from yfinance if not provided.
    regime_result : RegimeResult, optional
        Pre-computed regime. Detected if not provided.
    bias_result : BiasResult, optional
        Pre-computed bias. Detected from history if not provided.
    dealer_data : DealerData, optional
        Pre-computed dealer positioning. Computed from chain if not provided.

    Returns
    -------
    MarketState
    """
    from scanner.providers.yfinance_provider import YFinanceProvider
    from scanner.providers.flashalpha_client import (
        DealerData, fetch_gex, compute_dealer_data_from_chain,
    )
    from scanner.iv_rank import compute_iv_metrics
    from regime.detector import detect_regime
    from bias_detector import detect_bias
    from monte_carlo.garch_vol import fit_garch11
    from config import CHAIN_SCANNER_CONFIG

    now = datetime.now()
    provider = YFinanceProvider(delay=0.5)

    # 1. Fetch chain if needed
    if chain_snapshot is None:
        chain_snapshot = provider.get_chain(symbol, min_dte=0, max_dte=14)
    spot = chain_snapshot.spot
    if math.isnan(spot) or spot <= 0:
        spot = provider.get_spot(symbol)

    # 2. Fetch history if needed
    if history_data is None:
        history_data = provider.get_history(
            symbol, days=CHAIN_SCANNER_CONFIG["garch"]["history_days"],
        )

    # 3. Compute GARCH forward vol
    returns = history_data.returns
    garch_vol = 0.20  # fallback
    if len(returns) >= CHAIN_SCANNER_CONFIG["garch"]["min_returns"]:
        try:
            garch_fit = fit_garch11(returns)
            garch_vol = garch_fit["sigma0"]
        except Exception as e:
            logger.warning("GARCH fit failed for %s: %s", symbol, e)

    # 4. Vol surface from chain
    vol_surface = compute_vol_surface(chain_snapshot, spot)
    chain_iv = vol_surface.atm_iv

    # 5. IV-RV spread (the edge)
    iv_rv_spread = chain_iv - garch_vol
    iv_rv_edge_pct = (iv_rv_spread / chain_iv * 100) if chain_iv > 0 else 0.0

    # 6. HV20
    hv20 = history_data.realized_vol_30d  # closest available
    if math.isnan(hv20):
        hv20 = 0.20

    # 7. IV rank
    iv_metrics = compute_iv_metrics(chain_iv, history_data)
    iv_rank = iv_metrics["iv_rank"]

    # 8. Regime
    if regime_result is None:
        regime_result = detect_regime(iv_rank=iv_rank)
    regime = regime_result.regime.value
    regime_rationale = regime_result.rationale

    # 9. Bias
    if bias_result is None:
        try:
            closes = history_data.closes
            if hasattr(closes, 'index'):
                # Build a DataFrame with OHLCV from closes
                df = closes.to_frame(name='Close')
                df['Open'] = df['Close']
                df['High'] = df['Close']
                df['Low'] = df['Close']
                df['Volume'] = 0
                bias_result = detect_bias(df)
            else:
                bias_result = None
        except Exception as e:
            logger.warning("Bias detection failed for %s: %s", symbol, e)
            bias_result = None

    bias_label = bias_result.label if bias_result else "NEUTRAL"
    bias_score = bias_result.score if bias_result else 0
    atr_pctl = bias_result.atr_percentile if bias_result else 50.0

    # 10. Dealer positioning
    if dealer_data is None:
        dealer_data = fetch_gex(symbol)
        if dealer_data is None and chain_snapshot.contracts:
            try:
                dealer_data = compute_dealer_data_from_chain(chain_snapshot)
            except Exception as e:
                logger.warning("Chain dealer fallback failed for %s: %s", symbol, e)

    # 11. Chain quality
    chain_quality = compute_chain_quality(chain_snapshot, spot)

    # 12. VIX data from regime
    vix_val = regime_result.vix.vix
    vix_slope = regime_result.vix.term_structure_slope

    # 13. Dealer fields
    dealer_regime = dealer_data.dealer_regime if dealer_data else None
    net_gex = dealer_data.net_gex if dealer_data else 0.0
    gamma_flip = dealer_data.gamma_flip if dealer_data else spot
    gamma_flip_dist = ((spot - gamma_flip) / spot * 100) if spot > 0 else 0.0
    call_wall = dealer_data.call_wall if dealer_data else None
    put_wall = dealer_data.put_wall if dealer_data else None
    max_pain = dealer_data.max_pain if dealer_data else None
    pc_ratio = dealer_data.put_call_ratio if dealer_data else None

    return MarketState(
        symbol=symbol.upper(),
        spot=spot,
        timestamp=now,
        regime=regime,
        regime_rationale=regime_rationale,
        iv_rank=iv_rank,
        vix=vix_val,
        vix_term_slope=vix_slope,
        chain_iv=chain_iv,
        garch_vol=garch_vol,
        iv_rv_spread=iv_rv_spread,
        iv_rv_edge_pct=iv_rv_edge_pct,
        hv20=hv20,
        vol_surface=vol_surface,
        chain_quality=chain_quality,
        bias_label=bias_label,
        bias_score=bias_score,
        atr_percentile=atr_pctl,
        dealer_regime=dealer_regime,
        net_gex=net_gex,
        gamma_flip=gamma_flip,
        gamma_flip_distance_pct=gamma_flip_dist,
        call_wall=call_wall,
        put_wall=put_wall,
        max_pain=max_pain,
        put_call_ratio=pc_ratio,
        event_active=regime_result.event_active,
        event_type=regime_result.event_type,
        event_days=regime_result.event_days,
    )
