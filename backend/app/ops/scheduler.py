"""Built-in daily backup (runs inside the server process, so no Windows Task Scheduler entry is required).

Set BI_BACKUP_DAILY_AT="" to disable it (e.g. when backups are scheduled externally with backup.bat).
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime

from ..config import BACKUP_DAILY_AT

log = logging.getLogger("blasting.backup")
_stop = threading.Event()
_thread: threading.Thread | None = None
REASON = "scheduled"


def _due(now: datetime, at: str) -> bool:
    from .backup import last_backup_time

    hh, mm = (int(x) for x in at.split(":"))
    slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now < slot:
        return False
    last = last_backup_time(REASON)
    return last is None or last < slot


def _loop(at: str) -> None:
    while not _stop.wait(60):
        try:
            if _due(datetime.now(), at):
                from .backup import create_backup

                create_backup(reason=REASON)
        except Exception:  # noqa: BLE001 — a failed backup must never stop the server
            log.exception("Scheduled backup failed")


def start() -> None:
    global _thread
    if not BACKUP_DAILY_AT or _thread is not None:
        return
    try:
        hh, mm = (int(x) for x in BACKUP_DAILY_AT.split(":"))
        assert 0 <= hh < 24 and 0 <= mm < 60
    except Exception:  # noqa: BLE001
        log.error("Invalid BI_BACKUP_DAILY_AT=%r (expected HH:MM) — scheduled backup disabled", BACKUP_DAILY_AT)
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(BACKUP_DAILY_AT,), name="daily-backup", daemon=True)
    _thread.start()
    log.info("Daily backup scheduled at %s (local time)", BACKUP_DAILY_AT)


def stop() -> None:
    global _thread
    _stop.set()
    _thread = None
