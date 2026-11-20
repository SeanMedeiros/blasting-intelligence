"""Authentication, sessions and role-based permissions.

* Passwords: scrypt (Python standard library), random 16-byte salt, constant-time comparison.
* Sessions: random 256-bit token in an HttpOnly cookie (or `Authorization: Bearer`); only its
  SHA-256 is stored. Absolute lifetime + inactivity timeout; revoked on logout, password change,
  password reset and account deactivation.
* CSRF: state-changing requests authenticated by cookie must carry the `X-Requested-With`
  header, which a cross-site form or link cannot add.
* Brute force: account locked for a configurable time after N consecutive failures; the error
  message never reveals whether the username exists.
* Permissions are granted to roles in ROLE_PERMISSIONS; ADMIN holds every permission.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import (LOGIN_LOCK_MINUTES, LOGIN_MAX_ATTEMPTS, PASSWORD_MIN_LENGTH, SESSION_HOURS,
                      SESSION_IDLE_MINUTES)
from ..db import get_db
from ..i18n import _

COOKIE_NAME = "bi_session"
CSRF_HEADER = "x-requested-with"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# ----------------------------------------------------------------------------- permissions
PERMISSIONS: dict[str, str] = {
    "survey.write": "Run survey comparisons, import point clouds, record survey quality review",
    "drillhole.measure": "Record drillhole measurements",
    "drillhole.accept": "Record an engineering acceptance of an out-of-tolerance hole",
    "capa.create": "Open corrective actions",
    "vibration.write": "Import vibration events and review data quality",
    "lab.test": "Record laboratory tests",
    "lab.disposition": "Disposition laboratory non-conformances",
    "blast.operate": "Complete checkpoints, record inventory, inspections and status transitions",
    "blast.close": "Close a blast (final approval of the record)",
    "detonator.record": "Update detonator traceability records",
    "detonator.verify": "Verify detonator documentation and close traceability exceptions",
    "safety.report": "Report safety observations",
    "safety.close": "Close safety observations and corrective actions",
    "safety.configure": "Configure the risk matrix",
    "planning.write": "Reschedule and complete activities, receive deliveries",
    "postblast.edit": "Edit and advance post-blast reviews",
    "postblast.review": "Record the engineering review of a post-blast analysis",
    "config.targets": "Change KPI targets",
    "config.limits": "Change reference limits",
    "users.manage": "Manage user accounts",
    "system.backup": "Create and list database backups",
    "masterdata.manage": "Edit site, areas, benches, equipment, instruments and monitoring stations",
    "personnel.manage": "Edit personnel and training records",
    "calibration.record": "Record instrument calibrations",
    "pattern.manage": "Create drill patterns, import the drillhole design, record drilling completion",
}

ROLES = ("ADMIN", "ENGINEER", "TECHNICIAN", "QSSE", "VIEWER")

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "ADMIN": set(PERMISSIONS),
    "ENGINEER": {"survey.write", "drillhole.measure", "drillhole.accept", "capa.create", "vibration.write", "lab.test",
                 "lab.disposition", "blast.operate", "blast.close", "detonator.record", "detonator.verify",
                 "safety.report", "safety.close", "planning.write", "postblast.edit", "postblast.review",
                 "config.targets", "config.limits", "masterdata.manage", "personnel.manage", "calibration.record",
                 "pattern.manage"},
    "TECHNICIAN": {"survey.write", "drillhole.measure", "capa.create", "vibration.write", "lab.test", "blast.operate",
                   "detonator.record", "safety.report", "planning.write", "postblast.edit", "calibration.record",
                   "pattern.manage"},
    "QSSE": {"capa.create", "lab.disposition", "detonator.verify", "safety.report", "safety.close", "safety.configure",
             "personnel.manage"},
    "VIEWER": set(),
}


def permissions_for(role: str) -> set[str]:
    return ROLE_PERMISSIONS.get(role, set())


# ----------------------------------------------------------------------------- passwords
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(base64.b64decode(dk)))
        return hmac.compare_digest(got, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password(secrets.token_urlsafe(12))


def password_problems(password: str, username: str = "") -> list[str]:
    out = []
    if len(password) < PASSWORD_MIN_LENGTH:
        out.append(_('at least {PASSWORD_MIN_LENGTH} characters', PASSWORD_MIN_LENGTH=PASSWORD_MIN_LENGTH))
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        out.append(_('letters and digits'))
    if username and username.lower() in password.lower():
        out.append(_('must not contain the username'))
    return out


def check_password_policy(password: str, username: str = "") -> None:
    p = password_problems(password, username)
    if p:
        raise HTTPException(422, _("Password does not meet the policy: {problems}", problems="; ".join(p)))


def generate_password() -> str:
    return secrets.token_urlsafe(9) + "7a"


# ----------------------------------------------------------------------------- sessions
def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: m.AppUser, request: Request) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    db.add(m.AuthSession(user_id=user.id, token_hash=_digest(token), expires_at=now + timedelta(hours=SESSION_HOURS),
                         last_seen_at=now, ip=(request.client.host if request.client else None),
                         user_agent=(request.headers.get("user-agent") or "")[:255]))
    return token


def revoke_sessions(db: Session, user_id: int, except_hash: str | None = None) -> None:
    for s in db.scalars(select(m.AuthSession).where(m.AuthSession.user_id == user_id, m.AuthSession.revoked.is_(False))):
        if s.token_hash != except_hash:
            s.revoked = True


def _token(request: Request) -> tuple[str | None, bool]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip(), False
    return request.cookies.get(COOKIE_NAME), True


# ----------------------------------------------------------------------------- principal
class Actor(str):
    """Display name of the signed-in user, carrying the account id and role.

    Subclasses str so existing code that stores "who did it" as text keeps working.
    """

    user_id: int
    username: str
    role: str

    def __new__(cls, user: m.AppUser):
        obj = super().__new__(cls, user.full_name)
        obj.user_id, obj.username, obj.role = user.id, user.username, user.role
        return obj


@dataclass
class Principal:
    user: m.AppUser
    session_hash: str
    permissions: set[str] = field(default_factory=set)

    @property
    def actor(self) -> Actor:
        return Actor(self.user)

    def can(self, perm: str) -> bool:
        return perm in self.permissions


PASSWORD_CHANGE_PATHS = {"/api/v1/auth/me", "/api/v1/auth/logout", "/api/v1/auth/change-password"}


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    token, via_cookie = _token(request)
    if not token:
        raise HTTPException(401, _('Not authenticated'))
    s = db.scalars(select(m.AuthSession).where(m.AuthSession.token_hash == _digest(token))).first()
    now = _now()
    if s is None or s.revoked or s.expires_at <= now or s.last_seen_at + timedelta(minutes=SESSION_IDLE_MINUTES) <= now:
        raise HTTPException(401, _('Session expired — sign in again'))
    user = db.get(m.AppUser, s.user_id)
    if user is None or not user.active:
        raise HTTPException(401, _('Account disabled'))
    if via_cookie and request.method not in SAFE_METHODS and not request.headers.get(CSRF_HEADER):
        raise HTTPException(403, _('Missing X-Requested-With header'))
    if user.must_change_password and request.url.path not in PASSWORD_CHANGE_PATHS:
        raise HTTPException(403, _('Password change required'))
    if (now - s.last_seen_at).total_seconds() > 60:
        s.last_seen_at = now
        db.commit()
    return Principal(user=user, session_hash=s.token_hash, permissions=permissions_for(user.role))


def require(*perms: str):
    """Dependency: the signed-in user must hold every listed permission. Returns the Actor."""

    unknown = [p for p in perms if p not in PERMISSIONS]
    if unknown:
        raise ValueError(_('Unknown permission(s): {unknown}', unknown=unknown))

    def dep(p: Principal = Depends(get_principal)) -> Actor:
        missing = [x for x in perms if not p.can(x)]
        if missing:
            raise HTTPException(403, _('Your role ({role}) does not allow this action ({v})', role=p.user.role, v=', '.join(missing)))
        return p.actor

    return dep


def signed_in(p: Principal = Depends(get_principal)) -> Actor:
    return p.actor


# ----------------------------------------------------------------------------- login
def authenticate(db: Session, username: str, password: str) -> m.AppUser | None:
    """Returns the user, or None. Raises 423 when the account is locked."""
    user = db.scalars(select(m.AppUser).where(m.AppUser.username == username.strip().lower())).first()
    now = _now()
    if user is None:
        verify_password(password, _DUMMY_HASH)  # same cost whether or not the account exists
        return None
    if user.locked_until and user.locked_until > now:
        raise HTTPException(423, _('Account temporarily locked after {LOGIN_MAX_ATTEMPTS} failed attempts — try again later', LOGIN_MAX_ATTEMPTS=LOGIN_MAX_ATTEMPTS))
    if not user.active or not verify_password(password, user.password_hash):
        if user.active:
            user.failed_attempts = (user.failed_attempts or 0) + 1
            if user.failed_attempts >= LOGIN_MAX_ATTEMPTS:
                user.locked_until = now + timedelta(minutes=LOGIN_LOCK_MINUTES)
                user.failed_attempts = 0
        return None
    user.failed_attempts, user.locked_until, user.last_login_at = 0, None, now
    return user


def bootstrap_admin(db: Session, data_dir) -> str | None:
    """Creates the first administrator when no account exists. Returns the password file path if generated."""
    from ..config import ADMIN_INITIAL_PASSWORD

    if db.scalars(select(m.AppUser).limit(1)).first() is not None:
        return None
    pwd = ADMIN_INITIAL_PASSWORD or generate_password()
    db.add(m.AppUser(username="admin", full_name="Administrator", role="ADMIN", password_hash=hash_password(pwd),
                     must_change_password=True))
    db.commit()
    if ADMIN_INITIAL_PASSWORD:
        return None
    f = data_dir / "initial-admin-password.txt"
    f.write_text(f"username: admin\npassword: {pwd}\n\nYou must change this password at first sign-in. Delete this file afterwards.\n",
                 encoding="utf-8")
    return str(f)
