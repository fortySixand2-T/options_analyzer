"""Positions CRUD router — user-scoped trade positions with P&L tracking."""

import json
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.auth.dependencies import get_current_user
from src.data.user_db import get_user_db

router = APIRouter(prefix="/api/positions", tags=["positions"])


class PositionCreate(BaseModel):
    symbol: str
    strategy: str
    legs_json: Optional[str] = None
    entry_date: str
    entry_price: float
    is_credit: bool = True
    contracts: int = 1
    max_loss: Optional[float] = None
    profit_target: Optional[float] = None
    stop_loss: Optional[float] = None
    regime_at_entry: Optional[str] = None
    bias_at_entry: Optional[str] = None
    notes: str = ""


class PositionUpdate(BaseModel):
    contracts: Optional[int] = None
    profit_target: Optional[float] = None
    stop_loss: Optional[float] = None
    notes: Optional[str] = None


class PositionClose(BaseModel):
    exit_price: float
    exit_reason: str = "manual"


@router.get("")
def list_positions(
    status: str = Query("open", description="open, closed, or all"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user: dict = Depends(get_current_user),
):
    """List positions with optional status filter."""
    conn = get_user_db()
    try:
        if status == "all":
            where = "user_id = ?"
            params = [_user["id"]]
        elif status == "closed":
            where = "user_id = ? AND status = 'closed'"
            params = [_user["id"]]
        else:
            where = "user_id = ? AND status = 'open'"
            params = [_user["id"]]

        total = conn.execute(f"SELECT COUNT(*) FROM positions WHERE {where}", params).fetchone()[0]
        rows = conn.execute(
            f"""SELECT * FROM positions WHERE {where}
                ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, created_at DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
    finally:
        conn.close()

    positions = [dict(r) for r in rows]
    return {"positions": positions, "total": total, "count": len(positions)}


@router.get("/greeks")
def aggregate_greeks(_user: dict = Depends(get_current_user)):
    """Aggregate Greeks across all open positions."""
    conn = get_user_db()
    try:
        rows = conn.execute(
            "SELECT * FROM positions WHERE user_id = ? AND status = 'open'",
            (_user["id"],),
        ).fetchall()
    finally:
        conn.close()

    agg = {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}
    for r in rows:
        legs = json.loads(r["legs_json"]) if r["legs_json"] else []
        for leg in legs:
            mult = r["contracts"] * 100
            agg["delta"] += (leg.get("delta", 0) or 0) * mult
            agg["gamma"] += (leg.get("gamma", 0) or 0) * mult
            agg["theta"] += (leg.get("theta", 0) or 0) * mult
            agg["vega"] += (leg.get("vega", 0) or 0) * mult

    return {
        "greeks": {k: round(v, 4) for k, v in agg.items()},
        "open_count": len(rows),
    }


@router.get("/summary")
def positions_summary(_user: dict = Depends(get_current_user)):
    """Quick summary stats for open and closed positions."""
    conn = get_user_db()
    try:
        open_count = conn.execute(
            "SELECT COUNT(*) FROM positions WHERE user_id = ? AND status = 'open'",
            (_user["id"],),
        ).fetchone()[0]
        closed = conn.execute(
            """SELECT COUNT(*) as cnt, SUM(pnl) as total_pnl,
                      SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins
               FROM positions WHERE user_id = ? AND status = 'closed'""",
            (_user["id"],),
        ).fetchone()
    finally:
        conn.close()

    total_closed = closed["cnt"] or 0
    wins = closed["wins"] or 0
    total_pnl = closed["total_pnl"] or 0

    return {
        "open": open_count,
        "closed": total_closed,
        "wins": wins,
        "win_rate": round(wins / total_closed * 100, 1) if total_closed else 0,
        "total_pnl": round(total_pnl, 2),
    }


@router.post("", status_code=201)
def create_position(body: PositionCreate, _user: dict = Depends(get_current_user)):
    """Log a new position."""
    symbol = body.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol required")

    conn = get_user_db()
    now = datetime.now(timezone.utc).isoformat()
    try:
        cursor = conn.execute(
            """INSERT INTO positions (user_id, symbol, strategy, legs_json, entry_date,
               entry_price, is_credit, contracts, max_loss, profit_target, stop_loss,
               regime_at_entry, bias_at_entry, notes, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (_user["id"], symbol, body.strategy, body.legs_json, body.entry_date,
             body.entry_price, int(body.is_credit), body.contracts, body.max_loss,
             body.profit_target, body.stop_loss, body.regime_at_entry,
             body.bias_at_entry, body.notes, now),
        )
        conn.commit()
        return {"status": "ok", "id": cursor.lastrowid}
    finally:
        conn.close()


@router.put("/{position_id}")
def update_position(position_id: int, body: PositionUpdate, _user: dict = Depends(get_current_user)):
    """Update an open position's fields."""
    conn = get_user_db()
    try:
        row = conn.execute(
            "SELECT * FROM positions WHERE id = ? AND user_id = ?",
            (position_id, _user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Position not found")
        if row["status"] != "open":
            raise HTTPException(status_code=400, detail="Cannot update a closed position")

        updates = {}
        if body.contracts is not None:
            updates["contracts"] = body.contracts
        if body.profit_target is not None:
            updates["profit_target"] = body.profit_target
        if body.stop_loss is not None:
            updates["stop_loss"] = body.stop_loss
        if body.notes is not None:
            updates["notes"] = body.notes

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [position_id, _user["id"]]
            conn.execute(
                f"UPDATE positions SET {set_clause} WHERE id = ? AND user_id = ?",
                values,
            )
            conn.commit()
    finally:
        conn.close()

    return {"status": "ok"}


@router.post("/{position_id}/close")
def close_position(position_id: int, body: PositionClose, _user: dict = Depends(get_current_user)):
    """Close a position with exit price and reason."""
    conn = get_user_db()
    try:
        row = conn.execute(
            "SELECT * FROM positions WHERE id = ? AND user_id = ?",
            (position_id, _user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Position not found")
        if row["status"] != "open":
            raise HTTPException(status_code=400, detail="Position already closed")

        entry = row["entry_price"]
        exit_p = body.exit_price
        contracts = row["contracts"]
        is_credit = bool(row["is_credit"])

        if is_credit:
            pnl = (entry - exit_p) * contracts * 100
        else:
            pnl = (exit_p - entry) * contracts * 100

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        conn.execute(
            """UPDATE positions SET status = 'closed', exit_date = ?, exit_price = ?,
               exit_reason = ?, pnl = ? WHERE id = ? AND user_id = ?""",
            (now, exit_p, body.exit_reason, round(pnl, 2), position_id, _user["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok", "pnl": round(pnl, 2)}
