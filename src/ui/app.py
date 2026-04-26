"""
FastAPI backend for the Options Scanner web UI.

Routes:
    GET  /api/regime                  ��� current regime classification + VIX
    GET  /api/scan                    — scanner results with checklists
    GET  /api/chain/{symbol}          — options chain with Greeks
    POST /api/greeks                  — compute Greeks for arbitrary inputs
    GET  /api/backtest/{strategy}     — backtest results
    GET  /api/journal                 — trade journal entries
    POST /api/journal                 — log a trade

Options Analytics Team — 2026-04
"""

import logging
import os
from datetime import date
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Options Scanner API",
    description="Index Options Scanner — regime detection, strategy scoring, backtesting",
    version="1.0.0",
)

# CORS for React dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request/Response Models ──────────────────────────────────────────────────

class GreeksRequest(BaseModel):
    spot: float
    strike: float
    dte: int
    iv: float
    r: Optional[float] = None
    option_type: str = "call"


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
def get_regime(symbol: str = Query("SPY", description="Symbol for dealer data")):
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
        raise HTTPException(status_code=500, detail=str(e))


# ── Market State ──────────────────────────────────────────────────────────────

@app.get("/api/market-state")
def get_market_state(symbol: str = Query("SPY", description="Symbol")):
    """Full L1 market state snapshot — regime, edge, skew, dealer, quality."""
    try:
        from market_state import build_market_state
        state = build_market_state(symbol.upper())
        return state.to_dict()
    except Exception as e:
        logger.exception("Failed to build market state for %s", symbol)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trade-candidates")
def get_trade_candidates(
    symbol: str = Query("SPY", description="Symbol"),
    portfolio_value: float = Query(100_000, description="Portfolio value for sizing"),
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
        raise HTTPException(status_code=500, detail=str(e))


# In-memory portfolio singleton (persists across requests within a session)
_portfolio_instance = None

def _get_portfolio():
    global _portfolio_instance
    if _portfolio_instance is None:
        from portfolio import Portfolio
        _portfolio_instance = Portfolio()
    return _portfolio_instance


@app.get("/api/portfolio")
def get_portfolio():
    """L4 portfolio snapshot — positions, Greeks, risk, hedge triggers."""
    try:
        pf = _get_portfolio()
        return pf.to_dict()
    except Exception as e:
        logger.exception("Failed to get portfolio")
        raise HTTPException(status_code=500, detail=str(e))


# ── Scanner ────────────────���─────────────────────────────────────────────────

@app.get("/api/scan")
def scan(
    symbols: str = Query("SPY", description="Comma-separated symbols"),
    max_dte: int = Query(14, description="Max DTE filter"),
    min_dte: int = Query(0, description="Min DTE filter"),
    strategies: bool = Query(False, description="Include strategy evaluation"),
    top: int = Query(20, description="Max results"),
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
        raise HTTPException(status_code=500, detail=str(e))


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
        "score": s.score,
        "regime": s.regime.value,
        "checks_passed": s.checks_passed,
        "checks_total": s.checks_total,
        "checklist": [
            {"name": c.name, "passed": c.passed, "value": c.value}
            for c in s.checklist
        ],
        "legs": s.legs,
        "entry": s.entry,
        "is_credit": s.is_credit,
        "max_profit": s.max_profit,
        "max_loss": s.max_loss,
        "risk_reward": s.risk_reward,
        "prob_profit": s.prob_profit,
        "suggested_dte": s.suggested_dte,
        "rationale": s.rationale,
    }


# ── Chain ─────────��──────────────────────────��───────────────────────────────

@app.get("/api/chain/{symbol}")
def get_chain(
    symbol: str,
    max_dte: int = Query(14, description="Max DTE"),
    min_dte: int = Query(0, description="Min DTE"),
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
        raise HTTPException(status_code=500, detail=str(e))


# ── Greeks Calculator ─────────────────────────────────────���──────────────────

@app.post("/api/greeks")
def compute_greeks(req: GreeksRequest):
    """Compute BS price + Greeks for arbitrary inputs."""
    from models.black_scholes import black_scholes_price, calculate_greeks
    from config import RISK_FREE_RATE

    r = req.r if req.r is not None else RISK_FREE_RATE
    T = max(req.dte / 365.0, 1 / 365.0)

    price = black_scholes_price(req.spot, req.strike, T, r, req.iv, req.option_type)
    greeks = calculate_greeks(req.spot, req.strike, T, r, req.iv, req.option_type)

    return {
        "price": round(price, 4),
        "greeks": {k: round(v, 6) for k, v in greeks.items()},
        "inputs": {
            "spot": req.spot,
            "strike": req.strike,
            "dte": req.dte,
            "iv": req.iv,
            "r": r,
            "option_type": req.option_type,
        },
    }


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
            }
            for t in (result.trades or [])
        ],
        "trades_count": len(result.trades) if result.trades else 0,
    }


