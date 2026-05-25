"""User settings router — tier display, webhook configuration, notification prefs."""

import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from src.auth.dependencies import get_current_user
from src.auth.tier_middleware import get_tier_limits
from src.data.user_db import get_user_db

router = APIRouter(prefix="/api/user", tags=["user"])


class SettingsUpdate(BaseModel):
    notification_prefs: Optional[dict] = None


class WebhookCreate(BaseModel):
    name: str
    type: str  # discord, slack, telegram, webhook
    url: str
    config: dict = {}


@router.get("/settings")
def get_settings(_user: dict = Depends(get_current_user)):
    """Get user settings including tier, limits, and webhook configs."""
    conn = get_user_db()
    try:
        settings_row = conn.execute(
            "SELECT settings_json FROM user_settings WHERE user_id = ?",
            (_user["id"],),
        ).fetchone()

        webhooks = conn.execute(
            "SELECT id, name, type, url, is_active, created_at FROM webhooks WHERE user_id = ?",
            (_user["id"],),
        ).fetchall()
    finally:
        conn.close()

    settings = json.loads(settings_row["settings_json"]) if settings_row else {}
    limits = get_tier_limits(_user)

    return {
        "tier": _user.get("tier", "free"),
        "limits": limits,
        "settings": settings,
        "webhooks": [dict(w) for w in webhooks],
    }


@router.put("/settings")
def update_settings(body: SettingsUpdate, _user: dict = Depends(get_current_user)):
    """Update user settings."""
    conn = get_user_db()
    try:
        existing = conn.execute(
            "SELECT settings_json FROM user_settings WHERE user_id = ?",
            (_user["id"],),
        ).fetchone()

        current = json.loads(existing["settings_json"]) if existing else {}
        if body.notification_prefs is not None:
            current["notification_prefs"] = body.notification_prefs

        if existing:
            conn.execute(
                "UPDATE user_settings SET settings_json = ? WHERE user_id = ?",
                (json.dumps(current), _user["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO user_settings (user_id, settings_json) VALUES (?, ?)",
                (_user["id"], json.dumps(current)),
            )
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok"}


@router.post("/webhooks", status_code=201)
def create_webhook(body: WebhookCreate, _user: dict = Depends(get_current_user)):
    """Add a webhook for notifications."""
    valid_types = {"discord", "slack", "telegram", "webhook"}
    if body.type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Type must be one of: {valid_types}")
    if not body.url.strip():
        raise HTTPException(status_code=400, detail="URL required")

    conn = get_user_db()
    try:
        cursor = conn.execute(
            """INSERT INTO webhooks (user_id, name, type, url, config_json, is_active)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (_user["id"], body.name.strip(), body.type, body.url.strip(), json.dumps(body.config)),
        )
        conn.commit()
        return {"status": "ok", "id": cursor.lastrowid}
    finally:
        conn.close()


@router.delete("/webhooks/{webhook_id}")
def delete_webhook(webhook_id: int, _user: dict = Depends(get_current_user)):
    """Remove a webhook."""
    conn = get_user_db()
    try:
        cursor = conn.execute(
            "DELETE FROM webhooks WHERE id = ? AND user_id = ?",
            (webhook_id, _user["id"]),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Webhook not found")
    finally:
        conn.close()

    return {"status": "ok"}
