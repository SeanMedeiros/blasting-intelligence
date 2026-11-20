"""Sign-in, sessions, password management and user administration."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from .. import clock
from ..config import (APP_NAME, APP_VERSION, COOKIE_SECURE, MODE, PASSWORD_MIN_LENGTH,
                     SESSION_HOURS, TIMEZONE)
from ..db import get_db
from ..services.audit import record
from ..i18n import _
from ..services.security import (COOKIE_NAME, PERMISSIONS, ROLE_PERMISSIONS, ROLES, Actor, Principal, authenticate,
                                 check_password_policy, create_session, get_principal, hash_password, require,
                                 revoke_sessions, verify_password)

public = APIRouter(prefix="/api/v1", tags=["Authentication"])
router = APIRouter(prefix="/api/v1", tags=["Users"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(v):
    return v.isoformat() if v else None


def _me(p: Principal) -> dict:
    u = p.user
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "email": u.email, "role": u.role,
            "must_change_password": u.must_change_password, "permissions": sorted(p.permissions),
            "personnel_id": u.personnel_id}


@public.get("/meta")
def meta(db: Session = Depends(get_db)):
    from ..services.site import site_name

    return {"app": APP_NAME, "version": APP_VERSION, "mode": MODE, "disclaimer": _(clock.banner()) if clock.banner() else None,
            "today": clock.today().isoformat(), "timezone": TIMEZONE, "site": site_name(db),
            "site_configured": db.query(m.Site.id).first() is not None, "password_min_length": PASSWORD_MIN_LENGTH}


class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=60)
    password: str = Field(..., min_length=1, max_length=200)


def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(COOKIE_NAME, token, max_age=int(SESSION_HOURS * 3600), httponly=True, samesite="strict",
                    secure=COOKIE_SECURE, path="/")


@public.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    try:
        user = authenticate(db, body.username, body.password)
    finally:
        db.commit()  # persists failed-attempt counters even when locked/refused
    if user is None:
        record(db, "auth", 0, "LOGIN_FAILED", body.username.strip().lower()[:60], {"ip": request.client.host if request.client else None})
        db.commit()
        raise HTTPException(401, _('Invalid username or password'))
    token = create_session(db, user, request)
    record(db, "auth", user.id, "LOGIN", Actor(user), {"ip": request.client.host if request.client else None})
    db.commit()
    _set_cookie(response, token)
    from ..services.security import permissions_for
    return {"token": token, "user": _me(Principal(user=user, session_hash="", permissions=permissions_for(user.role)))}


@public.post("/auth/logout")
def logout(response: Response, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    s = db.scalars(select(m.AuthSession).where(m.AuthSession.token_hash == p.session_hash)).first()
    if s:
        s.revoked = True
    record(db, "auth", p.user.id, "LOGOUT", p.actor)
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@public.get("/auth/me")
def me(p: Principal = Depends(get_principal)):
    return _me(p)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=200)
    new_password: str = Field(..., min_length=1, max_length=200)


@public.post("/auth/change-password")
def change_password(body: ChangePasswordIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    u = db.get(m.AppUser, p.user.id)
    if not verify_password(body.current_password, u.password_hash):
        raise HTTPException(422, _('Current password is incorrect'))
    if body.new_password == body.current_password:
        raise HTTPException(422, _('The new password must be different from the current one'))
    check_password_policy(body.new_password, u.username)
    u.password_hash, u.must_change_password, u.password_changed_at = hash_password(body.new_password), False, _now()
    revoke_sessions(db, u.id, except_hash=p.session_hash)  # sign out every other device
    record(db, "app_user", u.id, "UPDATE", p.actor, {"password": "changed"})
    db.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------- administration
@router.get("/auth/roles")
def roles(_actor: Actor = Depends(require("users.manage"))):
    return {"roles": [{"role": r, "permissions": sorted(ROLE_PERMISSIONS[r])} for r in ROLES],
            "permissions": [{"key": k, "description": v} for k, v in PERMISSIONS.items()]}


def _user_out(db: Session, u: m.AppUser) -> dict:
    sessions = db.scalar(select(func.count()).select_from(m.AuthSession).where(
        m.AuthSession.user_id == u.id, m.AuthSession.revoked.is_(False), m.AuthSession.expires_at > _now()))
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "email": u.email, "role": u.role,
            "active": u.active, "must_change_password": u.must_change_password, "last_login_at": _iso(u.last_login_at),
            "locked": bool(u.locked_until and u.locked_until > _now()), "personnel_id": u.personnel_id,
            "open_sessions": sessions or 0, "created_at": _iso(u.created_at)}


@router.get("/users")
def list_users(db: Session = Depends(get_db), _actor: Actor = Depends(require("users.manage"))):
    return [_user_out(db, u) for u in db.scalars(select(m.AppUser).order_by(m.AppUser.username))]


class UserIn(BaseModel):
    username: str = Field(..., min_length=3, max_length=60, pattern=r"^[A-Za-z0-9._-]+$")
    full_name: str = Field(..., min_length=3, max_length=120)
    email: str | None = Field(None, max_length=160, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: str
    password: str = Field(..., min_length=1, max_length=200)
    personnel_id: int | None = None

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v not in ROLES:
            raise ValueError(_('role must be one of {v}', v=', '.join(ROLES)))
        return v


def _check_personnel(db: Session, pid: int | None) -> None:
    if pid is not None and db.get(m.Personnel, pid) is None:
        raise HTTPException(422, _('Unknown personnel record'))


@router.post("/users", status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db), actor: Actor = Depends(require("users.manage"))):
    uname = body.username.lower()
    if db.scalars(select(m.AppUser).where(m.AppUser.username == uname)).first():
        raise HTTPException(409, _('Username already exists'))
    check_password_policy(body.password, uname)
    _check_personnel(db, body.personnel_id)
    u = m.AppUser(username=uname, full_name=body.full_name.strip(), email=body.email, role=body.role,
                  password_hash=hash_password(body.password), must_change_password=True, personnel_id=body.personnel_id)
    db.add(u)
    db.flush()
    record(db, "app_user", u.id, "CREATE", actor, {"username": uname, "role": body.role})
    db.commit()
    return _user_out(db, u)


class UserPatch(BaseModel):
    full_name: str | None = Field(None, min_length=3, max_length=120)
    email: str | None = Field(None, max_length=160)
    role: str | None = None
    active: bool | None = None
    personnel_id: int | None = None
    unlock: bool | None = None

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v is not None and v not in ROLES:
            raise ValueError(_('role must be one of {v}', v=', '.join(ROLES)))
        return v


def _active_admins(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(m.AppUser).where(m.AppUser.role == "ADMIN", m.AppUser.active.is_(True))) or 0


@router.patch("/users/{uid}")
def update_user(uid: int, body: UserPatch, db: Session = Depends(get_db), actor: Actor = Depends(require("users.manage"))):
    u = db.get(m.AppUser, uid)
    if u is None:
        raise HTTPException(404, _('User not found'))
    data = body.model_dump(exclude_unset=True)
    removing_admin = u.role == "ADMIN" and u.active and (data.get("role", "ADMIN") != "ADMIN" or data.get("active") is False)
    if removing_admin and _active_admins(db) <= 1:
        raise HTTPException(409, _('At least one active administrator is required'))
    if uid == actor.user_id and (data.get("active") is False or data.get("role", u.role) != u.role):
        raise HTTPException(409, _('You cannot change your own role or deactivate your own account'))
    if "personnel_id" in data:
        _check_personnel(db, data["personnel_id"])
    before = _user_out(db, u)
    for k in ("full_name", "email", "role", "active", "personnel_id"):
        if k in data:
            setattr(u, k, data[k].strip() if isinstance(data[k], str) else data[k])
    if data.get("unlock"):
        u.locked_until, u.failed_attempts = None, 0
    if data.get("active") is False or "role" in data:
        revoke_sessions(db, u.id)  # permissions take effect at next sign-in
    record(db, "app_user", u.id, "UPDATE", actor, {"before": {k: before[k] for k in data if k in before}, "after": data})
    db.commit()
    return _user_out(db, u)


class ResetIn(BaseModel):
    temporary_password: str = Field(..., min_length=1, max_length=200)


@router.post("/users/{uid}/reset-password")
def reset_password(uid: int, body: ResetIn, db: Session = Depends(get_db), actor: Actor = Depends(require("users.manage"))):
    u = db.get(m.AppUser, uid)
    if u is None:
        raise HTTPException(404, _('User not found'))
    check_password_policy(body.temporary_password, u.username)
    u.password_hash, u.must_change_password, u.locked_until, u.failed_attempts = hash_password(body.temporary_password), True, None, 0
    revoke_sessions(db, u.id)
    record(db, "app_user", u.id, "UPDATE", actor, {"password": "reset by administrator"})
    db.commit()
    return _user_out(db, u)


@router.get("/users/{uid}/activity")
def user_activity(uid: int, db: Session = Depends(get_db), _actor: Actor = Depends(require("users.manage"))):
    rows = db.scalars(select(m.AuditLog).where(m.AuditLog.user_id == uid).order_by(m.AuditLog.performed_at.desc()).limit(100))
    return [{"at": _iso(a.performed_at), "entity": a.entity, "entity_id": a.entity_id, "action": a.action} for a in rows]
