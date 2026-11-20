"""Operational records created from the interface: work orders, schedule, deliveries, drill patterns
(with the drillhole design imported from CSV), blasts and detonator issue records.

Scope reminder: patterns hold the APPROVED DESIGN geometry produced by the engineer's design software
(positions, planned depth, dip, azimuth). Loading parameters are referenced by document only; the
application never calculates or stores explosive quantities, loading, stemming, timing or firing data.
"""
from __future__ import annotations

import csv
import io
import math
import re
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from .. import models as m
from ..config import DEFAULT_LANGUAGE
from ..db import get_db
from ..services import templates as tpl
from ..services.audit import record
from ..services.codes import next_code
from ..services.security import Actor, require, signed_in
from ..i18n import N_, S_, _

router = APIRouter(prefix="/api/v1/ops", tags=["Operational records"])


# ----------------------------------------------------------------------------- helpers
def _unique(db: Session, model, code: str, label: str) -> str:
    label = _(label)
    code = code.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._\-/]{1,29}", code):
        raise HTTPException(422, _('{label} code: 2–30 characters, letters, digits and . _ - /', label=label))
    if db.scalars(select(model).where(model.code == code)).first():
        raise HTTPException(409, _('{label} code {code} already exists', label=label, code=code))
    return code


def _get(db: Session, model, rid: int | None, label: str, required: bool = True):
    label = _(label)
    if rid is None:
        if required:
            raise HTTPException(422, _('{label} is required', label=label))
        return None
    obj = db.get(model, rid)
    if obj is None:
        raise HTTPException(422, _('Unknown {label} {rid}', label=label, rid=rid))
    if getattr(obj, "active", True) is False:
        raise HTTPException(422, _('{label} {rid} is inactive', label=label, rid=rid))
    return obj


def _iso(d):
    return d.isoformat() if d else None


# ----------------------------------------------------------------------------- work orders
WO_TYPES = ("BLAST", "SURVEY_CAMPAIGN", "LAB_SAMPLING")
WO_FLOW = {"OPEN": ("IN_PROGRESS", "CANCELLED"), "IN_PROGRESS": ("COMPLETED", "CANCELLED"), "COMPLETED": (), "CANCELLED": ()}


class WorkOrderIn(BaseModel):
    code: str | None = Field(None, max_length=30)
    title: str = Field(..., min_length=3, max_length=200)
    area_id: int
    wo_type: str = "BLAST"
    engineering_forecast_ref: str | None = Field(None, max_length=80)
    planned_start: date
    planned_end: date
    forecast_tonnes: float | None = Field(None, ge=0, le=1e8)

    @model_validator(mode="after")
    def _check(self):
        if self.wo_type not in WO_TYPES:
            raise ValueError(_('wo_type must be one of {v}', v=', '.join(WO_TYPES)))
        if self.planned_end < self.planned_start:
            raise ValueError(_('planned_end must be on or after planned_start'))
        return self


@router.post("/work-orders", status_code=201)
def create_work_order(body: WorkOrderIn, db: Session = Depends(get_db), actor: Actor = Depends(require("planning.write"))):
    _get(db, m.Area, body.area_id, N_("area"))
    code = _unique(db, m.WorkOrder, body.code, N_("Work order")) if body.code else next_code(db, m.WorkOrder, "WO", body.planned_start)
    wo = m.WorkOrder(code=code, title=body.title.strip(), area_id=body.area_id, wo_type=body.wo_type, status="OPEN",
                     engineering_forecast_ref=body.engineering_forecast_ref, planned_start=body.planned_start,
                     planned_end=body.planned_end, forecast_tonnes=body.forecast_tonnes)
    db.add(wo)
    db.flush()
    record(db, "work_order", wo.id, "CREATE", actor, body.model_dump(mode="json") | {"code": code})
    db.commit()
    return {"id": wo.id, "code": wo.code, "status": wo.status}


