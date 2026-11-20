"""Module 10 — Post-blast analysis.

Workflow: Data collection → Verification → Analysis → Interpretation → Improvement proposal →
Documentation → Completed. Any improvement proposal requires a recorded review by a qualified
engineer before the review can be completed.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import clock
from ..db import get_db
from ..services.audit import record
from ..services.security import require
from ..i18n import _

router = APIRouter(prefix="/api/v1/postblast", tags=["Post-blast analysis"])

STAGES = ["DATA_COLLECTION", "VERIFICATION", "ANALYSIS", "INTERPRETATION", "IMPROVEMENT_PROPOSAL", "DOCUMENTATION", "COMPLETED"]
TEXT_FIELDS = ["plan_compliance", "fragmentation_observation", "geology_observation", "operational_deviations", "lessons_learned", "improvement_proposal"]


def _review(db: Session, blast_id: int) -> tuple[m.Blast, m.PostBlastReview]:
    b = db.get(m.Blast, blast_id)
    if b is None:
        raise HTTPException(404, _('Blast not found'))
    r = db.scalars(select(m.PostBlastReview).where(m.PostBlastReview.blast_id == b.id)).first()
    if r is None:
        raise HTTPException(404, _('No post-blast review for this blast (not fired yet)'))
    return b, r


def collected(db: Session, b: m.Blast) -> dict:
    """Data collection step: everything already recorded about the blast, gathered automatically."""
    pattern = db.get(m.DrillPattern, b.pattern_id)
    holes = pattern.holes
    meas = [h.measurements[-1] for h in holes if h.measurements]
    out_tol = [x for x in meas if x.inspection_status != "WITHIN_TOLERANCE"]
    cps = db.scalars(select(m.BlastCheckpoint).where(m.BlastCheckpoint.blast_id == b.id)).all()
    st = {s.id: s.code for s in db.scalars(select(m.MonitorStation))}
    vib = db.scalars(select(m.VibrationEvent).where(m.VibrationEvent.blast_id == b.id)).all()
    surveys = db.scalars(select(m.Survey).where(m.Survey.blast_id == b.id)).all()
    comps = db.scalars(select(m.SurveyComparison).where(m.SurveyComparison.compared_survey_id.in_([s.id for s in surveys] or [-1]))).all()
    tests = db.scalars(select(m.LabTest).where(m.LabTest.blast_id == b.id)).all()
    wo = db.get(m.WorkOrder, b.work_order_id)
    delays = db.scalars(select(m.DelayEvent).where(m.DelayEvent.work_order_id == wo.id)).all()
    det = db.scalars(select(m.DetonatorRecord).where(m.DetonatorRecord.blast_id == b.id)).first()
    exc = db.scalars(select(m.TraceabilityException).where(m.TraceabilityException.detonator_record_id == (det.id if det else -1))).all()
    mv = db.scalars(select(m.InventoryMovement).where(m.InventoryMovement.blast_id == b.id)).all()
    tot = defaultdict(float)
    for x in mv:
        tot[x.movement_type] += x.quantity
    return {
        "drillholes": {"holes": len(holes), "measured": len(meas), "out_of_tolerance": len(out_tol),
                       "deviation_rate_pct": round(100 * len(out_tol) / len(meas), 1) if meas else None,
                       "avg_toe_deviation_m": round(sum(x.toe_deviation_m or 0 for x in meas) / len(meas), 2) if meas else None,
                       "water_holes": sum(1 for x in meas if x.water_present)},
        "checkpoints": {"completed": sum(1 for c in cps if c.completed), "total": len(cps)},
        "vibration": [{"station": st[e.station_id], "ppv_mm_s": e.ppv_mm_s, "frequency_hz": e.dominant_frequency_hz,
                       "limit": e.limit_ppv_mm_s, "compliance": e.compliance, "quality": e.data_quality} for e in vib],
        "surveys": [{"id": s.id, "code": s.code, "type": s.survey_type, "quality": s.quality_status} for s in surveys],
        "survey_comparisons": [{"survey_id": c.compared_survey_id, "reference": c.reference_label, "within_tolerance_pct": c.within_tolerance_pct,
                                "mean_m": c.mean_m} for c in comps],
        "quality_tests": [{"code": t.code, "type": t.test_type, "value": t.value, "unit": t.unit, "result": t.result} for t in tests],
        "delays": [{"category": d.category, "hours": d.hours, "description": d.description} for d in delays],
        "production": {"forecast_t": wo.forecast_tonnes, "actual_t": wo.actual_tonnes,
                       "variance_pct": round(100 * (wo.actual_tonnes - wo.forecast_tonnes) / wo.forecast_tonnes, 1) if wo.actual_tonnes and wo.forecast_tonnes else None},
        "inventory": {"received": round(tot["RECEIVED"], 3), "used": round(tot["USED"], 3), "returned": round(tot["RETURNED"], 3),
                      "balance": round(tot["RECEIVED"] - tot["USED"] - tot["RETURNED"], 3)},
        "traceability_exceptions": [{"description": x.description, "status": x.status} for x in exc],
    }


def requirements(db: Session, b: m.Blast, r: m.PostBlastReview) -> list[str]:
    if r.stage == "COMPLETED":
        return []
    nxt = STAGES[STAGES.index(r.stage) + 1]
    c = collected(db, b)
    unmet = []
    if nxt == "VERIFICATION":
        if not c["vibration"]:
            unmet.append(_('No vibration record linked to the blast'))
        if not any(s["type"] == "POST_BLAST" for s in c["surveys"]):
            unmet.append(_('No post-blast survey recorded (record it, or document the reason in operational deviations)')) \
                if not (r.operational_deviations or "").strip() else None
    elif nxt == "ANALYSIS":
        if any(v["quality"] == "QUESTIONABLE" for v in c["vibration"]):
            unmet.append(_('Questionable vibration records must be validated in Vibration Monitoring'))
        if not (r.plan_compliance or "").strip():
            unmet.append(_('Plan compliance statement is required'))
    elif nxt == "INTERPRETATION":
        if not (r.operational_deviations or "").strip():
            unmet.append(_("Operational deviations must be documented (write 'None significant' if applicable)"))
    elif nxt == "IMPROVEMENT_PROPOSAL":
        if not r.fragmentation_rating or not (r.fragmentation_observation or "").strip():
            unmet.append(_('Fragmentation observation and visual rating are required'))
        if not (r.geology_observation or "").strip():
            unmet.append(_('Geological observation is required'))
    elif nxt == "DOCUMENTATION":
        if not (r.lessons_learned or "").strip():
            unmet.append(_("Lessons learned are required (write 'None' if applicable)"))
    elif nxt == "COMPLETED":
        if (r.improvement_proposal or "").strip() and r.engineering_review_status != "REVIEWED":
            unmet.append(_('Improvement proposal awaiting review by a qualified engineer'))
    return [u for u in unmet if u]


def _row(db, b, r, benches):
    return {"blast_id": b.id, "blast": b.code, "bench": benches[b.bench_id], "fired_at": b.fired_at.isoformat() if b.fired_at else None,
            "stage": r.stage, "due_date": r.due_date.isoformat(), "completed_on": r.completed_on.isoformat() if r.completed_on else None,
            "overdue": r.completed_on is None and r.due_date < clock.today(), "fragmentation_rating": r.fragmentation_rating,
            "oversize_observed": r.oversize_observed, "engineering_review_status": r.engineering_review_status,
            "has_proposal": bool((r.improvement_proposal or "").strip())}


@router.get("/reviews")
def reviews(db: Session = Depends(get_db)):
    benches = {x.id: x.code for x in db.scalars(select(m.Bench))}
    out = []
    for r in db.scalars(select(m.PostBlastReview)):
        b = db.get(m.Blast, r.blast_id)
        out.append(_row(db, b, r, benches))
    out.sort(key=lambda x: x["fired_at"] or "", reverse=True)
    return {"stages": STAGES, "reviews": out}


@router.get("/reviews/{blast_id}")
def review_detail(blast_id: int, db: Session = Depends(get_db)):
    b, r = _review(db, blast_id)
    people = {p.id: p.full_name for p in db.scalars(select(m.Personnel))}
    bench = db.get(m.Bench, b.bench_id)
    return {**_row(db, b, r, {bench.id: bench.code}), "review_id": r.id, "rock_type": bench.rock_type, "approved_plan_ref": b.approved_plan_ref,
            "stages": STAGES, "next_requirements": requirements(db, b, r),
            "fields": {f: getattr(r, f) for f in TEXT_FIELDS}, "engineering_reviewer": r.engineering_reviewer,
            "prepared_by": people.get(r.prepared_by_id), "collected": collected(db, b),
            "notice": _('Technical recommendations are proposals only and require review by a qualified engineer.')}


class ReviewIn(BaseModel):
    plan_compliance: str | None = Field(None, max_length=2000)
    fragmentation_observation: str | None = Field(None, max_length=2000)
    fragmentation_rating: int | None = Field(None, ge=1, le=5)
    oversize_observed: bool | None = None
    geology_observation: str | None = Field(None, max_length=2000)
    operational_deviations: str | None = Field(None, max_length=2000)
    lessons_learned: str | None = Field(None, max_length=2000)
    improvement_proposal: str | None = Field(None, max_length=2000)


@router.patch("/reviews/{blast_id}")
def update_review(blast_id: int, body: ReviewIn, db: Session = Depends(get_db), user: str = Depends(require("postblast.edit"))):
    b, r = _review(db, blast_id)
    if r.stage == "COMPLETED":
        raise HTTPException(409, _('Review completed — locked'))
    changes = {}
    for k, v in body.model_dump(exclude_unset=True).items():
        if getattr(r, k) != v:
            changes[k] = {"before": getattr(r, k), "after": v}
            setattr(r, k, v)
    if "improvement_proposal" in changes:
        r.engineering_review_status = "PENDING" if (r.improvement_proposal or "").strip() else "NOT_REQUIRED"
        r.engineering_reviewer = None
    record(db, "post_blast_review", r.id, "UPDATE", user, changes)
    db.commit()
    return {"updated": list(changes)}


@router.post("/reviews/{blast_id}/advance")
def advance(blast_id: int, db: Session = Depends(get_db), user: str = Depends(require("postblast.edit"))):
    b, r = _review(db, blast_id)
    if r.stage == "COMPLETED":
        raise HTTPException(409, _('Already completed'))
    unmet = requirements(db, b, r)
    if unmet:
        raise HTTPException(409, {"message": _('Requirements not met'), "unmet": unmet})
    before = r.stage
    r.stage = STAGES[STAGES.index(r.stage) + 1]
    if r.stage == "COMPLETED":
        r.completed_on = clock.today()
    record(db, "post_blast_review", r.id, "STATUS", user, {"from": before, "to": r.stage})
    db.commit()
    return {"stage": r.stage}


class EngReviewIn(BaseModel):
    reviewer: str = Field(..., min_length=3, max_length=120)
    decision: str = Field(..., pattern="^(ACCEPTED|ACCEPTED_WITH_CHANGES|NOT_ACCEPTED)$")
    comment: str = Field(..., min_length=5, max_length=1000)


@router.post("/reviews/{blast_id}/engineering-review")
def engineering_review(blast_id: int, body: EngReviewIn, db: Session = Depends(get_db), user: str = Depends(require("postblast.review"))):
    b, r = _review(db, blast_id)
    if not (r.improvement_proposal or "").strip():
        raise HTTPException(409, _('No improvement proposal to review'))
    r.engineering_review_status = "REVIEWED"
    r.engineering_reviewer = f"{body.reviewer} — {body.decision.replace('_', ' ').lower()}: {body.comment}"[:120]
    record(db, "post_blast_review", r.id, "STATUS", user, {"engineering_review": body.model_dump(), "at": datetime.now().isoformat()})
    db.commit()
    return {"engineering_review_status": r.engineering_review_status}


@router.get("/compare")
def compare(blasts: str = Query(..., description="Comma-separated blast ids (2–4)"), db: Session = Depends(get_db)):
    ids = [int(x) for x in blasts.split(",") if x.strip().isdigit()]
    if not 2 <= len(ids) <= 4:
        raise HTTPException(422, _('Select 2 to 4 blasts'))
    out = []
    for i in ids:
        b, r = _review(db, i)
        bench = db.get(m.Bench, b.bench_id)
        c = collected(db, b)
        valid = [v for v in c["vibration"] if v["ppv_mm_s"] is not None and v["quality"] == "VALID"]
        out.append({"blast_id": b.id, "blast": b.code, "bench": bench.code, "rock_type": bench.rock_type,
                    "fired": b.fired_at.date().isoformat() if b.fired_at else None, "holes": c["drillholes"]["holes"],
                    "deviation_rate_pct": c["drillholes"]["deviation_rate_pct"], "avg_toe_deviation_m": c["drillholes"]["avg_toe_deviation_m"],
                    "water_holes": c["drillholes"]["water_holes"],
                    "max_ppv_mm_s": max((v["ppv_mm_s"] for v in valid), default=None),
                    "exceedances": sum(1 for v in c["vibration"] if v["compliance"] == "EXCEEDANCE"),
                    "fragmentation_rating": r.fragmentation_rating, "oversize_observed": r.oversize_observed,
                    "delay_hours": round(sum(d["hours"] for d in c["delays"]), 1),
                    "tonnes_variance_pct": c["production"]["variance_pct"],
                    "face_within_tolerance_pct": next((x["within_tolerance_pct"] for x in c["survey_comparisons"]), None),
                    "stage": r.stage})
    return out