@app.get("/api/backtest/{strategy}")
def get_backtest(
    strategy: str,
    symbol: str = Query("SPY"),
    start: str = Query("2022-01-01"),
    end: Optional[str] = Query(None),
    regime_filter: bool = Query(False),
    bias_filter: bool = Query(False),
    dealer_filter: bool = Query(False),
    edge_threshold: float = Query(0.0),
    exit_rule: str = Query("50pct"),
):
    """Run or retrieve cached backtest results with optional signal filters."""
    from backtest.models import BacktestRequest
    from backtest.local_backtest import run_local_backtest

    end_date = date.fromisoformat(end) if end else date.today()
    start_date = date.fromisoformat(start)

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
    )

    try:
        result = run_local_backtest(req)
        return _serialize_backtest(result, strategy, symbol, start_date, end_date)
    except Exception as e:
        logger.exception("Backtest failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/backtest/compare")
def compare_backtests(
    strategies: str = Query("iron_condor,short_put_spread"),
    symbol: str = Query("SPY"),
    start: str = Query("2022-01-01"),
    end: Optional[str] = Query(None),
    regime_filter: bool = Query(False),
    bias_filter: bool = Query(False),
    dealer_filter: bool = Query(False),
    edge_threshold: float = Query(0.0),
    exit_rule: str = Query("50pct"),
):
    """Compare backtests across multiple strategies."""
    from backtest.models import BacktestRequest
    from backtest.local_backtest import run_local_backtest

    end_date = date.fromisoformat(end) if end else date.today()
    start_date = date.fromisoformat(start)
    strategy_list = [s.strip() for s in strategies.split(",") if s.strip()]

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
        )
        try:
            result = run_local_backtest(req)
            results[strat] = _serialize_backtest(result, strat, symbol, start_date, end_date)
        except Exception as e:
            logger.warning("Backtest failed for %s: %s", strat, e)
            results[strat] = {"error": str(e)}

    return {"strategies": results, "symbol": symbol, "period": {"start": str(start_date), "end": str(end_date)}}


# ── Journal ───────────────────────────��──────────────────────────────────────

# Simple SQLite-backed journal
_JOURNAL_DB = os.getenv("JOURNAL_DB", "data/journal.db")