class WorkOrderPatch(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=200)
    engineering_forecast_ref: str | None = Field(None, max_length=80)
    planned_start: date | None = None
    planned_end: date | None = None
    forecast_tonnes: float | None = Field(None, ge=0, le=1e8)
    actual_tonnes: float | None = Field(None, ge=0, le=1e8)
    status: str | None = None
    reason: str | None = Field(None, max_length=500)


@router.patch("/work-orders/{wid}")
def update_work_order(wid: int, body: WorkOrderPatch, db: Session = Depends(get_db), actor: Actor = Depends(require("planning.write"))):
    wo = db.get(m.WorkOrder, wid)
    if wo is None:
        raise HTTPException(404, _('Work order not found'))
    data = body.model_dump(exclude_unset=True)
    before = {k: getattr(wo, k) for k in data if hasattr(wo, k)}
    if "status" in data and data["status"] != wo.status:
        new = data["status"]
        if new not in WO_FLOW.get(wo.status, ()):
            raise HTTPException(409, _('Work order {code}: {status} → {new} is not allowed', code=wo.code, status=wo.status, new=new))
        if new == "CANCELLED":
            if not (body.reason or "").strip():
                raise HTTPException(422, _('A reason is required to cancel a work order'))
            live = db.scalars(select(m.Blast).where(m.Blast.work_order_id == wo.id, m.Blast.status.not_in(("PLANNED",)))).first()
            if live:
                raise HTTPException(409, _('Blast {code} has started — the work order cannot be cancelled', code=live.code))
            for it in db.scalars(select(m.ScheduleItem).where(m.ScheduleItem.work_order_id == wo.id, m.ScheduleItem.status != "DONE")):
                it.status = "CANCELLED"
        if new == "IN_PROGRESS" and not wo.actual_start:
            wo.actual_start = clock.today()
        if new == "COMPLETED":
            open_blast = db.scalars(select(m.Blast).where(m.Blast.work_order_id == wo.id, m.Blast.status.not_in(("COMPLETED", "CLOSED")))).first()
            if open_blast:
                raise HTTPException(409, _('Blast {code} is not completed', code=open_blast.code))
            wo.actual_end = clock.today()
        wo.status = new
    for k in ("title", "engineering_forecast_ref", "planned_start", "planned_end", "forecast_tonnes", "actual_tonnes"):
        if k in data:
            setattr(wo, k, data[k])
    if wo.planned_end < wo.planned_start:
        raise HTTPException(422, _('planned_end must be on or after planned_start'))
    record(db, "work_order", wo.id, "UPDATE", actor, {"before": {k: _iso(v) if isinstance(v, date) else v for k, v in before.items()},
                                                     "after": body.model_dump(mode="json", exclude_unset=True)})
    db.commit()
    return {"id": wo.id, "code": wo.code, "status": wo.status}


# ----------------------------------------------------------------------------- schedule
class ScheduleItemIn(BaseModel):
    activity: str
    planned_date: date
    resources: str | None = Field(None, max_length=200)
    responsible_id: int | None = None

    @field_validator("activity")
    @classmethod
    def _act(cls, v):
        if v not in tpl.ACTIVITIES:
            raise ValueError(_('activity must be one of {v}', v=', '.join(tpl.ACTIVITIES)))
        return v


def _open_wo(db: Session, wid: int) -> m.WorkOrder:
    wo = db.get(m.WorkOrder, wid)
    if wo is None:
        raise HTTPException(404, _('Work order not found'))
    if wo.status in ("COMPLETED", "CANCELLED"):
        raise HTTPException(409, _('Work order {code} is {v}', code=wo.code, v=wo.status.lower()))
    return wo


