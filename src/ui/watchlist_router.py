"""Watchlist CRUD router — user-scoped symbol watchlist with alert thresholds."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from src.auth.dependencies import get_current_user
from src.data.user_db import get_user_db

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class WatchlistAdd(BaseModel):
    symbol: str
    alert_iv_rank_above: Optional[float] = None
    alert_iv_rank_below: Optional[float] = None
    notes: str = ""


class WatchlistUpdate(BaseModel):
    alert_iv_rank_above: Optional[float] = None
    alert_iv_rank_below: Optional[float] = None
    notes: Optional[str] = None
    sort_order: Optional[int] = None


@router.get("")
def list_watchlist(_user: dict = Depends(get_current_user)):
    """List watchlist items, enriched with live IV rank and regime badge."""
    conn = get_user_db()
    try:
        rows = conn.execute(
            """SELECT id, symbol, alert_iv_rank_above, alert_iv_rank_below,
                      notes, sort_order, created_at
               FROM watchlist_items WHERE user_id = ?
               ORDER BY sort_order, created_at""",
            (_user["id"],),
        ).fetchall()
    finally:
        conn.close()

    items = [dict(r) for r in rows]

    for item in items:
        item["iv_rank"] = None
        item["regime"] = None
        item["spot"] = None
        item["change_1d"] = None

    try:
        _enrich_watchlist(items)
    except Exception:
        pass

    return {"items": items, "count": len(items)}


def _enrich_watchlist(items):
    """Add live IV rank + regime data to watchlist items (best-effort)."""
    if not items:
        return
    try:
        import yfinance as yf
        from scanner.iv_rank import compute_iv_rank_for_symbol
    except ImportError:
        return

    for item in items:
        try:
            ticker = yf.Ticker(item["symbol"])
            hist = ticker.history(period="2d")
            if len(hist) >= 2:
                item["spot"] = round(float(hist["Close"].iloc[-1]), 2)
                prev = float(hist["Close"].iloc[-2])
                item["change_1d"] = round((item["spot"] - prev) / prev * 100, 2)
            elif len(hist) == 1:
                item["spot"] = round(float(hist["Close"].iloc[-1]), 2)

            rank_data = compute_iv_rank_for_symbol(item["symbol"])
            if rank_data:
                item["iv_rank"] = rank_data.get("iv_rank")
                item["regime"] = rank_data.get("regime")
        except Exception:
            pass


@router.post("", status_code=201)
def add_watchlist(body: WatchlistAdd, _user: dict = Depends(get_current_user)):
    """Add a symbol to the watchlist."""
    symbol = body.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol required")

    conn = get_user_db()
    try:
        existing = conn.execute(
            "SELECT id FROM watchlist_items WHERE user_id = ? AND symbol = ?",
            (_user["id"], symbol),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"{symbol} already in watchlist")

        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM watchlist_items WHERE user_id = ?",
            (_user["id"],),
        ).fetchone()[0]

        conn.execute(
            """INSERT INTO watchlist_items (user_id, symbol, alert_iv_rank_above,
               alert_iv_rank_below, notes, sort_order)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (_user["id"], symbol, body.alert_iv_rank_above,
             body.alert_iv_rank_below, body.notes, max_order + 1),
        )
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok", "symbol": symbol}


@router.put("/{item_id}")
def update_watchlist(item_id: int, body: WatchlistUpdate, _user: dict = Depends(get_current_user)):
    """Update watchlist item thresholds or notes."""
    conn = get_user_db()
    try:
        row = conn.execute(
            "SELECT * FROM watchlist_items WHERE id = ? AND user_id = ?",
            (item_id, _user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Item not found")

        updates = {}
        if body.alert_iv_rank_above is not None:
            updates["alert_iv_rank_above"] = body.alert_iv_rank_above
        if body.alert_iv_rank_below is not None:
            updates["alert_iv_rank_below"] = body.alert_iv_rank_below
        if body.notes is not None:
            updates["notes"] = body.notes
        if body.sort_order is not None:
            updates["sort_order"] = body.sort_order

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [item_id, _user["id"]]
            conn.execute(
                f"UPDATE watchlist_items SET {set_clause} WHERE id = ? AND user_id = ?",
                values,
            )
            conn.commit()
    finally:
        conn.close()

    return {"status": "ok"}


@router.delete("/{item_id}")
def delete_watchlist(item_id: int, _user: dict = Depends(get_current_user)):
    """Remove a symbol from the watchlist."""
    conn = get_user_db()
    try:
        cursor = conn.execute(
            "DELETE FROM watchlist_items WHERE id = ? AND user_id = ?",
            (item_id, _user["id"]),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Item not found")
    finally:
        conn.close()

    return {"status": "ok"}
