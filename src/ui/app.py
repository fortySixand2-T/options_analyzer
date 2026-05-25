"""
FastAPI backend for the Options Scanner web UI.

Core routes (0-14 DTE scanner only):
    GET  /api/regime                     — current regime + VIX + dealer
    GET  /api/market-state               — full L1 market state snapshot
    GET  /api/trade-candidates           — L1→L2→L3 pipeline
    GET  /api/scan                       — scanner results with checklists
    GET  /api/chain/{symbol}             — options chain with Greeks
    POST /api/greeks                     — compute Greeks for arbitrary inputs
    GET  /api/backtest/{strategy}        — backtest with signal filters
    GET  /api/backtest/compare           — multi-strategy comparison
    GET  /api/chain-snapshots/*          — stored chain snapshot data
    GET  /api/journal                    — trade journal entries
    POST /api/journal                    — log a trade
"""

import logging
import os
from datetime import date
from typing import Dict, List, Optional

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src.auth.database import cleanup_expired_tokens, init_auth_db
from src.auth.dependencies import get_current_user
from src.auth.router import limiter, router as auth_router
from src.data.user_db import init_user_tables, migrate_journal_from_legacy
from src.scheduler import scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_auth_db()
    init_user_tables()
    migrate_journal_from_legacy()
    cleanup_expired_tokens()
    scheduler.start_all()
    yield
    await scheduler.stop_all()


app = FastAPI(
    title="Options Scanner API",
    description="Index Options Scanner — regime detection, strategy scoring, backtesting",
    version="1.0.0",
    lifespan=lifespan,
)

from src.ui.watchlist_router import router as watchlist_router
from src.ui.scanner_presets_router import router as scanner_presets_router

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(auth_router)
app.include_router(watchlist_router)
app.include_router(scanner_presets_router)

# CORS for React dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
)

# ── Security Headers ────────────────────────────────────────────────────────

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response: StarletteResponse = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'"
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ── Request/Response Models ──────────────────────────────────────────────────

class GreeksRequest(BaseModel):
    spot: float
    strike: float
    dte: int
    iv: float
    r: Optional[float] = None
    option_type: str = "call"
    option_style: str = "european"


class JournalEntry(BaseModel):
    strategy: str
    symbol: str
    entry_date: str
    entry_price: float
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    contracts: int = 1
    pnl: Optional[float] = None
    notes: str = ""


# ── Regime ─────���─────────────────────────────────────────────────────────────

@app.get("/api/regime")
def get_regime(symbol: str = Query("SPY", description="Symbol for dealer data"), _user: dict = Depends(get_current_user)):
    """Current market regime classification + VIX + dealer positioning."""
    try:
        from regime.detector import detect_regime
        from scanner.providers.flashalpha_client import fetch_gex, classify_dealer_regime
        result = detect_regime()
        vix = result.vix

        response = {
            "regime": result.regime.value,
            "rationale": result.rationale,
            "event_active": result.event_active,
            "event_type": result.event_type,
            "event_days": result.event_days,
            "vix": {
                "vix": vix.vix,
                "vix9d": vix.vix9d,
                "vix3m": vix.vix3m,
                "vix6m": vix.vix6m,
                "contango": vix.contango,
                "backwardation": vix.backwardation,
                "term_structure_slope": vix.term_structure_slope,
                "vix_percentile_1y": vix.vix_percentile_1y,
            },
        }

        # Add dealer data — try FlashAlpha first, fall back to chain
        dealer = fetch_gex(symbol.upper())
        if not dealer:
            # Chain-based fallback: compute from yfinance options data
            try:
                from scanner.providers.flashalpha_client import compute_dealer_data_from_chain
                from scanner.providers.yfinance_provider import YFinanceProvider
                provider = YFinanceProvider(delay=0.5)
                chain = provider.get_chain(symbol.upper(), min_dte=0, max_dte=14)
                if chain.contracts:
                    dealer = compute_dealer_data_from_chain(chain)
            except Exception as chain_err:
                logger.warning("Chain-based dealer fallback failed: %s", chain_err)

        if dealer:
            classification = classify_dealer_regime(dealer)
            response["dealer"] = {
                "regime": dealer.dealer_regime,
                "net_gex": dealer.net_gex,
                "gamma_flip": dealer.gamma_flip,
                "call_wall": dealer.call_wall,
                "put_wall": dealer.put_wall,
                "max_pain": dealer.max_pain,
                "put_call_ratio": dealer.put_call_ratio,
                "implication": classification.get("implication"),
                "bias": classification.get("bias"),
                "pc_signal": classification.get("pc_signal"),
                "source": dealer.source,
            }
        else:
            response["dealer"] = None

        return response
    except Exception as e:
        logger.exception("Failed to detect regime")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Market State ──────────────────────────────────────────────────────────────