@router.post("/work-orders/{wid}/schedule-items", status_code=201)
def add_schedule_item(wid: int, body: ScheduleItemIn, db: Session = Depends(get_db), actor: Actor = Depends(require("planning.write"))):
    wo = _open_wo(db, wid)
    _get(db, m.Personnel, body.responsible_id, N_("responsible person"), required=False)
    it = m.ScheduleItem(work_order_id=wo.id, activity=body.activity, planned_date=body.planned_date, status="PLANNED",
                        resources=body.resources, responsible_id=body.responsible_id)
    db.add(it)
    db.flush()
    record(db, "schedule_item", it.id, "CREATE", actor, body.model_dump(mode="json") | {"work_order": wo.code})
    db.commit()
    return {"id": it.id}


class StandardIn(BaseModel):
    blast_date: date
    responsible_id: int | None = None


@router.post("/work-orders/{wid}/standard-schedule", status_code=201)
def standard_schedule(wid: int, body: StandardIn, db: Session = Depends(get_db), actor: Actor = Depends(require("planning.write"))):
    """Creates the site's standard activity sequence around the blast date (template in Settings)."""
    wo = _open_wo(db, wid)
    _get(db, m.Personnel, body.responsible_id, N_("responsible person"), required=False)
    existing = {(i.activity) for i in db.scalars(select(m.ScheduleItem).where(m.ScheduleItem.work_order_id == wo.id,
                                                                               m.ScheduleItem.status != "CANCELLED"))}
    created = []
    for act, off in tpl.get(db, "standard_schedule"):
        if act in existing:
            continue
        it = m.ScheduleItem(work_order_id=wo.id, activity=act, planned_date=body.blast_date + timedelta(days=off), status="PLANNED",
                            responsible_id=body.responsible_id)
        db.add(it)
        created.append(act)
    db.flush()
    record(db, "work_order", wo.id, "UPDATE", actor, {"standard_schedule": created, "blast_date": body.blast_date.isoformat()})
    db.commit()
    return {"created": created, "skipped_existing": sorted(existing)}


class CancelIn(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500)


@router.post("/schedule-items/{iid}/cancel")
def cancel_schedule_item(iid: int, body: CancelIn, db: Session = Depends(get_db), actor: Actor = Depends(require("planning.write"))):
    it = db.get(m.ScheduleItem, iid)
    if it is None:
        raise HTTPException(404, _('Activity not found'))
    if it.status in ("DONE", "CANCELLED"):
        raise HTTPException(409, _('Activity is already {v}', v=it.status.lower()))
    it.status = "CANCELLED"
    record(db, "schedule_item", it.id, "STATUS", actor, {"to": "CANCELLED", "reason": body.reason})
    db.commit()
    return {"id": it.id, "status": it.status}


# ----------------------------------------------------------------------------- deliveries
class DeliveryIn(BaseModel):
    code: str | None = Field(None, max_length=30)
    product_name: str = Field(..., min_length=2, max_length=120)
    destination_area_id: int
    planned_date: date
    planned_qty: float = Field(..., gt=0, le=1e6)
    unit: str = Field("t", pattern="^(t|kg|units)$")
    document_ref: str | None = Field(None, max_length=80)


@router.post("/deliveries", status_code=201)
def create_delivery(body: DeliveryIn, db: Session = Depends(get_db), actor: Actor = Depends(require("planning.write"))):
    _get(db, m.Area, body.destination_area_id, N_("area"))
    code = _unique(db, m.Delivery, body.code, N_("Delivery")) if body.code else next_code(db, m.Delivery, "DL", body.planned_date, 3)
    d = m.Delivery(code=code, product_name=body.product_name.strip(), destination_area_id=body.destination_area_id,
                   planned_date=body.planned_date, planned_qty=body.planned_qty, unit=body.unit, status="SCHEDULED",
                   document_ref=body.document_ref)
    db.add(d)
    db.flush()
    record(db, "delivery", d.id, "CREATE", actor, body.model_dump(mode="json") | {"code": code})
    db.commit()
    return {"id": d.id, "code": d.code}


# ----------------------------------------------------------------------------- drill patterns
class PatternIn(BaseModel):
    code: str | None = Field(None, max_length=30)
    bench_id: int
    design_document_ref: str = Field(..., min_length=2, max_length=80)
    approved_by: str = Field(..., min_length=3, max_length=120)
    hole_diameter_mm: float = Field(..., gt=20, le=500)


