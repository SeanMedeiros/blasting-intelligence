"""Audit trail helper: every write records who, when, what (before/after)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models as m


def record(db: Session, entity: str, entity_id: int, action: str, user: str, changes: dict | None = None) -> None:
    """`user` is normally a security.Actor (display name + account id); plain text is accepted for system events."""
    db.add(m.AuditLog(entity=entity, entity_id=entity_id, action=action, performed_by=str(user)[:120],
                      user_id=getattr(user, "user_id", None), changes=changes))


def limit(db: Session, parameter: str, scope: str = "*") -> m.ReferenceLimit | None:
    q = db.query(m.ReferenceLimit).filter(m.ReferenceLimit.parameter == parameter)
    return q.filter(m.ReferenceLimit.scope == scope).first() or q.filter(m.ReferenceLimit.scope == "*").first()
