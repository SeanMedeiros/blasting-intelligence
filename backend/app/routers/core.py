"""Cross-cutting endpoints: metadata, dashboard, KPIs, alerts and the read-only record browser."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import String, func, or_, select
from sqlalchemy.orm import Session

from ..analytics.rules import run_rules
from .. import clock
from ..db import Base, get_db
from ..services.dashboard import build_dashboard
from ..services.audit import record
from ..services.security import require
from ..services.kpis import KPI_DEFS, compute_kpis, kpi_series
from ..i18n import _

router = APIRouter(prefix="/api/v1")


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    return build_dashboard(db)


@router.get("/kpis")
def kpis(start: date | None = None, end: date | None = None, db: Session = Depends(get_db)):
    end = end or clock.today()
    start = start or date(end.year, end.month, 1)
    if start > end:
        raise HTTPException(422, _('start must be on or before end'))
    return compute_kpis(db, start, end)


@router.get("/kpis/definitions")
def kpi_definitions():
    return [k.__dict__ for k in KPI_DEFS]


@router.get("/kpis/series")
def kpis_series(granularity: str = Query("month", pattern="^(day|week|month)$"), start: date | None = None,
                end: date | None = None, db: Session = Depends(get_db)):
    end = end or clock.today()
    start = start or date(end.year - (end.month <= 4), (end.month - 5) % 12 + 1, 1)  # five months back
    if (end - start).days > 400 or (granularity == "day" and (end - start).days > 93):
        raise HTTPException(422, _('Range too large for the selected granularity'))
    return kpi_series(db, granularity, start, end)


class TargetIn(BaseModel):
    target: float = Field(..., ge=0, le=100000)
    source: str = Field(..., min_length=3, max_length=200)


@router.put("/kpis/targets/{key}")
def set_target(key: str, body: TargetIn, db: Session = Depends(get_db), user: str = Depends(require("config.targets"))):
    from .. import models as m

    from .masterdata import known_kpi, kpi_direction

    if not known_kpi(key):
        raise HTTPException(404, _('Unknown KPI'))
    t = db.scalars(select(m.KpiTarget).where(m.KpiTarget.kpi_key == key)).first()
    if t is None:  # first target for this KPI on a new site
        t = m.KpiTarget(kpi_key=key, target=body.target, direction=kpi_direction(key), is_demo_placeholder=False)
        db.add(t)
        db.flush()
    if key != "operational_downtime_h" and body.target > 100:
        raise HTTPException(422, _('Percentage targets must be between 0 and 100'))
    before = t.target
    t.target, t.is_demo_placeholder = body.target, False
    record(db, "kpi_target", t.id, "UPDATE", user, {"before": before, "after": body.target, "source": body.source})
    db.commit()
    return {"kpi_key": key, "target": t.target}


class LimitIn(BaseModel):
    min_value: float | None = None
    max_value: float | None = None
    source_document: str = Field(..., min_length=5, max_length=200)
    owner: str = Field(..., min_length=3, max_length=120)
    effective_from: date


@router.put("/settings/limits/{lid}")
def set_limit(lid: int, body: LimitIn, db: Session = Depends(get_db), user: str = Depends(require("config.limits"))):
    """Replace a reference limit with the value from authorized documentation.

    Results already evaluated keep the limit snapshot stored with them; new results use the new value.
    """
    from .. import models as m

    lim = db.get(m.ReferenceLimit, lid)
    if lim is None:
        raise HTTPException(404, _('Limit not found'))
    if body.min_value is None and body.max_value is None:
        raise HTTPException(422, _('At least one of min / max is required'))
    if body.min_value is not None and body.max_value is not None and body.min_value >= body.max_value:
        raise HTTPException(422, _('min must be lower than max'))
    if "PLACEHOLDER" in body.source_document.upper():
        raise HTTPException(422, _('Source document must identify the authorized document (not a placeholder)'))
    before = {k: getattr(lim, k) for k in ("min_value", "max_value", "source_document", "owner")}
    lim.min_value, lim.max_value, lim.source_document, lim.owner = body.min_value, body.max_value, body.source_document, body.owner
    lim.effective_from, lim.is_demo_placeholder = body.effective_from, False
    record(db, "reference_limit", lim.id, "UPDATE", user, {"before": before, "after": body.model_dump(mode="json")})
    db.commit()
    return {"id": lim.id, "parameter": lim.parameter, "min_value": lim.min_value, "max_value": lim.max_value}


@router.get("/alerts")
def alerts(db: Session = Depends(get_db)):
    return run_rules(db)


# ------------------------------------------------------------ record browser (read-only)
# Never exposed through the generic browser: credentials, sessions and migration bookkeeping.
HIDDEN = {"audit_log", "app_user", "auth_session", "alembic_version"}


def _table(name: str):
    t = Base.metadata.tables.get(name)
    if t is None or name in HIDDEN:
        raise HTTPException(404, _("Unknown record type '{name}'", name=name))
    return t


def _typed(col, raw: str):
    """Converts a filter value to the column's type so comparisons behave the same on SQLite and PostgreSQL."""
    try:
        py = col.type.python_type
    except NotImplementedError:
        py = str
    try:
        if py is bool:
            if raw.lower() in ("1", "true", "yes"):
                return True
            if raw.lower() in ("0", "false", "no"):
                return False
            raise ValueError
        if py is int:
            return int(raw)
        if py is float:
            return float(raw)
        if py is date:
            return date.fromisoformat(raw)
        if py is datetime:
            return datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(422, _("Bad value '{raw}' for column '{name}'", raw=raw, name=col.name)) from None
    return raw


@router.get("/records")
def record_types(db: Session = Depends(get_db)):
    out = []
    for name, t in sorted(Base.metadata.tables.items()):
        if name in HIDDEN:
            continue
        out.append({"name": name, "count": db.execute(select(func.count()).select_from(t)).scalar_one(),
                    "columns": [c.name for c in t.columns]})
    return out


@router.get("/records/{name}")
def list_records(name: str, q: str | None = None, order: str = "id", desc: bool = False,
                 limit: int = Query(100, ge=1, le=5000), offset: int = Query(0, ge=0), db: Session = Depends(get_db),
                 filters: str | None = Query(None, description="Comma-separated column=value pairs")):
    t = _table(name)
    stmt = select(t)
    if filters:
        for pair in filters.split(","):
            if "=" not in pair:
                raise HTTPException(422, _("Bad filter '{pair}'", pair=pair))
            k, v = pair.split("=", 1)
            if k not in t.c:
                raise HTTPException(422, _("Unknown column '{k}'", k=k))
            stmt = stmt.where(t.c[k] == _typed(t.c[k], v))
    if q:
        text_cols = [c for c in t.columns if isinstance(c.type, String)]
        if text_cols:
            stmt = stmt.where(or_(*[c.ilike(f"%{q}%") for c in text_cols]))
    if order not in t.c:
        raise HTTPException(422, _("Unknown order column '{order}'", order=order))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = stmt.order_by(t.c[order].desc() if desc else t.c[order]).limit(limit).offset(offset)
    rows = [dict(r._mapping) for r in db.execute(stmt)]
    return {"total": total, "limit": limit, "offset": offset, "items": rows}


@router.get("/records/{name}/{rid}")
def get_record(name: str, rid: int, db: Session = Depends(get_db)):
    t = _table(name)
    row = db.execute(select(t).where(t.c.id == rid)).first()
    if row is None:
        raise HTTPException(404, _('Record not found'))
    return dict(row._mapping)
