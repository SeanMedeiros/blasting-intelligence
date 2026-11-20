"""Schema migrations (Alembic) applied programmatically.

* New database: every migration runs from scratch.
* Database created by v0.2 / v0.3 (tables but no `alembic_version`): brought to the v0.3 schema
  with the same in-place steps those versions used, then stamped at the baseline revision.
* Before applying pending migrations to a database that already holds data, a backup is taken.
"""
from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from .db import Base, engine

log = logging.getLogger("blasting.migrate")

BACKEND_DIR = Path(__file__).resolve().parents[1]
BASELINE = "0001"


def config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def head() -> str:
    return ScriptDirectory.from_config(config()).get_current_head()


def current() -> str | None:
    with engine.connect() as c:
        return MigrationContext.configure(c).get_current_revision()


def _has_data(tables: set[str]) -> bool:
    if "blast" not in tables and "app_user" not in tables:
        return False
    with engine.connect() as c:
        for t in ("blast", "app_user"):
            if t in tables and c.exec_driver_sql(f"SELECT 1 FROM {t} LIMIT 1").first():
                return True
    return False


def _adopt_legacy(tables: set[str]) -> None:
    """v0.2/v0.3 databases were created with create_all; align them with the baseline and stamp."""
    from . import models  # noqa: F401

    log.warning("Database without migration history — aligning with the v0.3 baseline and stamping it")
    cols = {c["name"] for c in inspect(engine).get_columns("audit_log")} if "audit_log" in tables else set()
    if "audit_log" in tables and "user_id" not in cols:
        with engine.begin() as c:
            c.exec_driver_sql("ALTER TABLE audit_log ADD COLUMN user_id INTEGER")
    if "audit_log" in tables:
        with engine.begin() as c:
            c.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_audit_log_user_id ON audit_log (user_id)")
    # Tables introduced in v0.3. Their definitions are unchanged since the baseline; if a later migration
    # alters them, create them here from the 0001 definitions instead of the current models.
    Base.metadata.create_all(engine, tables=[Base.metadata.tables["app_user"], Base.metadata.tables["auth_session"]])
    command.stamp(config(), BASELINE)


def upgrade(backup_first: bool = True) -> str:
    """Brings the database to the latest revision. Returns the revision."""
    tables = set(inspect(engine).get_table_names())
    if "alembic_version" not in tables and tables & {"blast", "site", "audit_log"}:
        _adopt_legacy(tables)
    cur, target = current(), head()
    if cur != target:
        if backup_first and cur is not None and _has_data(tables):
            from .ops.backup import create_backup

            path = create_backup(reason=f"pre-migration-{cur}-to-{target}")
            log.warning("Backup before migration: %s", path)
        log.info("Migrating database schema %s → %s", cur or "(empty)", target)
        command.upgrade(config(), "head")
    return target


def drop_everything() -> None:
    """Used by the demonstration reset: removes every application table and the migration history."""
    from . import models  # noqa: F401

    Base.metadata.drop_all(engine)
    with engine.begin() as c:
        c.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
