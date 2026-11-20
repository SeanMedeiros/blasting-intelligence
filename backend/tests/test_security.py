"""Authentication, sessions, CSRF protection and role permissions."""


import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from helpers import CSRF, login, signed_client  # noqa: E402

from app import models as m  # noqa: E402
from app.config import DEMO_PASSWORD, LOGIN_MAX_ATTEMPTS  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.seed.generator import reset_and_seed  # noqa: E402
from app.services.security import ROLE_PERMISSIONS, hash_password, password_problems, verify_password  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _seed():
    reset_and_seed()


@pytest.fixture()
def anon():
    with TestClient(app, headers=CSRF) as c:
        yield c


def test_password_hashing():
    h = hash_password("Correct-horse-9")
    assert h.startswith("scrypt$") and "Correct-horse-9" not in h
    assert verify_password("Correct-horse-9", h) and not verify_password("wrong", h)
    assert hash_password("same-Pass-1") != hash_password("same-Pass-1")  # salted
    assert password_problems("short1") and password_problems("onlyletterslong") and not password_problems("Good-pass-123")
    assert password_problems("jdoe-password-1", "jdoe")


def test_public_and_protected(anon):
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/api/v1/meta").status_code == 200
    for path in ("/api/v1/dashboard", "/api/v1/kpis", "/api/v1/surveys", "/api/v1/reports", "/api/v1/users", "/api/v1/auth/me"):
        assert anon.get(path).status_code == 401, path
    assert anon.get("/api/v1/reports/kpi-monthly.pdf").status_code == 401


def test_login_cookie_and_me(anon):
    r = anon.post("/api/v1/auth/login", json={"username": "ERoy ", "password": DEMO_PASSWORD})
    assert r.status_code == 200
    ck = r.headers["set-cookie"].lower()
    assert "bi_session=" in ck and "httponly" in ck and "samesite=strict" in ck
    me = anon.get("/api/v1/auth/me").json()
    assert me["username"] == "eroy" and me["role"] == "TECHNICIAN"
    assert "drillhole.measure" in me["permissions"] and "drillhole.accept" not in me["permissions"]


def test_wrong_password_generic_message(anon):
    a = anon.post("/api/v1/auth/login", json={"username": "eroy", "password": "nope"})
    b = anon.post("/api/v1/auth/login", json={"username": "nobody", "password": "nope"})
    assert a.status_code == b.status_code == 401 and a.json()["detail"] == b.json()["detail"]


def test_csrf_header_required_for_cookie_writes():
    with TestClient(app) as c:  # no X-Requested-With by default
        login(c, "npelletier")
        body = {"description": "CSRF probe", "location": "North Pit", "category": "OTHER", "likelihood": 1, "severity": 1}
        assert c.post("/api/v1/safety/observations", json=body).status_code == 403


def test_bearer_token_without_cookie(anon):
    tok = anon.post("/api/v1/auth/login", json={"username": "jgagnon", "password": DEMO_PASSWORD}).json()["token"]
    with TestClient(app) as c:
        assert c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()["username"] == "jgagnon"
        assert c.get("/api/v1/auth/me", headers={"Authorization": "Bearer forged"}).status_code == 401


def test_logout_revokes_session(anon):
    tok = login(anon, "kbouchard").json()["token"]
    assert anon.post("/api/v1/auth/logout").status_code == 200
    with TestClient(app) as c:
        assert c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_viewer_reads_but_cannot_write():
    with signed_client("iouellet") as c:
        assert c.get("/api/v1/dashboard").status_code == 200
        assert c.get("/api/v1/reports/kpi-monthly.csv").status_code == 200
        r = c.post("/api/v1/safety/observations", json={"description": "x" * 12, "location": "North Pit"})
        assert r.status_code == 403 and "VIEWER" in r.json()["detail"]
        assert c.get("/api/v1/users").status_code == 403


def test_technician_limits():
    with signed_client("eroy") as c:
        mid = SessionLocal().query(m.DrillholeMeasurement).first().id
        r = c.post(f"/api/v1/drillholes/measurements/{mid}/engineering-acceptance",
                   json={"reviewer_name": "Someone", "reviewer_role": "Engineer", "justification": "Probe"})
        assert r.status_code == 403
        bid = SessionLocal().query(m.Blast).first().id
        assert c.post(f"/api/v1/blasts/{bid}/transition", json={"to_status": "CLOSED"}).status_code == 403
        assert c.put("/api/v1/settings/limits/1", json={}).status_code in (403, 422)
        assert c.put("/api/v1/kpis/targets/schedule_adherence", json={"target": 90, "source": "Probe doc"}).status_code == 403


def test_role_matrix_is_consistent():
    assert ROLE_PERMISSIONS["ADMIN"] >= set().union(*ROLE_PERMISSIONS.values())
    assert not ROLE_PERMISSIONS["VIEWER"]
    assert "drillhole.accept" in ROLE_PERMISSIONS["ENGINEER"] and "drillhole.accept" not in ROLE_PERMISSIONS["TECHNICIAN"]
    assert "safety.close" in ROLE_PERMISSIONS["QSSE"] and "safety.close" not in ROLE_PERMISSIONS["TECHNICIAN"]


