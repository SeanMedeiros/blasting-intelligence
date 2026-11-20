"""Module 09 — Safety & QSSE. The software records and tracks; it never declares an area safe."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import clock
from ..db import get_db
from ..services.audit import record
from ..services.codes import next_code
from ..services.security import require
from ..i18n import N_, _

router = APIRouter(prefix="/api/v1/safety", tags=["Safety & QSSE"])


DEFAULT_MATRIX = {
    "likelihood": [N_("Rare"), N_("Unlikely"), N_("Possible"), N_("Likely"), N_("Almost certain")],
    "severity": [N_("Negligible"), N_("Minor"), N_("Moderate"), N_("Major"), N_("Catastrophic")],
    "levels": [{"name": "LOW", "max_score": 4}, {"name": "MEDIUM", "max_score": 9},
               {"name": "HIGH", "max_score": 16}, {"name": "CRITICAL", "max_score": 25}],
    "source_document": N_("Default 5×5 matrix — replace with the site risk-assessment procedure"),
}


def risk_matrix(db: Session) -> dict:
    s = db.scalars(select(m.AppSetting).where(m.AppSetting.key == "risk_matrix")).first()
    stored = s.value if s else {}
    default = {**DEFAULT_MATRIX, "likelihood": [_(x) for x in DEFAULT_MATRIX["likelihood"]],
               "severity": [_(x) for x in DEFAULT_MATRIX["severity"]], "source_document": _(DEFAULT_MATRIX["source_document"])}
    return {**default, **stored}


def classify(db: Session, likelihood: int, severity: int) -> str:
    score = likelihood * severity
    for lv in risk_matrix(db)["levels"]:
        if score <= lv["max_score"]:
            return lv["name"]
    return "CRITICAL"


def _now():
    return clock.now()


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    obs = db.scalars(select(m.SafetyObservation)).all()
    capa = db.scalars(select(m.Capa)).all()
    insp = db.scalars(select(m.Inspection)).all()
    since = datetime.combine(clock.today() - timedelta(days=30), datetime.min.time())
    train = db.scalars(select(m.TrainingRecord).where(m.TrainingRecord.expires_on <= clock.today() + timedelta(days=30))).all()
    return {
        "open_observations": sum(1 for o in obs if o.status != "CLOSED"),
        "observations_30d": dict(Counter(o.obs_type for o in obs if o.observed_at >= since)),
        "open_by_risk": dict(Counter(o.risk_level for o in obs if o.status != "CLOSED")),
        "capa_open": sum(1 for c in capa if c.status != "CLOSED"),
        "capa_overdue": sum(1 for c in capa if c.status != "CLOSED" and c.due_date < clock.today()),
        "inspections_overdue": sum(1 for i in insp if i.status in ("OVERDUE", "SCHEDULED") and i.due_date < clock.today()),
        "inspections_30d": sum(1 for i in insp if i.inspected_at and i.inspected_at >= since),
        "training_expiring": len(train),
    }


@router.get("/risk-matrix")
def get_matrix(db: Session = Depends(get_db)):
    obs = db.scalars(select(m.SafetyObservation).where(m.SafetyObservation.status != "CLOSED")).all()
    counts = Counter((o.likelihood, o.severity) for o in obs)
    return {**risk_matrix(db), "open_counts": [{"likelihood": k[0], "severity": k[1], "count": v} for k, v in counts.items()]}


class MatrixIn(BaseModel):
    low_max: int = Field(..., ge=1, le=24)
    medium_max: int = Field(..., ge=2, le=24)
    high_max: int = Field(..., ge=3, le=24)
    source_document: str = Field(..., min_length=3, max_length=200)

    @field_validator("high_max")
    @classmethod
    def ordered(cls, v, info):
        d = info.data
        if not (d.get("low_max", 0) < d.get("medium_max", 0) < v):
            raise ValueError(_('thresholds must be strictly increasing: low < medium < high'))
        return v


@router.put("/risk-matrix")
def set_matrix(body: MatrixIn, db: Session = Depends(get_db), user: str = Depends(require("safety.configure"))):
    s = db.scalars(select(m.AppSetting).where(m.AppSetting.key == "risk_matrix")).first()
    if s is None:  # first configuration on a new site
        s = m.AppSetting(key="risk_matrix", value=dict(DEFAULT_MATRIX))
        db.add(s)
        db.flush()
    val = dict(s.value)
    before = val.get("levels")
    val["levels"] = [{"name": "LOW", "max_score": body.low_max}, {"name": "MEDIUM", "max_score": body.medium_max},
                     {"name": "HIGH", "max_score": body.high_max}, {"name": "CRITICAL", "max_score": 25}]
    val["source_document"] = body.source_document
    s.value = val
    n = 0
    for o in db.scalars(select(m.SafetyObservation)):
        lv = classify(db, o.likelihood, o.severity)
        if lv != o.risk_level:
            o.risk_level, n = lv, n + 1
    record(db, "app_setting", s.id, "UPDATE", user, {"before": before, "after": val["levels"], "reclassified": n})
    db.commit()
    return {"levels": val["levels"], "reclassified_observations": n}


@router.get("/observations")
def observations(status: str | None = None, obs_type: str | None = None, risk: str | None = None, db: Session = Depends(get_db)):
    people = {p.id: p.full_name for p in db.scalars(select(m.Personnel))}
    areas = {a.id: a.code for a in db.scalars(select(m.Area))}
    q = select(m.SafetyObservation).order_by(m.SafetyObservation.observed_at.desc())
    out = []
    for o in db.scalars(q):
        if (status == "OPEN" and o.status == "CLOSED") or (status == "CLOSED" and o.status != "CLOSED"):
            continue
        if obs_type and o.obs_type != obs_type or risk and o.risk_level != risk:
            continue
        out.append({"id": o.id, "code": o.code, "type": o.obs_type, "description": o.description, "observed_at": o.observed_at.isoformat(),
                    "area": areas.get(o.area_id), "location": o.location_detail, "reported_by": people.get(o.reported_by_id),
                    "responsible": people.get(o.responsible_id), "likelihood": o.likelihood, "severity": o.severity,
                    "risk_level": o.risk_level, "corrective_action": o.corrective_action, "status": o.status,
                    "due_date": o.due_date.isoformat() if o.due_date else None, "overdue": o.status != "CLOSED" and o.due_date and o.due_date < clock.today(),
                    "closed_at": o.closed_at.isoformat() if o.closed_at else None, "closure_evidence": o.closure_evidence})
    return out


class ObservationIn(BaseModel):
    obs_type: str = Field(..., pattern="^(OBSERVATION|HAZARD|NEAR_MISS|INCIDENT|POSITIVE)$")
    description: str = Field(..., min_length=10, max_length=2000)
    observed_at: datetime
    area_id: int
    location_detail: str = Field(..., min_length=2, max_length=160)
    responsible_id: int
    likelihood: int = Field(..., ge=1, le=5)
    severity: int = Field(..., ge=1, le=5)
    corrective_action: str | None = Field(None, max_length=1000)
    due_date: date | None = None


@router.post("/observations", status_code=201)
def create_observation(body: ObservationIn, db: Session = Depends(get_db), user: str = Depends(require("safety.report"))):
    if db.get(m.Area, body.area_id) is None or db.get(m.Personnel, body.responsible_id) is None:
        raise HTTPException(422, _('Unknown area or responsible person'))
    if body.observed_at.date() > clock.today() + timedelta(days=1):
        raise HTTPException(422, _('Observation date cannot be in the future'))
    level = classify(db, body.likelihood, body.severity)
    if body.obs_type != "POSITIVE" and not (body.corrective_action or "").strip():
        raise HTTPException(422, _('A corrective action is required'))
    o = m.SafetyObservation(code=next_code(db, m.SafetyObservation, "SO", body.observed_at.date(), 3), obs_type=body.obs_type, description=body.description, observed_at=body.observed_at,
                            area_id=body.area_id, location_detail=body.location_detail, responsible_id=body.responsible_id,
                            likelihood=body.likelihood, severity=body.severity, risk_level=level, corrective_action=body.corrective_action,
                            status="OPEN" if body.obs_type != "POSITIVE" else "CLOSED",
                            due_date=body.due_date or (clock.today() + timedelta(days=3 if level in ("HIGH", "CRITICAL") else 14)))
    db.add(o)
    db.flush()
    capa_code = None
    if level in ("HIGH", "CRITICAL"):
        c = m.Capa(code=next_code(db, m.Capa, "CA", width=3), action_type="CORRECTIVE", source_type="OBSERVATION", source_ref=o.code,
                   description=body.corrective_action, owner_id=body.responsible_id, raised_on=clock.today(), due_date=o.due_date, status="OPEN")
        db.add(c)
        db.flush()
        capa_code = c.code
    record(db, "safety_observation", o.id, "CREATE", user, {**body.model_dump(mode="json"), "risk_level": level, "capa": capa_code})
    db.commit()
    return {"id": o.id, "code": o.code, "risk_level": level, "capa": capa_code}


class CloseIn(BaseModel):
    closure_evidence: str = Field(..., min_length=10, max_length=1000)


@router.post("/observations/{oid}/close")
def close_observation(oid: int, body: CloseIn, db: Session = Depends(get_db), user: str = Depends(require("safety.close"))):
    o = db.get(m.SafetyObservation, oid)
    if o is None:
        raise HTTPException(404, _('Observation not found'))
    if o.status == "CLOSED":
        raise HTTPException(409, _('Already closed'))
    o.status, o.closed_at, o.closure_evidence = "CLOSED", _now(), body.closure_evidence
    record(db, "safety_observation", o.id, "STATUS", user, {"status": "CLOSED", **body.model_dump()})
    db.commit()
    return {"id": o.id, "status": o.status}


@router.get("/capa")
def capa(db: Session = Depends(get_db)):
    people = {p.id: p.full_name for p in db.scalars(select(m.Personnel))}
    return [{"id": c.id, "code": c.code, "type": c.action_type, "source_type": c.source_type, "source_ref": c.source_ref,
             "description": c.description, "owner": people.get(c.owner_id), "raised_on": c.raised_on.isoformat(),
             "due_date": c.due_date.isoformat(), "status": c.status, "closed_on": c.closed_on.isoformat() if c.closed_on else None,
             "closure_evidence": c.closure_evidence, "overdue": c.status != "CLOSED" and c.due_date < clock.today(),
             "days_open": ((c.closed_on or clock.today()) - c.raised_on).days}
            for c in db.scalars(select(m.Capa).order_by(m.Capa.due_date.desc()))]


@router.post("/capa/{cid}/close")
def close_capa(cid: int, body: CloseIn, db: Session = Depends(get_db), user: str = Depends(require("safety.close"))):
    c = db.get(m.Capa, cid)
    if c is None:
        raise HTTPException(404, _('Action not found'))
    if c.status == "CLOSED":
        raise HTTPException(409, _('Already closed'))
    c.status, c.closed_on, c.closure_evidence = "CLOSED", clock.today(), body.closure_evidence
    record(db, "capa", c.id, "STATUS", user, {"status": "CLOSED", **body.model_dump()})
    db.commit()
    return {"id": c.id, "status": c.status, "on_time": c.closed_on <= c.due_date}


@router.get("/inspections")
def inspections(inspection_type: str | None = None, db: Session = Depends(get_db)):
    people = {p.id: p.full_name for p in db.scalars(select(m.Personnel))}
    blasts = {b.id: b.code for b in db.scalars(select(m.Blast))}
    areas = {a.id: a.code for a in db.scalars(select(m.Area))}
    q = select(m.Inspection).order_by(m.Inspection.due_date.desc())
    if inspection_type:
        q = q.where(m.Inspection.inspection_type == inspection_type)
    out = []
    for i in db.scalars(q):
        st = "OVERDUE" if i.status != "COMPLETED" and i.due_date < clock.today() else i.status
        out.append({"id": i.id, "code": i.code, "type": i.inspection_type, "blast": blasts.get(i.blast_id), "area": areas.get(i.area_id),
                    "due_date": i.due_date.isoformat(), "inspected_at": i.inspected_at.isoformat() if i.inspected_at else None,
                    "inspector": people.get(i.inspector_id), "status": st, "findings": i.findings,
                    "items": [{"id": x.id, "seq": x.seq, "text": x.text, "result": x.result, "comment": x.comment} for x in sorted(i.items, key=lambda x: x.seq)]})
    return out


@router.get("/training")
def training(db: Session = Depends(get_db)):
    people = {p.id: (p.full_name, p.role) for p in db.scalars(select(m.Personnel))}
    out = []
    for t in db.scalars(select(m.TrainingRecord).order_by(m.TrainingRecord.expires_on)):
        st = "EXPIRED" if t.expires_on and t.expires_on < clock.today() else ("EXPIRING" if t.expires_on and t.expires_on <= clock.today() + timedelta(days=30) else "VALID")
        out.append({"id": t.id, "person": people[t.personnel_id][0], "role": people[t.personnel_id][1], "course": t.course,
                    "completed_on": t.completed_on.isoformat(), "expires_on": t.expires_on.isoformat() if t.expires_on else None,
                    "certificate_ref": t.certificate_ref, "status": st})
    return out