@app.get("/api/market-state")
def get_market_state(symbol: str = Query("SPY", description="Symbol"), _user: dict = Depends(get_current_user)):
    """Full L1 market state snapshot — regime, edge, skew, dealer, quality."""
    try:
        from market_state import build_market_state
        state = build_market_state(symbol.upper())
        return state.to_dict()
    except Exception as e:
        logger.exception("Failed to build market state for %s", symbol)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/trade-candidates")
def get_trade_candidates(
    symbol: str = Query("SPY", description="Symbol"),
    portfolio_value: float = Query(100_000, description="Portfolio value for sizing"),
    _user: dict = Depends(get_current_user),
):
    """Full L1→L2→L3 pipeline: market state → trade candidates → sizing.

    Returns ranked trade candidates with confluence scores and Kelly-derived
    position sizing. Strategies with negative historical Kelly are blocked.
    """
    try:
        from market_state import build_market_state
        from trade_generator import generate_trades
        from sizing import assess_execution

        state = build_market_state(symbol.upper())
        trades = generate_trades(state)

        # Enrich each candidate with L3 execution assessment
        enriched = []
        for tc in trades:
            execution = assess_execution(
                trade_candidate=tc,
                portfolio_value=portfolio_value,
            )
            entry = tc.to_dict()
            entry["execution"] = execution.to_dict()
            enriched.append(entry)

        return {
            "symbol": symbol.upper(),
            "market_state": state.to_dict(),
            "candidates": enriched,
            "count": len(enriched),
            "tradeable_count": sum(1 for e in enriched if e["execution"]["executable"]),
        }
    except Exception as e:
        logger.exception("Failed to generate trade candidates for %s", symbol)
        raise HTTPException(status_code=500, detail="Internal server error")


# In-memory portfolio singleton (persists across requests within a session)
_portfolio_instance = None

def _get_portfolio():
    global _portfolio_instance
    if _portfolio_instance is None:
        from portfolio import Portfolio
        _portfolio_instance = Portfolio()
    return _portfolio_instance


@app.get("/api/portfolio")
def get_portfolio(_user: dict = Depends(get_current_user)):
    """L4 portfolio snapshot — positions, Greeks, risk, hedge triggers."""
    try:
        pf = _get_portfolio()
        return pf.to_dict()
    except Exception as e:
        logger.exception("Failed to get portfolio")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Scanner ────────────────���─────────────────────────────────────────────────

@app.get("/api/scan")
def scan(
    symbols: str = Query("SPY", description="Comma-separated symbols"),
    max_dte: int = Query(14, ge=0, le=365, description="Max DTE filter"),
    min_dte: int = Query(0, ge=0, le=365, description="Min DTE filter"),
    strategies: bool = Query(False, description="Include strategy evaluation"),
    top: int = Query(20, ge=1, le=100, description="Max results"),
    _user: dict = Depends(get_current_user),
):
    """Scan for options signals, optionally with strategy evaluation."""
    tickers = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not tickers:
        raise HTTPException(status_code=400, detail="No symbols provided")

    scanner_config = {
        "filter": {"min_dte": min_dte, "max_dte": max_dte},
    }

    try:
        if strategies:
            from strategy_scanner import scan_strategies
            result = scan_strategies(
                tickers=tickers,
                scanner_config=scanner_config,
                top=top,
            )
            regime = result["regime"]
            bias = result.get("bias")
            dealer = result.get("dealer")
            response = {
                "regime": {
                    "regime": regime.regime.value,
                    "rationale": regime.rationale,
                },
                "bias": {
                    "label": bias.label,
                    "score": bias.score,
                    "atr_percentile": bias.atr_percentile,
                } if bias else None,
                "dealer": {
                    "regime": dealer.dealer_regime,
                    "net_gex": dealer.net_gex,
                    "gamma_flip": dealer.gamma_flip,
                    "call_wall": dealer.call_wall,
                    "put_wall": dealer.put_wall,
                    "max_pain": dealer.max_pain,
                    "put_call_ratio": dealer.put_call_ratio,
                    "source": dealer.source,
                } if dealer else None,
                "strategies": [_serialize_strategy(s) for s in result["strategies"]],
                "signals_count": result["signals_count"],
            }
            return response
        else:
            from scanner import scan_watchlist
            signals = scan_watchlist(tickers, config=scanner_config)
            signals = signals[:top]
            return {
                "signals": [_serialize_signal(s) for s in signals],
                "count": len(signals),
            }
    except Exception as e:
        logger.exception("Scan failed")
        raise HTTPException(status_code=500, detail="Internal server error")