def _get_journal_db():
    import sqlite3
    os.makedirs(os.path.dirname(_JOURNAL_DB) if os.path.dirname(_JOURNAL_DB) else ".", exist_ok=True)
    conn = sqlite3.connect(_JOURNAL_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy TEXT NOT NULL,
            symbol TEXT NOT NULL,
            entry_date TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_date TEXT,
            exit_price REAL,
            contracts INTEGER DEFAULT 1,
            pnl REAL,
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


@app.get("/api/journal")
def list_journal(limit: int = Query(50)):
    """List trade journal entries."""
    conn = _get_journal_db()
    rows = conn.execute(
        "SELECT * FROM journal ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    cols = ["id", "strategy", "symbol", "entry_date", "entry_price",
            "exit_date", "exit_price", "contracts", "pnl", "notes", "created_at"]
    entries = [dict(zip(cols, row)) for row in rows]
    conn.close()
    return {"entries": entries, "count": len(entries)}


@app.post("/api/journal")
def add_journal(entry: JournalEntry):
    """Log a trade to the journal."""
    conn = _get_journal_db()
    conn.execute(
        """INSERT INTO journal (strategy, symbol, entry_date, entry_price,
           exit_date, exit_price, contracts, pnl, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (entry.strategy, entry.symbol, entry.entry_date, entry.entry_price,
         entry.exit_date, entry.exit_price, entry.contracts, entry.pnl, entry.notes),
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}


# ── Streaming WebSocket ─────────────────────────────────────────────────────

@app.websocket("/ws/greeks")
async def ws_greeks(websocket):
    """WebSocket endpoint for live streaming Greeks.

    Client sends JSON: {"action": "subscribe", "symbols": ["SPY"], "max_dte": 14}
    Server streams JSON: {symbol, bid, ask, mid, iv, delta, gamma, theta, vega, ...}
    """
    from starlette.websockets import WebSocketDisconnect

    await websocket.accept()

    try:
        from streaming.dxfeed_streamer import DXFeedStreamer
        from streaming.score_engine import LiveScoreEngine

        streamer = DXFeedStreamer()
        engine = LiveScoreEngine()

        # Wait for subscription message from client
        msg = await websocket.receive_json()
        symbols = msg.get("symbols", ["SPY"])
        max_dte = msg.get("max_dte", 14)

        connected = await streamer.connect()
        if not connected:
            await websocket.send_json({"error": "Could not connect to streaming feed"})
            await websocket.close()
            return

        count = await streamer.subscribe(symbols, max_dte=max_dte)
        await websocket.send_json({"status": "subscribed", "contracts": count})

        # Stream updates to client
        async def on_update(update):
            score = engine.on_quote_update(update)
            if score:
                try:
                    await websocket.send_json({
                        "symbol": score.symbol,
                        "strike": score.strike,
                        "option_type": score.option_type,
                        "dte": score.dte,
                        "spot": score.spot,
                        "bid": score.bid,
                        "ask": score.ask,
                        "mid": score.mid,
                        "iv": score.iv,
                        "delta": score.delta,
                        "gamma": score.gamma,
                        "theta": score.theta,
                        "vega": score.vega,
                        "theo_price": score.theo_price,
                        "edge_pct": score.edge_pct,
                        "conviction": score.conviction,
                    })
                except Exception:
                    pass

        await streamer.listen(callback=on_update)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.warning("WebSocket error: %s", e)
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
    finally:
        if 'streamer' in dir():
            await streamer.disconnect()


# ── Order Execution ──────────────────────────────────────────────────────────

class PlaceOrderRequest(BaseModel):
    underlying: str
    strategy: str
    legs: List[Dict]  # [{action, option_type, strike, quantity}]
    order_type: str = "limit"
    price: Optional[float] = None
    dry_run: bool = True  # default to dry run for safety


@app.post("/api/order")
def place_order(req: PlaceOrderRequest):
    """Place an order via Tastytrade (paper by default)."""
    from execution.order_manager import OrderManager, OrderRequest, OrderLeg

    mgr = OrderManager()
    if not mgr.connect():
        raise HTTPException(status_code=503, detail="Cannot connect to Tastytrade")

    legs = []
    for leg in req.legs:
        legs.append(OrderLeg(
            action=leg.get("action", "buy_to_open"),
            symbol=leg.get("symbol", ""),
            quantity=int(leg.get("quantity", 1)),
            option_type=leg.get("option_type", "call"),
            strike=float(leg.get("strike", 0)),
            expiry=leg.get("expiry", ""),
        ))

    order_req = OrderRequest(
        underlying=req.underlying,
        strategy=req.strategy,
        legs=legs,
        order_type=req.order_type,
        price=req.price,
        dry_run=req.dry_run,
    )

    result = mgr.submit(order_req)
    return {
        "status": result.status.value,
        "order_id": result.order_id,
        "message": result.message,
        "is_paper": result.is_paper,
    }


@app.get("/api/positions")
def get_positions():
    """Get current account positions from Tastytrade."""
    from execution.order_manager import OrderManager
    mgr = OrderManager()
    if not mgr.connect():
        return {"positions": [], "error": "Not connected to Tastytrade"}
    return {"positions": mgr.get_positions()}


@app.get("/api/streamer/status")
def streamer_status():
    """Check if streaming is available."""
    has_creds = bool(os.getenv("TT_USERNAME")) and bool(os.getenv("TT_PASSWORD"))
    return {
        "streaming_available": has_creds,
        "credentials_set": has_creds,
        "websocket_url": "/ws/greeks",
    }


# ── Static Files (React build) ──────────────────────────────────────────────

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(_STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(_STATIC_DIR, "assets")), name="assets")

    @app.get("/{path:path}")
    def serve_spa(path: str):
        """Serve React SPA — all non-API routes serve index.html."""
        file_path = os.path.join(_STATIC_DIR, path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))
