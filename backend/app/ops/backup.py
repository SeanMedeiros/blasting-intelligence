"""Backups, verification, restore and database-to-database copy.

A backup is one zip file:
    manifest.json        app version, schema revision, dialect, reason, row counts, SHA-256 of the payload
    database.sqlite      SQLite: consistent online copy (sqlite3 backup API), integrity-checked
    database.dump        PostgreSQL: pg_dump custom format (needs pg_dump on PATH or BI_PG_BIN)
    surveys/...          imported point-cloud files

Backups can be taken while the server is running. Restoring requires the server to be stopped.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import Engine, make_url

from .. import models  # noqa: F401
from ..config import APP_VERSION, BACKUP_DIR, BACKUP_KEEP, DATABASE_URL, FILE_DIRS, PG_BIN
from ..db import Base, engine
from ..i18n import _

log = logging.getLogger("blasting.backup")

PROTECTED_REASONS = ("pre-migration", "pre-restore")  # never pruned automatically
_NAME = re.compile(r"^bi-backup-(\d{8}-\d{6})-([a-z0-9._-]+)\.zip$")


class BackupError(RuntimeError):
    pass


# ----------------------------------------------------------------------------- helpers
def _dialect(url: str = DATABASE_URL) -> str:
    return make_url(url).get_backend_name()


def _sqlite_path(url: str = DATABASE_URL) -> Path:
    db = make_url(url).database
    if not db or db == ":memory:":
        raise BackupError(_('In-memory SQLite databases cannot be backed up'))
    return Path(db)


def _pg_tool(name: str) -> str:
    exe = name + (".exe" if os.name == "nt" else "")
    if PG_BIN:
        p = Path(PG_BIN) / exe
        if p.exists():
            return str(p)
    found = shutil.which(name)
    if not found:
        raise BackupError(_('{name} not found — install the PostgreSQL client tools or set BI_PG_BIN', name=name))
    return found


def _pg_args(url: str) -> tuple[list[str], dict]:
    u = make_url(url)
    args = ["-h", u.host or "localhost", "-p", str(u.port or 5432), "-U", u.username or "postgres", "-d", u.database or "postgres"]
    env = dict(os.environ)
    if u.password:
        env["PGPASSWORD"] = u.password
    return args, env


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _row_counts(eng: Engine) -> dict[str, int]:
    names = set(inspect(eng).get_table_names())
    with eng.connect() as c:
        return {t.name: c.execute(select(func.count()).select_from(t)).scalar_one()
                for t in Base.metadata.sorted_tables if t.name in names}


def _revision(eng: Engine) -> str | None:
    from alembic.runtime.migration import MigrationContext

    with eng.connect() as c:
        return MigrationContext.configure(c).get_current_revision()


def _slug(reason: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", reason.lower()).strip("-")[:60] or "manual"


# ----------------------------------------------------------------------------- create
def create_backup(reason: str = "manual", dest_dir: Path | None = None) -> Path:
    dest = Path(dest_dir or BACKUP_DIR)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    final = dest / f"bi-backup-{stamp}-{_slug(reason)}.zip"
    n = 1
    while final.exists():
        final = dest / f"bi-backup-{stamp}-{_slug(reason)}-{n}.zip"
        n += 1
    dialect = _dialect()
    with tempfile.TemporaryDirectory(prefix="bi-backup-") as tmp:
        tmpdir = Path(tmp)
        if dialect == "sqlite":
            payload = tmpdir / "database.sqlite"
            src = sqlite3.connect(str(_sqlite_path()))
            dst = sqlite3.connect(str(payload))
            try:
                src.backup(dst)
                ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                dst.close()
                src.close()
            if ok != "ok":
                raise BackupError(_('Integrity check of the copy failed: {ok}', ok=ok))
        elif dialect == "postgresql":
            payload = tmpdir / "database.dump"
            args, env = _pg_args(DATABASE_URL)
            r = subprocess.run([_pg_tool("pg_dump"), *args, "-Fc", "--no-owner", "-f", str(payload)],
                               env=env, capture_output=True, text=True)
            if r.returncode != 0:
                raise BackupError(_('pg_dump failed: {v}', v=r.stderr.strip()[:500]))
        else:
            raise BackupError(_("Backups are not implemented for '{dialect}'", dialect=dialect))

        manifest = {
            "format": 1, "app_version": APP_VERSION, "dialect": dialect, "schema_revision": _revision(engine),
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"), "reason": reason,
            "payload": payload.name, "payload_sha256": _sha256(payload), "row_counts": _row_counts(engine),
        }
        part = final.with_suffix(".zip.part")
        with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
            z.write(payload, payload.name)
            for prefix, folder in FILE_DIRS.items():  # imported point clouds and attachments
                if folder.exists():
                    for f in sorted(folder.rglob("*")):
                        if f.is_file():
                            z.write(f, f"{prefix}/" + f.relative_to(folder).as_posix())
        os.replace(part, final)  # never leaves a half-written backup under the final name
    verify_backup(final)
    log.info("Backup written: %s", final)
    prune(dest)
    return final


# ----------------------------------------------------------------------------- inspect
def read_manifest(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("manifest.json"))


def verify_backup(path: Path) -> dict:
    """Checks the archive, the payload hash and (SQLite) the database integrity. Returns the manifest."""
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as z:
            bad = z.testzip()
            if bad:
                raise BackupError(_('Corrupted member in archive: {bad}', bad=bad))
            man = json.loads(z.read("manifest.json"))
            with tempfile.TemporaryDirectory(prefix="bi-verify-") as tmp:
                p = Path(z.extract(man["payload"], tmp))
                if _sha256(p) != man["payload_sha256"]:
                    raise BackupError(_('Payload checksum mismatch'))
                if man["dialect"] == "sqlite":
                    con = sqlite3.connect(str(p))
                    try:
                        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise BackupError(_('SQLite integrity check failed'))
                    finally:
                        con.close()
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
        raise BackupError(_('Not a valid backup: {e}', e=e)) from e
    return man


def list_backups(dest_dir: Path | None = None) -> list[dict]:
    dest = Path(dest_dir or BACKUP_DIR)
    out = []
    for f in sorted(dest.glob("bi-backup-*.zip"), reverse=True):
        try:
            man = read_manifest(f)
        except Exception:  # noqa: BLE001 — listed as unreadable rather than hidden
            man = {}
        out.append({"file": f.name, "size_bytes": f.stat().st_size, "created_at": man.get("created_at"),
                    "reason": man.get("reason"), "dialect": man.get("dialect"),
                    "schema_revision": man.get("schema_revision"), "app_version": man.get("app_version"),
                    "readable": bool(man)})
    return out


def prune(dest_dir: Path | None = None, keep: int = BACKUP_KEEP) -> list[str]:
    dest = Path(dest_dir or BACKUP_DIR)
    files = sorted((f for f in dest.glob("bi-backup-*.zip") if not any(r in f.name for r in PROTECTED_REASONS)),
                   reverse=True)
    removed = []
    for f in files[keep:]:
        f.unlink(missing_ok=True)
        removed.append(f.name)
    return removed


def resolve(name_or_path: str, dest_dir: Path | None = None) -> Path:
    p = Path(name_or_path)
    if p.exists():
        return p
    q = Path(dest_dir or BACKUP_DIR) / name_or_path
    if q.exists():
        return q
    raise BackupError(_('Backup not found: {name_or_path}', name_or_path=name_or_path))


# ----------------------------------------------------------------------------- restore
def restore_backup(path: Path) -> dict:
    """Replaces the current database (and imported surveys) with the backup. The server must be stopped."""
    man = verify_backup(path)
    dialect = _dialect()
    if man["dialect"] != dialect:
        raise BackupError(_('Backup is {dialect} but the configured database is {dialect2}; restore into a database of the same type, then use copy-db', dialect=man['dialect'], dialect2=dialect))
    safety = None
    if set(inspect(engine).get_table_names()) & {"blast", "app_user"}:
        safety = create_backup(reason="pre-restore")
    engine.dispose()
    with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory(prefix="bi-restore-") as tmp:
        payload = Path(z.extract(man["payload"], tmp))
        if dialect == "sqlite":
            target = _sqlite_path()
            for suffix in ("-wal", "-shm"):
                Path(str(target) + suffix).unlink(missing_ok=True)
            shutil.copyfile(payload, target)
        else:
            args, env = _pg_args(DATABASE_URL)
            r = subprocess.run([_pg_tool("pg_restore"), *args, "--clean", "--if-exists", "--no-owner", "--single-transaction",
                                str(payload)], env=env, capture_output=True, text=True)
            if r.returncode != 0:
                raise BackupError(_('pg_restore failed: {v}', v=r.stderr.strip()[:500]))
        for prefix, folder in FILE_DIRS.items():
            shutil.rmtree(folder, ignore_errors=True)
        for name in z.namelist():
            prefix = name.split("/", 1)[0]
            folder = FILE_DIRS.get(prefix)
            if folder is None or name.endswith("/") or "/" not in name:
                continue
            out = folder / name[len(prefix) + 1:]
            if folder.resolve() not in out.resolve().parents:
                raise BackupError(_('Unsafe path in backup: {name}', name=name))
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(name) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
    from ..migrate import upgrade

    rev = upgrade(backup_first=False)  # a backup from an older version is brought to the current schema
    return {"restored": Path(path).name, "safety_backup": safety.name if safety else None, "schema_revision": rev,
            "row_counts": _row_counts(engine)}


# ----------------------------------------------------------------------------- copy between databases
def copy_database(src_url: str, dst_url: str, batch: int = 2000) -> dict:
    """Copies every table from one database to another empty one (e.g. SQLite pilot → PostgreSQL)."""
    from alembic import command

    from ..migrate import config as alembic_config
    from ..migrate import head

    src = create_engine(src_url)
    dst = create_engine(dst_url, pool_pre_ping=True)
    try:
        if _revision(src) != head():
            raise BackupError(_('Bring the source database to the current schema first (start the application once on it)'))
        existing = set(inspect(dst).get_table_names()) - {"alembic_version"}
        if existing:
            with dst.connect() as c:
                if any(c.execute(select(func.count()).select_from(t)).scalar_one()
                       for t in Base.metadata.sorted_tables if t.name in existing):
                    raise BackupError(_('Destination database is not empty'))
        cfg = alembic_config()
        with dst.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
        counts = {}
        with src.connect() as s, dst.begin() as d:
            for t in Base.metadata.sorted_tables:
                rows = s.execute(select(t)).mappings()
                n = 0
                buf = []
                for r in rows:
                    buf.append(dict(r))
                    if len(buf) >= batch:
                        d.execute(t.insert(), buf)
                        n += len(buf)
                        buf = []
                if buf:
                    d.execute(t.insert(), buf)
                    n += len(buf)
                counts[t.name] = n
            if dst.dialect.name == "postgresql":
                for t in Base.metadata.sorted_tables:
                    d.execute(text(f"SELECT setval(pg_get_serial_sequence('{t.name}', 'id'), "
                                   f"COALESCE((SELECT MAX(id) FROM {t.name}), 0) + 1, false)"))
        check = _row_counts(dst)
        diff = {k: (v, check.get(k)) for k, v in counts.items() if check.get(k) != v}
        if diff:
            raise BackupError(_('Row counts differ after copy: {diff}', diff=diff))
        return {"tables": len(counts), "rows": sum(counts.values()), "row_counts": counts}
    finally:
        src.dispose()
        dst.dispose()


def last_backup_time(reason: str, dest_dir: Path | None = None) -> datetime | None:
    for f in sorted(Path(dest_dir or BACKUP_DIR).glob(f"bi-backup-*-{_slug(reason)}*.zip"), reverse=True):
        m = _NAME.match(f.name)
        if m:
            return datetime.strptime(m.group(1), "%Y%m%d-%H%M%S")
    return None
