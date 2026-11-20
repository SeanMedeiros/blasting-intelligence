"""Module 02 — Production and delivery planning."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import clock
from ..db import get_db
from ..services.audit import record
from ..services.security import require
from ..i18n import _

router = APIRouter(prefix="/api/v1/planning", tags=["Production planning"])
CAUSES = ["WEATHER", "EQUIPMENT", "PRODUCT_SUPPLY", "CLIENT_ACCESS", "REDRILL", "AUTHORIZATION_WAIT", "WILDLIFE_EXCLUSION", "OTHER"]


def _now():
    return clock.now()


@router.get("/schedule")
def schedule(start: date | None = None, end: date | None = None, db: Session = Depends(get_db)):
    start = start or clock.today() - timedelta(days=clock.today().weekday())
    end = end or start + timedelta(days=13)
    if (end - start).days > 92:
        raise HTTPException(422, _('Range limited to 92 days'))
    people = {p.id: p.full_name for p in db.scalars(select(m.Personnel))}
    wos = {w.id: w for w in db.scalars(select(m.WorkOrder))}
    blasts = {b.work_order_id: b for b in db.scalars(select(m.Blast))}
    benches = {b.id: b.code for b in db.scalars(select(m.Bench))}
    changes = defaultdict(int)
    for c in db.scalars(select(m.ScheduleChange)):
        changes[c.schedule_item_id] += 1
    items = db.scalars(select(m.ScheduleItem).where(m.ScheduleItem.planned_date >= start - timedelta(days=7),
                                                    m.ScheduleItem.planned_date <= end).order_by(m.ScheduleItem.planned_date)).all()
    out = []
    for i in items:
        w = wos[i.work_order_id]
        b = blasts.get(w.id)
        out.append({"id": i.id, "work_order": w.code, "work_order_id": w.id, "blast": b.code if b else None,
                    "bench": benches.get(b.bench_id) if b else None, "activity": i.activity, "planned_date": i.planned_date.isoformat(),
                    "actual_date": i.actual_date.isoformat() if i.actual_date else None, "status": i.status, "resources": i.resources,
                    "responsible": people.get(i.responsible_id), "changes": changes[i.id],
                    "late": i.status != "DONE" and i.planned_date < clock.today()})
    gantt = defaultdict(list)
    for r in out:
        gantt[r["work_order"]].append(r)
    gantt_rows = [{"work_order": k, "blast": v[0]["blast"], "bench": v[0]["bench"],
                   "items": v} for k, v in gantt.items() if any(start.isoformat() <= x["planned_date"] <= end.isoformat() for x in v)]
    return {"start": start.isoformat(), "end": end.isoformat(), "today": clock.today().isoformat(),
            "items": [r for r in out if start.isoformat() <= r["planned_date"] <= end.isoformat()], "gantt": gantt_rows}


@router.get("/work-orders")
def work_orders(db: Session = Depends(get_db)):
    areas = {a.id: a.code for a in db.scalars(select(m.Area))}
    items = defaultdict(list)
    for i in db.scalars(select(m.ScheduleItem)):
        items[i.work_order_id].append(i)
    out = []
    for w in db.scalars(select(m.WorkOrder).order_by(m.WorkOrder.planned_start.desc())):
        its = items[w.id]
        done = sum(1 for i in its if i.status == "DONE")
        out.append({"id": w.id, "code": w.code, "title": w.title, "area": areas[w.area_id], "type": w.wo_type, "status": w.status,
                    "engineering_forecast_ref": w.engineering_forecast_ref, "planned_start": w.planned_start.isoformat(),
                    "planned_end": w.planned_end.isoformat(), "actual_start": w.actual_start.isoformat() if w.actual_start else None,
                    "actual_end": w.actual_end.isoformat() if w.actual_end else None, "forecast_tonnes": w.forecast_tonnes,
                    "actual_tonnes": w.actual_tonnes,
                    "tonnes_variance_pct": round(100 * (w.actual_tonnes - w.forecast_tonnes) / w.forecast_tonnes, 1) if w.actual_tonnes and w.forecast_tonnes else None,
                    "progress_pct": round(100 * done / len(its), 0) if its else 0})
    return out


@router.get("/production")
def production(db: Session = Depends(get_db)):
    """Weekly forecast vs actual blasted tonnes (engineering forecast vs post-blast survey)."""
    wk = defaultdict(lambda: {"forecast": 0.0, "actual": 0.0, "blasts": 0})
    for w in db.scalars(select(m.WorkOrder)):
        b = db.scalars(select(m.Blast).where(m.Blast.work_order_id == w.id)).first()
        if not b:
            continue
        d = b.planned_date
        key = (d - timedelta(days=d.weekday())).isoformat()
        wk[key]["forecast"] += w.forecast_tonnes or 0
        if w.actual_tonnes:
            wk[key]["actual"] += w.actual_tonnes
        wk[key]["blasts"] += 1
    return [{"week": k, "forecast_t": round(v["forecast"]), "actual_t": round(v["actual"]) if v["actual"] else None, "blasts": v["blasts"]}
            for k, v in sorted(wk.items())]


@router.get("/deliveries")
def deliveries(db: Session = Depends(get_db)):
    areas = {a.id: a.code for a in db.scalars(select(m.Area))}
    return [{"id": d.id, "code": d.code, "product": d.product_name, "area": areas[d.destination_area_id], "planned_date": d.planned_date.isoformat(),
             "actual_date": d.actual_date.isoformat() if d.actual_date else None, "planned_qty": d.planned_qty, "delivered_qty": d.delivered_qty,
             "unit": d.unit, "status": d.status, "document_ref": d.document_ref,
             "on_time": d.actual_date is not None and d.actual_date <= d.planned_date}
            for d in db.scalars(select(m.Delivery).order_by(m.Delivery.planned_date.desc()))]


@router.get("/delays")
def delays(db: Session = Depends(get_db)):
    wos = {w.id: w.code for w in db.scalars(select(m.WorkOrder))}
    rows = db.scalars(select(m.DelayEvent).order_by(m.DelayEvent.occurred_on.desc())).all()
    pareto = defaultdict(lambda: [0, 0.0])
    for d in rows:
        pareto[d.category][0] += 1
        pareto[d.category][1] += d.hours
    changes = db.scalars(select(m.ScheduleChange).order_by(m.ScheduleChange.changed_at.desc(), m.ScheduleChange.id.desc())).all()
    items = {i.id: i for i in db.scalars(select(m.ScheduleItem))}
    return {"events": [{"id": d.id, "date": d.occurred_on.isoformat(), "work_order": wos.get(d.work_order_id), "category": d.category,
                        "hours": d.hours, "description": d.description} for d in rows],
            "pareto": sorted([{"category": k, "events": v[0], "hours": round(v[1], 1)} for k, v in pareto.items()], key=lambda x: -x["hours"]),
            "changes": [{"id": c.id, "at": c.changed_at.isoformat(), "work_order": wos.get(items[c.schedule_item_id].work_order_id),
                         "activity": items[c.schedule_item_id].activity, "old_date": c.old_date.isoformat(), "new_date": c.new_date.isoformat(),
                         "cause_category": c.cause_category, "cause": c.cause, "by": c.changed_by} for c in changes]}


class RescheduleIn(BaseModel):
    new_date: date
    cause_category: str
    cause: str = Field(..., min_length=5, max_length=500)
    delay_hours: float | None = Field(None, ge=0, le=500)


@router.post("/items/{iid}/reschedule")
def reschedule(iid: int, body: RescheduleIn, db: Session = Depends(get_db), user: str = Depends(require("planning.write"))):
    it = db.get(m.ScheduleItem, iid)
    if it is None:
        raise HTTPException(404, _('Schedule item not found'))
    if it.status == "DONE":
        raise HTTPException(409, _('Completed activities cannot be rescheduled'))
    if body.cause_category not in CAUSES:
        raise HTTPException(422, _('cause_category must be one of {CAUSES}', CAUSES=CAUSES))
    if body.new_date == it.planned_date:
        raise HTTPException(422, _('New date equals the current planned date'))
    if body.new_date < clock.today():
        raise HTTPException(422, _('New date cannot be in the past'))
    db.add(m.ScheduleChange(schedule_item_id=it.id, changed_at=_now(), old_date=it.planned_date, new_date=body.new_date,
                            cause_category=body.cause_category, cause=body.cause, changed_by=user))
    if body.delay_hours:
        db.add(m.DelayEvent(work_order_id=it.work_order_id, occurred_on=clock.today(), category=body.cause_category, hours=body.delay_hours,
                            description=body.cause))
    old = it.planned_date
    it.planned_date = body.new_date
    it.status = "DELAYED" if body.new_date > old else "PLANNED"
    record(db, "schedule_item", it.id, "UPDATE", user, {"old_date": old.isoformat(), **body.model_dump(mode="json")})
    db.commit()
    return {"id": it.id, "planned_date": it.planned_date.isoformat(), "status": it.status}


class CompleteIn(BaseModel):
    actual_date: date


@router.post("/items/{iid}/complete")
def complete(iid: int, body: CompleteIn, db: Session = Depends(get_db), user: str = Depends(require("planning.write"))):
    it = db.get(m.ScheduleItem, iid)
    if it is None:
        raise HTTPException(404, _('Schedule item not found'))
    if it.status == "DONE":
        raise HTTPException(409, _('Already completed'))
    if body.actual_date > clock.today():
        raise HTTPException(422, _('Actual date cannot be in the future'))
    if it.activity == "BLAST":
        raise HTTPException(409, _('Blast execution is recorded through the blasting operations workflow'))
    it.actual_date, it.status = body.actual_date, "DONE"
    record(db, "schedule_item", it.id, "STATUS", user, {"status": "DONE", "actual_date": body.actual_date.isoformat()})
    db.commit()
    return {"id": it.id, "status": it.status}


class ReceiveIn(BaseModel):
    actual_date: date
    delivered_qty: float = Field(..., gt=0, le=200)
    document_ref: str = Field(..., min_length=2, max_length=80)


@router.post("/deliveries/{did}/receive")
def receive(did: int, body: ReceiveIn, db: Session = Depends(get_db), user: str = Depends(require("planning.write"))):
    d = db.get(m.Delivery, did)
    if d is None:
        raise HTTPException(404, _('Delivery not found'))
    if d.actual_date:
        raise HTTPException(409, _('Delivery already received'))
    if body.actual_date > clock.today():
        raise HTTPException(422, _('Receipt date cannot be in the future'))
    d.actual_date, d.delivered_qty, d.document_ref = body.actual_date, body.delivered_qty, body.document_ref
    d.status = "PARTIAL" if body.delivered_qty < 0.95 * d.planned_qty else ("LATE" if body.actual_date > d.planned_date else "DELIVERED")
    record(db, "delivery", d.id, "UPDATE", user, body.model_dump(mode="json"))
    db.commit()
    return {"id": d.id, "status": d.status}
