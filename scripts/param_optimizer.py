#!/usr/bin/env python3
"""
Parameter optimizer — grid search over agent backtest params per ticker.

Sweeps key trading parameters (stop loss, profit target, DTE range,
IV rank threshold, confluence minimum, bias strength) across Dolt
historical data. Stores results in SQLite for retrieval by the UI
or future tuning runs.

Usage:
    python scripts/param_optimizer.py --tickers SPY AAPL --start 2020-01-01 --end 2024-12-31
    python scripts/param_optimizer.py --status
    python scripts/param_optimizer.py --best SPY
    python scripts/param_optimizer.py --best-all
"""

import argparse
import itertools
import json
import logging
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from backtest.analyzer import analyze_results
from backtest.models import BacktestStats, BacktestTrade

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "param_optimization.db"

# ─── Parameter grid ───────────────────────────────────────────────────────────

PARAM_GRID = {
    "stop_loss_pct": [120, 150, 175, 200, 250],
    "profit_target_pct": [25, 30, 40, 50, 75],
    "dte_min": [3, 5, 7],
    "dte_max": [7, 10, 14],
    "iv_rank_threshold": [40, 50, 60, 70],
    "min_confluence": [60, 65, 70, 75, 80],
    "min_bias_strength": [2, 3, 4],
}

STRATEGY_CLASSES = {
    "credit": ["iron_condor", "short_put_spread", "short_call_spread"],
    "debit": ["long_call_spread", "long_put_spread"],
    "neutral": ["butterfly"],
}

CREDIT_STRATEGIES = {"iron_condor", "short_put_spread", "short_call_spread"}


# ─── Database ─────────────────────────────────────────────────────────────────

def _init_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS optimization_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            strategy_class TEXT NOT NULL,
            params_json TEXT NOT NULL,
            total_trades INTEGER NOT NULL,
            win_rate REAL,
            sharpe_ratio REAL,
            profit_factor REAL,
            total_pnl REAL,
            avg_win REAL,
            avg_loss REAL,
            max_drawdown REAL,
            avg_dte REAL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            run_timestamp TEXT NOT NULL,
            pricing_mode TEXT NOT NULL DEFAULT 'bs_simulated',
            UNIQUE(ticker, strategy_class, params_json, start_date, end_date, pricing_mode)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS best_params (
            ticker TEXT NOT NULL,
            strategy_class TEXT NOT NULL,
            params_json TEXT NOT NULL,
            sharpe_ratio REAL,
            profit_factor REAL,
            total_pnl REAL,
            win_rate REAL,
            total_trades INTEGER,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            pricing_mode TEXT NOT NULL DEFAULT 'bs_simulated',
            PRIMARY KEY (ticker, strategy_class, pricing_mode)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_opt_ticker
        ON optimization_runs(ticker, strategy_class, pricing_mode, sharpe_ratio DESC)
    """)
    # Migrate existing tables: add pricing_mode if missing
    try:
        conn.execute("SELECT pricing_mode FROM optimization_runs LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE optimization_runs ADD COLUMN pricing_mode TEXT NOT NULL DEFAULT 'bs_simulated'")
    try:
        conn.execute("SELECT pricing_mode FROM best_params LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE best_params ADD COLUMN pricing_mode TEXT NOT NULL DEFAULT 'bs_simulated'")
    conn.commit()
    return conn


def _store_result(conn: sqlite3.Connection, ticker: str, strategy_class: str,
                  params: Dict, stats: BacktestStats, start_date: str, end_date: str,
                  pricing_mode: str = "bs_simulated"):
    params_json = json.dumps(params, sort_keys=True)
    try:
        conn.execute("""
            INSERT OR REPLACE INTO optimization_runs
            (ticker, strategy_class, params_json, total_trades, win_rate,
             sharpe_ratio, profit_factor, total_pnl, avg_win, avg_loss,
             max_drawdown, avg_dte, start_date, end_date, run_timestamp, pricing_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker, strategy_class, params_json, stats.total_trades,
            stats.win_rate, stats.sharpe_ratio, stats.profit_factor,
            stats.total_pnl, stats.avg_win, stats.avg_loss,
            stats.max_drawdown, stats.avg_dte_at_entry,
            start_date, end_date, datetime.now().isoformat(), pricing_mode,
        ))
    except sqlite3.IntegrityError:
        pass


