"""Shared test helpers: a TestClient signed in with one of the demonstration accounts."""
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.config import DEMO_PASSWORD
from app.main import app

CSRF = {"X-Requested-With": "pytest"}


def login(c: TestClient, username: str = "admin", password: str = DEMO_PASSWORD):
    r = c.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r


@contextmanager
def signed_client(username: str = "admin"):
    with TestClient(app, headers=CSRF) as c:
        login(c, username)
        yield c


ADMIN_PWD = "Prod-admin-2026"


@contextmanager
def production_client():
    """Production mode on an EMPTY database with one administrator; restores demo mode and data afterwards."""
    import app.config as cfg
    import app.main as main
    import app.routers.auth as auth_router
    from app import models as m
    from app.db import SessionLocal
    from app.migrate import drop_everything, upgrade
    from app.seed.generator import reset_and_seed
    from app.services.security import hash_password

    patches = [(cfg, "IS_DEMO", False), (cfg, "MODE", "production"), (cfg, "DATA_DISCLAIMER", ""),
               (main, "IS_DEMO", False), (auth_router, "MODE", "production")]
    saved = [(o, n, getattr(o, n)) for o, n, _ in patches]
    for o, n, v in patches:
        setattr(o, n, v)
    try:
        drop_everything()
        upgrade()
        with SessionLocal() as db:
            db.add(m.AppUser(username="admin", full_name="Site Admin", role="ADMIN", password_hash=hash_password(ADMIN_PWD),
                             must_change_password=False))
            db.commit()
        with TestClient(app, headers=CSRF) as c:
            login(c, "admin", ADMIN_PWD)
            yield c
    finally:
        for o, n, v in saved:
            setattr(o, n, v)
        reset_and_seed()
