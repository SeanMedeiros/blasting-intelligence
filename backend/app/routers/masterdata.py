"""Master data: the reference records every operational module depends on.

One declarative definition per entity drives validation, the API and the generic editor in the UI.
Rules: every change is audited; codes are unique; a record referenced by other records cannot be
deleted — it is deactivated instead (entities with an `active` flag), so history stays intact.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m
from ..db import Base, get_db
from ..services.audit import record
from ..services.kpis import KPI_DEFS
from ..services.security import Actor, permissions_for, signed_in
from ..i18n import _

router = APIRouter(prefix="/api/v1/masterdata", tags=["Master data"])


@dataclass
class F:
    name: str
    kind: str  # text | longtext | number | date | bool | choice | ref
    required: bool = False
    max_len: int | None = None
    choices: tuple[str, ...] = ()
    ref: str | None = None  # entity key for kind == "ref"
    min: float | None = None
    max: float | None = None
    unique: bool = False
    upper: bool = False  # codes are stored upper-case


@dataclass
class Entity:
    key: str
    model: type
    perm: str
    fields: list[F]
    label_field: str = "name"
    order_by: str = "code"
    group: str = "site"
    extra: dict = field(default_factory=dict)


ENTITIES: dict[str, Entity] = {e.key: e for e in [
    Entity("site", m.Site, "masterdata.manage", [
        F("code", "text", True, 20, unique=True, upper=True), F("name", "text", True, 120),
        F("region", "text", False, 120), F("client", "text", False, 120)]),
    Entity("area", m.Area, "masterdata.manage", [
        F("site_id", "ref", True, ref="site"), F("code", "text", True, 20, unique=True, upper=True), F("name", "text", True, 120),
        F("area_type", "choice", True, choices=("OPEN_PIT", "QUARRY", "UNDERGROUND", "STOCKPILE", "OTHER")), F("active", "bool")]),
    Entity("bench", m.Bench, "masterdata.manage", [
        F("area_id", "ref", True, ref="area"), F("code", "text", True, 30, unique=True, upper=True),
        F("elevation_m", "number", True, min=-5000, max=9000), F("bench_height_m", "number", True, min=0.5, max=60),
        F("rock_type", "text", False, 80), F("active", "bool")], label_field="code"),
    Entity("personnel", m.Personnel, "personnel.manage", [
        F("code", "text", True, 20, unique=True, upper=True), F("full_name", "text", True, 120), F("role", "text", True, 60),
        F("qualifications", "longtext", False, 2000), F("active", "bool")], label_field="full_name", group="people"),
    Entity("training_record", m.TrainingRecord, "personnel.manage", [
        F("personnel_id", "ref", True, ref="personnel"), F("course", "text", True, 160), F("completed_on", "date", True),
        F("expires_on", "date"), F("certificate_ref", "text", False, 80)], label_field="course", order_by="completed_on", group="people"),
    Entity("equipment", m.Equipment, "masterdata.manage", [
        F("code", "text", True, 20, unique=True, upper=True), F("name", "text", True, 120),
        F("equipment_type", "choice", True, choices=("DRILL", "MMU", "SCANNER", "VEHICLE", "SEISMOGRAPH", "OTHER")),
        F("status", "choice", True, choices=("AVAILABLE", "DOWN", "MAINTENANCE")), F("active", "bool")], group="equipment"),
    Entity("instrument", m.Instrument, "masterdata.manage", [
        F("code", "text", True, 20, unique=True, upper=True), F("name", "text", True, 120),
        F("instrument_type", "choice", True, choices=("VISCOMETER", "DENSITY", "VOD", "FLOWABILITY", "NOX", "SEISMOGRAPH",
                                                      "SCANNER", "DEPTH_PROBE", "DEVIATION_PROBE", "OTHER")),
        F("serial_number", "text", True, 60), F("location", "text", False, 80), F("active", "bool")], group="equipment"),
    Entity("calibration", m.Calibration, "calibration.record", [
        F("instrument_id", "ref", True, ref="instrument"), F("calibrated_on", "date", True), F("valid_until", "date", True),
        F("certificate_ref", "text", True, 80), F("performed_by", "text", True, 120)],
        label_field="certificate_ref", order_by="calibrated_on", group="equipment"),
    Entity("monitor_station", m.MonitorStation, "masterdata.manage", [
        F("code", "text", True, 20, unique=True, upper=True), F("name", "text", True, 120),
        F("station_type", "choice", True, choices=("RECEPTOR", "STRUCTURE", "PIT_EDGE", "OTHER")),
        F("x", "number", True), F("y", "number", True), F("instrument_id", "ref", False, ref="instrument"), F("active", "bool")],
        group="equipment"),
    Entity("product_batch", m.ProductBatch, "lab.test", [
        F("code", "text", True, 30, unique=True, upper=True), F("product_code", "text", True, 20, upper=True),
        F("product_name", "text", True, 120), F("produced_on", "date", True), F("quantity", "number", True, min=0),
        F("unit", "choice", True, choices=("t", "kg", "units")),
        F("status", "choice", True, choices=("PENDING_TESTS", "RELEASED", "QUARANTINE", "REJECTED"))],
        label_field="code", order_by="produced_on", group="products"),
]}


def _check_perm(actor: Actor, perm: str) -> None:
    if perm not in permissions_for(actor.role):
        raise HTTPException(403, _('Your role ({role}) does not allow this action ({perm})', role=actor.role, perm=perm))


def _entity(key: str) -> Entity:
    e = ENTITIES.get(key)
    if e is None:
        raise HTTPException(404, _("Unknown master-data type '{key}'", key=key))
    return e


def _label(obj, e: Entity) -> str:
    v = getattr(obj, e.label_field)
    code = getattr(obj, "code", None)
    return f"{code} — {v}" if code and e.label_field != "code" else str(v)


def _out(obj, e: Entity, labels: dict) -> dict:
    d = obj.to_dict()
    for f in e.fields:
        if f.kind == "ref":
            d[f"{f.name}_label"] = labels.get(f.ref, {}).get(d.get(f.name))
    return d


def _labels_for(db: Session, e: Entity) -> dict:
    out = {}
    for f in e.fields:
        if f.kind == "ref" and f.ref not in out:
            r = ENTITIES[f.ref]
            out[f.ref] = {o.id: _label(o, r) for o in db.scalars(select(r.model))}
    return out


def _clean(e: Entity, data: dict, partial: bool) -> dict:
    out = {}
    names = {f.name for f in e.fields}
    unknown = set(data) - names
    if unknown:
        raise HTTPException(422, _('Unknown field(s): {v}', v=', '.join(sorted(unknown))))
    for f in e.fields:
        if f.name not in data:
            if not partial and f.required:
                raise HTTPException(422, _('{name} is required', name=f.name))
            continue
        v = data[f.name]
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                v = None
        if v is None:
            if f.required:
                raise HTTPException(422, _('{name} is required', name=f.name))
            out[f.name] = None
            continue
        try:
            if f.kind in ("text", "longtext"):
                v = str(v)
                if f.upper:
                    v = v.upper()
                if f.max_len and len(v) > f.max_len:
                    raise ValueError(_('at most {max_len} characters', max_len=f.max_len))
            elif f.kind == "number":
                v = float(v)
                if (f.min is not None and v < f.min) or (f.max is not None and v > f.max):
                    raise ValueError(_('must be between {min} and {max}', min=f.min, max=f.max))
            elif f.kind == "date":
                v = v if isinstance(v, date) else date.fromisoformat(str(v))
            elif f.kind == "bool":
                if not isinstance(v, bool):
                    raise ValueError(_('must be true or false'))
            elif f.kind == "choice":
                if v not in f.choices:
                    raise ValueError(_('must be one of {v}', v=', '.join(f.choices)))
            elif f.kind == "ref":
                v = int(v)
        except (TypeError, ValueError) as ex:
            raise HTTPException(422, _('{name}: {ex}', name=f.name, ex=ex)) from None
        out[f.name] = v
    return out


def _validate_refs(db: Session, e: Entity, data: dict) -> None:
    for f in e.fields:
        if f.kind == "ref" and data.get(f.name) is not None and db.get(ENTITIES[f.ref].model, data[f.name]) is None:
            raise HTTPException(422, _('{name}: unknown {ref} {v}', name=f.name, ref=f.ref, v=data[f.name]))


def _cross_checks(e: Entity, obj) -> None:
    if e.key == "calibration" and obj.valid_until <= obj.calibrated_on:
        raise HTTPException(422, _('valid_until must be after calibrated_on'))
    if e.key == "training_record" and obj.expires_on and obj.expires_on <= obj.completed_on:
        raise HTTPException(422, _('expires_on must be after completed_on'))


def _usage(db: Session, e: Entity, rid: int) -> dict[str, int]:
    """Rows in other tables that reference this record (foreign keys declared in the models)."""
    used = {}
    table = e.model.__table__
    for t in Base.metadata.sorted_tables:
        for fk in t.foreign_keys:
            if fk.column.table is table:
                n = db.scalar(select(func.count()).select_from(t).where(fk.parent == rid)) or 0
                if n:
                    used[t.name] = used.get(t.name, 0) + n
    return used


# ----------------------------------------------------------------------------- endpoints
@router.get("")
def schema(actor: Actor = Depends(signed_in)):
    perms = permissions_for(actor.role)
    return [{"key": e.key, "group": e.group, "label_field": e.label_field, "can_edit": e.perm in perms,
             "has_active": any(f.name == "active" for f in e.fields),
             "fields": [{"name": f.name, "kind": f.kind, "required": f.required, "max_len": f.max_len, "choices": list(f.choices),
                         "ref": f.ref, "min": f.min, "max": f.max} for f in e.fields]} for e in ENTITIES.values()]


@router.get("/{key}")
def list_rows(key: str, include_inactive: bool = True, db: Session = Depends(get_db)):
    e = _entity(key)
    col = getattr(e.model, e.order_by)
    q = select(e.model).order_by(col.desc() if e.order_by.endswith("_on") else col)
    if not include_inactive and hasattr(e.model, "active"):
        q = q.where(e.model.active.is_(True))
    labels = _labels_for(db, e)
    return [_out(o, e, labels) for o in db.scalars(q)]


@router.get("/{key}/options")
def options(key: str, db: Session = Depends(get_db)):
    """Active records as {id, label} for selection lists."""
    e = _entity(key)
    q = select(e.model)
    if hasattr(e.model, "active"):
        q = q.where(e.model.active.is_(True))
    rows = sorted(db.scalars(q), key=lambda o: _label(o, e))
    return [{"id": o.id, "label": _label(o, e)} for o in rows]


@router.post("/{key}", status_code=201)
def create(key: str, body: dict, db: Session = Depends(get_db), actor: Actor = Depends(signed_in)):
    e = _entity(key)
    _check_perm(actor, e.perm)
    data = _clean(e, body, partial=False)
    if "active" in {f.name for f in e.fields} and data.get("active") is None:
        data["active"] = True
    _validate_refs(db, e, data)
    obj = e.model(**data)
    _cross_checks(e, obj)
    db.add(obj)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, _('A record with this code already exists')) from None
    record(db, key, obj.id, "CREATE", actor, {k: (v.isoformat() if isinstance(v, date) else v) for k, v in data.items()})
    db.commit()
    return _out(obj, e, _labels_for(db, e))


@router.patch("/{key}/{rid}")
def update(key: str, rid: int, body: dict, db: Session = Depends(get_db), actor: Actor = Depends(signed_in)):
    e = _entity(key)
    _check_perm(actor, e.perm)
    obj = db.get(e.model, rid)
    if obj is None:
        raise HTTPException(404, _('Record not found'))
    data = _clean(e, body, partial=True)
    _validate_refs(db, e, data)
    before = {k: getattr(obj, k) for k in data}
    for k, v in data.items():
        setattr(obj, k, v)
    _cross_checks(e, obj)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, _('A record with this code already exists')) from None
    ser = lambda d: {k: (v.isoformat() if isinstance(v, date) else v) for k, v in d.items()}  # noqa: E731
    record(db, key, obj.id, "UPDATE", actor, {"before": ser(before), "after": ser(data)})
    db.commit()
    return _out(obj, e, _labels_for(db, e))


@router.delete("/{key}/{rid}")
def delete(key: str, rid: int, db: Session = Depends(get_db), actor: Actor = Depends(signed_in)):
    e = _entity(key)
    _check_perm(actor, e.perm)
    obj = db.get(e.model, rid)
    if obj is None:
        raise HTTPException(404, _('Record not found'))
    used = _usage(db, e, rid)
    if used:
        hint = _(" Deactivate it instead.") if hasattr(e.model, "active") else ""
        raise HTTPException(409, {"message": _('Cannot delete: referenced by other records.{hint}', hint=hint), "used_by": used})
    snapshot = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in obj.to_dict().items()}
    db.delete(obj)
    record(db, key, rid, "DELETE", actor, snapshot)
    db.commit()
    return {"deleted": rid}


# ----------------------------------------------------------------------------- reference limits & KPI targets
PARAMETERS = {
    "VISCOSITY": "mPa·s", "DENSITY": "g/cm³", "VOD": "m/s", "FLOWABILITY": "s", "NOX": "ppm", "PPV": "mm/s",
    "DEPTH_TOL": "m", "DEVIATION_TOL": "m", "FACE_TOL": "m", "FRONT_DIST_MIN": "m", "TOE_DIST_MAX": "m",
}


class NewLimitIn(BaseModel):
    parameter: str
    scope: str = Field("*", min_length=1, max_length=80)
    min_value: float | None = None
    max_value: float | None = None
    source_document: str = Field(..., min_length=3, max_length=200)
    owner: str = Field(..., min_length=3, max_length=120)
    effective_from: date


@router.post("/reference-limits/new", status_code=201)
def create_limit(body: NewLimitIn, db: Session = Depends(get_db), actor: Actor = Depends(signed_in)):
    _check_perm(actor, "config.limits")
    if body.parameter not in PARAMETERS:
        raise HTTPException(422, _('parameter must be one of {v}', v=', '.join(PARAMETERS)))
    if body.min_value is None and body.max_value is None:
        raise HTTPException(422, _('At least one of min / max is required'))
    if body.min_value is not None and body.max_value is not None and body.min_value >= body.max_value:
        raise HTTPException(422, _('min must be lower than max'))
    if "PLACEHOLDER" in body.source_document.upper():
        raise HTTPException(422, _('Source document must identify the authorized document'))
    scope = body.scope.strip().upper() if body.scope.strip() != "*" else "*"
    if db.scalars(select(m.ReferenceLimit).where(m.ReferenceLimit.parameter == body.parameter, m.ReferenceLimit.scope == scope)).first():
        raise HTTPException(409, _('A limit already exists for this parameter and scope — edit it instead'))
    lim = m.ReferenceLimit(parameter=body.parameter, scope=scope, min_value=body.min_value, max_value=body.max_value,
                           unit=PARAMETERS[body.parameter], source_document=body.source_document, owner=body.owner,
                           effective_from=body.effective_from, is_demo_placeholder=False)
    db.add(lim)
    db.flush()
    record(db, "reference_limit", lim.id, "CREATE", actor, body.model_dump(mode="json"))
    db.commit()
    return lim.to_dict()


@router.get("/reference-limits/parameters")
def limit_parameters():
    return [{"parameter": k, "unit": v} for k, v in PARAMETERS.items()]


KPI_DIRECTION = {"drillhole_deviation_rate": "LOWER", "operational_downtime_h": "LOWER"}


def kpi_direction(key: str) -> str:
    return KPI_DIRECTION.get(key, "HIGHER")


def known_kpi(key: str) -> bool:
    return any(k.key == key for k in KPI_DEFS)


@router.get("/setup/status")
def setup_status(db: Session = Depends(get_db)):
    """First-run checklist: what is still missing before the site can be operated."""
    def n(model, active=False):
        q = select(func.count()).select_from(model)
        if active and hasattr(model, "active"):
            q = q.where(model.active.is_(True))
        return db.scalar(q) or 0

    steps = [
        ("site", n(m.Site)), ("area", n(m.Area, True)), ("bench", n(m.Bench, True)), ("personnel", n(m.Personnel, True)),
        ("equipment", n(m.Equipment, True)), ("instrument", n(m.Instrument, True)), ("calibration", n(m.Calibration)),
        ("monitor_station", n(m.MonitorStation, True)),
        ("reference_limit", db.scalar(select(func.count()).select_from(m.ReferenceLimit)
                                      .where(m.ReferenceLimit.is_demo_placeholder.is_(False))) or 0),
        ("kpi_target", db.scalar(select(func.count()).select_from(m.KpiTarget)
                                 .where(m.KpiTarget.is_demo_placeholder.is_(False))) or 0),
        ("app_user", db.scalar(select(func.count()).select_from(m.AppUser).where(m.AppUser.role != "ADMIN")) or 0),
    ]
    return {"complete": all(c > 0 for _k, c in steps), "steps": [{"key": k, "count": c, "done": c > 0} for k, c in steps]}


@router.get("/{key}/{rid}/usage")
def usage(key: str, rid: int, db: Session = Depends(get_db)):
    e = _entity(key)
    if db.get(e.model, rid) is None:
        raise HTTPException(404, _('Record not found'))
    return _usage(db, e, rid)

