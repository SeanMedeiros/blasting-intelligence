"""Migrations, backups, restore, database copy and the system API."""
import os
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import CSRF, signed_client

from app import models as m
from app.config import DATABASE_URL
from app.db import Base, SessionLocal, engine
from app.main import app
from app.migrate import current, head
from app.ops import backup as bk
from app.seed.generator import reset_and_seed

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", autouse=True)
def _seed():
    reset_and_seed()
    yield
    reset_and_seed()


def _manage(*args, url: str | None = None, **env):
    e = dict(os.environ, **env)
    if url:
        e["BI_DATABASE_URL"] = url
    return subprocess.run([sys.executable, "-m", "app.manage", *args], cwd=BACKEND, env=e, capture_output=True, text=True)


def test_schema_is_at_head_and_matches_models():
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    assert current() == head()
    with engine.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata)
    assert diff == [], f"models changed without a migration: {diff[:5]}"


def test_fresh_database_via_cli(tmp_path):
    url = f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}"
    r = _manage("db-upgrade", url=url)
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(tmp_path / "fresh.db")
    tables = {x[0] for x in con.execute("select name from sqlite_master where type='table'")}
    assert {"blast", "app_user", "auth_session", "alembic_version"} <= tables
    assert con.execute("select version_num from alembic_version").fetchone()[0] == head()


def test_legacy_v02_database_is_adopted(tmp_path):
    """A v0.2 database (create_all, no accounts, no audit_log.user_id, no migration history) keeps its data."""
    db = tmp_path / "legacy.db"
    url = f"sqlite:///{db.as_posix()}"
    code = "from alembic import command; from app.migrate import config; command.upgrade(config(), '0001')"
    r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=dict(os.environ, BI_DATABASE_URL=url), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr  # baseline = the v0.3 schema
    con = sqlite3.connect(db)
    con.execute("drop table alembic_version")
    con.execute("drop table auth_session")
    con.execute("drop table app_user")
    con.execute("drop index ix_audit_log_user_id")
    con.execute("alter table audit_log drop column user_id")
    con.execute("insert into site (code, name, created_at, updated_at) values ('X1', 'Legacy site', '2026-01-01', '2026-01-01')")
    con.commit()
    con.close()
    r = _manage("db-upgrade", url=f"sqlite:///{db.as_posix()}")
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(db)
    assert con.execute("select name from site").fetchone()[0] == "Legacy site"
    assert "user_id" in {c[1] for c in con.execute("pragma table_info(audit_log)")}
    assert "ix_audit_log_user_id" in {x[1] for x in con.execute("pragma index_list(audit_log)")}
    assert {"app_user", "auth_session"} <= {x[0] for x in con.execute("select name from sqlite_master where type='table'")}
    assert con.execute("select version_num from alembic_version").fetchone()[0] == head()


def test_backup_verify_list_and_tamper(tmp_path):
    p = bk.create_backup(reason="Test run!", dest_dir=tmp_path)
    assert p.name.startswith("bi-backup-") and p.name.endswith("-test-run.zip")
    man = bk.verify_backup(p)
    assert man["dialect"] == engine.dialect.name and man["schema_revision"] == head() and man["row_counts"]["blast"] == 40
    assert [x["file"] for x in bk.list_backups(tmp_path)] == [p.name]
    # a modified payload is detected
    bad = tmp_path / "bi-backup-20000101-000000-bad.zip"
    with zipfile.ZipFile(p) as zin, zipfile.ZipFile(bad, "w") as zout:
        for n in zin.namelist():
            data = zin.read(n)
            zout.writestr(n, data[:-10] + b"0123456789" if n == man["payload"] else data)
    with pytest.raises(bk.BackupError):
        bk.verify_backup(bad)
    (tmp_path / "bi-backup-20000101-000001-junk.zip").write_bytes(b"not a zip")
    with pytest.raises(bk.BackupError):
        bk.verify_backup(tmp_path / "bi-backup-20000101-000001-junk.zip")


