"""Scanner presets CRUD — save and load scanner filter configurations."""

import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from src.auth.dependencies import get_current_user
from src.data.user_db import get_user_db

router = APIRouter(prefix="/api/scanner/presets", tags=["scanner"])


class PresetCreate(BaseModel):
    name: str
    config: dict
    is_pinned: bool = False


@router.get("")
def list_presets(_user: dict = Depends(get_current_user)):
    """List saved scanner presets."""
    conn = get_user_db()
    try:
        rows = conn.execute(
            """SELECT id, name, config_json, is_pinned, created_at
               FROM scanner_presets WHERE user_id = ?
               ORDER BY is_pinned DESC, created_at DESC""",
            (_user["id"],),
        ).fetchall()
    finally:
        conn.close()

    presets = []
    for r in rows:
        d = dict(r)
        d["config"] = json.loads(d.pop("config_json"))
        presets.append(d)

    return {"presets": presets, "count": len(presets)}


@router.post("", status_code=201)
def create_preset(body: PresetCreate, _user: dict = Depends(get_current_user)):
    """Save a scanner preset."""
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Name required")

    conn = get_user_db()
    try:
        conn.execute(
            """INSERT INTO scanner_presets (user_id, name, config_json, is_pinned)
               VALUES (?, ?, ?, ?)""",
            (_user["id"], body.name.strip(), json.dumps(body.config), int(body.is_pinned)),
        )
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok"}


@router.delete("/{preset_id}")
def delete_preset(preset_id: int, _user: dict = Depends(get_current_user)):
    """Delete a scanner preset."""
    conn = get_user_db()
    try:
        cursor = conn.execute(
            "DELETE FROM scanner_presets WHERE id = ? AND user_id = ?",
            (preset_id, _user["id"]),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Preset not found")
    finally:
        conn.close()

    return {"status": "ok"}
