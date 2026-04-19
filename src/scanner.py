"""
Options opportunity scanner — Trading Copilot service module.

Orchestrates a full scan for a ticker using TC's existing infrastructure:
  - Market data:  app.services.market_data  (DB-backed yfinance cache)
  - TA signals:   app.services.ta_engine    (full TC signal set)
  - Knowledge base: tools.knowledge_base.strategy_gen (same process, no HTTP)
  - Pricing:      app.services.options.pricing.pricer (bundled BS/MC/IV)
"""
import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

# TC-DECOUPLED: from app.services.market_data import get_or_refresh_data, get_weekly_prices
# TC-DECOUPLED: from app.services.ta_engine import analyze_ticker as _tc_analyze, _prepare_dataframe
from config import RISK_FREE_RATE
from pricer import get_vol_surface
from opportunity_builder import build_all_opportunities

logger = logging.getLogger(__name__)


# ── Signal adapter ────────────────────────────────────────────────────────────

def _compute_hist_vol(prices: List[Dict]) -> float:
    """Annualised 20-day historical vol from daily close prices."""
    closes = [float(p["close"]) for p in prices[-22:]]
    if len(closes) < 2:
        return 0.20
    log_returns = np.diff(np.log(closes))
    return float(np.std(log_returns) * np.sqrt(252))


def _compute_atr_percentile(df: pd.DataFrame) -> float:
    """Rolling ATR(14) percentile rank — mirrors standalone ta_signals.py."""
    try:
        from ta.volatility import AverageTrueRange
        atr = AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range()
        atr_clean = atr.dropna()
        if len(atr_clean) < 2:
            return 0.0
        current = float(atr_clean.iloc[-1])
        return float(np.mean(atr_clean <= current) * 100)
    except Exception:
        return 0.0


def _adapt_signals(tc: Dict, df: pd.DataFrame, prices: List[Dict]) -> Dict:
    """
    Normalise TC's analyze_ticker output to the shape the options scanner expects.

    TC's signal dict differs from the standalone scanner in several key areas:
      - trend: uses string comparisons ("above"/"below") instead of bool flags;
               no current_price inside trend (it's at the top level)
      - momentum: macd_crossover is a string ("bullish_crossover" / ...) not bools;
                  no macd_bullish, stoch_oversold, stoch_overbought bool keys
      - volatility: uses atr_vs_price_pct instead of atr_pct; no hist_vol or atr_percentile
      - support_resistance: no next_resistance / next_support keys (uses swing_highs/lows lists)

    This function adds all the missing keys without modifying TC's existing output,
    so the scanner can run against TC's full signal set.
    """
    tr    = tc["trend"]
    mom   = tc["momentum"]
    vol   = tc["volatility"]
    sr    = tc["support_resistance"]
    price = tc["price"]

    sma_20  = tr.get("sma_20")  or 0.0
    sma_50  = tr.get("sma_50")  or 0.0
    sma_200 = tr.get("sma_200") or 0.0

    macd_val = mom.get("macd")         or 0.0
    macd_sig = mom.get("macd_signal")  or 0.0
    stoch_k  = mom.get("stochastic_k")

    # next_resistance / next_support from TC's ranked swing level lists
    swing_highs = sr.get("swing_highs", [])
    swing_lows  = sr.get("swing_lows",  [])
    next_res = (swing_highs[1]["price"] if len(swing_highs) >= 2
                else round(sr["nearest_resistance"] * 1.05, 2))
    next_sup = (swing_lows[1]["price"]  if len(swing_lows)  >= 2
                else round(sr["nearest_support"]    * 0.95, 2))

    hist_vol       = _compute_hist_vol(prices)
    atr_percentile = _compute_atr_percentile(df)

    return {
        "trend": {
            **tr,
            "current_price":      price,
            "above_sma20":        tr["price_vs_sma20"]  == "above",
            "above_sma50":        tr["price_vs_sma50"]  == "above",
            "above_sma200":       tr["price_vs_sma200"] == "above",
            "sma20_above_sma50":  sma_20  > sma_50,
            "sma50_above_sma200": sma_50  > sma_200,
        },
        "momentum": {
            **mom,
            "macd_bullish":    macd_val > macd_sig,
            "macd_crossover":  mom["macd_crossover"] == "bullish_crossover",
            "macd_crossunder": mom["macd_crossover"] == "bearish_crossover",
            "stoch_oversold":  stoch_k is not None and stoch_k < 20,
            "stoch_overbought": stoch_k is not None and stoch_k > 80,
        },
        "volatility": {
            **vol,
            "atr_pct":        vol.get("atr_vs_price_pct") or 0.0,
            "atr_percentile": atr_percentile,
            "hist_vol":       hist_vol,
        },
        "support_resistance": {
            **sr,
            "next_resistance": next_res,
            "next_support":    next_sup,
        },
    }


def _historical_returns(prices: List[Dict]) -> np.ndarray:
    closes = np.array([float(p["close"]) for p in prices])
    return np.diff(np.log(closes)) if len(closes) >= 2 else np.array([])


# ── Public API ────────────────────────────────────────────────────────────────

def scan_ticker(ticker: str, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Full scan for one ticker using TC's DB-backed market data and TA engine.

    Returns a result dict compatible with the formatter and AI narrative modules.
    """
    if settings is None:
        settings = {}

    logger.info(f"Options scan: {ticker}")

    # ── Market data (DB cache → yfinance refresh) ─────────────────────────
    ticker_info, prices, _ = get_or_refresh_data(ticker)
    weekly_prices          = get_weekly_prices(ticker)
    df                     = _prepare_dataframe(prices)
    current_price          = float(prices[-1]["close"]) if prices else 0.0

    # ── TA signals (full TC engine) ────────────────────────────────────────
    tc_signals = _tc_analyze(
        df,
        symbol=ticker,
        price=current_price,
        weekly_price_list=weekly_prices or None,
    )
    signals = _adapt_signals(tc_signals, df, prices)

    # ── Vol surface + MC inputs ───────────────────────────────────────────
    r           = float(settings.get("risk_free_rate", RISK_FREE_RATE))
    vol_surface = get_vol_surface(ticker, r=r)
    hist_ret    = _historical_returns(prices)

    # ── Build opportunities ────────────────────────────────────────────────
    opportunities = build_all_opportunities(ticker, signals, vol_surface, hist_ret)

    # ── Knowledge base enrichment (direct TC import — no HTTP) ────────────
    knowledge: Optional[str] = None
    try:
        from tools.knowledge_base.strategy_gen import generate_strategies
        knowledge = generate_strategies(ticker)
    except Exception as exc:
        logger.warning(f"Knowledge base unavailable for {ticker}: {exc}")

    return {
        "ticker":               ticker,
        "name":                 ticker_info.get("company_name", ticker),
        "sector":               ticker_info.get("sector", ""),
        "current_price":        round(current_price, 2),
        "signals":              signals,
        "opportunities":        opportunities,
        "knowledge_strategies": knowledge,
    }


def run_scan(tickers: List[str], settings: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Scan every ticker in the list and return all results."""
    results = []
    for ticker in tickers:
        try:
            results.append(scan_ticker(ticker, settings))
        except Exception as exc:
            logger.error(f"Scan failed for {ticker}: {exc}")
            results.append({"ticker": ticker, "error": str(exc), "opportunities": []})
    return results
