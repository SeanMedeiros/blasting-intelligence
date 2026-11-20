"""Database status and backups (administrators)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from ..config import APP_VERSION, BACKUP_DAILY_AT, BACKUP_DIR, BACKUP_KEEP, DATABASE_URL
from ..db import get_db
from ..migrate import current, head
from ..ops import backup as bk
from ..services.audit import record
from ..services.security import Actor, require
from ..web import server_info

router = APIRouter(prefix="/api/v1/system", tags=["System"])


@router.get("/status")
def status(_actor: Actor = Depends(require("system.backup"))):
    u = make_url(DATABASE_URL)
    backups = bk.list_backups()
    return {
        "app_version": APP_VERSION,
        "database": {"type": u.get_backend_name(), "location": u.render_as_string(hide_password=True)},
        "schema": {"revision": current(), "head": head()},
        "backups": {"directory": str(BACKUP_DIR), "keep": BACKUP_KEEP, "daily_at": BACKUP_DAILY_AT or None,
                    "count": len(backups), "latest": backups[0] if backups else None},
        "server": server_info(),
    }


@router.get("/backups")
def backups(_actor: Actor = Depends(require("system.backup"))):
    return bk.list_backups()


@router.post("/backups", status_code=201)
def backup_now(db: Session = Depends(get_db), actor: Actor = Depends(require("system.backup"))):
    try:
        path = bk.create_backup(reason="manual")
    except bk.BackupError as e:
        raise HTTPException(500, str(e)) from e
    record(db, "backup", 0, "CREATE", actor, {"file": path.name})
    db.commit()
    return next(x for x in bk.list_backups() if x["file"] == path.name)
