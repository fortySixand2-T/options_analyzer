"""Performance analytics — read-only stats derived from closed positions."""

from fastapi import APIRouter, Depends, Query
from typing import Optional

from src.auth.dependencies import get_current_user
from src.data.user_db import get_user_db

router = APIRouter(prefix="/api/performance", tags=["performance"])


@router.get("/summary")
def performance_summary(_user: dict = Depends(get_current_user)):
    """Cumulative P&L, win rate, trade count, profit factor."""
    conn = get_user_db()
    try:
        rows = conn.execute(
            "SELECT pnl FROM positions WHERE user_id = ? AND status = 'closed' AND pnl IS NOT NULL",
            (_user["id"],),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "total_pnl": 0, "avg_pnl": 0, "profit_factor": 0,
                "avg_win": 0, "avg_loss": 0, "max_win": 0, "max_loss": 0}

    pnls = [r["pnl"] for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0

    return {
        "total_trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(pnls) * 100, 1),
        "total_pnl": round(sum(pnls), 2),
        "avg_pnl": round(sum(pnls) / len(pnls), 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else 999,
        "avg_win": round(gross_profit / len(wins), 2) if wins else 0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0,
        "max_win": round(max(pnls), 2),
        "max_loss": round(min(pnls), 2),
    }


@router.get("/by-strategy")
def by_strategy(_user: dict = Depends(get_current_user)):
    """P&L breakdown per strategy."""
    conn = get_user_db()
    try:
        rows = conn.execute(
            """SELECT strategy, COUNT(*) as trades, SUM(pnl) as total_pnl,
                      SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins
               FROM positions WHERE user_id = ? AND status = 'closed' AND pnl IS NOT NULL
               GROUP BY strategy""",
            (_user["id"],),
        ).fetchall()
    finally:
        conn.close()

    return {"strategies": [
        {
            "strategy": r["strategy"],
            "trades": r["trades"],
            "total_pnl": round(r["total_pnl"] or 0, 2),
            "win_rate": round((r["wins"] or 0) / r["trades"] * 100, 1) if r["trades"] else 0,
        }
        for r in rows
    ]}


@router.get("/by-regime")
def by_regime(_user: dict = Depends(get_current_user)):
    """P&L breakdown per regime at entry."""
    conn = get_user_db()
    try:
        rows = conn.execute(
            """SELECT regime_at_entry as regime, COUNT(*) as trades, SUM(pnl) as total_pnl,
                      SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins
               FROM positions WHERE user_id = ? AND status = 'closed' AND pnl IS NOT NULL
               GROUP BY regime_at_entry""",
            (_user["id"],),
        ).fetchall()
    finally:
        conn.close()

    return {"regimes": [
        {
            "regime": r["regime"] or "Unknown",
            "trades": r["trades"],
            "total_pnl": round(r["total_pnl"] or 0, 2),
            "win_rate": round((r["wins"] or 0) / r["trades"] * 100, 1) if r["trades"] else 0,
        }
        for r in rows
    ]}


@router.get("/by-month")
def by_month(_user: dict = Depends(get_current_user)):
    """Monthly P&L grid."""
    conn = get_user_db()
    try:
        rows = conn.execute(
            """SELECT substr(exit_date, 1, 7) as month, COUNT(*) as trades,
                      SUM(pnl) as total_pnl,
                      SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins
               FROM positions WHERE user_id = ? AND status = 'closed'
                    AND pnl IS NOT NULL AND exit_date IS NOT NULL
               GROUP BY month ORDER BY month""",
            (_user["id"],),
        ).fetchall()
    finally:
        conn.close()

    return {"months": [
        {
            "month": r["month"],
            "trades": r["trades"],
            "total_pnl": round(r["total_pnl"] or 0, 2),
            "win_rate": round((r["wins"] or 0) / r["trades"] * 100, 1) if r["trades"] else 0,
        }
        for r in rows
    ]}


@router.get("/equity-curve")
def equity_curve(_user: dict = Depends(get_current_user)):
    """Cumulative P&L series ordered by exit date."""
    conn = get_user_db()
    try:
        rows = conn.execute(
            """SELECT exit_date, pnl FROM positions
               WHERE user_id = ? AND status = 'closed' AND pnl IS NOT NULL AND exit_date IS NOT NULL
               ORDER BY exit_date""",
            (_user["id"],),
        ).fetchall()
    finally:
        conn.close()

    curve = []
    cumulative = 0
    for r in rows:
        cumulative += r["pnl"]
        curve.append({"date": r["exit_date"], "pnl": round(r["pnl"], 2), "cumulative": round(cumulative, 2)})

    return {"curve": curve}


@router.get("/drawdown")
def drawdown(_user: dict = Depends(get_current_user)):
    """Running max drawdown series."""
    conn = get_user_db()
    try:
        rows = conn.execute(
            """SELECT exit_date, pnl FROM positions
               WHERE user_id = ? AND status = 'closed' AND pnl IS NOT NULL AND exit_date IS NOT NULL
               ORDER BY exit_date""",
            (_user["id"],),
        ).fetchall()
    finally:
        conn.close()

    series = []
    cumulative = 0
    peak = 0
    max_dd = 0
    for r in rows:
        cumulative += r["pnl"]
        peak = max(peak, cumulative)
        dd = cumulative - peak
        max_dd = min(max_dd, dd)
        series.append({"date": r["exit_date"], "drawdown": round(dd, 2)})

    return {"series": series, "max_drawdown": round(max_dd, 2)}
