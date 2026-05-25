"""Saved backtest configurations — CRUD for user-scoped backtest presets."""

import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.auth.dependencies import get_current_user
from src.data.user_db import get_user_db

router = APIRouter(prefix="/api/backtest/configs", tags=["backtest"])


class ConfigCreate(BaseModel):
    name: str
    config: dict


@router.get("")
def list_configs(_user: dict = Depends(get_current_user)):
    """List saved backtest configurations."""
    conn = get_user_db()
    try:
        rows = conn.execute(
            """SELECT id, name, config_json, created_at
               FROM backtest_configs WHERE user_id = ?
               ORDER BY created_at DESC""",
            (_user["id"],),
        ).fetchall()
    finally:
        conn.close()

    configs = []
    for r in rows:
        d = dict(r)
        d["config"] = json.loads(d.pop("config_json"))
        configs.append(d)

    return {"configs": configs, "count": len(configs)}


@router.post("", status_code=201)
def save_config(body: ConfigCreate, _user: dict = Depends(get_current_user)):
    """Save a backtest configuration."""
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Name required")

    conn = get_user_db()
    try:
        cursor = conn.execute(
            """INSERT INTO backtest_configs (user_id, name, config_json)
               VALUES (?, ?, ?)""",
            (_user["id"], body.name.strip(), json.dumps(body.config)),
        )
        conn.commit()
        return {"status": "ok", "id": cursor.lastrowid}
    finally:
        conn.close()


@router.delete("/{config_id}")
def delete_config(config_id: int, _user: dict = Depends(get_current_user)):
    """Delete a saved backtest configuration."""
    conn = get_user_db()
    try:
        cursor = conn.execute(
            "DELETE FROM backtest_configs WHERE id = ? AND user_id = ?",
            (config_id, _user["id"]),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Config not found")
    finally:
        conn.close()

    return {"status": "ok"}
