"""Application configuration.

All values can be overridden with environment variables prefixed BI_.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]


def _load_env_file(path: Path) -> None:
    """KEY=VALUE lines from server.env (installation settings for the service); real environment variables win."""
    if not path.is_file():
        return
    for n, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if not sep or not key.startswith("BI_"):
            raise RuntimeError(f"{path.name} line {n}: expected BI_NAME=value")
        os.environ.setdefault(key, value)


ENV_FILE = Path(os.getenv("BI_ENV_FILE", ROOT_DIR / "server.env"))
_load_env_file(ENV_FILE)

# Operating mode.
#   production   real date and time, empty database at first start, no demonstration data
#   demo         fictional site regenerated on demand, clock fixed at BI_DEMO_TODAY
MODE = os.getenv("BI_MODE", "production").strip().lower()
if MODE not in ("production", "demo"):
    raise RuntimeError(f"BI_MODE must be 'production' or 'demo', not {MODE!r}")
IS_DEMO = MODE == "demo"

# Site language: language of the default record templates (checkpoints, checklists) created on this site.
# The interface and server texts follow each user's language choice.
DEFAULT_LANGUAGE = os.getenv("BI_DEFAULT_LANGUAGE", "en").strip().lower()[:2]
if DEFAULT_LANGUAGE not in ("en", "fr"):
    DEFAULT_LANGUAGE = "en"

# Demo and production never share a folder or a database.
DATA_DIR = Path(os.getenv("BI_DATA_DIR", ROOT_DIR / "data" / ("demo" if IS_DEMO else "")))
SURVEY_DIR = DATA_DIR / "surveys"
ATTACHMENT_DIR = DATA_DIR / "attachments"
# File folders stored next to the database; included in every backup and restored with it.
FILE_DIRS = {"surveys": SURVEY_DIR, "attachments": ATTACHMENT_DIR}
FRONTEND_DIST = Path(os.getenv("BI_FRONTEND_DIST", ROOT_DIR / "frontend" / "dist"))

# SQLite by default (single workstation). PostgreSQL: postgresql+psycopg://user:pass@host:5432/db
DATABASE_URL = os.getenv("BI_DATABASE_URL",
                         f"sqlite:///{(DATA_DIR / ('demo.db' if IS_DEMO else 'blasting.db')).as_posix()}")

# Site time zone: "today", due dates and timestamps use the local date of the operation.
TIMEZONE = os.getenv("BI_TIMEZONE", "America/Toronto")

# Demonstration clock (demo mode only): the fictional operation is anchored to this date.
DEMO_TODAY = date.fromisoformat(os.getenv("BI_DEMO_TODAY", "2026-12-04"))

APP_NAME = "Blasting Intelligence"
APP_VERSION = "0.9.0"
DATA_DISCLAIMER = "DEMONSTRATION DATA — FICTIONAL SITE" if IS_DEMO else ""

# Post-blast review due this many days after firing (created automatically when the blast is fired)
POST_BLAST_REVIEW_DAYS = int(os.getenv("BI_POST_BLAST_REVIEW_DAYS", "5"))

# Attachments (evidence files)
ATTACHMENT_MAX_MB = float(os.getenv("BI_ATTACHMENT_MAX_MB", "25"))

# Authentication
SESSION_HOURS = float(os.getenv("BI_SESSION_HOURS", "12"))          # absolute session lifetime (one shift)
SESSION_IDLE_MINUTES = float(os.getenv("BI_SESSION_IDLE_MINUTES", "120"))  # inactivity timeout
# Network service (python -m app.serve). Defaults keep the application on this computer only.
HOST = os.getenv("BI_HOST", "127.0.0.1")                              # 0.0.0.0 = every network interface
PORT = int(os.getenv("BI_PORT", "8001" if IS_DEMO else "8000"))
TLS_CERT = os.getenv("BI_TLS_CERT", "")                               # PEM certificate (chain) → HTTPS
TLS_KEY = os.getenv("BI_TLS_KEY", "")                                 # PEM private key
TLS_KEY_PASSWORD = os.getenv("BI_TLS_KEY_PASSWORD", "") or None
HTTPS = bool(TLS_CERT and TLS_KEY)
HTTP_REDIRECT_PORT = int(os.getenv("BI_HTTP_REDIRECT_PORT", "0") or 0)  # e.g. 80: plain-HTTP listener that redirects to HTTPS
PUBLIC_URL = os.getenv("BI_PUBLIC_URL", "").rstrip("/")                # address users type, e.g. https://blasting.mine.local
ALLOWED_HOSTS = [h.strip().lower() for h in os.getenv("BI_ALLOWED_HOSTS", "").split(",") if h.strip()]  # extra names; "*" = no check
TRUSTED_PROXIES = os.getenv("BI_TRUSTED_PROXIES", "")                  # reverse proxy address(es) allowed to set X-Forwarded-*
LOG_DIR = Path(os.getenv("BI_LOG_DIR", DATA_DIR / "logs"))
TLS_DIR = Path(os.getenv("BI_TLS_DIR", ROOT_DIR / "data" / "tls"))     # certificates made by `manage make-cert` / `import-pfx`
# Session cookie sent over HTTPS only: automatic when this server does HTTPS; set BI_COOKIE_SECURE=1 behind an HTTPS proxy
COOKIE_SECURE = HTTPS or os.getenv("BI_COOKIE_SECURE", "0") == "1"
LOGIN_MAX_ATTEMPTS = int(os.getenv("BI_LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_LOCK_MINUTES = int(os.getenv("BI_LOGIN_LOCK_MINUTES", "15"))
PASSWORD_MIN_LENGTH = int(os.getenv("BI_PASSWORD_MIN_LENGTH", "10"))
ADMIN_INITIAL_PASSWORD = os.getenv("BI_ADMIN_PASSWORD")               # optional; otherwise generated on first start
DEMO_PASSWORD = os.getenv("BI_DEMO_PASSWORD", "Demo-2026!")          # demonstration accounts only

# Backups
BACKUP_DIR = Path(os.getenv("BI_BACKUP_DIR", DATA_DIR / "backups"))
BACKUP_KEEP = int(os.getenv("BI_BACKUP_KEEP", "30"))                 # scheduled/manual backups kept (pre-migration and pre-restore are never pruned)
BACKUP_DAILY_AT = os.getenv("BI_BACKUP_DAILY_AT", "02:30")           # local time HH:MM; empty to disable the built-in schedule
PG_BIN = os.getenv("BI_PG_BIN", "")                                  # folder holding pg_dump / pg_restore if not on PATH
