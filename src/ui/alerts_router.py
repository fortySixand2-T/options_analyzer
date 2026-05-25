"""Alerts CRUD router — user-scoped alert configurations."""

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.auth.dependencies import get_current_user
from src.data.user_db import get_user_db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class AlertCreate(BaseModel):
    name: str
    trigger_type: str  # iv_rank_above, iv_rank_below, regime_change, scan_match
    trigger_config: dict  # {symbol, threshold, ...}
    channels: list = ["in_app"]  # in_app, email, webhook
    cooldown_minutes: int = 60
    is_active: bool = True


class AlertUpdate(BaseModel):
    name: Optional[str] = None
    trigger_config: Optional[dict] = None
    channels: Optional[list] = None
    cooldown_minutes: Optional[int] = None
    is_active: Optional[bool] = None


@router.get("")
def list_alerts(_user: dict = Depends(get_current_user)):
    """List all alerts for the current user."""
    conn = get_user_db()
    try:
        rows = conn.execute(
            """SELECT id, name, trigger_type, trigger_config_json, channels_json,
                      is_active, cooldown_minutes, last_triggered_at, created_at
               FROM alerts WHERE user_id = ?
               ORDER BY created_at DESC""",
            (_user["id"],),
        ).fetchall()
    finally:
        conn.close()

    alerts = []
    for r in rows:
        d = dict(r)
        d["trigger_config"] = json.loads(d.pop("trigger_config_json"))
        d["channels"] = json.loads(d.pop("channels_json"))
        alerts.append(d)

    return {"alerts": alerts, "count": len(alerts)}


@router.post("", status_code=201)
def create_alert(body: AlertCreate, _user: dict = Depends(get_current_user)):
    """Create a new alert."""
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Name required")

    valid_types = {"iv_rank_above", "iv_rank_below", "regime_change", "scan_match", "price_above", "price_below"}
    if body.trigger_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid trigger_type. Must be one of: {valid_types}")

    conn = get_user_db()
    try:
        cursor = conn.execute(
            """INSERT INTO alerts (user_id, name, trigger_type, trigger_config_json,
               channels_json, is_active, cooldown_minutes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (_user["id"], body.name.strip(), body.trigger_type,
             json.dumps(body.trigger_config), json.dumps(body.channels),
             int(body.is_active), body.cooldown_minutes),
        )
        conn.commit()
        return {"status": "ok", "id": cursor.lastrowid}
    finally:
        conn.close()


@router.put("/{alert_id}")
def update_alert(alert_id: int, body: AlertUpdate, _user: dict = Depends(get_current_user)):
    """Update an alert's configuration."""
    conn = get_user_db()
    try:
        row = conn.execute(
            "SELECT * FROM alerts WHERE id = ? AND user_id = ?",
            (alert_id, _user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Alert not found")

        updates = {}
        if body.name is not None:
            updates["name"] = body.name.strip()
        if body.trigger_config is not None:
            updates["trigger_config_json"] = json.dumps(body.trigger_config)
        if body.channels is not None:
            updates["channels_json"] = json.dumps(body.channels)
        if body.cooldown_minutes is not None:
            updates["cooldown_minutes"] = body.cooldown_minutes
        if body.is_active is not None:
            updates["is_active"] = int(body.is_active)

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [alert_id, _user["id"]]
            conn.execute(
                f"UPDATE alerts SET {set_clause} WHERE id = ? AND user_id = ?",
                values,
            )
            conn.commit()
    finally:
        conn.close()

    return {"status": "ok"}


@router.delete("/{alert_id}")
def delete_alert(alert_id: int, _user: dict = Depends(get_current_user)):
    """Delete an alert."""
    conn = get_user_db()
    try:
        cursor = conn.execute(
            "DELETE FROM alerts WHERE id = ? AND user_id = ?",
            (alert_id, _user["id"]),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Alert not found")
    finally:
        conn.close()

    return {"status": "ok"}


@router.post("/{alert_id}/test")
def test_alert(alert_id: int, _user: dict = Depends(get_current_user)):
    """Send a test notification for this alert."""
    conn = get_user_db()
    try:
        row = conn.execute(
            "SELECT * FROM alerts WHERE id = ? AND user_id = ?",
            (alert_id, _user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Alert not found")
    finally:
        conn.close()

    from src.notifications.dispatcher import send_notification
    send_notification(
        _user["id"],
        title=f"Test: {row['name']}",
        body=f"This is a test notification for alert '{row['name']}'",
        notif_type="alert_test",
    )

    return {"status": "ok", "message": "Test notification sent"}


@router.get("/history")
def alert_history(
    limit: int = Query(50, ge=1, le=200),
    _user: dict = Depends(get_current_user),
):
    """Get alert trigger history from notifications."""
    conn = get_user_db()
    try:
        rows = conn.execute(
            """SELECT id, title, body, type, read, created_at
               FROM notifications WHERE user_id = ? AND type LIKE 'alert%'
               ORDER BY created_at DESC LIMIT ?""",
            (_user["id"], limit),
        ).fetchall()
    finally:
        conn.close()

    return {"history": [dict(r) for r in rows], "count": len(rows)}
