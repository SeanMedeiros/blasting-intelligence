"""Module 06 — Explosives product quality laboratory (QA/QC).

Acceptance limits are never hard-coded: each result is evaluated against the configurable
reference_limit in force, and a snapshot of that limit is stored with the result.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import clock
from ..db import get_db
from ..services.audit import limit, record
from ..services.codes import next_code
from ..services.security import require
from ..i18n import S_, _

router = APIRouter(prefix="/api/v1/lab", tags=["Product laboratory"])

UNITS = {"VISCOSITY": "mPa·s", "DENSITY": "g/cm³", "VOD": "m/s", "FLOWABILITY": "s", "NOX": "ppm"}
INSTRUMENT_TYPE = {"VISCOSITY": "VISCOMETER", "DENSITY": "DENSITY", "VOD": "VOD", "FLOWABILITY": "FLOWABILITY", "NOX": "NOX"}


def _calib_status(ins: m.Instrument, on: date | None = None) -> dict:
    on = on or clock.today()
    if not ins.calibrations:
        return {"status": "NO_RECORD", "valid_until": None}
    last = max(ins.calibrations, key=lambda c: c.valid_until)
    st = "EXPIRED" if last.valid_until < on else ("DUE_SOON" if last.valid_until <= on + timedelta(days=30) else "VALID")
    return {"status": st, "valid_until": last.valid_until.isoformat(), "last_calibrated": last.calibrated_on.isoformat(),
            "certificate": last.certificate_ref, "performed_by": last.performed_by}


def _lookups(db: Session):
    return ({p.id: p.full_name for p in db.scalars(select(m.Personnel))},
            {i.id: i for i in db.scalars(select(m.Instrument))},
            {b.id: b for b in db.scalars(select(m.ProductBatch))},
            {b.id: b.code for b in db.scalars(select(m.Blast))})


def _test_row(t: m.LabTest, people, instr, batches, blasts) -> dict:
    b = batches.get(t.batch_id)
    return {"id": t.id, "code": t.code, "test_type": t.test_type, "tested_at": t.tested_at.isoformat(),
            "batch": b.code if b else None, "product": b.product_code if b else ("G-200" if t.blast_id else None),
            "blast": blasts.get(t.blast_id), "instrument": instr[t.instrument_id].code, "calibration_valid": t.calibration_valid,
            "technician": people.get(t.technician_id), "value": t.value, "unit": t.unit, "limit_min": t.limit_min, "limit_max": t.limit_max,
            "result": t.result, "data_quality": t.data_quality, "test_conditions": t.test_conditions,
            "sample_temperature_c": t.sample_temperature_c, "approved_test_ref": t.approved_test_ref, "notes": t.notes}


@router.get("/tests")
def list_tests(test_type: str | None = None, product: str | None = None, result: str | None = None,
               start: date | None = None, end: date | None = None, db: Session = Depends(get_db)):
    lk = _lookups(db)
    q = select(m.LabTest).order_by(m.LabTest.tested_at.desc())
    if test_type:
        q = q.where(m.LabTest.test_type == test_type)
    if result:
        q = q.where(m.LabTest.result == result)
    if start:
        q = q.where(m.LabTest.tested_at >= datetime.combine(start, datetime.min.time()))
    if end:
        q = q.where(m.LabTest.tested_at < datetime.combine(end + timedelta(days=1), datetime.min.time()))
    rows = [_test_row(t, *lk) for t in db.scalars(q)]
    return [r for r in rows if not product or r["product"] == product]


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    since = datetime.combine(clock.today() - timedelta(days=30), datetime.min.time())
    tests = db.scalars(select(m.LabTest).where(m.LabTest.tested_at >= since)).all()
    by_type = defaultdict(Counter)
    for t in tests:
        by_type[t.test_type][t.result] += 1
    instr = [i for i in db.scalars(select(m.Instrument)) if i.instrument_type in INSTRUMENT_TYPE.values()]
    ncs = db.scalars(select(m.NonConformance).order_by(m.NonConformance.raised_on.desc())).all()
    tests_by_id = {t.id: t for t in db.scalars(select(m.LabTest).where(m.LabTest.id.in_([n.lab_test_id for n in ncs if n.lab_test_id])))}
    batches = {b.id: b for b in db.scalars(select(m.ProductBatch))}
    return {
        "period_days": 30, "tests": len(tests),
        "by_type": {k: dict(v) for k, v in by_type.items()},
        "calibration_invalid_tests": sum(1 for t in tests if not t.calibration_valid),
        "instruments": [{"id": i.id, "code": i.code, "name": i.name, "type": i.instrument_type, "serial": i.serial_number,
                         "location": i.location, **_calib_status(i)} for i in instr],
        "nonconformances": [{"id": n.id, "code": n.code, "raised_on": n.raised_on.isoformat(), "description": n.description,
                             "disposition": n.disposition, "status": n.status,
                             "test": tests_by_id[n.lab_test_id].code if n.lab_test_id in tests_by_id else None,
                             "batch": batches[tests_by_id[n.lab_test_id].batch_id].code
                             if n.lab_test_id in tests_by_id and tests_by_id[n.lab_test_id].batch_id else None} for n in ncs],
        "batches_on_hold": [{"code": b.code, "product": b.product_code, "status": b.status, "produced_on": b.produced_on.isoformat()}
                            for b in batches.values() if b.status in ("QUARANTINE", "PENDING_TESTS")],
    }


@router.get("/trend")
def trend(test_type: str, product: str, db: Session = Depends(get_db)):
    rows = [r for r in list_tests(test_type=test_type, product=product, db=db)]
    rows.reverse()
    lim = limit(db, test_type, product)
    return {"test_type": test_type, "product": product, "unit": UNITS.get(test_type),
            "limit": {"min": lim.min_value, "max": lim.max_value, "source": lim.source_document,
                      "is_demo_placeholder": lim.is_demo_placeholder} if lim else None,
            "points": [{"code": r["code"], "date": r["tested_at"][:10], "value": r["value"], "result": r["result"],
                        "data_quality": r["data_quality"], "batch": r["batch"] or r["blast"]} for r in rows if r["value"] is not None]}


@router.get("/batches/{code}")
def batch_trace(code: str, db: Session = Depends(get_db)):
    b = db.scalars(select(m.ProductBatch).where(m.ProductBatch.code == code)).first()
    if b is None:
        raise HTTPException(404, _('Batch not found'))
    lk = _lookups(db)
    tests = [_test_row(t, *lk) for t in db.scalars(select(m.LabTest).where(m.LabTest.batch_id == b.id).order_by(m.LabTest.tested_at))]
    ncs = db.scalars(select(m.NonConformance).where(m.NonConformance.lab_test_id.in_([t["id"] for t in tests]))).all()
    moves = db.scalars(select(m.InventoryMovement).where(m.InventoryMovement.batch_id == b.id)).all()
    return {"code": b.code, "product_code": b.product_code, "product_name": b.product_name, "produced_on": b.produced_on.isoformat(),
            "quantity": b.quantity, "unit": b.unit, "status": b.status, "tests": tests,
            "nonconformances": [{"code": n.code, "description": n.description, "status": n.status, "disposition": n.disposition} for n in ncs],
            "inventory_movements": [{"type": x.movement_type, "quantity": x.quantity, "unit": x.unit, "at": x.recorded_at.isoformat(),
                                     "document_ref": x.document_ref} for x in moves]}


class TestIn(BaseModel):
    test_type: str = Field(..., pattern="^(VISCOSITY|DENSITY|VOD|FLOWABILITY|NOX)$")
    batch_code: str | None = None
    blast_code: str | None = None
    instrument_id: int
    technician_id: int
    value: float
    tested_at: datetime | None = None
    test_conditions: str | None = Field(None, max_length=500)
    sample_temperature_c: float | None = Field(None, ge=-40, le=80)
    approved_test_ref: str | None = Field(None, max_length=80)
    data_quality: str = Field("VALID", pattern="^(VALID|QUESTIONABLE|INVALID)$")
    notes: str | None = Field(None, max_length=1000)


@router.post("/tests", status_code=201)
def record_test(body: TestIn, db: Session = Depends(get_db), user: str = Depends(require("lab.test"))):
    batch = blast = None
    if body.batch_code:
        batch = db.scalars(select(m.ProductBatch).where(m.ProductBatch.code == body.batch_code)).first()
        if batch is None:
            raise HTTPException(422, _('Unknown batch'))
    if body.blast_code:
        blast = db.scalars(select(m.Blast).where(m.Blast.code == body.blast_code)).first()
        if blast is None:
            raise HTTPException(422, _('Unknown blast'))
    if not batch and not blast:
        raise HTTPException(422, _('A product batch or a blast (field / VOD / NOx test) is required'))
    if body.test_type in ("VOD", "NOX") and not body.approved_test_ref:
        raise HTTPException(422, _('VOD and NOx tests require the approved test reference'))
    ins = db.get(m.Instrument, body.instrument_id)
    if ins is None or ins.instrument_type != INSTRUMENT_TYPE[body.test_type]:
        raise HTTPException(422, _('Instrument must be of type {v}', v=INSTRUMENT_TYPE[body.test_type]))
    tech = db.get(m.Personnel, body.technician_id)
    if tech is None:
        raise HTTPException(422, _('Unknown technician'))
    if body.value < 0:
        raise HTTPException(422, _('Measured value cannot be negative'))
    when = body.tested_at or clock.now()
    if when.date() > clock.today() + timedelta(days=1):
        raise HTTPException(422, _('Test date cannot be in the future'))
    cal_ok = any(c.calibrated_on <= when.date() <= c.valid_until for c in ins.calibrations)
    product = batch.product_code if batch else "G-200"
    lim = limit(db, body.test_type, product)
    quality = body.data_quality if cal_ok else "QUESTIONABLE"
    result, reasons = "NOT_EVALUATED", []
    if not cal_ok:
        reasons.append(_('{code} calibration not valid on {v} — result not evaluated', code=ins.code, v=when.date()))
    elif quality != "VALID":
        reasons.append(_('Data quality {quality} — result not evaluated', quality=quality))
    elif lim is None:
        reasons.append(_('No reference limit configured for this product/test — result not evaluated'))
    else:
        ok = (lim.min_value is None or body.value >= lim.min_value) and (lim.max_value is None or body.value <= lim.max_value)
        result = "PASS" if ok else "FAIL"
        reasons.append(_("Compared with configured limit {min}–{max} {unit}", min=lim.min_value, max=lim.max_value, unit=lim.unit) +
                       (" (DEMO PLACEHOLDER)" if lim.is_demo_placeholder else ""))
    t = m.LabTest(code=next_code(db, m.LabTest, "LT", when.date(), 5), batch_id=batch.id if batch else None, blast_id=blast.id if blast else None,
                  test_type=body.test_type, instrument_id=ins.id, tested_at=when, technician_id=tech.id, value=body.value,
                  unit=UNITS[body.test_type], test_conditions=body.test_conditions, sample_temperature_c=body.sample_temperature_c,
                  approved_test_ref=body.approved_test_ref, data_quality=quality, calibration_valid=cal_ok,
                  limit_id=lim.id if lim else None, limit_min=lim.min_value if lim else None, limit_max=lim.max_value if lim else None,
                  result=result, notes=body.notes)
    db.add(t)
    db.flush()
    record(db, "lab_test", t.id, "CREATE", user, {**body.model_dump(mode="json"), "result": result})
    nc_code = None
    if result == "FAIL":
        nc = m.NonConformance(code=next_code(db, m.NonConformance, "NC", when.date(), 3), lab_test_id=t.id, raised_on=when.date(), status="OPEN",
                              description=S_("{product} {test} {value} {unit} outside configured specification.", product=product, test=body.test_type.lower(), value=body.value, unit=UNITS[body.test_type]))
        db.add(nc)
        db.flush()
        nc_code = nc.code
        reasons.append(_('Non-conformance {code} opened', code=nc.code))
        if batch:
            batch.status = "QUARANTINE"
            reasons.append(_('Batch {code} placed on QC hold pending disposition by the QC lead', code=batch.code))
        record(db, "nonconformance", nc.id, "CREATE", user, {"test": t.code})
    db.commit()
    return {"id": t.id, "code": t.code, "result": result, "data_quality": quality, "reasons": reasons, "nonconformance": nc_code}


class DispositionIn(BaseModel):
    disposition: str = Field(..., pattern="^(RETEST|QUARANTINE|REJECT|USE_AS_IS_ENGINEERING)$")
    close: bool = False
    closure_note: str | None = Field(None, max_length=1000)
    decided_by: str = Field(..., min_length=3, max_length=120)


@router.patch("/nonconformances/{nid}")
def disposition(nid: int, body: DispositionIn, db: Session = Depends(get_db), user: str = Depends(require("lab.disposition"))):
    nc = db.get(m.NonConformance, nid)
    if nc is None:
        raise HTTPException(404, _('Non-conformance not found'))
    if nc.status == "CLOSED":
        raise HTTPException(409, _('Non-conformance already closed'))
    if body.close and not (body.closure_note or "").strip():
        raise HTTPException(422, _('Closure requires a note describing the evidence'))
    before = {"disposition": nc.disposition, "status": nc.status}
    nc.disposition = body.disposition
    if body.close:
        nc.status = "CLOSED"
        nc.description += f" | Closed by {body.decided_by}: {body.closure_note}"
        t = db.get(m.LabTest, nc.lab_test_id) if nc.lab_test_id else None
        if t and t.batch_id:
            b = db.get(m.ProductBatch, t.batch_id)
            b.status = "REJECTED" if body.disposition == "REJECT" else ("RELEASED" if body.disposition == "USE_AS_IS_ENGINEERING" else b.status)
    record(db, "nonconformance", nc.id, "UPDATE", user, {"before": before, "after": body.model_dump()})
    db.commit()
    return {"id": nc.id, "status": nc.status, "disposition": nc.disposition}