def _serialize_signal(s) -> Dict:
    return {
        "ticker": s.ticker,
        "strike": s.strike,
        "expiry": s.expiry,
        "option_type": s.option_type,
        "dte": s.dte,
        "spot": s.spot,
        "bid": s.bid,
        "ask": s.ask,
        "mid": s.mid,
        "iv_rank": s.iv_rank,
        "iv_percentile": s.iv_percentile,
        "iv_regime": s.iv_regime,
        "garch_vol": s.garch_vol,
        "edge_pct": s.edge_pct,
        "direction": s.direction,
        "delta": s.delta,
        "gamma": s.gamma,
        "theta": s.theta,
        "vega": s.vega,
        "conviction": s.conviction,
    }


def _serialize_strategy(s) -> Dict:
    return {
        "strategy_name": s.strategy_name,
        "strategy_label": s.strategy_label,
        "ticker": s.ticker,
        "score": _safe_float(s.score),
        "regime": s.regime.value,
        "checks_passed": int(s.checks_passed),
        "checks_total": int(s.checks_total),
        "checklist": [
            {"name": c.name, "passed": bool(c.passed), "value": _to_json_safe(c.value)}
            for c in s.checklist
        ],
        "legs": _to_json_safe(s.legs),
        "entry": _to_json_safe(s.entry),
        "is_credit": bool(s.is_credit) if s.is_credit is not None else None,
        "max_profit": _safe_float(s.max_profit),
        "max_loss": _safe_float(s.max_loss),
        "risk_reward": _safe_float(s.risk_reward),
        "prob_profit": _safe_float(s.prob_profit),
        "suggested_dte": int(s.suggested_dte) if s.suggested_dte is not None else None,
        "rationale": s.rationale,
    }


def _safe_float(val):
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _to_json_safe(obj):
    """Convert numpy types to native Python for JSON serialization."""
    import numpy as np
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json_safe(v) for v in obj]
    return obj


# ── Chain ─────────��──────────────────────────��───────────────────────────────