def _update_best(conn: sqlite3.Connection, ticker: str, strategy_class: str,
                 start_date: str, end_date: str, pricing_mode: str = "bs_simulated"):
    """Pick the best param set for this ticker+class by Sharpe (min 10 trades)."""
    row = conn.execute("""
        SELECT params_json, sharpe_ratio, profit_factor, total_pnl, win_rate, total_trades
        FROM optimization_runs
        WHERE ticker = ? AND strategy_class = ? AND start_date = ? AND end_date = ?
          AND pricing_mode = ? AND total_trades >= 10
        ORDER BY sharpe_ratio DESC
        LIMIT 1
    """, (ticker, strategy_class, start_date, end_date, pricing_mode)).fetchone()

    if row:
        conn.execute("""
            INSERT OR REPLACE INTO best_params
            (ticker, strategy_class, params_json, sharpe_ratio, profit_factor,
             total_pnl, win_rate, total_trades, start_date, end_date, updated_at, pricing_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker, strategy_class, row["params_json"], row["sharpe_ratio"],
            row["profit_factor"], row["total_pnl"], row["win_rate"],
            row["total_trades"], start_date, end_date, datetime.now().isoformat(),
            pricing_mode,
        ))


# ─── Backtest runner (lightweight, no full orchestrator) ──────────────────────

@dataclass
class PrecomputedDay:
    """Precomputed market state and candidates for a single date."""
    date_str: str
    spot: float
    chain_iv: float
    iv_rank: float
    bias_score: int
    candidates: List[Any]


def precompute_days(ticker: str, dates: List[str], snapshots: Dict) -> List[PrecomputedDay]:
    """Precompute market state + trade candidates once for all dates."""
    import math
    from market_state import build_market_state
    from trade_generator import generate_trades

    days = []
    for date_str in dates:
        snapshot = snapshots.get(date_str)
        if not snapshot or not snapshot.contracts:
            continue
        try:
            state = build_market_state(ticker, chain_snapshot=snapshot)
        except Exception:
            continue
        try:
            candidates = generate_trades(state)
        except Exception:
            candidates = []

        chain_iv = state.chain_iv if not math.isnan(state.chain_iv) else 0.20
        iv_rank = getattr(state, "iv_rank", None) or 0
        bias_score = getattr(state, "bias_score", 0) or 0

        days.append(PrecomputedDay(
            date_str=date_str,
            spot=state.spot,
            chain_iv=chain_iv,
            iv_rank=iv_rank,
            bias_score=bias_score,
            candidates=candidates,
        ))
    return days


def _run_single_backtest(
    ticker: str,
    strategy_class: str,
    params: Dict,
    precomputed: List[PrecomputedDay],
    start_date: str,
    end_date: str,
) -> Optional[BacktestStats]:
    """Run a single param combination through precomputed data."""
    stop_loss_pct = params["stop_loss_pct"]
    profit_target_pct = params["profit_target_pct"]
    dte_min = params["dte_min"]
    dte_max = params["dte_max"]
    iv_rank_threshold = params["iv_rank_threshold"]
    min_confluence = params["min_confluence"]
    min_bias_strength = params["min_bias_strength"]
    slippage_pct = 3.0

    allowed_strategies = STRATEGY_CLASSES[strategy_class]
    trades: List[BacktestTrade] = []
    open_trade = None
    cooldown_until = None

    for day in precomputed:
        date_str = day.date_str

        # Check exit on open trade
        if open_trade:
            entry_dt = datetime.strptime(open_trade["entry_date"], "%Y-%m-%d")
            current_dt = datetime.strptime(date_str, "%Y-%m-%d")
            days_held = (current_dt - entry_dt).days
            dte_remaining = open_trade["dte"] - days_held

            current_value = _price_position_fast(
                day.spot, open_trade["entry_spot"], day.chain_iv,
                dte_remaining, open_trade["strategy"], open_trade["is_credit"],
            )

            if open_trade["is_credit"]:
                pnl = open_trade["entry_price"] - current_value
            else:
                pnl = current_value - open_trade["entry_price"]

            exit_reason = None
            entry_price = open_trade["entry_price"]

            if entry_price > 0:
                if pnl >= entry_price * (profit_target_pct / 100):
                    exit_reason = "profit_target"
                elif pnl <= -entry_price * (stop_loss_pct / 100):
                    exit_reason = "stop_loss"

            if dte_remaining <= 1:
                exit_reason = "dte_exit"

            if exit_reason:
                slip = abs(current_value) * (slippage_pct / 100.0)
                if open_trade["is_credit"]:
                    final_pnl = entry_price - (current_value + slip)
                else:
                    final_pnl = (current_value - slip) - entry_price

                entry_d = datetime.strptime(open_trade["entry_date"], "%Y-%m-%d").date()
                exit_d = datetime.strptime(date_str, "%Y-%m-%d").date()

                trades.append(BacktestTrade(
                    entry_date=entry_d,
                    exit_date=exit_d,
                    entry_price=round(entry_price, 2),
                    exit_price=round(current_value, 2),
                    pnl=round(final_pnl * 100, 2),
                    pnl_pct=round(final_pnl / max(abs(entry_price), 0.01) * 100, 1),
                    dte_at_entry=open_trade["dte"],
                    dte_at_exit=max(dte_remaining, 0),
                    regime=open_trade["regime"],
                    score=open_trade["confluence"],
                    win=final_pnl > 0,
                    exit_reason=exit_reason,
                    bias_label=open_trade.get("bias_label"),
                    iv_at_entry=open_trade.get("iv"),
                ))
                open_trade = None
                cooldown_until = date_str

        # Try new entry (no open trade, past cooldown)
        if open_trade is None:
            if cooldown_until:
                cd_dt = datetime.strptime(cooldown_until, "%Y-%m-%d")
                cur_dt = datetime.strptime(date_str, "%Y-%m-%d")
                if (cur_dt - cd_dt).days < 5:
                    continue

            # IV rank filter for credit strategies
            if strategy_class == "credit" and day.iv_rank < iv_rank_threshold:
                continue

            # Bias strength filter for debit strategies
            if strategy_class == "debit" and abs(day.bias_score) < min_bias_strength:
                continue

            for tc in day.candidates:
                if tc.strategy not in allowed_strategies:
                    continue
                if tc.confluence_score < min_confluence:
                    continue

                dte = tc.suggested_dte if tc.suggested_dte > 0 else 7
                if dte < dte_min or dte > dte_max:
                    continue

                is_credit = tc.strategy in CREDIT_STRATEGIES
                raw_price = _price_position_fast(
                    day.spot, day.spot, day.chain_iv, dte, tc.strategy, is_credit
                )
                if raw_price <= 0.05:
                    continue

                slip = abs(raw_price) * (slippage_pct / 100.0)
                entry_price = (raw_price - slip) if is_credit else (raw_price + slip)
                if entry_price <= 0.01:
                    continue

                open_trade = {
                    "entry_date": date_str,
                    "entry_spot": day.spot,
                    "entry_price": entry_price,
                    "dte": dte,
                    "strategy": tc.strategy,
                    "is_credit": is_credit,
                    "regime": tc.regime,
                    "confluence": tc.confluence_score,
                    "bias_label": tc.bias_label,
                    "iv": day.chain_iv,
                }
                break

    if len(trades) < 3:
        return None

    return analyze_results(trades)


def _price_position_fast(spot, entry_spot, iv, dte_remaining, strategy, is_credit):
    """Lightweight BS repricing for position value."""
    from models.black_scholes import black_scholes_price
    from config import RISK_FREE_RATE

    T = max(dte_remaining / 365.0, 1 / 365.0)
    r = RISK_FREE_RATE
    inc = 5.0 if entry_spot >= 100 else (2.5 if entry_spot >= 50 else 1.0)
    atm = round(entry_spot / inc) * inc

    try:
        if strategy == "iron_condor":
            sc = black_scholes_price(spot, atm + inc, T, r, iv, "call")
            bc = black_scholes_price(spot, atm + 2 * inc, T, r, iv, "call")
            sp = black_scholes_price(spot, atm - inc, T, r, iv, "put")
            bp = black_scholes_price(spot, atm - 2 * inc, T, r, iv, "put")
            return (sc - bc) + (sp - bp)
        elif strategy == "short_put_spread":
            s = black_scholes_price(spot, atm - inc, T, r, iv, "put")
            b = black_scholes_price(spot, atm - 2 * inc, T, r, iv, "put")
            return s - b
        elif strategy == "short_call_spread":
            s = black_scholes_price(spot, atm + inc, T, r, iv, "call")
            b = black_scholes_price(spot, atm + 2 * inc, T, r, iv, "call")
            return s - b
        elif strategy == "long_call_spread":
            b = black_scholes_price(spot, atm, T, r, iv, "call")
            s = black_scholes_price(spot, atm + inc, T, r, iv, "call")
            return b - s
        elif strategy == "long_put_spread":
            b = black_scholes_price(spot, atm, T, r, iv, "put")
            s = black_scholes_price(spot, atm - inc, T, r, iv, "put")
            return b - s
        elif strategy == "butterfly":
            bc_lo = black_scholes_price(spot, atm - inc, T, r, iv, "call")
            sc_2 = black_scholes_price(spot, atm, T, r, iv, "call") * 2
            bc_hi = black_scholes_price(spot, atm + inc, T, r, iv, "call")
            return bc_lo - sc_2 + bc_hi
        return 0.0
    except Exception:
        return 0.0


# ─── Grid search ──────────────────────────────────────────────────────────────

def _generate_param_combos(strategy_class: str) -> List[Dict]:
    """Generate valid param combinations for a strategy class."""
    combos = []

    if strategy_class == "credit":
        for sl, pt, dte_min, dte_max, iv_th, conf in itertools.product(
            PARAM_GRID["stop_loss_pct"],
            PARAM_GRID["profit_target_pct"],
            PARAM_GRID["dte_min"],
            PARAM_GRID["dte_max"],
            PARAM_GRID["iv_rank_threshold"],
            PARAM_GRID["min_confluence"],
        ):
            if dte_min >= dte_max:
                continue
            combos.append({
                "stop_loss_pct": sl,
                "profit_target_pct": pt,
                "dte_min": dte_min,
                "dte_max": dte_max,
                "iv_rank_threshold": iv_th,
                "min_confluence": conf,
                "min_bias_strength": 0,
            })

    elif strategy_class == "debit":
        for sl, pt, dte_min, dte_max, bias, conf in itertools.product(
            [50, 75, 100],  # tighter stops for debit
            PARAM_GRID["profit_target_pct"],
            PARAM_GRID["dte_min"],
            PARAM_GRID["dte_max"],
            PARAM_GRID["min_bias_strength"],
            PARAM_GRID["min_confluence"],
        ):
            if dte_min >= dte_max:
                continue
            combos.append({
                "stop_loss_pct": sl,
                "profit_target_pct": pt,
                "dte_min": dte_min,
                "dte_max": dte_max,
                "iv_rank_threshold": 0,
                "min_confluence": conf,
                "min_bias_strength": bias,
            })

    elif strategy_class == "neutral":
        for pt, dte_min, dte_max, conf in itertools.product(
            [50, 75, 100, 150],
            [0, 3, 5],
            [5, 7, 10],
            PARAM_GRID["min_confluence"],
        ):
            if dte_min >= dte_max:
                continue
            combos.append({
                "stop_loss_pct": 100,
                "profit_target_pct": pt,
                "dte_min": dte_min,
                "dte_max": dte_max,
                "iv_rank_threshold": 0,
                "min_confluence": conf,
                "min_bias_strength": 0,
            })

    return combos


def optimize_ticker(
    ticker: str,
    start_date: str,
    end_date: str,
    strategy_classes: Optional[List[str]] = None,
    source: str = "dolt",
    pricing_mode: str = "bs_simulated",
) -> Dict[str, Dict]:
    """Run full grid search for a ticker across strategy classes."""
    from data.chain_store import get_available_dates, get_snapshot

    if strategy_classes is None:
        strategy_classes = ["credit", "debit", "neutral"]

    label = source if source != "chain_store" else "backfill"

    # Load all snapshots upfront for speed
    logger.info("Loading snapshots for %s (%s to %s) [label=%s]...", ticker, start_date, end_date, label)
    available = get_available_dates(ticker, label=label)
    dates = sorted([d for d in available if start_date <= d <= end_date])
    logger.info("  %d dates available", len(dates))

    if len(dates) < 30:
        logger.warning("  Insufficient data for %s, skipping", ticker)
        return {}

    snapshots = {}
    for d in dates:
        snap = get_snapshot(ticker, d, label=label)
        if snap and snap.contracts:
            snapshots[d] = snap

    logger.info("  %d valid snapshots loaded", len(snapshots))
    valid_dates = sorted(snapshots.keys())

    # Precompute all market states + candidates once (the expensive part)
    logger.info("  Precomputing market states and trade candidates...")
    precomputed = precompute_days(ticker, valid_dates, snapshots)
    logger.info("  %d days precomputed, ready for grid search", len(precomputed))

    conn = _init_db()
    results = {}

    for sc in strategy_classes:
        combos = _generate_param_combos(sc)
        logger.info("  %s: %d param combinations to test", sc, len(combos))

        tested = 0
        positive = 0
        t0 = time.time()

        for params in combos:
            stats = _run_single_backtest(
                ticker, sc, params, precomputed, start_date, end_date
            )
            if stats is None:
                continue

            tested += 1
            if stats.sharpe_ratio > 0:
                positive += 1

            _store_result(conn, ticker, sc, params, stats, start_date, end_date, pricing_mode)

            if tested % 100 == 0:
                conn.commit()
                elapsed = time.time() - t0
                logger.info(
                    "    %s %s: %d/%d tested (%.0f/sec), %d positive Sharpe",
                    ticker, sc, tested, len(combos), tested / elapsed, positive
                )

        conn.commit()
        _update_best(conn, ticker, sc, start_date, end_date, pricing_mode)

        elapsed = time.time() - t0
        logger.info(
            "  %s %s: DONE — %d tested in %.1fs, %d positive Sharpe",
            ticker, sc, tested, elapsed, positive
        )

        # Fetch best for reporting
        best = conn.execute("""
            SELECT params_json, sharpe_ratio, profit_factor, total_pnl, win_rate, total_trades
            FROM optimization_runs
            WHERE ticker = ? AND strategy_class = ? AND start_date = ? AND end_date = ?
              AND pricing_mode = ? AND total_trades >= 10
            ORDER BY sharpe_ratio DESC
            LIMIT 1
        """, (ticker, sc, start_date, end_date, pricing_mode)).fetchone()

        if best:
            results[sc] = {
                "params": json.loads(best["params_json"]),
                "sharpe": best["sharpe_ratio"],
                "pf": best["profit_factor"],
                "pnl": best["total_pnl"],
                "win_rate": best["win_rate"],
                "trades": best["total_trades"],
            }

    conn.close()
    return results


# ─── Query functions (for use by other modules) ───────────────────────────────

def get_best_params(ticker: str, strategy_class: Optional[str] = None,
                    pricing_mode: Optional[str] = None) -> List[Dict]:
    """Fetch stored best params for a ticker."""
    conn = _init_db()
    query = "SELECT * FROM best_params WHERE ticker = ?"
    args = [ticker]
    if strategy_class:
        query += " AND strategy_class = ?"
        args.append(strategy_class)
    if pricing_mode:
        query += " AND pricing_mode = ?"
        args.append(pricing_mode)
    rows = conn.execute(query, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_best_params(pricing_mode: Optional[str] = None) -> Dict[str, List[Dict]]:
    """Fetch best params for all tickers."""
    conn = _init_db()
    if pricing_mode:
        rows = conn.execute(
            "SELECT * FROM best_params WHERE pricing_mode = ? ORDER BY ticker, strategy_class",
            (pricing_mode,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM best_params ORDER BY ticker, strategy_class"
        ).fetchall()
    conn.close()

    result = {}
    for r in rows:
        ticker = r["ticker"]
        if ticker not in result:
            result[ticker] = []
        result[ticker].append(dict(r))
    return result


def get_optimization_status() -> Dict:
    """Get summary of optimization runs."""
    conn = _init_db()
    rows = conn.execute("""
        SELECT ticker, strategy_class, pricing_mode,
               COUNT(*) as combos_tested,
               MAX(sharpe_ratio) as best_sharpe,
               MAX(total_pnl) as best_pnl,
               run_timestamp
        FROM optimization_runs
        WHERE total_trades >= 10
        GROUP BY ticker, strategy_class, pricing_mode
        ORDER BY ticker, strategy_class, pricing_mode
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _print_best(ticker: str):
    results = get_best_params(ticker)
    if not results:
        print(f"  No optimization results for {ticker}")
        return

    print(f"\n{'='*60}")
    print(f"  Best Parameters: {ticker}")
    print(f"{'='*60}")

    for r in results:
        params = json.loads(r["params_json"])
        mode = r.get("pricing_mode", "bs_simulated")
        mode_label = "BS Simulated" if mode == "bs_simulated" else "Real Bid/Ask"
        print(f"\n  Strategy class: {r['strategy_class']}  [{mode_label}]")
        print(f"  Sharpe: {r['sharpe_ratio']:.2f} | PF: {r['profit_factor']:.2f} | "
              f"Win%: {r['win_rate']:.1f}% | Trades: {r['total_trades']}")
        print(f"  Total P&L: ${r['total_pnl']:.0f}")
        print(f"  Parameters:")
        for k, v in sorted(params.items()):
            print(f"    {k}: {v}")
    print()


def _print_all_best():
    all_best = get_all_best_params()
    if not all_best:
        print("  No optimization results found. Run optimizer first.")
        return

    print(f"\n{'='*80}")
    print(f"  Optimal Parameters by Ticker (ranked by Sharpe)")
    print(f"{'='*80}")
    print(f"\n  {'Ticker':<6} {'Class':<8} {'Pricing':<10} {'Sharpe':>7} {'PF':>6} {'Win%':>6} "
          f"{'Trades':>7} {'P&L':>8} {'StopL':>6} {'ProfT':>6} {'DTE':>7} {'Conf':>5}")
    print(f"  {'-'*6} {'-'*8} {'-'*10} {'-'*7} {'-'*6} {'-'*6} {'-'*7} {'-'*8} {'-'*6} {'-'*6} {'-'*7} {'-'*5}")

    for ticker, entries in sorted(all_best.items()):
        for e in entries:
            params = json.loads(e["params_json"])
            dte_str = f"{params.get('dte_min', '?')}-{params.get('dte_max', '?')}"
            mode = e.get("pricing_mode", "bs_simulated")
            mode_label = "BS" if mode == "bs_simulated" else "Real"
            print(f"  {ticker:<6} {e['strategy_class']:<8} {mode_label:<10} "
                  f"{e['sharpe_ratio']:>7.2f} {e['profit_factor']:>6.2f} "
                  f"{e['win_rate']:>5.1f}% {e['total_trades']:>7} "
                  f"${e['total_pnl']:>7.0f} "
                  f"{params.get('stop_loss_pct', '-'):>5}% "
                  f"{params.get('profit_target_pct', '-'):>5}% "
                  f"{dte_str:>7} {params.get('min_confluence', '-'):>5}")
    print()


def _print_status():
    rows = get_optimization_status()
    if not rows:
        print("  No optimization runs found.")
        return

    print(f"\n{'='*70}")
    print(f"  Parameter Optimization Status")
    print(f"{'='*70}")
    print(f"\n  {'Ticker':<6} {'Class':<8} {'Pricing':<10} {'Tested':>7} {'Best Sharpe':>12} {'Best P&L':>9}")
    print(f"  {'-'*6} {'-'*8} {'-'*10} {'-'*7} {'-'*12} {'-'*9}")

    for r in rows:
        mode = r.get("pricing_mode", "bs_simulated")
        mode_label = "BS" if mode == "bs_simulated" else "Real"
        print(f"  {r['ticker']:<6} {r['strategy_class']:<8} {mode_label:<10} "
              f"{r['combos_tested']:>7} {r['best_sharpe']:>12.2f} "
              f"${r['best_pnl']:>8.0f}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Parameter optimizer for agent backtests")
    parser.add_argument("--tickers", nargs="+", default=["SPY"])
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--classes", nargs="+", default=None,
                        choices=["credit", "debit", "neutral"])
    parser.add_argument("--source", default="dolt", choices=["dolt", "backfill"],
                        help="Data label in chain_snapshots.db")
    parser.add_argument("--pricing-mode", default="bs_simulated",
                        choices=["bs_simulated", "real_bidask"],
                        help="Pricing method: bs_simulated (Black-Scholes) or real_bidask (actual bid/ask)")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--best", type=str, help="Show best params for ticker")
    parser.add_argument("--best-all", action="store_true")
    args = parser.parse_args()

    if args.status:
        _print_status()
        return

    if args.best:
        _print_best(args.best)
        return

    if args.best_all:
        _print_all_best()
        return

    # Run optimization
    pricing_label = "Black-Scholes Simulated" if args.pricing_mode == "bs_simulated" else "Real Bid/Ask"
    print(f"\n{'='*60}")
    print(f"  Parameter Optimization")
    print(f"  Tickers: {', '.join(args.tickers)}")
    print(f"  Period: {args.start} to {args.end}")
    print(f"  Strategy classes: {args.classes or ['credit', 'debit', 'neutral']}")
    print(f"  Pricing: {pricing_label}")
    print(f"  Output: {DB_PATH}")
    print(f"{'='*60}\n")

    all_results = {}
    for ticker in args.tickers:
        logger.info("Optimizing %s...", ticker)
        results = optimize_ticker(ticker, args.start, args.end, args.classes,
                                  source=args.source, pricing_mode=args.pricing_mode)
        all_results[ticker] = results

    # Final summary
    print(f"\n{'='*60}")
    print(f"  Optimization Complete")
    print(f"{'='*60}\n")

    for ticker, results in all_results.items():
        print(f"  {ticker}:")
        if not results:
            print(f"    No tradeable configurations found")
            continue
        for sc, data in results.items():
            print(f"    {sc}: Sharpe={data['sharpe']:.2f} PF={data['pf']:.2f} "
                  f"Win={data['win_rate']:.1f}% Trades={data['trades']} "
                  f"P&L=${data['pnl']:.0f}")
            print(f"      Best params: {data['params']}")
        print()

    print(f"  Results stored in: {DB_PATH}")
    print(f"  Query with: python scripts/param_optimizer.py --best-all\n")


if __name__ == "__main__":
    main()
