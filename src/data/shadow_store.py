"""
SQLite storage for shadow paper trades.

Logs trade candidates as shadow trades, tracks daily mark-to-market,
and records exit outcomes. No real orders are placed.

Tables:
    shadow_trades      — one row per shadow trade (entry, exit, P&L)
    shadow_trade_marks — daily mark-to-market snapshots for open trades

Options Analytics Team — 2026-05
"""

import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "shadow_trades.db",
)


def _get_db_path() -> str:
    path = os.getenv("SHADOW_DB", _DEFAULT_DB_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_schema(conn)
    _migrate_agent_id(conn)
    return conn


def _migrate_agent_id(conn: sqlite3.Connection):
    """Add agent_id column to existing shadow_trades tables."""
    try:
        conn.execute("SELECT agent_id FROM shadow_trades LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE shadow_trades ADD COLUMN agent_id TEXT NOT NULL DEFAULT 'legacy'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shadow_agent ON shadow_trades(agent_id, status)")
        conn.commit()


def _init_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS shadow_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            strategy TEXT NOT NULL,
            strategy_label TEXT NOT NULL,
            legs_json TEXT NOT NULL,
            is_credit INTEGER NOT NULL,
            contracts INTEGER NOT NULL DEFAULT 1,
            -- Entry
            entry_date TEXT NOT NULL,
            entry_time TEXT,
            entry_net_price REAL NOT NULL,
            entry_leg_prices_json TEXT,
            entry_spot REAL,
            expiry TEXT,
            -- Exit
            exit_date TEXT,
            exit_time TEXT,
            exit_net_price REAL,
            exit_leg_prices_json TEXT,
            exit_spot REAL,
            exit_reason TEXT,
            -- P&L
            pnl_per_contract REAL,
            pnl_total REAL,
            -- Exit rules (snapshot at entry)
            profit_target_pct REAL,
            stop_loss_pct REAL,
            time_exit_dte INTEGER,
            -- Context (snapshot at entry)
            confluence_score REAL,
            regime TEXT,
            bias_label TEXT,
            dealer_regime TEXT,
            iv_rv_edge_pct REAL,
            rationale TEXT,
            -- Agent orchestrator
            agent_id TEXT NOT NULL DEFAULT 'legacy',
            -- Status: open, closed, expired, error
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(symbol, strategy, entry_date, legs_json, agent_id)
        );

        CREATE INDEX IF NOT EXISTS idx_shadow_status
            ON shadow_trades(status);
        CREATE INDEX IF NOT EXISTS idx_shadow_symbol
            ON shadow_trades(symbol, status);
        CREATE INDEX IF NOT EXISTS idx_shadow_date
            ON shadow_trades(entry_date);
        CREATE INDEX IF NOT EXISTS idx_shadow_agent
            ON shadow_trades(agent_id, status);

        CREATE TABLE IF NOT EXISTS shadow_trade_marks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL REFERENCES shadow_trades(id),
            mark_date TEXT NOT NULL,
            mark_net_price REAL,
            mark_leg_prices_json TEXT,
            mark_spot REAL,
            unrealized_pnl REAL,
            dte_remaining INTEGER,
            price_source TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(trade_id, mark_date)
        );

        CREATE INDEX IF NOT EXISTS idx_marks_trade
            ON shadow_trade_marks(trade_id);
    """)


def log_shadow_trade(
    trade_candidate,
    entry_leg_prices: List[Dict],
    spot: float,
    contracts: int = 1,
    agent_id: str = "legacy",
) -> Optional[int]:
    """Log a TradeCandidate as a shadow trade.

    Args:
        trade_candidate: TradeCandidate from trade_generator.
        entry_leg_prices: List of {strike, expiry, option_type, action, mid, bid, ask}.
        spot: Current underlying spot price.
        contracts: Number of contracts (default 1).

    Returns:
        Shadow trade ID, or None if duplicate.
    """
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    # Compute net entry price: sell legs are positive, buy legs are negative
    net_price = 0.0
    for lp in entry_leg_prices:
        mid = lp.get("mid", 0.0) or 0.0
        if lp["action"] == "sell":
            net_price += mid
        else:
            net_price -= mid

    # Determine expiry from legs (use the latest expiry)
    expiry = None
    if entry_leg_prices:
        expiries = [lp.get("expiry") for lp in entry_leg_prices if lp.get("expiry")]
        if expiries:
            expiry = max(expiries)

    legs_json = json.dumps(trade_candidate.legs)

    conn = _get_conn()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO shadow_trades (
                symbol, strategy, strategy_label, legs_json, is_credit, contracts,
                entry_date, entry_time, entry_net_price, entry_leg_prices_json,
                entry_spot, expiry,
                profit_target_pct, stop_loss_pct, time_exit_dte,
                confluence_score, regime, bias_label, dealer_regime,
                iv_rv_edge_pct, rationale, agent_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
            (
                trade_candidate.symbol,
                trade_candidate.strategy,
                trade_candidate.strategy_label,
                legs_json,
                1 if trade_candidate.is_credit else 0,
                contracts,
                today,
                now.isoformat(),
                round(net_price, 4),
                json.dumps(entry_leg_prices),
                round(spot, 2),
                expiry,
                trade_candidate.exit_rule.profit_target_pct,
                trade_candidate.exit_rule.stop_loss_pct,
                trade_candidate.exit_rule.time_exit_dte,
                trade_candidate.confluence_score,
                trade_candidate.regime,
                trade_candidate.bias_label,
                trade_candidate.dealer_regime,
                trade_candidate.iv_rv_edge_pct,
                trade_candidate.rationale,
                agent_id,
            ),
        )
        conn.commit()

        if conn.total_changes == 0:
            logger.info("Shadow trade already exists for %s/%s on %s",
                        trade_candidate.symbol, trade_candidate.strategy, today)
            return None

        trade_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        logger.info("Logged shadow trade #%d: %s %s score=%.0f entry=%.4f",
                     trade_id, trade_candidate.symbol,
                     trade_candidate.strategy, trade_candidate.confluence_score,
                     net_price)
        return trade_id
    finally:
        conn.close()


def get_open_trades(agent_id: Optional[str] = None) -> List[Dict]:
    """Return open shadow trades, optionally filtered by agent."""
    conn = _get_conn()
    try:
        if agent_id:
            rows = conn.execute(
                "SELECT * FROM shadow_trades WHERE status = 'open' AND agent_id = ? ORDER BY entry_date",
                (agent_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM shadow_trades WHERE status = 'open' ORDER BY entry_date"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_trades(
    status: Optional[str] = None,
    symbol: Optional[str] = None,
    strategy: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """Return shadow trades with optional filters."""
    clauses = []
    params: list = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol)
    if strategy:
        clauses.append("strategy = ?")
        params.append(strategy)
    if agent_id:
        clauses.append("agent_id = ?")
        params.append(agent_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM shadow_trades {where} ORDER BY entry_date DESC LIMIT ?"
    params.append(limit)

    conn = _get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def close_trade(
    trade_id: int,
    exit_leg_prices: List[Dict],
    exit_reason: str,
    exit_spot: float,
) -> float:
    """Close a shadow trade and compute P&L.

    Returns pnl_per_contract.
    """
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM shadow_trades WHERE id = ?", (trade_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Shadow trade #{trade_id} not found")

        # Compute exit net price (same convention: sell=+, buy=-)
        # At exit, actions are reversed: we close the position
        exit_net = 0.0
        for lp in exit_leg_prices:
            mid = lp.get("mid", 0.0) or 0.0
            # Closing: reverse the original action
            if lp["action"] == "sell":
                # Originally sold, now buying to close
                exit_net -= mid
            else:
                # Originally bought, now selling to close
                exit_net += mid

        entry_net = row["entry_net_price"]
        is_credit = row["is_credit"]

        # P&L: for credit trades, profit = entry_credit - exit_cost
        # For debit trades, profit = exit_value - entry_cost
        if is_credit:
            pnl_per = (entry_net + exit_net) * 100  # entry_net>0 (credit), exit_net<0 (cost to close)
        else:
            pnl_per = (exit_net + entry_net) * 100  # entry_net<0 (debit paid), exit_net>0 (value received)

        contracts = row["contracts"]
        pnl_total = pnl_per * contracts

        conn.execute(
            """UPDATE shadow_trades SET
                exit_date = ?, exit_time = ?, exit_net_price = ?,
                exit_leg_prices_json = ?, exit_spot = ?, exit_reason = ?,
                pnl_per_contract = ?, pnl_total = ?,
                status = 'closed', updated_at = ?
            WHERE id = ?""",
            (
                today, now.isoformat(), round(exit_net, 4),
                json.dumps(exit_leg_prices), round(exit_spot, 2), exit_reason,
                round(pnl_per, 2), round(pnl_total, 2),
                now.isoformat(), trade_id,
            ),
        )
        conn.commit()

        logger.info("Closed shadow trade #%d (%s): %s, P&L=%.2f",
                     trade_id, exit_reason, row["symbol"], pnl_total)
        return pnl_per
    finally:
        conn.close()


def record_mark(
    trade_id: int,
    mark_date: str,
    mark_leg_prices: List[Dict],
    mark_spot: float,
    unrealized_pnl: float,
    dte_remaining: int,
    price_source: str = "snapshot",
):
    """Record a daily mark-to-market snapshot for an open trade."""
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO shadow_trade_marks (
                trade_id, mark_date, mark_net_price, mark_leg_prices_json,
                mark_spot, unrealized_pnl, dte_remaining, price_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade_id, mark_date,
                _compute_mark_net(mark_leg_prices),
                json.dumps(mark_leg_prices),
                round(mark_spot, 2),
                round(unrealized_pnl, 2),
                dte_remaining,
                price_source,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _compute_mark_net(leg_prices: List[Dict]) -> float:
    """Compute current net spread value from leg prices."""
    net = 0.0
    for lp in leg_prices:
        mid = lp.get("mid", 0.0) or 0.0
        if lp.get("action") == "sell":
            net += mid
        else:
            net -= mid
    return round(net, 4)


def get_stats() -> Dict[str, Any]:
    """Compute aggregate shadow trading statistics."""
    conn = _get_conn()
    try:
        # Closed trade stats
        closed = conn.execute(
            "SELECT * FROM shadow_trades WHERE status = 'closed'"
        ).fetchall()

        open_trades = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades WHERE status = 'open'"
        ).fetchone()[0]

        total_closed = len(closed)
        if total_closed == 0:
            return {
                "total_trades": open_trades,
                "open_trades": open_trades,
                "closed_trades": 0,
                "wins": 0, "losses": 0, "win_rate": 0.0,
                "total_pnl": 0.0, "avg_pnl": 0.0,
                "best_trade": 0.0, "worst_trade": 0.0,
                "by_strategy": {}, "by_regime": {},
            }

        pnls = [r["pnl_total"] for r in closed]
        wins = sum(1 for p in pnls if p > 0)
        losses = total_closed - wins

        # By strategy
        by_strategy: Dict[str, Dict] = {}
        for r in closed:
            s = r["strategy"]
            if s not in by_strategy:
                by_strategy[s] = {"trades": 0, "wins": 0, "pnl": 0.0}
            by_strategy[s]["trades"] += 1
            by_strategy[s]["pnl"] += r["pnl_total"]
            if r["pnl_total"] > 0:
                by_strategy[s]["wins"] += 1
        for s in by_strategy:
            t = by_strategy[s]["trades"]
            by_strategy[s]["win_rate"] = round(by_strategy[s]["wins"] / t * 100, 1) if t else 0
            by_strategy[s]["avg_pnl"] = round(by_strategy[s]["pnl"] / t, 2) if t else 0

        # By regime
        by_regime: Dict[str, Dict] = {}
        for r in closed:
            reg = r["regime"] or "UNKNOWN"
            if reg not in by_regime:
                by_regime[reg] = {"trades": 0, "wins": 0, "pnl": 0.0}
            by_regime[reg]["trades"] += 1
            by_regime[reg]["pnl"] += r["pnl_total"]
            if r["pnl_total"] > 0:
                by_regime[reg]["wins"] += 1

        return {
            "total_trades": total_closed + open_trades,
            "open_trades": open_trades,
            "closed_trades": total_closed,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total_closed * 100, 1),
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl": round(sum(pnls) / total_closed, 2),
            "best_trade": round(max(pnls), 2),
            "worst_trade": round(min(pnls), 2),
            "by_strategy": by_strategy,
            "by_regime": by_regime,
        }
    finally:
        conn.close()


def get_trade_marks(trade_id: int) -> List[Dict]:
    """Get all mark-to-market records for a trade."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM shadow_trade_marks WHERE trade_id = ? ORDER BY mark_date",
            (trade_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_agent_positions(agent_id: str) -> List[Dict]:
    """Return open trades for a specific agent with ticker and direction info."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM shadow_trades WHERE agent_id = ? AND status = 'open' ORDER BY entry_date",
            (agent_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_daily_pnl(agent_id: Optional[str] = None, date: Optional[str] = None) -> float:
    """Compute realized P&L for closed trades on a given date."""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    conn = _get_conn()
    try:
        if agent_id:
            row = conn.execute(
                "SELECT COALESCE(SUM(pnl_total), 0) FROM shadow_trades "
                "WHERE agent_id = ? AND status = 'closed' AND exit_date = ?",
                (agent_id, date),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COALESCE(SUM(pnl_total), 0) FROM shadow_trades "
                "WHERE status = 'closed' AND exit_date = ?",
                (date,),
            ).fetchone()
        return float(row[0])
    finally:
        conn.close()


def get_cumulative_pnl(agent_id: Optional[str] = None) -> float:
    """Compute total realized P&L across all closed trades."""
    conn = _get_conn()
    try:
        if agent_id:
            row = conn.execute(
                "SELECT COALESCE(SUM(pnl_total), 0) FROM shadow_trades "
                "WHERE agent_id = ? AND status = 'closed'",
                (agent_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COALESCE(SUM(pnl_total), 0) FROM shadow_trades "
                "WHERE status = 'closed'",
            ).fetchone()
        return float(row[0])
    finally:
        conn.close()


def get_agent_stats(agent_id: str) -> Dict[str, Any]:
    """Compute per-agent trading statistics."""
    conn = _get_conn()
    try:
        closed = conn.execute(
            "SELECT * FROM shadow_trades WHERE agent_id = ? AND status = 'closed'",
            (agent_id,),
        ).fetchall()

        open_count = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades WHERE agent_id = ? AND status = 'open'",
            (agent_id,),
        ).fetchone()[0]

        total_closed = len(closed)
        if total_closed == 0:
            return {
                "agent_id": agent_id,
                "open_trades": open_count,
                "closed_trades": 0,
                "wins": 0, "losses": 0, "win_rate": 0.0,
                "total_pnl": 0.0, "avg_pnl": 0.0,
                "max_drawdown": 0.0,
                "by_strategy": {},
            }

        pnls = [r["pnl_total"] for r in closed]
        wins = sum(1 for p in pnls if p > 0)

        # Max drawdown from cumulative P&L curve
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for r in sorted(closed, key=lambda x: x["exit_date"] or ""):
            cumulative += r["pnl_total"]
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        by_strategy: Dict[str, Dict] = {}
        for r in closed:
            s = r["strategy"]
            if s not in by_strategy:
                by_strategy[s] = {"trades": 0, "wins": 0, "pnl": 0.0}
            by_strategy[s]["trades"] += 1
            by_strategy[s]["pnl"] += r["pnl_total"]
            if r["pnl_total"] > 0:
                by_strategy[s]["wins"] += 1

        return {
            "agent_id": agent_id,
            "open_trades": open_count,
            "closed_trades": total_closed,
            "wins": wins,
            "losses": total_closed - wins,
            "win_rate": round(wins / total_closed * 100, 1),
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl": round(sum(pnls) / total_closed, 2),
            "max_drawdown": round(max_dd, 2),
            "by_strategy": by_strategy,
        }
    finally:
        conn.close()