def test_prune_keeps_protected(tmp_path):
    for i in range(5):
        (tmp_path / f"bi-backup-2026010{i}-000000-scheduled.zip").write_bytes(b"x")
    (tmp_path / "bi-backup-20250101-000000-pre-migration-0001-to-0002.zip").write_bytes(b"x")
    removed = bk.prune(tmp_path, keep=2)
    left = sorted(f.name for f in tmp_path.iterdir())
    assert len(removed) == 3 and "bi-backup-20250101-000000-pre-migration-0001-to-0002.zip" in left
    assert "bi-backup-20260104-000000-scheduled.zip" in left and "bi-backup-20260100-000000-scheduled.zip" not in left


def test_restore_replaces_data_and_keeps_safety_copy(tmp_path):
    if engine.dialect.name != "sqlite" and not bk.shutil.which("pg_restore"):
        pytest.skip("pg_restore not available")
    p = bk.create_backup(reason="before-change", dest_dir=tmp_path)
    with SessionLocal() as db:
        db.add(m.Site(code="TMP", name="Added after backup"))
        db.commit()
    res = bk.restore_backup(p)
    assert res["safety_backup"] and res["schema_revision"] == head()
    with SessionLocal() as db:
        assert db.query(m.Site).filter_by(code="TMP").count() == 0
        assert db.query(m.Blast).count() == 40
    safety = bk.resolve(res["safety_backup"])
    assert bk.read_manifest(safety)["row_counts"]["site"] == res["row_counts"]["site"] + 1


def test_restore_refuses_other_dialect(tmp_path):
    p = bk.create_backup(reason="x", dest_dir=tmp_path)
    other = tmp_path / "bi-backup-20000101-000000-other.zip"
    with zipfile.ZipFile(p) as zin, zipfile.ZipFile(other, "w") as zout:
        for n in zin.namelist():
            data = zin.read(n)
            if n == "manifest.json":
                data = data.replace(engine.dialect.name.encode(), b"oracle")
            zout.writestr(n, data)
    with pytest.raises(bk.BackupError):
        bk.restore_backup(other)


def test_copy_database_to_empty_sqlite(tmp_path):
    dst = f"sqlite:///{(tmp_path / 'copy.db').as_posix()}"
    res = bk.copy_database(DATABASE_URL, dst)
    assert res["row_counts"]["blast"] == 40 and res["rows"] > 5000
    with pytest.raises(bk.BackupError):  # destination no longer empty
        bk.copy_database(DATABASE_URL, dst)


@pytest.mark.skipif(not os.getenv("BI_TEST_PG_URL"), reason="set BI_TEST_PG_URL to an empty PostgreSQL database")
def test_copy_database_to_postgresql():
    from sqlalchemy import create_engine, text

    url = os.environ["BI_TEST_PG_URL"]
    e = create_engine(url)
    with e.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    e.dispose()
    res = bk.copy_database(DATABASE_URL, url)
    assert res["row_counts"]["drillhole"] > 1000
    e = create_engine(url)
    with e.begin() as c:  # sequences continue after the copied ids
        new_id = c.execute(text("INSERT INTO site (code, name, created_at, updated_at) VALUES ('Z9', 'z', now(), now()) RETURNING id")).scalar_one()
        assert new_id > c.execute(text("SELECT MIN(id) FROM site")).scalar_one()
    e.dispose()


def test_cli_set_password_unlocks(tmp_path):
    r = _manage("set-password", "eroy", BI_NEW_PASSWORD="Console-pass-42")
    assert r.returncode == 0, r.stderr
    with TestClient(app, headers=CSRF) as c:
        assert c.post("/api/v1/auth/login", json={"username": "eroy", "password": "Console-pass-42"}).status_code == 200
    assert _manage("set-password", "eroy", BI_NEW_PASSWORD="short").returncode != 0
    assert _manage("create-admin", "eroy", BI_NEW_PASSWORD="Another-pass-42").returncode != 0