def test_user_lifecycle_and_audit():
    with signed_client("admin") as adm:
        bad = adm.post("/api/v1/users", json={"username": "newtech", "full_name": "New Tech", "role": "TECHNICIAN", "password": "short"})
        assert bad.status_code == 422
        assert adm.post("/api/v1/users", json={"username": "x", "full_name": "Bad Role", "role": "GOD", "password": "Valid-pass-123"}).status_code == 422
        r = adm.post("/api/v1/users", json={"username": "NewTech", "full_name": "New Tech", "role": "TECHNICIAN", "password": "Temp-pass-123"})
        assert r.status_code == 201 and r.json()["username"] == "newtech" and r.json()["must_change_password"]
        uid = r.json()["id"]
        assert adm.post("/api/v1/users", json={"username": "newtech", "full_name": "Dup", "role": "VIEWER", "password": "Temp-pass-123"}).status_code == 409

        with TestClient(app, headers=CSRF) as u:
            login(u, "newtech", "Temp-pass-123")
            assert u.get("/api/v1/dashboard").status_code == 403  # must change password first
            assert u.post("/api/v1/auth/change-password", json={"current_password": "wrong", "new_password": "New-pass-456"}).status_code == 422
            assert u.post("/api/v1/auth/change-password", json={"current_password": "Temp-pass-123", "new_password": "newtech-123"}).status_code == 422
            assert u.post("/api/v1/auth/change-password", json={"current_password": "Temp-pass-123", "new_password": "New-pass-456"}).status_code == 200
            assert u.get("/api/v1/dashboard").status_code == 200
            obs = u.post("/api/v1/safety/observations", json={
                "obs_type": "HAZARD", "description": "Loose material on ramp edge", "observed_at": "2026-12-04T08:00:00",
                "area_id": 1, "location_detail": "North Pit ramp", "responsible_id": 1, "likelihood": 2, "severity": 2,
                "corrective_action": "Scale and berm the ramp edge", "due_date": "2026-12-10"})
            assert obs.status_code == 201, obs.text
            oid = obs.json()["id"]
            close = {"closure_evidence": "Photo PH-1 of scaled ramp edge"}
            assert u.post(f"/api/v1/safety/observations/{oid}/close", json=close).status_code == 403  # technician
            with signed_client("npelletier") as q:
                assert q.post(f"/api/v1/safety/observations/{oid}/close", json=close).status_code != 403  # QSSE may close

            # role change and deactivation revoke the session immediately
            assert adm.patch(f"/api/v1/users/{uid}", json={"active": False}).status_code == 200
            assert u.get("/api/v1/auth/me").status_code == 401
        with TestClient(app, headers=CSRF) as u2:
            assert u2.post("/api/v1/auth/login", json={"username": "newtech", "password": "New-pass-456"}).status_code == 401

        acts = adm.get(f"/api/v1/users/{uid}/activity").json()
        assert any(a["entity"] == "auth" and a["action"] == "LOGIN" for a in acts)
        with SessionLocal() as db:
            assert db.query(m.AuditLog).filter(m.AuditLog.entity == "app_user", m.AuditLog.entity_id == uid).count() >= 3


def test_admin_safeguards():
    with signed_client("admin") as adm:
        me = adm.get("/api/v1/auth/me").json()
        assert adm.patch(f"/api/v1/users/{me['id']}", json={"active": False}).status_code == 409
        assert adm.patch(f"/api/v1/users/{me['id']}", json={"role": "VIEWER"}).status_code == 409
        roles = adm.get("/api/v1/auth/roles").json()
        assert {r["role"] for r in roles["roles"]} == {"ADMIN", "ENGINEER", "TECHNICIAN", "QSSE", "VIEWER"}


def test_lockout_and_admin_unlock():
    with signed_client("admin") as adm:
        uid = adm.post("/api/v1/users", json={"username": "locktest", "full_name": "Lock Test", "role": "VIEWER",
                                              "password": "Temp-pass-123"}).json()["id"]
        with TestClient(app, headers=CSRF) as u:
            for _ in range(LOGIN_MAX_ATTEMPTS):
                assert u.post("/api/v1/auth/login", json={"username": "locktest", "password": "bad"}).status_code == 401
            assert u.post("/api/v1/auth/login", json={"username": "locktest", "password": "Temp-pass-123"}).status_code == 423
            assert next(x for x in adm.get("/api/v1/users").json() if x["id"] == uid)["locked"]
            assert adm.patch(f"/api/v1/users/{uid}", json={"unlock": True}).status_code == 200
            assert u.post("/api/v1/auth/login", json={"username": "locktest", "password": "Temp-pass-123"}).status_code == 200
        # admin reset forces a new password change and revokes sessions
        assert adm.post(f"/api/v1/users/{uid}/reset-password", json={"temporary_password": "Reset-pass-789"}).status_code == 200
        with TestClient(app, headers=CSRF) as u:
            assert login(u, "locktest", "Reset-pass-789").json()["user"]["must_change_password"]


def test_bootstrap_admin_when_no_accounts(tmp_path):
    from app.services.security import bootstrap_admin
    with SessionLocal() as db:
        assert bootstrap_admin(db, tmp_path) is None  # accounts exist → nothing created
        db.query(m.AuthSession).delete()
        db.query(m.AppUser).delete()
        db.commit()
        f = bootstrap_admin(db, tmp_path)
        assert f and "password:" in open(f, encoding="utf-8").read()
        u = db.query(m.AppUser).one()
        assert u.username == "admin" and u.role == "ADMIN" and u.must_change_password
    reset_and_seed()
