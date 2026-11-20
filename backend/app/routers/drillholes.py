"""Module 04 — Drillhole measurement and verification (QA/QC).

Inspection status is computed against configurable tolerances (reference_limit DEPTH_TOL and
DEVIATION_TOL). Approved loading parameters are stored as document references only; the
application never calculates or prescribes explosive quantities or loading instructions.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import clock
from ..db import get_db
from ..services.audit import limit, record
from ..services.codes import next_code
from ..services.security import require
from ..i18n import N_, _

router = APIRouter(prefix="/api/v1/drillholes", tags=["Drillhole verification"])

FIRED = {"IN_PROGRESS", "AWAITING_VERIFICATION", "COMPLETED", "CLOSED"}


def tolerances(db: Session) -> dict:
    d, v = limit(db, "DEPTH_TOL"), limit(db, "DEVIATION_TOL")
    """Tolerances from the approved design (reference limits DEPTH_TOL and DEVIATION_TOL). Never invented:
    when they are not configured, measurements are refused until they are."""
    ok = bool(d and d.min_value is not None and d.max_value is not None and v and v.max_value is not None)
    return {"configured": ok, "depth_min_m": d.min_value if ok else None, "depth_max_m": d.max_value if ok else None,
            "toe_deviation_max_m": v.max_value if ok else None,
            "source": d.source_document if ok else None, "is_demo_placeholder": bool(ok and (d.is_demo_placeholder or v.is_demo_placeholder))}


NOT_CONFIGURED = N_("Drillhole tolerances are not configured. In Settings, add DEPTH_TOL (min and max, m) and DEVIATION_TOL "
                  "(max, m) from the approved design document, then record the measurement.")


def evaluate(depth_diff: float, toe_dev: float | None, condition: str, tol: dict) -> tuple[str, list[str]]:
    """Returns (inspection_status, reasons). Rules are documented and deterministic."""
    reasons = []
    if depth_diff < tol["depth_min_m"]:
        reasons.append(_('Depth {depth_diff:+.2f} m below tolerance ({depth_min_m:+.2f} m)', depth_diff=depth_diff, depth_min_m=tol['depth_min_m']))
    if depth_diff > tol["depth_max_m"]:
        reasons.append(_('Depth {depth_diff:+.2f} m above tolerance (+{depth_max_m:.2f} m)', depth_diff=depth_diff, depth_max_m=tol['depth_max_m']))
    if toe_dev is not None and toe_dev > tol["toe_deviation_max_m"]:
        reasons.append(_('Toe deviation {toe_dev:.2f} m above tolerance ({toe_deviation_max_m:.2f} m)', toe_dev=toe_dev, toe_deviation_max_m=tol['toe_deviation_max_m']))
    if condition == "COLLAPSED":
        reasons.append(_('Hole recorded as collapsed'))
    if condition == "COLLAPSED" or depth_diff < 2 * tol["depth_min_m"]:
        return "REDRILL_REQUIRED", reasons + [_("Rule: collapsed hole or shortfall beyond twice the tolerance → redrill request to driller")]
    if reasons:
        return "OUT_OF_TOLERANCE", reasons
    return "WITHIN_TOLERANCE", [_("Within configured tolerances")]


def _hole_row(h: m.Drillhole, people: dict) -> dict:
    last = h.measurements[-1] if h.measurements else None
    return {
        "id": h.id, "hole_code": h.hole_code, "row": h.row_no, "col": h.col_no,
        "planned_x": h.planned_x, "planned_y": h.planned_y, "planned_z": h.planned_z, "planned_depth_m": h.planned_depth_m,
        "measured_depth_m": last.measured_depth_m if last else None,
        "depth_diff_m": round(last.measured_depth_m - h.planned_depth_m, 2) if last else None,
        "toe_deviation_m": last.toe_deviation_m if last else None,
        "collar_offset_m": last.collar_offset_m if last else None,
        "water_present": last.water_present if last else None,
        "hole_condition": last.hole_condition if last else None,
        "status": last.inspection_status if last else "NOT_MEASURED",
        "measured_at": last.measured_at.isoformat() if last else None,
        "technician": people.get(last.technician_id) if last else None,
        "measurement_count": len(h.measurements), "notes": last.notes if last else None,
    }


def _pattern_stats(holes: list[dict]) -> dict:
    meas = [h for h in holes if h["status"] != "NOT_MEASURED"]
    out = [h for h in meas if h["status"] != "WITHIN_TOLERANCE"]
    dd = [abs(h["depth_diff_m"]) for h in meas]
    td = [h["toe_deviation_m"] for h in meas if h["toe_deviation_m"] is not None]
    return {
        "holes": len(holes), "measured": len(meas),
        "inspected_pct": round(100 * len(meas) / len(holes), 1) if holes else None,
        "deviations": len(out), "deviation_rate_pct": round(100 * len(out) / len(meas), 1) if meas else None,
        "redrill": sum(1 for h in meas if h["status"] == "REDRILL_REQUIRED"),
        "accepted_by_engineer": sum(1 for h in meas if h["status"] == "ACCEPTED_BY_ENGINEER"),
        "avg_abs_depth_diff_m": round(sum(dd) / len(dd), 2) if dd else None,
        "avg_toe_deviation_m": round(sum(td) / len(td), 2) if td else None,
        "outstanding": len(holes) - len(meas),
        "water_holes": sum(1 for h in meas if h["water_present"]),
    }


def _people(db):
    return {p.id: p.full_name for p in db.scalars(select(m.Personnel))}


@router.get("/tolerances")
def get_tolerances(db: Session = Depends(get_db)):
    return tolerances(db)


@router.get("/patterns")
def list_patterns(db: Session = Depends(get_db)):
    people = _people(db)
    benches = {b.id: b for b in db.scalars(select(m.Bench))}
    areas = {a.id: a.code for a in db.scalars(select(m.Area))}
    blasts = {b.pattern_id: b for b in db.scalars(select(m.Blast))}
    out = []
    for p in db.scalars(select(m.DrillPattern)).all():
        b = blasts.get(p.id)
        holes = [_hole_row(h, people) for h in p.holes]
        bench = benches[p.bench_id]
        out.append({"id": p.id, "code": p.code, "bench": bench.code, "area": areas[bench.area_id],
                    "blast": b.code if b else None, "blast_status": b.status if b else None,
                    "planned_blast_date": b.planned_date.isoformat() if b else None,
                    "drilled_on": p.drilled_on.isoformat() if p.drilled_on else None, **_pattern_stats(holes)})
    out.sort(key=lambda x: x["planned_blast_date"] or "", reverse=True)
    return out


@router.get("/patterns/{pid}")
def pattern_detail(pid: int, db: Session = Depends(get_db)):
    p = db.get(m.DrillPattern, pid)
    if p is None:
        raise HTTPException(404, _('Pattern not found'))
    people = _people(db)
    holes = [_hole_row(h, people) for h in p.holes]
    bench = db.get(m.Bench, p.bench_id)
    blast = db.scalars(select(m.Blast).where(m.Blast.pattern_id == p.id)).first()
    alr = db.scalars(select(m.ApprovedLoadingRecord).where(m.ApprovedLoadingRecord.pattern_id == p.id)).all()
    capas = db.scalars(select(m.Capa).where(m.Capa.source_type == "DRILLHOLE")).all()
    capas = [c for c in capas if c.source_ref and (c.source_ref == p.code or (c.source_ref.endswith("*") and p.code.startswith(c.source_ref[:-1])))]
    survey = db.scalars(select(m.Survey).where(m.Survey.blast_id == (blast.id if blast else -1), m.Survey.survey_type == "FACE_PROFILE",
                                                m.Survey.quality_status == "ACCEPTED")).first()
    return {
        "id": p.id, "code": p.code, "bench": bench.code, "bench_height_m": bench.bench_height_m, "rock_type": bench.rock_type,
        "design_document_ref": p.design_document_ref, "approved_by": p.approved_by, "hole_diameter_mm": p.hole_diameter_mm,
        "drilled_on": p.drilled_on.isoformat() if p.drilled_on else None,
        "blast": {"id": blast.id, "code": blast.code, "status": blast.status, "planned_date": blast.planned_date.isoformat()} if blast else None,
        "locked": bool(blast and blast.status in FIRED),
        "face_survey_id": survey.id if survey else None,
        "approved_loading_records": [{"document_ref": a.document_ref, "revision": a.revision, "approved_by": a.approved_by,
                                      "approved_on": a.approved_on.isoformat(), "notes": a.notes} for a in alr],
        "tolerances": tolerances(db), "stats": _pattern_stats(holes), "holes": holes,
        "capa": [{"code": c.code, "description": c.description, "status": c.status, "due_date": c.due_date.isoformat(),
                  "owner": people.get(c.owner_id), "overdue": c.status != "CLOSED" and c.due_date < clock.today()} for c in capas],
    }


@router.get("/holes/{hid}")
def hole_detail(hid: int, db: Session = Depends(get_db)):
    h = db.get(m.Drillhole, hid)
    if h is None:
        raise HTTPException(404, _('Hole not found'))
    people = _people(db)
    instr = {i.id: i.code for i in db.scalars(select(m.Instrument))}
    return {**_hole_row(h, people), "pattern": h.pattern.code,
            "history": [{"id": x.id, "measured_at": x.measured_at.isoformat(), "technician": people.get(x.technician_id),
                         "instrument": instr.get(x.instrument_id), "measured_depth_m": x.measured_depth_m,
                         "depth_diff_m": round(x.measured_depth_m - h.planned_depth_m, 2), "toe_deviation_m": x.toe_deviation_m,
                         "collar_offset_m": x.collar_offset_m, "water_present": x.water_present, "hole_condition": x.hole_condition,
                         "status": x.inspection_status, "notes": x.notes} for x in h.measurements]}


class MeasurementIn(BaseModel):
    measured_depth_m: float = Field(..., gt=0, le=60)
    toe_deviation_m: float | None = Field(None, ge=0, le=10)
    collar_offset_m: float = Field(0.0, ge=0, le=5)
    water_present: bool = False
    hole_condition: str = Field("OPEN", pattern="^(OPEN|PARTIALLY_BLOCKED|COLLAPSED)$")
    technician_id: int
    instrument_id: int | None = None
    measured_at: datetime | None = None
    notes: str | None = Field(None, max_length=1000)


@router.post("/holes/{hid}/measurements", status_code=201)
def add_measurement(hid: int, body: MeasurementIn, db: Session = Depends(get_db), user: str = Depends(require("drillhole.measure"))):
    h = db.get(m.Drillhole, hid)
    if h is None:
        raise HTTPException(404, _('Hole not found'))
    blast = db.scalars(select(m.Blast).where(m.Blast.pattern_id == h.pattern_id)).first()
    if blast and blast.status in FIRED:
        raise HTTPException(409, _('Blast {code} has been fired ({status}); hole records are locked', code=blast.code, status=blast.status))
    tech = db.get(m.Personnel, body.technician_id)
    if tech is None or not tech.active:
        raise HTTPException(422, _('Unknown or inactive technician'))
    when = body.measured_at or clock.now()
    if when.date() > clock.today() + timedelta(days=1):
        raise HTTPException(422, _('Measurement date cannot be in the future'))
    if body.instrument_id is not None:
        ins = db.get(m.Instrument, body.instrument_id)
        if ins is None or ins.instrument_type not in ("DEPTH_PROBE", "DEVIATION_PROBE"):
            raise HTTPException(422, _('Instrument must be a depth or deviation probe'))
        if not any(c.calibrated_on <= when.date() <= c.valid_until for c in ins.calibrations):
            raise HTTPException(422, _('{code} has no valid calibration on {v}', code=ins.code, v=when.date()))
    tol = tolerances(db)
    if not tol["configured"]:
        raise HTTPException(409, _(NOT_CONFIGURED))
    status, reasons = evaluate(body.measured_depth_m - h.planned_depth_m, body.toe_deviation_m, body.hole_condition, tol)
    x = m.DrillholeMeasurement(drillhole_id=h.id, measured_at=when, technician_id=tech.id, instrument_id=body.instrument_id,
                               measured_depth_m=round(body.measured_depth_m, 2), collar_offset_m=round(body.collar_offset_m, 2),
                               toe_deviation_m=body.toe_deviation_m, water_present=body.water_present,
                               hole_condition=body.hole_condition, inspection_status=status, notes=body.notes)
    db.add(x)
    db.flush()
    record(db, "drillhole_measurement", x.id, "CREATE", user,
           {"hole": f"{h.pattern.code}/{h.hole_code}", "status": status, **body.model_dump(mode="json")})
    db.commit()
    return {"id": x.id, "status": status, "reasons": reasons, "depth_diff_m": round(body.measured_depth_m - h.planned_depth_m, 2)}


class AcceptanceIn(BaseModel):
    reviewer_name: str = Field(..., min_length=3, max_length=120)
    reviewer_role: str = Field(..., min_length=3, max_length=80)
    justification: str = Field(..., min_length=10, max_length=1000)


@router.post("/measurements/{mid}/engineering-acceptance")
def engineering_acceptance(mid: int, body: AcceptanceIn, db: Session = Depends(get_db), user: str = Depends(require("drillhole.accept"))):
    """Records an acceptance decision taken by a qualified engineer outside the software."""
    x = db.get(m.DrillholeMeasurement, mid)
    if x is None:
        raise HTTPException(404, _('Measurement not found'))
    if x.inspection_status not in ("OUT_OF_TOLERANCE", "REDRILL_REQUIRED"):
        raise HTTPException(409, _('Only out-of-tolerance measurements can receive an engineering acceptance record'))
    if x is not x.drillhole.measurements[-1]:
        raise HTTPException(409, _('Only the latest measurement of a hole can be accepted'))
    before = x.inspection_status
    x.inspection_status = "ACCEPTED_BY_ENGINEER"
    x.notes = ((x.notes + " | ") if x.notes else "") + f"Accepted by {body.reviewer_name} ({body.reviewer_role}): {body.justification}"
    record(db, "drillhole_measurement", x.id, "STATUS", user, {"from": before, "to": "ACCEPTED_BY_ENGINEER", **body.model_dump()})
    db.commit()
    return {"id": x.id, "status": x.inspection_status}


class CapaIn(BaseModel):
    description: str = Field(..., min_length=10, max_length=2000)
    owner_id: int
    due_date: date


@router.post("/patterns/{pid}/capa", status_code=201)
def create_capa(pid: int, body: CapaIn, db: Session = Depends(get_db), user: str = Depends(require("capa.create"))):
    p = db.get(m.DrillPattern, pid)
    if p is None:
        raise HTTPException(404, _('Pattern not found'))
    if db.get(m.Personnel, body.owner_id) is None:
        raise HTTPException(422, _('Unknown owner'))
    if body.due_date < clock.today():
        raise HTTPException(422, _('Due date cannot be in the past'))
    c = m.Capa(code=next_code(db, m.Capa, "CA", width=3), action_type="CORRECTIVE", source_type="DRILLHOLE", source_ref=p.code,
               description=body.description, owner_id=body.owner_id, raised_on=clock.today(), due_date=body.due_date, status="OPEN")
    db.add(c)
    db.flush()
    record(db, "capa", c.id, "CREATE", user, {"pattern": p.code, **body.model_dump(mode="json")})
    db.commit()
    return {"id": c.id, "code": c.code}


@router.get("/trend")
def deviation_trend(bench: str | None = None, db: Session = Depends(get_db)):
    pats = list_patterns(db)
    pats = [p for p in pats if p["measured"] and (bench is None or p["bench"] == bench)]
    pats.sort(key=lambda p: p["planned_blast_date"] or "")
    return [{"pattern": p["code"], "bench": p["bench"], "date": p["planned_blast_date"], "deviation_rate_pct": p["deviation_rate_pct"],
             "avg_toe_deviation_m": p["avg_toe_deviation_m"], "avg_abs_depth_diff_m": p["avg_abs_depth_diff_m"]} for p in pats]


@router.get("/outstanding")
def outstanding(db: Session = Depends(get_db)):
    return [p for p in list_patterns(db) if p["outstanding"] and p["blast_status"] not in FIRED and p["drilled_on"]]


@router.get("/patterns/{pid}/export.csv")
def export_csv(pid: int, db: Session = Depends(get_db)):
    d = pattern_detail(pid, db)
    buf = io.StringIO()
    w = csv.writer(buf)
    if clock.banner():
        w.writerow(["# DEMONSTRATION DATA - FICTIONAL SITE"])
    w.writerow(["# Drillhole verification report", d["code"], d["bench"], d["design_document_ref"]])
    t = d["tolerances"]
    w.writerow(["# Tolerances (demo placeholders)" if t["is_demo_placeholder"] else "# Tolerances",
                f"depth {t['depth_min_m']}/{t['depth_max_m']} m" if t["configured"] else "not configured",
                f"toe deviation <= {t['toe_deviation_max_m']} m" if t["configured"] else ""])
    cols = ["hole_code", "row", "col", "planned_depth_m", "measured_depth_m", "depth_diff_m", "toe_deviation_m",
            "collar_offset_m", "water_present", "hole_condition", "status", "measured_at", "technician", "notes"]
    w.writerow(cols)
    for h in d["holes"]:
        w.writerow([h[c] for c in cols])
    return Response("﻿" + buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{d["code"]}_verification.csv"'})