@router.post("/patterns", status_code=201)
def create_pattern(body: PatternIn, db: Session = Depends(get_db), actor: Actor = Depends(require("pattern.manage"))):
    bench = _get(db, m.Bench, body.bench_id, N_("bench"))
    code = _unique(db, m.DrillPattern, body.code, N_("Pattern")) if body.code else next_code(db, m.DrillPattern, f"PT-{bench.code}")
    p = m.DrillPattern(code=code, bench_id=bench.id, design_document_ref=body.design_document_ref.strip(),
                       approved_by=body.approved_by.strip(), hole_count=0, hole_diameter_mm=body.hole_diameter_mm, origin_x=0, origin_y=0)
    db.add(p)
    db.flush()
    record(db, "drill_pattern", p.id, "CREATE", actor, body.model_dump(mode="json") | {"code": code})
    db.commit()
    return {"id": p.id, "code": p.code}


HOLE_COLUMNS = {"hole_code", "x", "y", "z", "depth_m"}
OPTIONAL_COLUMNS = {"dip_deg", "azimuth_deg", "row", "col"}
_RC = re.compile(r"^R(\d+)-(\d+)$", re.I)


def parse_holes(text: str) -> tuple[list[dict], list[str]]:
    """Validates a drillhole design CSV. Returns (rows, errors); nothing is stored here."""
    errors: list[str] = []
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return [], [_("The file is empty")]
    sample = lines[0]
    delim = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delim)
    cols = {c.strip().lower() for c in (reader.fieldnames or [])}
    missing = HOLE_COLUMNS - cols
    if missing:
        return [], [f"Missing column(s): {', '.join(sorted(missing))}. Required: {', '.join(sorted(HOLE_COLUMNS))}; "
                    f"optional: {', '.join(sorted(OPTIONAL_COLUMNS))}"]
    rows, seen = [], set()
    for n, raw in enumerate(reader, start=2):
        r = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        code = r["hole_code"].upper()
        try:
            if not code or len(code) > 20:
                raise ValueError(_('hole_code must be 1–20 characters'))
            if code in seen:
                raise ValueError(_('duplicate hole_code {code}', code=code))
            num = lambda k, lo, hi, default=None: _num(r.get(k, ""), k, lo, hi, default)  # noqa: E731
            x, y, z = num("x", -1e7, 1e7), num("y", -1e7, 1e7), num("z", -1e4, 1e4)
            depth = num("depth_m", 0.5, 150)
            dip = num("dip_deg", 0, 90, 90.0)
            az = num("azimuth_deg", 0, 360, 0.0)
            rc = _RC.match(code)
            row = int(num("row", 1, 99, float(rc.group(1)) if rc else None) or 0)
            col = int(num("col", 1, 999, float(rc.group(2)) if rc else None) or 0)
            if not row:
                raise ValueError(_('row is required (1 = front row, nearest the free face) unless the hole code is R<row>-<n>'))
            if not col:
                col = sum(1 for h in rows if h["row_no"] == row) + 1
        except ValueError as e:
            errors.append(_('line {n}: {e}', n=n, e=e))
            continue
        seen.add(code)
        rows.append({"hole_code": code, "planned_x": x, "planned_y": y, "planned_z": z, "planned_depth_m": depth,
                     "planned_dip_deg": dip, "planned_azimuth_deg": az, "row_no": row, "col_no": col})
        if len(rows) > 2000:
            errors.append(_('More than 2000 holes — split the pattern'))
            break
    if not rows and not errors:
        errors.append(_('No hole found in the file'))
    return rows, errors