def test_system_api_admin_only():
    with signed_client("admin") as c:
        st = c.get("/api/v1/system/status").json()
        assert st["schema"]["revision"] == st["schema"]["head"] and st["database"]["type"] == engine.dialect.name
        assert "password" not in st["database"]["location"] or "***" in st["database"]["location"]
        r = c.post("/api/v1/system/backups")
        assert r.status_code == 201 and r.json()["reason"] == "manual"
        assert any(x["file"] == r.json()["file"] for x in c.get("/api/v1/system/backups").json())
    with signed_client("jgagnon") as c:
        assert c.get("/api/v1/system/status").status_code == 403
        assert c.post("/api/v1/system/backups").status_code == 403


def test_record_browser_hides_credentials():
    with signed_client("iouellet") as c:
        names = {t["name"] for t in c.get("/api/v1/records").json()}
        assert not names & {"app_user", "auth_session", "audit_log", "alembic_version"}
        for t in ("app_user", "auth_session"):
            assert c.get(f"/api/v1/records/{t}").status_code == 404
        assert c.get("/api/v1/records/lab_test", params={"filters": "calibration_valid=maybe"}).status_code == 422


def test_scheduler_due_logic(tmp_path, monkeypatch):
    from app.ops import scheduler

    monkeypatch.setattr(bk, "BACKUP_DIR", tmp_path)
    assert not scheduler._due(datetime(2026, 12, 4, 2, 0), "02:30")
    assert scheduler._due(datetime(2026, 12, 4, 2, 31), "02:30")
    (tmp_path / "bi-backup-20261204-023100-scheduled.zip").write_bytes(b"x")
    assert not scheduler._due(datetime(2026, 12, 4, 23, 0), "02:30")
    assert scheduler._due(datetime(2026, 12, 5, 2, 30), "02:30")


def test_backup_taken_before_pending_migration(tmp_path, monkeypatch):
    """When the schema is behind and the database holds data, a backup precedes the upgrade."""
    import app.migrate as mg

    calls = []
    monkeypatch.setattr(mg, "current", lambda: "0000")
    monkeypatch.setattr(mg.command, "upgrade", lambda cfg, rev: calls.append(rev))
    monkeypatch.setattr(bk, "BACKUP_DIR", tmp_path)
    mg.upgrade()
    assert calls == ["head"]
    files = [f.name for f in tmp_path.iterdir()]
    assert len(files) == 1 and "pre-migration-0000-to-" in files[0]


def test_ensure_admin_on_new_database(tmp_path):
    url = f"sqlite:///{(tmp_path / 'new.db').as_posix()}"
    assert _manage("db-upgrade", url=url).returncode == 0
    r = subprocess.run([sys.executable, "-m", "app.manage", "ensure-admin"], cwd=BACKEND, input="Boss\nSite Boss\n",
                       env=dict(os.environ, BI_DATABASE_URL=url, BI_NEW_PASSWORD="Granite-ridge-2026"), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(tmp_path / "new.db")
    assert con.execute("select username, full_name, role from app_user").fetchall() == [("boss", "Site Boss", "ADMIN")]
    r = _manage("ensure-admin", url=url)
    assert r.returncode == 0 and "already exist" in r.stdout


def test_restore_script_drops_settings_unknown_to_the_server():
    """Client tools newer than the server (pg_restore 17+ → PostgreSQL 16) write `SET transaction_timeout`."""
    from app.ops.backup import filter_restore_script
    script = [b"SET statement_timeout = 0;\n", b"SET transaction_timeout = 0;\n", b"CREATE TABLE t (a text);\n",
              b"COPY public.t (a) FROM stdin;\n", b"SET transaction_timeout = 0;\n", b"\\.\n", b"SET lock_timeout = 0;\n"]
    out = list(filter_restore_script(iter(script), {"statement_timeout", "lock_timeout"}))
    assert b"SET transaction_timeout = 0;\n" in out[3:5]  # inside COPY data: kept as data
    assert out.count(b"SET transaction_timeout = 0;\n") == 1 and out[0] == b"SET statement_timeout = 0;\n"
    assert out[-1] == b"SET lock_timeout = 0;\n" and len(out) == 6
