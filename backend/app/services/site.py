"""Site identity used in headers of reports and exports."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..i18n import _


def site_name(db: Session) -> str:
    s = db.scalars(select(m.Site).order_by(m.Site.id)).first()
    return s.name if s else _("Site not configured")
