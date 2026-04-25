"""Tests for the L1 Market State module."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from datetime import datetime
from unittest.mock import MagicMock, patch

from market_state import (
    MarketState, VolSurface, ChainQuality,
    compute_vol_surface, compute_chain_quality,
)


def _make_chain_snapshot(spot=587.0):
    """Create a minimal ChainSnapshot for testing."""
    from scanner.providers.base import ChainSnapshot, OptionContract

    contracts = [
        # ATM calls
        OptionContract(ticker="SPY", strike=585, expiry="2026-05-02",
                       option_type="call", bid=5.0, ask=5.4, mid=5.2, last=5.2,
                       volume=5000, open_interest=12000, implied_volatility=0.18),
        OptionContract(ticker="SPY", strike=590, expiry="2026-05-02",
                       option_type="call", bid=2.8, ask=3.2, mid=3.0, last=3.0,
                       volume=3000, open_interest=8000, implied_volatility=0.19),
        OptionContract(ticker="SPY", strike=595, expiry="2026-05-02",
                       option_type="call", bid=1.2, ask=1.5, mid=1.35, last=1.35,
                       volume=2000, open_interest=6000, implied_volatility=0.20),
        OptionContract(ticker="SPY", strike=600, expiry="2026-05-02",
                       option_type="call", bid=0.5, ask=0.7, mid=0.60, last=0.60,
                       volume=1000, open_interest=4000, implied_volatility=0.21),
        # ATM puts
        OptionContract(ticker="SPY", strike=585, expiry="2026-05-02",
                       option_type="put", bid=3.0, ask=3.4, mid=3.2, last=3.2,
                       volume=4000, open_interest=10000, implied_volatility=0.19),
        OptionContract(ticker="SPY", strike=580, expiry="2026-05-02",
                       option_type="put", bid=1.8, ask=2.1, mid=1.95, last=1.95,
                       volume=3000, open_interest=9000, implied_volatility=0.21),
        OptionContract(ticker="SPY", strike=575, expiry="2026-05-02",
                       option_type="put", bid=0.9, ask=1.2, mid=1.05, last=1.05,
                       volume=2000, open_interest=7000, implied_volatility=0.23),
        OptionContract(ticker="SPY", strike=570, expiry="2026-05-02",
                       option_type="put", bid=0.4, ask=0.6, mid=0.50, last=0.50,
                       volume=1000, open_interest=5000, implied_volatility=0.25),
    ]
    return ChainSnapshot(
        ticker="SPY", spot=spot, fetched_at=datetime.now(),
        contracts=contracts, expiries=["2026-05-02"],
    )


class TestVolSurface:
    def test_atm_iv_from_chain(self):
        chain = _make_chain_snapshot()
        vs = compute_vol_surface(chain, 587.0)
        # ATM call at 585 has IV=0.18, which is closest to 587
        assert vs.atm_iv == 0.18

    def test_skew_positive_normal(self):
        chain = _make_chain_snapshot()
        vs = compute_vol_surface(chain, 587.0)
        # Put 25d IV should be higher than ATM (normal skew)
        if vs.put_25d_iv is not None:
            assert vs.skew_25d >= 0, "Put skew should be positive (puts more expensive)"

    def test_empty_chain(self):
        from scanner.providers.base import ChainSnapshot
        chain = ChainSnapshot(
            ticker="SPY", spot=587.0, fetched_at=datetime.now(),
            contracts=[], expiries=[],
        )
        vs = compute_vol_surface(chain, 587.0)
        assert vs.atm_iv == 0.20  # fallback

    def test_iv_by_strike_populated(self):
        chain = _make_chain_snapshot()
        vs = compute_vol_surface(chain, 587.0)
        assert len(vs.iv_by_strike) > 0


class TestChainQuality:
    def test_quality_score_range(self):
        chain = _make_chain_snapshot()
        cq = compute_chain_quality(chain, 587.0)
        assert 0 <= cq.quality_score <= 1.0

    def test_liquid_strikes_counted(self):
        chain = _make_chain_snapshot()
        cq = compute_chain_quality(chain, 587.0)
        # All contracts have OI > 100
        assert cq.liquid_strikes > 0

    def test_total_oi(self):
        chain = _make_chain_snapshot()
        cq = compute_chain_quality(chain, 587.0)
        assert cq.total_oi > 0

    def test_spreads_computed(self):
        chain = _make_chain_snapshot()
        cq = compute_chain_quality(chain, 587.0)
        assert cq.avg_spread_pct > 0
        assert cq.median_spread_pct > 0

    def test_empty_chain_quality(self):
        from scanner.providers.base import ChainSnapshot
        chain = ChainSnapshot(
            ticker="SPY", spot=587.0, fetched_at=datetime.now(),
            contracts=[], expiries=[],
        )
        cq = compute_chain_quality(chain, 587.0)
        assert cq.quality_score == 0.0


class TestMarketState:
    def test_has_edge_credit(self):
        """Credit edge when IV is rich vs GARCH."""
        state = MarketState(
            symbol="SPY", spot=587.0, timestamp=datetime.now(),
            regime="HIGH_IV", regime_rationale="test",
            iv_rank=65.0, vix=22.0, vix_term_slope=5.0,
            chain_iv=0.25, garch_vol=0.18, iv_rv_spread=0.07,
            iv_rv_edge_pct=28.0, hv20=0.19,
            vol_surface=VolSurface(atm_iv=0.25),
            chain_quality=ChainQuality(quality_score=0.7),
            bias_label="NEUTRAL", bias_score=0, atr_percentile=50.0,
        )
        assert state.has_edge("iron_condor") is True
        assert state.has_edge("short_put_spread") is True

    def test_no_edge_when_spread_small(self):
        """No edge when IV-RV spread is negligible."""
        state = MarketState(
            symbol="SPY", spot=587.0, timestamp=datetime.now(),
            regime="HIGH_IV", regime_rationale="test",
            iv_rank=55.0, vix=20.0, vix_term_slope=3.0,
            chain_iv=0.20, garch_vol=0.195, iv_rv_spread=0.005,
            iv_rv_edge_pct=2.5, hv20=0.19,
            vol_surface=VolSurface(atm_iv=0.20),
            chain_quality=ChainQuality(quality_score=0.7),
            bias_label="NEUTRAL", bias_score=0, atr_percentile=50.0,
        )
        assert state.has_edge("iron_condor") is False

    def test_has_edge_debit(self):
        """Debit edge when IV is cheap vs GARCH."""
        state = MarketState(
            symbol="SPY", spot=587.0, timestamp=datetime.now(),
            regime="LOW_IV", regime_rationale="test",
            iv_rank=20.0, vix=14.0, vix_term_slope=8.0,
            chain_iv=0.12, garch_vol=0.20, iv_rv_spread=-0.08,
            iv_rv_edge_pct=-66.7, hv20=0.18,
            vol_surface=VolSurface(atm_iv=0.12),
            chain_quality=ChainQuality(quality_score=0.7),
            bias_label="LEAN_BULLISH", bias_score=3, atr_percentile=50.0,
        )
        assert state.has_edge("long_call_spread") is True
        assert state.has_edge("iron_condor") is False

    def test_no_edge_illiquid(self):
        """No edge if chain quality is too low."""
        state = MarketState(
            symbol="XYZ", spot=50.0, timestamp=datetime.now(),
            regime="HIGH_IV", regime_rationale="test",
            iv_rank=70.0, vix=25.0, vix_term_slope=2.0,
            chain_iv=0.35, garch_vol=0.20, iv_rv_spread=0.15,
            iv_rv_edge_pct=42.9, hv20=0.22,
            vol_surface=VolSurface(atm_iv=0.35),
            chain_quality=ChainQuality(quality_score=0.1),  # illiquid
            bias_label="NEUTRAL", bias_score=0, atr_percentile=50.0,
        )
        assert state.has_edge("iron_condor") is False

    def test_strategy_candidates_high_iv_neutral(self):
        state = MarketState(
            symbol="SPY", spot=587.0, timestamp=datetime.now(),
            regime="HIGH_IV", regime_rationale="test",
            iv_rank=60.0, vix=22.0, vix_term_slope=5.0,
            chain_iv=0.22, garch_vol=0.18, iv_rv_spread=0.04,
            iv_rv_edge_pct=18.0, hv20=0.19,
            vol_surface=VolSurface(atm_iv=0.22),
            chain_quality=ChainQuality(quality_score=0.7),
            bias_label="NEUTRAL", bias_score=0, atr_percentile=50.0,
            dealer_regime="LONG_GAMMA",
        )
        candidates = state.strategy_candidates()
        assert "iron_condor" in candidates

    def test_strategy_candidates_spike(self):
        state = MarketState(
            symbol="SPY", spot=550.0, timestamp=datetime.now(),
            regime="SPIKE", regime_rationale="test",
            iv_rank=90.0, vix=35.0, vix_term_slope=-5.0,
            chain_iv=0.40, garch_vol=0.30, iv_rv_spread=0.10,
            iv_rv_edge_pct=25.0, hv20=0.35,
            vol_surface=VolSurface(atm_iv=0.40),
            chain_quality=ChainQuality(quality_score=0.5),
            bias_label="STRONG_BEARISH", bias_score=-5, atr_percentile=90.0,
        )
        candidates = state.strategy_candidates()
        assert "long_put_spread" in candidates
        assert "iron_condor" not in candidates

    def test_strategy_candidates_low_iv_bullish(self):
        state = MarketState(
            symbol="SPY", spot=600.0, timestamp=datetime.now(),
            regime="LOW_IV", regime_rationale="test",
            iv_rank=15.0, vix=12.0, vix_term_slope=10.0,
            chain_iv=0.10, garch_vol=0.15, iv_rv_spread=-0.05,
            iv_rv_edge_pct=-50.0, hv20=0.12,
            vol_surface=VolSurface(atm_iv=0.10),
            chain_quality=ChainQuality(quality_score=0.8),
            bias_label="LEAN_BULLISH", bias_score=3, atr_percentile=40.0,
        )
        candidates = state.strategy_candidates()
        assert "long_call_spread" in candidates

    def test_edge_magnitude(self):
        state = MarketState(
            symbol="SPY", spot=587.0, timestamp=datetime.now(),
            regime="HIGH_IV", regime_rationale="test",
            iv_rank=60.0, vix=22.0, vix_term_slope=5.0,
            chain_iv=0.25, garch_vol=0.18, iv_rv_spread=0.07,
            iv_rv_edge_pct=28.0, hv20=0.19,
            vol_surface=VolSurface(atm_iv=0.25),
            chain_quality=ChainQuality(quality_score=0.7),
            bias_label="NEUTRAL", bias_score=0, atr_percentile=50.0,
        )
        assert state.edge_magnitude() == 28.0

    def test_to_dict_keys(self):
        state = MarketState(
            symbol="SPY", spot=587.0, timestamp=datetime.now(),
            regime="HIGH_IV", regime_rationale="test",
            iv_rank=60.0, vix=22.0, vix_term_slope=5.0,
            chain_iv=0.22, garch_vol=0.18, iv_rv_spread=0.04,
            iv_rv_edge_pct=18.0, hv20=0.19,
            vol_surface=VolSurface(atm_iv=0.22),
            chain_quality=ChainQuality(quality_score=0.7),
            bias_label="NEUTRAL", bias_score=0, atr_percentile=50.0,
        )
        d = state.to_dict()
        assert "regime" in d
        assert "edge" in d
        assert "vol_surface" in d
        assert "chain_quality" in d
        assert "bias" in d
        assert "dealer" in d
        assert d["edge"]["has_credit_edge"] is True
        assert d["edge"]["magnitude"] == 18.0
