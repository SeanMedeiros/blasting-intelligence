"""Operations Control Center (Module 01) aggregation."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..analytics.rules import run_rules
from .. import clock
from .kpis import compute_kpis, kpi_series

OPEN_BLAST = ["PLANNED", "IN_PREPARATION", "UNDER_INSPECTION", "AUTHORIZED", "IN_PROGRESS", "AWAITING_VERIFICATION"]


def build_dashboard(db: Session, today: date | None = None) -> dict:
    today = today or clock.today()
    people = {p.id: p.full_name for p in db.scalars(select(m.Personnel)).all()}
    benches = {b.id: b.code for b in db.scalars(select(m.Bench)).all()}
    areas = {a.id: a.code for a in db.scalars(select(m.Area)).all()}
    wos = {w.id: w for w in db.scalars(select(m.WorkOrder)).all()}

    # --- today's activities
    items = db.scalars(select(m.ScheduleItem).where(m.ScheduleItem.planned_date == today)).all()
    late = db.scalars(select(m.ScheduleItem).where(m.ScheduleItem.planned_date < today,
                                                   m.ScheduleItem.status.in_(["DELAYED", "PLANNED", "IN_PROGRESS"]))).all()
    today_items = [{"id": i.id, "work_order": wos[i.work_order_id].code, "activity": i.activity, "status": i.status,
                    "planned_date": i.planned_date.isoformat(), "responsible": people.get(i.responsible_id), "resources": i.resources}
                   for i in sorted(items + late, key=lambda x: (x.planned_date, x.activity))]

    # --- blasts
    blasts = db.scalars(select(m.Blast).order_by(m.Blast.planned_date)).all()
    pending = [b for b in blasts if b.status in OPEN_BLAST]
    pattern_progress = {}
    for b in pending:
        holes = db.scalars(select(m.Drillhole).where(m.Drillhole.pattern_id == b.pattern_id)).all()
        meas = [h for h in holes if h.measurements]
        out = [h for h in meas if h.measurements[-1].inspection_status != "WITHIN_TOLERANCE"]
        pattern_progress[b.id] = {"holes": len(holes), "measured": len(meas), "out_of_tolerance": len(out)}
    pending_blasts = [{"code": b.code, "status": b.status, "planned_date": b.planned_date.isoformat(), "bench": benches[b.bench_id],
                       "approved_plan_ref": b.approved_plan_ref, "authorization_ref": b.authorization_ref,
                       "verification": pattern_progress[b.id]} for b in pending]
    status_counts = Counter(b.status for b in blasts)

    # --- deliveries (±7 days)
    dl = db.scalars(select(m.Delivery).where(m.Delivery.planned_date >= today - timedelta(days=7),
                                             m.Delivery.planned_date <= today + timedelta(days=7)).order_by(m.Delivery.planned_date)).all()
    deliveries = [{"code": d.code, "product": d.product_name, "area": areas[d.destination_area_id], "planned_date": d.planned_date.isoformat(),
                   "actual_date": d.actual_date.isoformat() if d.actual_date else None, "planned_qty": d.planned_qty,
                   "delivered_qty": d.delivered_qty, "unit": d.unit, "status": d.status} for d in dl]

    # --- equipment
    eq = db.scalars(select(m.Equipment)).all()
    downs = db.scalars(select(m.EquipmentDowntime).where(m.EquipmentDowntime.started_at >= datetime.combine(today - timedelta(days=30), datetime.min.time()))).all()
    dh = defaultdict(float)
    for x in downs:
        dh[x.equipment_id] += x.hours
    equipment = [{"code": e.code, "name": e.name, "type": e.equipment_type, "status": e.status,
                  "availability_30d": round(100 * (720 - min(dh[e.id], 720)) / 720, 1)} for e in eq]

    # --- surveys
    s30 = db.scalars(select(m.Survey).where(m.Survey.surveyed_at >= datetime.combine(today - timedelta(days=30), datetime.min.time()))).all()
    survey_status = dict(Counter(s.quality_status for s in s30))
    fired30 = [b for b in blasts if b.fired_at and b.fired_at.date() >= today - timedelta(days=30)]
    post_ids = {s.blast_id for s in db.scalars(select(m.Survey).where(m.Survey.survey_type == "POST_BLAST")).all()}
    missing_post = [b.code for b in fired30 if b.id not in post_ids and b.fired_at.date() < today - timedelta(days=1)]

    # --- laboratory
    t30 = db.scalars(select(m.LabTest).where(m.LabTest.tested_at >= datetime.combine(today - timedelta(days=30), datetime.min.time()))).all()
    lab = {"tests": len(t30), "by_result": dict(Counter(t.result for t in t30)),
           "by_type": dict(Counter(t.test_type for t in t30)),
           "open_nonconformances": len(db.scalars(select(m.NonConformance).where(m.NonConformance.status == "OPEN")).all()),
           "quarantined_batches": [b.code for b in db.scalars(select(m.ProductBatch).where(m.ProductBatch.status == "QUARANTINE")).all()]}

    # --- vibration
    stations = {s.id: s for s in db.scalars(select(m.MonitorStation)).all()}
    v30 = db.scalars(select(m.VibrationEvent).where(m.VibrationEvent.recorded_at >= datetime.combine(today - timedelta(days=30), datetime.min.time()))).all()
    vib = []
    for sid, st in stations.items():
        es = [e for e in v30 if e.station_id == sid]
        valid = [e for e in es if e.ppv_mm_s is not None and e.data_quality == "VALID"]
        vib.append({"station": st.code, "name": st.name, "events": len(es), "valid": len(valid),
                    "max_ppv": max((e.ppv_mm_s for e in valid), default=None),
                    "limit": es[-1].limit_ppv_mm_s if es else None,
                    "exceedances": sum(1 for e in es if e.compliance == "EXCEEDANCE")})

    # --- safety
    obs = db.scalars(select(m.SafetyObservation).where(m.SafetyObservation.status != "CLOSED")).all()
    capa = db.scalars(select(m.Capa).where(m.Capa.status != "CLOSED")).all()
    safety = {"open_observations": len(obs), "open_by_risk": dict(Counter(o.risk_level for o in obs)),
              "open_capa": len(capa), "overdue_capa": sum(1 for c in capa if c.due_date < today),
              "near_misses_30d": len(db.scalars(select(m.SafetyObservation).where(
                  m.SafetyObservation.obs_type == "NEAR_MISS",
                  m.SafetyObservation.observed_at >= datetime.combine(today - timedelta(days=30), datetime.min.time()))).all())}

    kpis = compute_kpis(db, today - timedelta(days=29), today)
    trend = kpi_series(db, "week", today - timedelta(weeks=11), today)

    return {"today": today.isoformat(), "activities": today_items, "blast_status_counts": dict(status_counts),
            "pending_blasts": pending_blasts, "deliveries": deliveries, "equipment": equipment,
            "surveys": {"last_30d": survey_status, "missing_post_blast": missing_post},
            "laboratory": lab, "vibration": vib, "safety": safety, "kpis": kpis, "kpi_trend": trend,
            "alerts": run_rules(db, today)}
