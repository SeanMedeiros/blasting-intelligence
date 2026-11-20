"""Module 05 — Blasting operations monitoring, and Module 08 — Electronic detonator traceability.

The status workflow records what happened under company procedure. The AUTHORIZED status
only records the reference of an authorization issued outside the software by the
competent person; the software never authorizes blasting or declares an area safe.
No loading quantities, stemming instructions, detonator programming, connection or
firing information is generated or stored.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import clock
from ..db import get_db
from ..services.audit import record
from ..services.security import permissions_for, require

router = APIRouter(prefix="/api/v1", tags=["Blasting operations & detonator traceability"])

FLOW = ["PLANNED", "IN_PREPARATION", "UNDER_INSPECTION", "AUTHORIZED", "IN_PROGRESS", "AWAITING_VERIFICATION", "COMPLETED", "CLOSED"]
from ..services.templates import auth_names, is_auth  # noqa: E402
from ..i18n import S_, _


def _now() -> datetime:
    return clock.now()


def _blast(db: Session, bid: int) -> m.Blast:
    b = db.get(m.Blast, bid)
    if b is None:
        raise HTTPException(404, _('Blast not found'))
    return b


def _inventory_balance(db: Session, b: m.Blast) -> dict:
    mv = db.scalars(select(m.InventoryMovement).where(m.InventoryMovement.blast_id == b.id)).all()
    tot = defaultdict(float)
    for x in mv:
        tot[x.movement_type] += x.quantity
    bal = round(tot["RECEIVED"] - tot["USED"] - tot["RETURNED"], 3)
    return {"received": round(tot["RECEIVED"], 3), "used": round(tot["USED"], 3), "returned": round(tot["RETURNED"], 3),
            "balance": bal, "reconciled": bool(mv) and abs(bal) < 1e-6, "unit": mv[0].unit if mv else "t"}


def requirements(db: Session, b: m.Blast, target: str) -> list[str]:
    """Unmet conditions to move blast b to target. Empty list = transition allowed."""
    unmet: list[str] = []
    cur = FLOW.index(b.status)
    if target not in FLOW or FLOW.index(target) != cur + 1:
        return [_("Transition {current} → {target} is not part of the workflow (next step: {next})", current=b.status, target=target,
                  next=FLOW[cur + 1] if cur + 1 < len(FLOW) else "—")]
    cps = db.scalars(select(m.BlastCheckpoint).where(m.BlastCheckpoint.blast_id == b.id)).all()

    def open_cps(stage, exclude=()):
        return [c.name for c in cps if c.stage == stage and c.required and not c.completed and c.name not in exclude]

    pattern = db.get(m.DrillPattern, b.pattern_id)
    if target == "IN_PREPARATION":
        if not pattern.drilled_on:
            unmet.append(_('Pattern has not been drilled'))
    elif target == "UNDER_INSPECTION":
        unmet += [_("Checkpoint open: {name}", name=n) for n in open_cps("PREPARATION")]
        unmeasured = [h.hole_code for h in pattern.holes if not h.measurements]
        if unmeasured:
            unmet.append(_('{n} hole(s) not verified', n=len(unmeasured)))
        bad = [h.hole_code for h in pattern.holes if h.measurements and h.measurements[-1].inspection_status in ("OUT_OF_TOLERANCE", "REDRILL_REQUIRED")]
        if bad:
            unmet.append(_('{n} hole(s) out of tolerance without resolution or engineering acceptance: {v}', n=len(bad), v=', '.join(bad[:6])))
    elif target == "AUTHORIZED":
        unmet += [_("Checkpoint open: {name}", name=n) for n in open_cps("LOADING") + open_cps("PRE_BLAST", exclude=auth_names())]
        insp = db.scalars(select(m.Inspection).where(m.Inspection.blast_id == b.id, m.Inspection.inspection_type == "PRE_BLAST")).first()
        if not insp or insp.status != "COMPLETED":
            unmet.append(_('Pre-blast verification checklist not completed'))
        elif any(i.result not in ("YES", "NA") for i in insp.items):
            unmet.append(_('Pre-blast checklist has items answered NO or not recorded'))
    elif target == "AWAITING_VERIFICATION":
        pass
    elif target == "COMPLETED":
        unmet += [_("Checkpoint open: {name}", name=n) for n in open_cps("POST_BLAST")]
        inv = _inventory_balance(db, b)
        if not inv["reconciled"]:
            unmet.append(_('Product inventory not reconciled (balance {balance} {unit})', balance=inv['balance'], unit=inv['unit']))
    elif target == "CLOSED":
        r = db.scalars(select(m.PostBlastReview).where(m.PostBlastReview.blast_id == b.id)).first()
        if not r or r.stage != "COMPLETED":
            unmet.append(_('Post-blast review not completed'))
        det = db.scalars(select(m.DetonatorRecord).where(m.DetonatorRecord.blast_id == b.id)).first()
        if not det or det.documentation_status != "COMPLETE":
            unmet.append(_('Detonator traceability documentation not verified'))
        exc = db.scalars(select(m.TraceabilityException).join(m.DetonatorRecord).where(
            m.DetonatorRecord.blast_id == b.id, m.TraceabilityException.status == "OPEN")).all()
        if exc:
            unmet.append(_('{n} open traceability exception(s)', n=len(exc)))
    return unmet


@router.get("/blasts")
def board(db: Session = Depends(get_db)):
    benches = {x.id: x.code for x in db.scalars(select(m.Bench))}
    wos = {w.id: w.code for w in db.scalars(select(m.WorkOrder))}
    cps = defaultdict(lambda: [0, 0])
    for c in db.scalars(select(m.BlastCheckpoint)):
        cps[c.blast_id][1] += 1
        cps[c.blast_id][0] += c.completed
    out = []
    for b in db.scalars(select(m.Blast).order_by(m.Blast.planned_date.desc())):
        nxt = FLOW[FLOW.index(b.status) + 1] if b.status != "CLOSED" else None
        out.append({"id": b.id, "code": b.code, "status": b.status, "planned_date": b.planned_date.isoformat(), "bench": benches[b.bench_id],
                    "work_order": wos[b.work_order_id], "approved_plan_ref": b.approved_plan_ref, "authorization_ref": b.authorization_ref,
                    "checkpoints_done": cps[b.id][0], "checkpoints_total": cps[b.id][1], "next_status": nxt,
                    "blocked": bool(nxt and requirements(db, b, nxt)) if b.status not in ("CLOSED",) and b.planned_date >= clock.today().replace(day=1) else None})
    return {"flow": FLOW, "blasts": out}


@router.get("/blasts/{bid}")
def blast_detail(bid: int, db: Session = Depends(get_db)):
    b = _blast(db, bid)
    people = {p.id: p.full_name for p in db.scalars(select(m.Personnel))}
    wo = db.get(m.WorkOrder, b.work_order_id)
    pattern = db.get(m.DrillPattern, b.pattern_id)
    holes = pattern.holes
    meas = [h for h in holes if h.measurements]
    insp = db.scalars(select(m.Inspection).where(m.Inspection.blast_id == b.id, m.Inspection.inspection_type == "PRE_BLAST")).first()
    review = db.scalars(select(m.PostBlastReview).where(m.PostBlastReview.blast_id == b.id)).first()
    vib = db.scalars(select(m.VibrationEvent).where(m.VibrationEvent.blast_id == b.id)).all()
    st = {s.id: s.code for s in db.scalars(select(m.MonitorStation))}
    surveys = db.scalars(select(m.Survey).where(m.Survey.blast_id == b.id)).all()
    delays = db.scalars(select(m.DelayEvent).where(m.DelayEvent.work_order_id == wo.id)).all()
    nxt = FLOW[FLOW.index(b.status) + 1] if b.status != "CLOSED" else None
    return {
        "id": b.id, "code": b.code, "status": b.status, "flow": FLOW, "next_status": nxt,
        "next_requirements": requirements(db, b, nxt) if nxt else [],
        "planned_date": b.planned_date.isoformat(), "fired_at": b.fired_at.isoformat() if b.fired_at else None,
        "bench": db.get(m.Bench, b.bench_id).code, "pattern": pattern.code, "pattern_id": pattern.id,
        "work_order": {"code": wo.code, "title": wo.title, "status": wo.status, "engineering_forecast_ref": wo.engineering_forecast_ref,
                       "forecast_tonnes": wo.forecast_tonnes, "actual_tonnes": wo.actual_tonnes},
        "approved_plan_ref": b.approved_plan_ref, "supervisor": people.get(b.supervisor_id), "blaster": people.get(b.blaster_id),
        "equipment": b.equipment_codes,
        "authorization": {"ref": b.authorization_ref, "by": b.authorized_by, "role": b.authorized_role,
                          "at": b.authorized_at.isoformat() if b.authorized_at else None},
        "checkpoints": [{"id": c.id, "stage": c.stage, "name": c.name, "required": c.required, "completed": c.completed,
                         "completed_by": c.completed_by, "completed_at": c.completed_at.isoformat() if c.completed_at else None,
                         "evidence_ref": c.evidence_ref, "is_authorization": is_auth(c.name)}
                        for c in db.scalars(select(m.BlastCheckpoint).where(m.BlastCheckpoint.blast_id == b.id).order_by(m.BlastCheckpoint.id))],
        "history": [{"from": h.from_status, "to": h.to_status, "at": h.changed_at.isoformat(), "by": h.changed_by, "note": h.note}
                    for h in db.scalars(select(m.BlastStatusHistory).where(m.BlastStatusHistory.blast_id == b.id).order_by(m.BlastStatusHistory.changed_at))],
        "inventory": {**_inventory_balance(db, b), "movements": [
            {"id": x.id, "type": x.movement_type, "product": x.product_name, "quantity": x.quantity, "unit": x.unit,
             "at": x.recorded_at.isoformat(), "by": x.recorded_by, "document_ref": x.document_ref}
            for x in db.scalars(select(m.InventoryMovement).where(m.InventoryMovement.blast_id == b.id).order_by(m.InventoryMovement.recorded_at))]},
        "pre_blast_inspection": {"id": insp.id, "code": insp.code, "status": insp.status,
                                 "inspected_at": insp.inspected_at.isoformat() if insp.inspected_at else None,
                                 "inspector": people.get(insp.inspector_id),
                                 "items": [{"id": i.id, "seq": i.seq, "text": i.text, "result": i.result, "comment": i.comment}
                                           for i in sorted(insp.items, key=lambda i: i.seq)]} if insp else None,
        "drillholes": {"holes": len(holes), "measured": len(meas),
                       "out_of_tolerance": sum(1 for h in meas if h.measurements[-1].inspection_status != "WITHIN_TOLERANCE")},
        "surveys": [{"id": s.id, "code": s.code, "type": s.survey_type, "quality": s.quality_status} for s in surveys],
        "vibration": [{"id": e.id, "station": st[e.station_id], "ppv_mm_s": e.ppv_mm_s, "compliance": e.compliance, "quality": e.data_quality} for e in vib],
        "delays": [{"date": d.occurred_on.isoformat(), "category": d.category, "hours": d.hours, "description": d.description} for d in delays],
        "post_blast_review": {"stage": review.stage, "due_date": review.due_date.isoformat()} if review else None,
        "notice": _('Administrative and documentary records only. Authorization is issued outside this software under company procedure.'),
    }


class TransitionIn(BaseModel):
    to_status: str
    note: str | None = Field(None, max_length=1000)
    authorization_ref: str | None = Field(None, max_length=80)
    authorized_by: str | None = Field(None, max_length=120)
    authorized_role: str | None = Field(None, max_length=80)


@router.post("/blasts/{bid}/transition")
def transition(bid: int, body: TransitionIn, db: Session = Depends(get_db), user: str = Depends(require("blast.operate"))):
    b = _blast(db, bid)
    if body.to_status == "CLOSED" and "blast.close" not in permissions_for(getattr(user, "role", "")):
        raise HTTPException(403, _('Closing a blast record requires the blast.close permission (engineer or administrator)'))
    unmet = requirements(db, b, body.to_status)
    if body.to_status == "AUTHORIZED":
        for f in ("authorization_ref", "authorized_by", "authorized_role"):
            if not (getattr(body, f) or "").strip():
                unmet.append(_('{v} is required (authorization issued outside the software)', v=f.replace('_', ' ')))
    if unmet:
        raise HTTPException(409, {"message": _('Cannot move {code} to {to_status}', code=b.code, to_status=body.to_status), "unmet": unmet})
    now = _now()
    if body.to_status == "AUTHORIZED":
        b.authorization_ref, b.authorized_by, b.authorized_role, b.authorized_at = body.authorization_ref, body.authorized_by, body.authorized_role, now
        cp = db.scalars(select(m.BlastCheckpoint).where(m.BlastCheckpoint.blast_id == b.id, m.BlastCheckpoint.name.in_(auth_names()))).first()
        if cp:
            cp.completed, cp.completed_by, cp.completed_at, cp.evidence_ref = True, user, now, body.authorization_ref
    if body.to_status == "IN_PROGRESS":
        b.fired_at = now
        if not db.scalars(select(m.PostBlastReview).where(m.PostBlastReview.blast_id == b.id)).first():
            from ..config import POST_BLAST_REVIEW_DAYS

            db.add(m.PostBlastReview(blast_id=b.id, stage="DATA_COLLECTION", due_date=now.date() + timedelta(days=POST_BLAST_REVIEW_DAYS),
                                     engineering_review_status="NOT_REQUIRED"))
    if body.to_status == "CLOSED":
        b.closed_at = now
    db.add(m.BlastStatusHistory(blast_id=b.id, from_status=b.status, to_status=body.to_status, changed_at=now, changed_by=user,
                                note=body.note or (S_("Authorization issued externally under company procedure; reference recorded.")
                                                   if body.to_status == "AUTHORIZED" else None)))
    record(db, "blast", b.id, "STATUS", user, {"from": b.status, **body.model_dump()})
    b.status = body.to_status
    db.commit()
    return {"id": b.id, "status": b.status}


class CheckpointIn(BaseModel):
    evidence_ref: str = Field(..., min_length=2, max_length=120)


@router.post("/checkpoints/{cid}/complete")
def complete_checkpoint(cid: int, body: CheckpointIn, db: Session = Depends(get_db), user: str = Depends(require("blast.operate"))):
    c = db.get(m.BlastCheckpoint, cid)
    if c is None:
        raise HTTPException(404, _('Checkpoint not found'))
    if c.completed:
        raise HTTPException(409, _('Checkpoint already completed'))
    if is_auth(c.name):
        raise HTTPException(409, _('Recorded automatically with the AUTHORIZED status (external authorization reference)'))
    b = db.get(m.Blast, c.blast_id)
    if b.status == "CLOSED":
        raise HTTPException(409, _('Blast is closed'))
    c.completed, c.completed_by, c.completed_at, c.evidence_ref = True, user, _now(), body.evidence_ref
    record(db, "blast_checkpoint", c.id, "UPDATE", user, {"completed": True, "evidence_ref": body.evidence_ref})
    db.commit()
    return {"id": c.id, "completed": True}


class MovementIn(BaseModel):
    movement_type: str = Field(..., pattern="^(RECEIVED|USED|RETURNED)$")
    quantity: float = Field(..., gt=0, le=1000)
    document_ref: str = Field(..., min_length=2, max_length=80)
    product_name: str | None = Field(None, min_length=2, max_length=120)


@router.post("/blasts/{bid}/inventory", status_code=201)
def add_movement(bid: int, body: MovementIn, db: Session = Depends(get_db), user: str = Depends(require("blast.operate"))):
    """Administrative reconciliation entry (quantities as recorded on site documents)."""
    b = _blast(db, bid)
    if b.status in ("COMPLETED", "CLOSED"):
        raise HTTPException(409, _('Inventory is locked after completion'))
    bal = _inventory_balance(db, b)
    if body.movement_type in ("USED", "RETURNED") and body.quantity > bal["balance"] + 1e-9:
        raise HTTPException(422, _('Quantity exceeds the unreconciled balance ({balance} {unit})', balance=bal['balance'], unit=bal['unit']))
    product = (body.product_name or "").strip() or db.scalars(
        select(m.InventoryMovement.product_name).where(m.InventoryMovement.blast_id == b.id)
        .order_by(m.InventoryMovement.recorded_at.desc())).first()
    if not product:
        raise HTTPException(422, _('Product name is required for the first movement of a blast'))
    x = m.InventoryMovement(blast_id=b.id, product_name=product, movement_type=body.movement_type,
                            quantity=round(body.quantity, 3), unit="t", recorded_at=_now(), recorded_by=user, document_ref=body.document_ref)
    db.add(x)
    db.flush()
    record(db, "inventory_movement", x.id, "CREATE", user, body.model_dump())
    db.commit()
    return {"id": x.id, **_inventory_balance(db, b)}


class ChecklistIn(BaseModel):
    result: str = Field(..., pattern="^(YES|NO|NA)$")
    comment: str | None = Field(None, max_length=500)


@router.patch("/checklist-items/{iid}")
def set_item(iid: int, body: ChecklistIn, db: Session = Depends(get_db), user: str = Depends(require("blast.operate"))):
    it = db.get(m.ChecklistItem, iid)
    if it is None:
        raise HTTPException(404, _('Item not found'))
    if it.inspection.status == "COMPLETED":
        raise HTTPException(409, _('Inspection already completed'))
    if body.result == "NO" and not (body.comment or "").strip():
        raise HTTPException(422, _('A comment is required when an item is answered NO'))
    it.result, it.comment = body.result, body.comment
    record(db, "checklist_item", it.id, "UPDATE", user, body.model_dump())
    db.commit()
    return {"id": it.id, "result": it.result}


class InspectionCompleteIn(BaseModel):
    inspector_id: int


@router.post("/inspections/{iid}/complete")
def complete_inspection(iid: int, body: InspectionCompleteIn, db: Session = Depends(get_db), user: str = Depends(require("blast.operate"))):
    insp = db.get(m.Inspection, iid)
    if insp is None:
        raise HTTPException(404, _('Inspection not found'))
    if insp.status == "COMPLETED":
        raise HTTPException(409, _('Already completed'))
    missing = [i.seq for i in insp.items if i.result is None]
    if missing:
        raise HTTPException(422, _('Items not recorded: {missing}', missing=missing))
    if db.get(m.Personnel, body.inspector_id) is None:
        raise HTTPException(422, _('Unknown inspector'))
    insp.status, insp.inspected_at, insp.inspector_id = "COMPLETED", _now(), body.inspector_id
    no = [i.seq for i in insp.items if i.result == "NO"]
    insp.findings = S_("Items answered NO: {items}", items=no) if no else S_("All items YES/NA")
    record(db, "inspection", insp.id, "STATUS", user, {"status": "COMPLETED", "findings": insp.findings})
    db.commit()
    return {"id": insp.id, "status": insp.status, "findings": insp.findings}


# ------------------------------------------------------------------ Module 08 — detonator traceability
def _det_row(d: m.DetonatorRecord, blasts) -> dict:
    b = blasts[d.blast_id]
    unaccounted = None
    if d.units_used is not None and d.units_returned is not None:
        unaccounted = d.units_issued - d.units_used - d.units_returned
    return {"id": d.id, "blast": b.code, "blast_status": b.status, "planned_date": b.planned_date.isoformat(),
            "approved_plan_ref": b.approved_plan_ref, "inventory_lot_ref": d.inventory_lot_ref, "units_issued": d.units_issued,
            "units_used": d.units_used, "units_returned": d.units_returned, "unaccounted": unaccounted,
            "equipment_ref": d.equipment_ref, "authorized_personnel": d.authorized_personnel, "procedure_ref": d.procedure_ref,
            "inspection_status": d.inspection_status, "documentation_status": d.documentation_status,
            "verified_by": d.verified_by, "verified_at": d.verified_at.isoformat() if d.verified_at else None}


@router.get("/detonators")
def detonators(db: Session = Depends(get_db)):
    blasts = {b.id: b for b in db.scalars(select(m.Blast))}
    exc = defaultdict(list)
    for x in db.scalars(select(m.TraceabilityException)):
        exc[x.detonator_record_id].append({"id": x.id, "raised_at": x.raised_at.isoformat(), "description": x.description,
                                           "severity": x.severity, "status": x.status, "resolution": x.resolution})
    out = []
    for d in db.scalars(select(m.DetonatorRecord)):
        r = _det_row(d, blasts)
        r["exceptions"] = exc[d.id]
        out.append(r)
    out.sort(key=lambda r: r["planned_date"], reverse=True)
    return {"records": out, "notice": _('Administrative traceability only. This module contains no programming, wiring, connection or firing information.')}


@router.get("/detonators/{did}/audit")
def det_audit(did: int, db: Session = Depends(get_db)):
    d = db.get(m.DetonatorRecord, did)
    if d is None:
        raise HTTPException(404, _('Record not found'))
    exc_ids = [x.id for x in db.scalars(select(m.TraceabilityException).where(m.TraceabilityException.detonator_record_id == did))]
    logs = db.scalars(select(m.AuditLog).where(
        ((m.AuditLog.entity == "detonator_record") & (m.AuditLog.entity_id == did)) |
        ((m.AuditLog.entity == "traceability_exception") & (m.AuditLog.entity_id.in_(exc_ids or [-1])))).order_by(m.AuditLog.performed_at)).all()
    hist = db.scalars(select(m.BlastStatusHistory).where(m.BlastStatusHistory.blast_id == d.blast_id).order_by(m.BlastStatusHistory.changed_at)).all()
    events = [{"at": h.changed_at.isoformat(), "by": h.changed_by, "action": _("Blast status → {status}", status=h.to_status), "detail": h.note} for h in hist]
    if d.verified_at:
        events.append({"at": d.verified_at.isoformat(), "by": d.verified_by, "action": _('Documentation verified'), "detail": None})
    events += [{"at": a.performed_at.isoformat(), "by": a.performed_by, "action": f"{a.entity} {a.action}", "detail": str(a.changes)} for a in logs]
    return sorted(events, key=lambda e: e["at"])


class DetUpdateIn(BaseModel):
    units_used: int = Field(..., ge=0)
    units_returned: int = Field(..., ge=0)
    inspection_done: bool = True


@router.patch("/detonators/{did}")
def det_update(did: int, body: DetUpdateIn, db: Session = Depends(get_db), user: str = Depends(require("detonator.record"))):
    d = db.get(m.DetonatorRecord, did)
    if d is None:
        raise HTTPException(404, _('Record not found'))
    if d.documentation_status == "COMPLETE":
        raise HTTPException(409, _('Record verified — locked'))
    if body.units_used + body.units_returned > d.units_issued:
        raise HTTPException(422, _('Used + returned cannot exceed units issued'))
    before = {"units_used": d.units_used, "units_returned": d.units_returned}
    d.units_used, d.units_returned = body.units_used, body.units_returned
    d.inspection_status = "DONE" if body.inspection_done else "PENDING"
    diff = d.units_issued - d.units_used - d.units_returned
    if diff:
        db.add(m.TraceabilityException(detonator_record_id=d.id, raised_at=_now(), severity="HIGH", status="OPEN",
                                       description=S_("Reconciliation difference of {n} unit(s) (issued − used − returned ≠ 0). Report to QSSE per procedure.", n=diff)))
    record(db, "detonator_record", d.id, "UPDATE", user, {"before": before, "after": body.model_dump()})
    db.commit()
    return _det_row(d, {b.id: b for b in db.scalars(select(m.Blast))})


class VerifyIn(BaseModel):
    verified_by: str = Field(..., min_length=3, max_length=120)


@router.post("/detonators/{did}/verify")
def det_verify(did: int, body: VerifyIn, db: Session = Depends(get_db), user: str = Depends(require("detonator.verify"))):
    d = db.get(m.DetonatorRecord, did)
    if d is None:
        raise HTTPException(404, _('Record not found'))
    problems = []
    if d.units_used is None or d.units_returned is None:
        problems.append(_('Used / returned units not recorded'))
    elif d.units_issued - d.units_used - d.units_returned != 0:
        problems.append(_('Units not reconciled'))
    if d.inspection_status != "DONE":
        problems.append(_('Inspection not recorded'))
    if any(x.status == "OPEN" for x in db.scalars(select(m.TraceabilityException).where(m.TraceabilityException.detonator_record_id == d.id))):
        problems.append(_('Open exception(s)'))
    if problems:
        raise HTTPException(409, {"message": _('Cannot verify'), "unmet": problems})
    d.documentation_status, d.verified_by, d.verified_at = "COMPLETE", body.verified_by, _now()
    record(db, "detonator_record", d.id, "STATUS", user, {"documentation_status": "COMPLETE", "verified_by": body.verified_by})
    db.commit()
    return {"id": d.id, "documentation_status": d.documentation_status}


class ExceptionCloseIn(BaseModel):
    resolution: str = Field(..., min_length=10, max_length=1000)


@router.post("/traceability-exceptions/{xid}/close")
def close_exception(xid: int, body: ExceptionCloseIn, db: Session = Depends(get_db), user: str = Depends(require("detonator.verify"))):
    x = db.get(m.TraceabilityException, xid)
    if x is None:
        raise HTTPException(404, _('Exception not found'))
    if x.status == "CLOSED":
        raise HTTPException(409, _('Already closed'))
    x.status, x.resolution = "CLOSED", body.resolution
    record(db, "traceability_exception", x.id, "STATUS", user, {"status": "CLOSED", "resolution": body.resolution})
    db.commit()
    return {"id": x.id, "status": x.status}