def _num(v: str, name: str, lo: float, hi: float, default: float | None = None) -> float | None:
    if v == "":
        if default is None and name not in ("row", "col"):
            raise ValueError(_('{name} is required', name=name))
        return default
    try:
        f = float(v.replace(",", ".")) if v.count(",") == 1 and "." not in v else float(v)
    except ValueError:
        raise ValueError(_('{name} is not a number ({v!r})', name=name, v=v)) from None
    if not math.isfinite(f) or f < lo or f > hi:
        raise ValueError(_('{name} {f} outside {lo}–{hi}', name=name, f=f, lo=lo, hi=hi))
    return f


def _pattern(db: Session, pid: int) -> m.DrillPattern:
    p = db.get(m.DrillPattern, pid)
    if p is None:
        raise HTTPException(404, _('Pattern not found'))
    return p


@router.post("/patterns/{pid}/holes/import")
async def import_holes(pid: int, file: UploadFile = File(...), dry_run: bool = Query(True), db: Session = Depends(get_db),
                       actor: Actor = Depends(require("pattern.manage"))):
    """Imports the approved drillhole design (from the design software). dry_run=true validates only."""
    p = _pattern(db, pid)
    raw = await file.read()
    if len(raw) > 5_000_000:
        raise HTTPException(413, _('File larger than 5 MB'))
    text = raw.decode("utf-8-sig", errors="replace")
    rows, errors = parse_holes(text)
    measured = db.scalar(select(func.count()).select_from(m.DrillholeMeasurement).join(m.Drillhole)
                         .where(m.Drillhole.pattern_id == p.id)) or 0
    if measured:
        errors.insert(0, _("{n} measurement(s) already recorded on this pattern — the design can no longer be replaced", n=measured))
    summary = {"holes": len(rows), "rows": len({r["row_no"] for r in rows}), "errors": errors[:50], "error_count": len(errors),
               "replaces": len(p.holes), "dry_run": dry_run,
               "extent": {"x": [min(r["planned_x"] for r in rows), max(r["planned_x"] for r in rows)],
                          "y": [min(r["planned_y"] for r in rows), max(r["planned_y"] for r in rows)]} if rows else None,
               "depth_m": [min(r["planned_depth_m"] for r in rows), max(r["planned_depth_m"] for r in rows)] if rows else None}
    if dry_run or errors:
        if errors and not dry_run:
            raise HTTPException(422, {"message": _('Import refused — fix the file and validate again'), "unmet": errors[:20]})
        return summary
    for h in list(p.holes):
        db.delete(h)
    db.flush()
    for r in rows:
        db.add(m.Drillhole(pattern_id=p.id, **r))
    p.hole_count = len(rows)
    p.origin_x = min(r["planned_x"] for r in rows)
    p.origin_y = min(r["planned_y"] for r in rows)
    record(db, "drill_pattern", p.id, "UPDATE", actor, {"holes_imported": len(rows), "replaced": summary["replaces"],
                                                        "file": file.filename})
    db.commit()
    return summary | {"dry_run": False}