@app.get("/api/chain/{symbol}")
def get_chain(
    symbol: str,
    max_dte: int = Query(14, ge=0, le=365, description="Max DTE"),
    min_dte: int = Query(0, ge=0, le=365, description="Min DTE"),
    _user: dict = Depends(get_current_user),
):
    """Full options chain with Greeks for a symbol."""
    try:
        from scanner.providers import create_provider
        provider = create_provider()
        chain = provider.get_chain(symbol.upper(), min_dte=min_dte, max_dte=max_dte)
        return {
            "symbol": chain.ticker,
            "spot": chain.spot,
            "expiries": chain.expiries,
            "contracts": [
                {
                    "strike": c.strike,
                    "expiry": c.expiry,
                    "option_type": c.option_type,
                    "bid": c.bid,
                    "ask": c.ask,
                    "mid": c.mid,
                    "last": c.last,
                    "volume": c.volume,
                    "open_interest": c.open_interest,
                    "implied_volatility": c.implied_volatility,
                }
                for c in chain.contracts
            ],
        }
    except Exception as e:
        logger.exception("Chain fetch failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Quick Quote ──────────────────────────────────────────────────────────────

@app.get("/api/quote/{symbol}")
def get_quote(symbol: str, _user: dict = Depends(get_current_user)):
    """Spot price + ATM implied volatility for a ticker."""
    try:
        from scanner.providers import create_provider
        provider = create_provider()
        chain = provider.get_chain(symbol.upper(), min_dte=7, max_dte=45)
        spot = chain.spot
        atm_iv = None
        if chain.contracts:
            calls = [c for c in chain.contracts if c.option_type == "call" and c.implied_volatility and c.implied_volatility > 0]
            if calls:
                closest = min(calls, key=lambda c: abs(c.strike - spot))
                atm_iv = closest.implied_volatility
        return {"symbol": chain.ticker, "spot": round(spot, 2), "iv": round(atm_iv, 4) if atm_iv else None}
    except Exception as e:
        logger.exception("Quote fetch failed for %s", symbol)
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Greeks Calculator ─────────────────────────────────────────────────────────

@app.post("/api/greeks")
def compute_greeks(req: GreeksRequest, _user: dict = Depends(get_current_user)):
    """Compute option price + Greeks. Supports European (BS) and American (LSMC)."""
    from models.black_scholes import black_scholes_price, calculate_greeks
    from config import RISK_FREE_RATE

    r = req.r if req.r is not None else RISK_FREE_RATE
    T = max(req.dte / 365.0, 1 / 365.0)

    greeks = calculate_greeks(req.spot, req.strike, T, r, req.iv, req.option_type)

    if req.option_style == "american":
        from monte_carlo.gbm_simulator import simulate_gbm_paths
        from monte_carlo.american_mc import price_american_lsmc
        paths = simulate_gbm_paths(req.spot, r, req.iv, T, num_paths=10000, num_steps=max(req.dte, 30), seed=42)
        price, std_error = price_american_lsmc(paths, req.strike, r, T, req.option_type)
        bs_price = black_scholes_price(req.spot, req.strike, T, r, req.iv, req.option_type)
        early_exercise_premium = max(price - bs_price, 0)
    else:
        price = black_scholes_price(req.spot, req.strike, T, r, req.iv, req.option_type)
        std_error = None
        early_exercise_premium = None

    resp = {
        "price": round(price, 4),
        "greeks": {k: round(v, 6) for k, v in greeks.items()},
        "option_style": req.option_style,
        "inputs": {
            "spot": req.spot,
            "strike": req.strike,
            "dte": req.dte,
            "iv": req.iv,
            "r": r,
            "option_type": req.option_type,
        },
    }
    if std_error is not None:
        resp["std_error"] = round(std_error, 6)
        resp["early_exercise_premium"] = round(early_exercise_premium, 4)
    return resp


# ── Backtest ──────────────────��──────────────────────────────────────────────

def _serialize_backtest(result, strategy, symbol, start_date, end_date):
    """Serialize a BacktestResult to a JSON-safe dict."""
    stats = result.stats
    return {
        "strategy": strategy,
        "symbol": symbol,
        "period": {"start": str(start_date), "end": str(end_date)},
        "source": result.source,
        "cached": result.cached,
        "stats": {
            "total_trades": stats.total_trades,
            "wins": stats.wins,
            "losses": stats.losses,
            "win_rate": stats.win_rate,
            "avg_win": stats.avg_win,
            "avg_loss": stats.avg_loss,
            "avg_pnl": stats.avg_pnl,
            "total_pnl": stats.total_pnl,
            "profit_factor": stats.profit_factor,
            "max_drawdown": stats.max_drawdown,
            "max_drawdown_pct": stats.max_drawdown_pct,
            "sharpe_ratio": stats.sharpe_ratio,
            "avg_dte_at_entry": stats.avg_dte_at_entry,
            "avg_days_in_trade": stats.avg_days_in_trade,
        },
        "equity_curve": result.equity_curve,
        "regime_breakdown": result.regime_breakdown,
        "dte_breakdown": result.dte_breakdown,
        "pnl_distribution": result.pnl_distribution,
        "trades": [
            {
                "entry_date": str(t.entry_date),
                "exit_date": str(t.exit_date),
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "dte_at_entry": t.dte_at_entry,
                "regime": t.regime,
                "win": t.win,
                "exit_reason": t.exit_reason,
                "bias_score": t.bias_score,
                "bias_label": t.bias_label,
                "edge_pct": t.edge_pct,
                "iv_at_entry": t.iv_at_entry,
                "dealer_regime": t.dealer_regime,
            }
            for t in (result.trades or [])
        ],
        "trades_count": len(result.trades) if result.trades else 0,
    }


@app.get("/api/backtest/compare")
def compare_backtests(
    strategies: str = Query("iron_condor,short_put_spread"),
    symbol: str = Query("SPY"),
    start: str = Query("2022-01-01"),
    end: Optional[str] = Query(None),
    regime_filter: bool = Query(False),
    bias_filter: bool = Query(False),
    dealer_filter: bool = Query(False),
    edge_threshold: float = Query(0.0, ge=0.0, le=100.0),
    exit_rule: str = Query("50pct"),
    slippage_pct: float = Query(0.0, ge=0.0, le=1.0, description="Slippage as decimal, e.g. 0.03 for 3%"),
    source: str = Query("local", description="Pricing source: 'local' (BS) or 'chain_replay' (real data)"),
    option_style: str = Query("european", description="Option style: 'european' (BS) or 'american' (LSMC)"),
    _user: dict = Depends(get_current_user),
):
    """Compare backtests across multiple strategies."""
    from backtest.models import BacktestRequest
    from backtest.local_backtest import run_local_backtest
    from backtest.chain_replay import run_chain_replay

    try:
        end_date = date.fromisoformat(end) if end else date.today()
        start_date = date.fromisoformat(start)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")
    strategy_list = [s.strip() for s in strategies.split(",") if s.strip()]
    runner = run_chain_replay if source == "chain_replay" else run_local_backtest

    results = {}
    for strat in strategy_list:
        req = BacktestRequest(
            strategy=strat,
            symbol=symbol.upper(),
            start_date=start_date,
            end_date=end_date,
            regime_filter=regime_filter,
            bias_filter=bias_filter,
            dealer_filter=dealer_filter,
            edge_threshold=edge_threshold,
            exit_rule=exit_rule,
            slippage_pct=slippage_pct,
            option_style=option_style,
        )
        try:
            result = runner(req)
            resp = _serialize_backtest(result, strat, symbol, start_date, end_date)
            if result.data_issues:
                resp["data_issues"] = result.data_issues
            results[strat] = resp
        except Exception as e:
            logger.warning("Backtest failed for %s: %s", strat, e)
            results[strat] = {"error": str(e)}

    return {"strategies": results, "symbol": symbol, "period": {"start": str(start_date), "end": str(end_date)}}


@app.get("/api/backtest/{strategy}")
def get_backtest(
    strategy: str,
    symbol: str = Query("SPY"),
    start: str = Query("2022-01-01"),
    end: Optional[str] = Query(None),
    regime_filter: bool = Query(False),
    bias_filter: bool = Query(False),
    dealer_filter: bool = Query(False),
    edge_threshold: float = Query(0.0, ge=0.0, le=100.0),
    exit_rule: str = Query("50pct"),
    slippage_pct: float = Query(0.0, ge=0.0, le=1.0, description="Slippage as decimal, e.g. 0.03 for 3%"),
    source: str = Query("local", description="Pricing source: 'local' (BS) or 'chain_replay' (real data)"),
    option_style: str = Query("european", description="Option style: 'european' (BS) or 'american' (LSMC)"),
    _user: dict = Depends(get_current_user),
):
    """Run or retrieve cached backtest results with optional signal filters."""
    from backtest.models import BacktestRequest
    from backtest.local_backtest import run_local_backtest
    from backtest.chain_replay import run_chain_replay

    try:
        end_date = date.fromisoformat(end) if end else date.today()
        start_date = date.fromisoformat(start)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")

    req = BacktestRequest(
        strategy=strategy,
        symbol=symbol.upper(),
        start_date=start_date,
        end_date=end_date,
        regime_filter=regime_filter,
        bias_filter=bias_filter,
        dealer_filter=dealer_filter,
        edge_threshold=edge_threshold,
        exit_rule=exit_rule,
        slippage_pct=slippage_pct,
        option_style=option_style,
    )

    try:
        runner = run_chain_replay if source == "chain_replay" else run_local_backtest
        result = runner(req)
        resp = _serialize_backtest(result, strategy, symbol, start_date, end_date)
        if result.data_issues:
            resp["data_issues"] = result.data_issues
        return resp
    except Exception as e:
        logger.exception("Backtest failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Journal (user-scoped, in users.db) ──────────────────────────────────────

@app.get("/api/journal")
def list_journal(limit: int = Query(50, ge=1, le=500), _user: dict = Depends(get_current_user)):
    """List trade journal entries for the current user."""
    from src.data.user_db import get_user_db
    conn = get_user_db()
    try:
        rows = conn.execute(
            """SELECT id, strategy, symbol, entry_date, entry_price, exit_date,
                      exit_price, contracts, pnl, notes, regime_at_entry,
                      bias_at_entry, edge_at_entry, tags, created_at
               FROM journal WHERE user_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (_user["id"], limit),
        ).fetchall()
        return {"entries": [dict(r) for r in rows], "count": len(rows)}
    finally:
        conn.close()


@app.post("/api/journal")
def add_journal(entry: JournalEntry, _user: dict = Depends(get_current_user)):
    """Log a trade to the journal."""
    from src.data.user_db import get_user_db
    conn = get_user_db()
    try:
        conn.execute(
            """INSERT INTO journal (user_id, strategy, symbol, entry_date, entry_price,
               exit_date, exit_price, contracts, pnl, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (_user["id"], entry.strategy, entry.symbol, entry.entry_date, entry.entry_price,
             entry.exit_date, entry.exit_price, entry.contracts, entry.pnl, entry.notes),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok"}


@app.put("/api/journal/{entry_id}")
def update_journal(entry_id: int, entry: JournalEntry, _user: dict = Depends(get_current_user)):
    """Update a journal entry."""
    from src.data.user_db import get_user_db
    conn = get_user_db()
    try:
        cursor = conn.execute(
            """UPDATE journal SET strategy=?, symbol=?, entry_date=?, entry_price=?,
               exit_date=?, exit_price=?, contracts=?, pnl=?, notes=?
               WHERE id=? AND user_id=?""",
            (entry.strategy, entry.symbol, entry.entry_date, entry.entry_price,
             entry.exit_date, entry.exit_price, entry.contracts, entry.pnl,
             entry.notes, entry_id, _user["id"]),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Entry not found")
    finally:
        conn.close()
    return {"status": "ok"}


@app.delete("/api/journal/{entry_id}")
def delete_journal(entry_id: int, _user: dict = Depends(get_current_user)):
    """Delete a journal entry."""
    from src.data.user_db import get_user_db
    conn = get_user_db()
    try:
        cursor = conn.execute(
            "DELETE FROM journal WHERE id=? AND user_id=?",
            (entry_id, _user["id"]),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Entry not found")
    finally:
        conn.close()
    return {"status": "ok"}


@app.get("/api/journal/export")
def export_journal(
    format: str = Query("csv", description="Export format: csv"),
    _user: dict = Depends(get_current_user),
):
    """Export journal entries as CSV."""
    import csv
    import io
    from starlette.responses import StreamingResponse

    from src.data.user_db import get_user_db
    conn = get_user_db()
    try:
        rows = conn.execute(
            """SELECT strategy, symbol, entry_date, entry_price, exit_date,
                      exit_price, contracts, pnl, notes, regime_at_entry,
                      bias_at_entry, created_at
               FROM journal WHERE user_id = ?
               ORDER BY created_at DESC""",
            (_user["id"],),
        ).fetchall()
    finally:
        conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["strategy", "symbol", "entry_date", "entry_price", "exit_date",
                     "exit_price", "contracts", "pnl", "notes", "regime", "bias", "created_at"])
    for r in rows:
        writer.writerow([r["strategy"], r["symbol"], r["entry_date"], r["entry_price"],
                         r["exit_date"], r["exit_price"], r["contracts"], r["pnl"],
                         r["notes"], r["regime_at_entry"], r["bias_at_entry"], r["created_at"]])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=journal_export.csv"},
    )


# ── Notifications ───────────────────────────────────────────────────────────

@app.get("/api/notifications")
def list_notifications(
    limit: int = Query(50, ge=1, le=200),
    unread_only: bool = Query(False),
    _user: dict = Depends(get_current_user),
):
    """List notifications for the current user."""
    from src.notifications.dispatcher import get_notifications, get_unread_count
    items = get_notifications(_user["id"], limit=limit, include_read=not unread_only)
    count = get_unread_count(_user["id"])
    return {"notifications": items, "unread_count": count}


@app.post("/api/notifications/{notification_id}/read")
def read_notification(notification_id: int, _user: dict = Depends(get_current_user)):
    """Mark a notification as read."""
    from src.notifications.dispatcher import mark_as_read
    if not mark_as_read(_user["id"], notification_id):
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "ok"}


@app.post("/api/notifications/read-all")
def read_all_notifications(_user: dict = Depends(get_current_user)):
    """Mark all notifications as read."""
    from src.notifications.dispatcher import mark_all_read
    count = mark_all_read(_user["id"])
    return {"status": "ok", "marked": count}


# ── Scheduler Status ────────────────────────────────────────────────────────

@app.get("/api/scheduler/status")
def scheduler_status(_user: dict = Depends(get_current_user)):
    """Check status of background scheduled tasks."""
    return {"tasks": scheduler.status()}


# ── Chain Snapshots ──────────────────────────────────────────────────────────

@app.post("/api/chain-snapshots/collect")
def collect_chain_snapshots(
    symbols: str = Query("SPY,QQQ,IWM", description="Comma-separated symbols"),
    max_dte: int = Query(60, ge=0, le=365, description="Max DTE to collect"),
    _user: dict = Depends(get_current_user),
):
    """Trigger daily chain snapshot collection for the given tickers."""
    from data.chain_collector import collect_daily_snapshots

    tickers = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not tickers:
        raise HTTPException(status_code=400, detail="No symbols provided")

    try:
        result = collect_daily_snapshots(tickers=tickers, max_dte=max_dte)
        return result
    except Exception as e:
        logger.exception("Chain snapshot collection failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/chain-snapshots/stats")
def chain_snapshot_stats(_user: dict = Depends(get_current_user)):
    """Database statistics for stored chain snapshots."""
    from data.chain_store import get_db_stats
    return get_db_stats()


@app.get("/api/chain-snapshots/{symbol}/dates")
def chain_snapshot_dates(symbol: str, _user: dict = Depends(get_current_user)):
    """List available snapshot dates for a symbol."""
    from data.chain_store import get_available_dates
    dates = get_available_dates(symbol.upper())
    return {"symbol": symbol.upper(), "dates": dates, "count": len(dates)}


@app.get("/api/chain-snapshots/{symbol}/{date}")
def chain_snapshot_detail(
    symbol: str,
    date: str,
    option_type: Optional[str] = Query(None, description="Filter: call or put"),
    min_strike: Optional[float] = Query(None),
    max_strike: Optional[float] = Query(None),
    _user: dict = Depends(get_current_user),
):
    """Retrieve a stored chain snapshot for a symbol and date."""
    from data.chain_store import get_snapshot
    snapshot = get_snapshot(symbol.upper(), date)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"No snapshot for {symbol} on {date}")

    contracts = snapshot.contracts
    if option_type:
        contracts = [c for c in contracts if c.option_type == option_type]
    if min_strike is not None:
        contracts = [c for c in contracts if c.strike >= min_strike]
    if max_strike is not None:
        contracts = [c for c in contracts if c.strike <= max_strike]

    return {
        "symbol": snapshot.ticker,
        "date": date,
        "spot": snapshot.spot,
        "expiries": snapshot.expiries,
        "contracts_count": len(contracts),
        "contracts": [
            {
                "strike": c.strike,
                "expiry": c.expiry,
                "option_type": c.option_type,
                "bid": c.bid,
                "ask": c.ask,
                "mid": c.mid,
                "last": c.last,
                "volume": c.volume,
                "open_interest": c.open_interest,
                "implied_volatility": c.implied_volatility,
            }
            for c in contracts
        ],
    }


@app.get("/api/iv-history/{symbol}")
def iv_history(
    symbol: str,
    start: str = Query("", description="Start date YYYY-MM-DD"),
    end: str = Query("", description="End date YYYY-MM-DD"),
    _user: dict = Depends(get_current_user),
):
    """IV history for a symbol from stored snapshots."""
    from data.chain_store import get_iv_history
    history = get_iv_history(symbol.upper(), start_date=start, end_date=end)
    return {"symbol": symbol.upper(), "history": history, "count": len(history)}




# ── Static Files (React build) ──────────────────────────────────────────────

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(_STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(_STATIC_DIR, "assets")), name="assets")

    _STATIC_DIR_REAL = os.path.realpath(_STATIC_DIR)

    @app.get("/{path:path}")
    def serve_spa(path: str):
        """Serve React SPA — all non-API routes serve index.html."""
        file_path = os.path.realpath(os.path.join(_STATIC_DIR, path))
        if not file_path.startswith(_STATIC_DIR_REAL):
            return FileResponse(os.path.join(_STATIC_DIR, "index.html"))
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))