@router.get("/patterns/holes-template.csv")
def holes_template():
    from fastapi.responses import Response

    txt = ("# Drillhole design export: one line per hole, coordinates in the mine grid (m).\n"
           "# row: 1 = front row (nearest the free face). dip_deg: 90 = vertical. Optional: dip_deg, azimuth_deg, row, col.\n"
           "hole_code,x,y,z,depth_m,dip_deg,azimuth_deg,row\n"
           "R1-01,1000.00,500.00,310.00,13.0,90,0,1\nR1-02,1004.00,500.00,310.00,13.0,90,0,1\n"
           "R2-01,1002.00,503.50,310.00,13.0,90,0,2\n")
    return Response(txt, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="drillhole_design_template.csv"'})


class DrilledIn(BaseModel):
    drilled_on: date


@router.post("/patterns/{pid}/drilled")
def pattern_drilled(pid: int, body: DrilledIn, db: Session = Depends(get_db), actor: Actor = Depends(require("pattern.manage"))):
    p = _pattern(db, pid)
    if not p.holes:
        raise HTTPException(409, _('Import the drillhole design first'))
    if body.drilled_on > clock.today():
        raise HTTPException(422, _('Drilling completion cannot be in the future'))
    before = _iso(p.drilled_on)
    p.drilled_on = body.drilled_on
    record(db, "drill_pattern", p.id, "UPDATE", actor, {"drilled_on": {"before": before, "after": body.drilled_on.isoformat()}})
    db.commit()
    return {"id": p.id, "drilled_on": p.drilled_on.isoformat()}


class LoadingRefIn(BaseModel):
    document_ref: str = Field(..., min_length=2, max_length=80)
    revision: str = Field(..., min_length=1, max_length=10)
    approved_by: str = Field(..., min_length=3, max_length=120)
    approved_on: date
    notes: str | None = Field(None, max_length=1000)


@router.post("/patterns/{pid}/loading-references", status_code=201)
def add_loading_reference(pid: int, body: LoadingRefIn, db: Session = Depends(get_db), actor: Actor = Depends(require("pattern.manage"))):
    """Reference to the approved loading document. The content of that document is never entered or calculated here."""
    p = _pattern(db, pid)
    a = m.ApprovedLoadingRecord(pattern_id=p.id, document_ref=body.document_ref.strip(), revision=body.revision.strip(),
                                approved_by=body.approved_by.strip(), approved_on=body.approved_on, notes=body.notes)
    db.add(a)
    db.flush()
    record(db, "approved_loading_record", a.id, "CREATE", actor, body.model_dump(mode="json") | {"pattern": p.code})
    db.commit()
    return {"id": a.id}


@router.delete("/patterns/{pid}")
def delete_pattern(pid: int, db: Session = Depends(get_db), actor: Actor = Depends(require("pattern.manage"))):
    p = _pattern(db, pid)
    if db.scalars(select(m.Blast).where(m.Blast.pattern_id == p.id)).first():
        raise HTTPException(409, _('A blast uses this pattern'))
    if any(h.measurements for h in p.holes):
        raise HTTPException(409, _('Measurements are recorded on this pattern'))
    for a in db.scalars(select(m.ApprovedLoadingRecord).where(m.ApprovedLoadingRecord.pattern_id == p.id)):
        db.delete(a)
    for h in list(p.holes):
        db.delete(h)
    db.flush()
    record(db, "drill_pattern", p.id, "DELETE", actor, {"code": p.code, "holes": p.hole_count})
    db.delete(p)
    db.commit()
    return {"deleted": pid}


# ----------------------------------------------------------------------------- blasts
class BlastIn(BaseModel):
    code: str | None = Field(None, max_length=30)
    work_order_id: int
    pattern_id: int
    approved_plan_ref: str = Field(..., min_length=2, max_length=80)
    planned_date: date
    supervisor_id: int | None = None
    blaster_id: int | None = None
    equipment_codes: str | None = Field(None, max_length=200)
    rock_tonnes_forecast: float | None = Field(None, ge=0, le=1e8)


def instantiate_blast_records(db: Session, b: m.Blast, area_id: int) -> None:
    """Checkpoints and the pre-blast checklist from the site templates (current version at creation)."""
    for stage, name in tpl.get(db, "blast_checkpoints"):
        db.add(m.BlastCheckpoint(blast_id=b.id, stage=stage, name=name, required=True, completed=False))
    insp = m.Inspection(code=f"IN-PB-{b.code}"[:30], inspection_type="PRE_BLAST", blast_id=b.id, area_id=area_id,
                        due_date=b.planned_date, status="SCHEDULED")
    db.add(insp)
    db.flush()
    for k, text in enumerate(tpl.get(db, "pre_blast_checklist")):
        db.add(m.ChecklistItem(inspection_id=insp.id, seq=k + 1, text=text))


@router.post("/blasts", status_code=201)
def create_blast(body: BlastIn, db: Session = Depends(get_db), actor: Actor = Depends(require("planning.write"))):
    wo = _open_wo(db, body.work_order_id)
    if wo.wo_type != "BLAST":
        raise HTTPException(422, _('Work order {code} is not a blast work order', code=wo.code))
    p = _pattern(db, body.pattern_id)
    if not p.holes:
        raise HTTPException(409, _('Pattern {code} has no drillhole design — import it first', code=p.code))
    if db.scalars(select(m.Blast).where(m.Blast.pattern_id == p.id)).first():
        raise HTTPException(409, _('Pattern {code} already has a blast', code=p.code))
    bench = db.get(m.Bench, p.bench_id)
    if bench.area_id != wo.area_id:
        raise HTTPException(422, _("Pattern {code} is not in the work order's area", code=p.code))
    for pid, label in ((body.supervisor_id, N_("supervisor")), (body.blaster_id, N_("blaster"))):
        _get(db, m.Personnel, pid, label, required=False)
    code = _unique(db, m.Blast, body.code, N_("Blast")) if body.code else next_code(db, m.Blast, "BL", body.planned_date)
    b = m.Blast(code=code, work_order_id=wo.id, bench_id=bench.id, pattern_id=p.id, approved_plan_ref=body.approved_plan_ref.strip(),
                planned_date=body.planned_date, status="PLANNED", supervisor_id=body.supervisor_id, blaster_id=body.blaster_id,
                equipment_codes=body.equipment_codes, rock_tonnes_forecast=body.rock_tonnes_forecast)
    db.add(b)
    db.flush()
    db.add(m.BlastStatusHistory(blast_id=b.id, from_status=None, to_status="PLANNED", changed_at=clock.now(), changed_by=str(actor),
                                note=S_("Blast record created")))
    instantiate_blast_records(db, b, bench.area_id)
    record(db, "blast", b.id, "CREATE", actor, body.model_dump(mode="json") | {"code": code})
    db.commit()
    return {"id": b.id, "code": b.code, "status": b.status}


@router.delete("/blasts/{bid}")
def delete_blast(bid: int, db: Session = Depends(get_db), actor: Actor = Depends(require("planning.write"))):
    """Only a blast still PLANNED, with nothing recorded against it, can be deleted (e.g. created by mistake)."""
    b = db.get(m.Blast, bid)
    if b is None:
        raise HTTPException(404, _('Blast not found'))
    if b.status != "PLANNED":
        raise HTTPException(409, _('Only a planned blast can be deleted'))
    if db.scalars(select(m.BlastCheckpoint).where(m.BlastCheckpoint.blast_id == b.id, m.BlastCheckpoint.completed.is_(True))).first():
        raise HTTPException(409, _('Checkpoints are already completed for this blast'))
    from .masterdata import Entity, _usage  # generic foreign-key scan

    used = _usage(db, Entity("blast", m.Blast, "", []), b.id)
    other = {t: n for t, n in used.items() if t not in ("blast_checkpoint", "blast_status_history", "inspection")}
    if other:
        raise HTTPException(409, {"message": _('Records already exist for this blast'), "used_by": other})
    insps = db.scalars(select(m.Inspection).where(m.Inspection.blast_id == b.id)).all()
    for insp in insps:
        for it in list(insp.items):
            db.delete(it)
    db.flush()
    for x in insps:
        db.delete(x)
    for model in (m.BlastCheckpoint, m.BlastStatusHistory):
        for x in db.scalars(select(model).where(model.blast_id == b.id)):
            db.delete(x)
    db.flush()
    record(db, "blast", b.id, "DELETE", actor, {"code": b.code})
    db.delete(b)
    db.commit()
    return {"deleted": bid}


class DetonatorIssueIn(BaseModel):
    inventory_lot_ref: str = Field(..., min_length=2, max_length=60)
    units_issued: int = Field(..., ge=1, le=100000)
    equipment_ref: str | None = Field(None, max_length=80)
    authorized_personnel: str = Field(..., min_length=3, max_length=200)
    procedure_ref: str = Field(..., min_length=2, max_length=80)


@router.post("/blasts/{bid}/detonator-record", status_code=201)
def create_detonator_record(bid: int, body: DetonatorIssueIn, db: Session = Depends(get_db),
                            actor: Actor = Depends(require("detonator.record"))):
    """Administrative issue record (lot, units, equipment tag, authorized persons, procedure reference) — nothing technical."""
    b = db.get(m.Blast, bid)
    if b is None:
        raise HTTPException(404, _('Blast not found'))
    if b.status in ("COMPLETED", "CLOSED"):
        raise HTTPException(409, _('The blast is completed'))
    if db.scalars(select(m.DetonatorRecord).where(m.DetonatorRecord.blast_id == b.id)).first():
        raise HTTPException(409, _('A detonator record already exists for this blast'))
    d = m.DetonatorRecord(blast_id=b.id, inventory_lot_ref=body.inventory_lot_ref.strip(), units_issued=body.units_issued,
                          equipment_ref=body.equipment_ref, authorized_personnel=body.authorized_personnel.strip(),
                          procedure_ref=body.procedure_ref.strip(), inspection_status="PENDING", documentation_status="INCOMPLETE")
    db.add(d)
    db.flush()
    record(db, "detonator_record", d.id, "CREATE", actor, body.model_dump() | {"blast": b.code})
    db.commit()
    return {"id": d.id}


# ----------------------------------------------------------------------------- templates
@router.get("/templates")
def get_templates(db: Session = Depends(get_db), _actor: Actor = Depends(signed_in)):
    return {name: {"items": tpl.get(db, name), "is_default": tpl.get(db, name) == tpl.default(name)} for name in tpl.DEFAULTS} | {
        "_meta": {"stages": list(tpl.STAGES), "activities": list(tpl.ACTIVITIES), "test_types": list(tpl.TEST_TYPES), "required_checkpoint": tpl.translate(tpl.AUTH_CHECKPOINT, DEFAULT_LANGUAGE),
                  "note": _("Changes apply to blasts and work orders created afterwards; existing records keep their version.")}}


class TemplateIn(BaseModel):
    items: list
    source_document: str = Field(..., min_length=3, max_length=200)


@router.put("/templates/{name}")
def put_template(name: str, body: TemplateIn, db: Session = Depends(get_db), actor: Actor = Depends(require("masterdata.manage"))):
    try:
        items = tpl.validate(name, body.items)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    before = tpl.get(db, name)
    tpl.save(db, name, items)
    record(db, "template", 0, "UPDATE", actor, {"template": name, "source_document": body.source_document,
                                                 "before": before, "after": items})
    db.commit()
    return {"name": name, "items": items}


@router.get("/options")
def options(db: Session = Depends(get_db)):
    """Selection lists for the creation forms."""
    wos = db.scalars(select(m.WorkOrder).where(m.WorkOrder.status.in_(("OPEN", "IN_PROGRESS"))).order_by(m.WorkOrder.code.desc())).all()
    used = {pid for (pid,) in db.execute(select(m.Blast.pattern_id))}
    pats = db.scalars(select(m.DrillPattern).order_by(m.DrillPattern.code.desc())).all()
    benches = {b.id: b for b in db.scalars(select(m.Bench))}
    return {
        "work_orders": [{"id": w.id, "label": f"{w.code} — {w.title}", "area_id": w.area_id, "type": w.wo_type} for w in wos],
        "patterns_free": [{"id": p.id, "label": f"{p.code} ({p.hole_count} holes)", "area_id": benches[p.bench_id].area_id,
                           "has_holes": p.hole_count > 0} for p in pats if p.id not in used],
        "blasts_without_detonator_record": [
            {"id": b.id, "label": b.code} for b in db.scalars(select(m.Blast).where(m.Blast.status.not_in(("COMPLETED", "CLOSED"))))
            if not db.scalars(select(m.DetonatorRecord).where(m.DetonatorRecord.blast_id == b.id)).first()],
        "activities": list(tpl.ACTIVITIES), "wo_types": list(WO_TYPES),
    }
