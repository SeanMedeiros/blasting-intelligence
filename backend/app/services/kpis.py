"""KPI engine.

Every KPI is a DEMONSTRATION KPI. Each one returns its numerator, denominator and
documented formula so the result can be audited. Targets come from the kpi_target
table and are configurable.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import clock
from ..i18n import N_, _
from . import templates as tpl


@dataclass(frozen=True)
class KpiDef:
    key: str
    name: str
    unit: str
    formula: str


KPI_DEFS: list[KpiDef] = [
    KpiDef("schedule_adherence", N_("Schedule adherence"), "%",
           N_("Activities completed on their planned date ÷ activities planned in the period (planned date ≤ today)")),
    KpiDef("activity_completion", N_("Operational activity completion"), "%",
           N_("Activities with status DONE ÷ activities planned in the period (planned date ≤ today)")),
    KpiDef("drillhole_inspection_compliance", N_("Drillhole inspection compliance"), "%",
           N_("Holes with at least one recorded measurement ÷ holes in patterns of blasts fired in the period")),
    KpiDef("drillhole_deviation_rate", N_("Drillhole deviation rate"), "%",
           N_("Holes whose latest measurement is not WITHIN_TOLERANCE ÷ holes measured in the period")),
    KpiDef("survey_completion", N_("3D survey completion"), "%",
           N_("Blasts fired in the period with an ACCEPTED pre-blast face profile AND a post-blast survey ÷ blasts fired")),
    KpiDef("product_qaqc_compliance", N_("Product QA/QC compliance"), "%",
           N_("Tests with result PASS ÷ tests evaluated (VALID data quality, PASS or FAIL) in the period")),
    KpiDef("lab_testing_completion", N_("Laboratory testing completion"), "%",
           N_("Required tests performed with valid calibration ÷ required tests (site sampling plan — per batch: {per_batch}; per blast fired: {per_blast})")),
    KpiDef("vibration_monitoring_compliance", N_("Vibration monitoring compliance"), "%",
           N_("Blasts fired with a VALID record at every receptor station ÷ blasts fired in the period")),
    KpiDef("post_blast_report_completion", N_("Post-blast report completion"), "%",
           N_("Post-blast reviews completed on or before their due date ÷ reviews due in the period (due date ≤ today)")),
    KpiDef("capa_closure_rate", N_("Corrective action closure rate"), "%",
           N_("Corrective/preventive actions closed on or before due date ÷ actions due in the period (due date ≤ today)")),
    KpiDef("equipment_availability", N_("Equipment availability"), "%",
           N_("(Calendar hours − recorded downtime hours) ÷ calendar hours, all equipment, period up to today")),
    KpiDef("operational_downtime_h", N_("Operational downtime"), "h",
           N_("Sum of recorded operational delay hours in the period")),
    KpiDef("documentation_completeness", N_("Documentation completeness"), "%",
           N_("Required blast checkpoints completed ÷ required checkpoints, for blasts fired in the period")),
]
KPI_BY_KEY = {k.key: k for k in KPI_DEFS}


def _pct(num: float, den: float) -> float | None:
    return round(100.0 * num / den, 1) if den else None


def _d(v) -> date:
    return v.date() if isinstance(v, datetime) else v


def compute_kpis(db: Session, start: date, end: date, today: date | None = None) -> list[dict]:
    today = today or clock.today()
    end_eff = min(end, today)
    res: dict[str, tuple[float | None, float, float]] = {}

    # 1-2 schedule
    items = db.scalars(select(m.ScheduleItem).where(m.ScheduleItem.planned_date >= start,
                                                    m.ScheduleItem.planned_date <= end_eff)).all()
    items = [i for i in items if i.status != "CANCELLED"]
    on_time = sum(1 for i in items if i.actual_date == i.planned_date)
    done = sum(1 for i in items if i.status == "DONE")
    res["schedule_adherence"] = (_pct(on_time, len(items)), on_time, len(items))
    res["activity_completion"] = (_pct(done, len(items)), done, len(items))

    # blasts fired in period
    blasts = [b for b in db.scalars(select(m.Blast).where(m.Blast.fired_at.is_not(None))).all()
              if start <= b.fired_at.date() <= end_eff]
    pattern_ids = [b.pattern_id for b in blasts]

    # 3 inspection compliance
    holes = db.scalars(select(m.Drillhole).where(m.Drillhole.pattern_id.in_(pattern_ids))).all() if pattern_ids else []
    measured = sum(1 for h in holes if h.measurements)
    res["drillhole_inspection_compliance"] = (_pct(measured, len(holes)), measured, len(holes))

    # 4 deviation rate (latest measurement per hole measured in period)
    meas = db.scalars(select(m.DrillholeMeasurement).where(
        m.DrillholeMeasurement.measured_at >= datetime.combine(start, datetime.min.time()),
        m.DrillholeMeasurement.measured_at < datetime.combine(end_eff + timedelta(days=1), datetime.min.time()))).all()
    latest: dict[int, m.DrillholeMeasurement] = {}
    for x in meas:
        if x.drillhole_id not in latest or x.measured_at > latest[x.drillhole_id].measured_at:
            latest[x.drillhole_id] = x
    dev = sum(1 for x in latest.values() if x.inspection_status != "WITHIN_TOLERANCE")
    res["drillhole_deviation_rate"] = (_pct(dev, len(latest)), dev, len(latest))

    # 5 survey completion
    bid = [b.id for b in blasts]
    surveys = db.scalars(select(m.Survey).where(m.Survey.blast_id.in_(bid))).all() if bid else []
    by_blast = defaultdict(list)
    for s in surveys:
        by_blast[s.blast_id].append(s)
    ok = 0
    for b in blasts:
        ss = by_blast[b.id]
        pre = any(s.survey_type in ("FACE_PROFILE", "PRE_BLAST") and s.quality_status == "ACCEPTED" for s in ss)
        post = any(s.survey_type == "POST_BLAST" and s.quality_status != "REJECTED" for s in ss)
        ok += pre and post
    res["survey_completion"] = (_pct(ok, len(blasts)), ok, len(blasts))

    # 6-7 laboratory
    tests = db.scalars(select(m.LabTest).where(
        m.LabTest.tested_at >= datetime.combine(start, datetime.min.time()),
        m.LabTest.tested_at < datetime.combine(end_eff + timedelta(days=1), datetime.min.time()))).all()
    evaluated = [t for t in tests if t.data_quality == "VALID" and t.result in ("PASS", "FAIL")]
    passed = sum(1 for t in evaluated if t.result == "PASS")
    res["product_qaqc_compliance"] = (_pct(passed, len(evaluated)), passed, len(evaluated))

    batches = db.scalars(select(m.ProductBatch).where(m.ProductBatch.produced_on >= start,
                                                      m.ProductBatch.produced_on <= end_eff)).all()
    batch_tests = defaultdict(set)
    for t in db.scalars(select(m.LabTest).where(m.LabTest.batch_id.in_([b.id for b in batches]))).all() if batches else []:
        if t.calibration_valid and t.value is not None:
            batch_tests[t.batch_id].add(t.test_type)
    plan = tpl.get(db, "lab_sampling_plan")  # site sampling plan (Settings → Record templates)
    per_batch = {t for scope, t in plan if scope == "BATCH"}
    per_blast = {t for scope, t in plan if scope == "BLAST"}
    required = performed = 0
    for b in batches:
        required += len(per_batch)
        performed += len(per_batch & batch_tests[b.id])
    blast_tests = defaultdict(set)
    if bid and per_blast:
        for t in db.scalars(select(m.LabTest).where(m.LabTest.blast_id.in_(bid), m.LabTest.test_type.in_(per_blast))).all():
            if t.calibration_valid and t.value is not None:
                blast_tests[t.blast_id].add(t.test_type)
    required += len(blasts) * len(per_blast)
    performed += sum(len(per_blast & blast_tests[b.id]) for b in blasts)
    res["lab_testing_completion"] = (_pct(performed, required), performed, required)

    # 8 vibration monitoring compliance
    receptors = db.scalars(select(m.MonitorStation).where(m.MonitorStation.station_type == "RECEPTOR")).all()
    rec_ids = {s.id for s in receptors}
    events = db.scalars(select(m.VibrationEvent).where(m.VibrationEvent.blast_id.in_(bid))).all() if bid else []
    valid_by_blast = defaultdict(set)
    for e in events:
        if e.data_quality == "VALID":
            valid_by_blast[e.blast_id].add(e.station_id)
    vib_ok = sum(1 for b in blasts if rec_ids <= valid_by_blast[b.id])
    res["vibration_monitoring_compliance"] = (_pct(vib_ok, len(blasts)), vib_ok, len(blasts))

    # 9 post-blast report completion
    reviews = db.scalars(select(m.PostBlastReview).where(m.PostBlastReview.due_date >= start,
                                                         m.PostBlastReview.due_date <= end_eff)).all()
    on_time_r = sum(1 for r in reviews if r.completed_on and r.completed_on <= r.due_date)
    res["post_blast_report_completion"] = (_pct(on_time_r, len(reviews)), on_time_r, len(reviews))

    # 10 CAPA closure
    capas = db.scalars(select(m.Capa).where(m.Capa.due_date >= start, m.Capa.due_date <= end_eff)).all()
    closed = sum(1 for c in capas if c.closed_on and c.closed_on <= c.due_date)
    res["capa_closure_rate"] = (_pct(closed, len(capas)), closed, len(capas))

    # 11 equipment availability
    eq = db.scalars(select(m.Equipment)).all()
    hours = (end_eff - start).days + 1
    cal = max(hours, 0) * 24 * len(eq)
    downs = db.scalars(select(m.EquipmentDowntime)).all()
    down_h = 0.0
    p0 = datetime.combine(start, datetime.min.time())
    p1 = datetime.combine(end_eff + timedelta(days=1), datetime.min.time())
    for x in downs:
        a, b = x.started_at, x.started_at + timedelta(hours=x.hours)
        ov = (min(b, p1) - max(a, p0)).total_seconds() / 3600
        down_h += max(ov, 0)
    res["equipment_availability"] = (_pct(cal - down_h, cal), round(cal - down_h, 1), cal)

    # 12 downtime
    delays = db.scalars(select(m.DelayEvent).where(m.DelayEvent.occurred_on >= start, m.DelayEvent.occurred_on <= end_eff)).all()
    tot = round(sum(x.hours for x in delays), 1)
    res["operational_downtime_h"] = (tot, tot, len(delays))

    # 13 documentation completeness
    cps = db.scalars(select(m.BlastCheckpoint).where(m.BlastCheckpoint.blast_id.in_(bid),
                                                     m.BlastCheckpoint.required.is_(True))).all() if bid else []
    cdone = sum(1 for c in cps if c.completed)
    res["documentation_completeness"] = (_pct(cdone, len(cps)), cdone, len(cps))

    targets = {t.kpi_key: t for t in db.scalars(select(m.KpiTarget)).all()}
    out = []
    for k in KPI_DEFS:
        val, num, den = res[k.key]
        t = targets.get(k.key)
        status = "NO_DATA"
        if val is not None and t is not None:
            good = val >= t.target if t.direction == "HIGHER" else val <= t.target
            near = abs(val - t.target) <= (0.05 * t.target if t.target else 1)
            status = "ON_TARGET" if good else ("NEAR_TARGET" if near else "OFF_TARGET")
        if k.key == "operational_downtime_h":
            num_label, den_label = _("hours"), _("delay events")
        else:
            num_label, den_label = _("numerator"), _("denominator")
        fmt = {"per_batch": ", ".join(sorted(per_batch)) or "—", "per_blast": ", ".join(sorted(per_blast)) or "—"} \
            if k.key == "lab_testing_completion" else {}
        out.append({"key": k.key, "name": _(k.name), "unit": k.unit, "value": val, "numerator": num, "denominator": den,
                    "numerator_label": num_label, "denominator_label": den_label, "formula": _(k.formula, **fmt),
                    "target": t.target if t else None,
                    "direction": t.direction if t else None, "target_is_demo": t.is_demo_placeholder if t else False,
                    "status": status, "period": {"start": start.isoformat(), "end": end_eff.isoformat()},
                    "is_demonstration_kpi": clock.is_demo()})
    return out


def periods(granularity: str, start: date, end: date) -> list[tuple[str, date, date]]:
    out = []
    if granularity == "month":
        d = date(start.year, start.month, 1)
        while d <= end:
            nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
            out.append((d.strftime("%Y-%m"), d, nxt - timedelta(days=1)))
            d = nxt
    elif granularity == "week":
        d = start - timedelta(days=start.weekday())
        while d <= end:
            out.append((f"{d.isocalendar().year}-W{d.isocalendar().week:02d}", d, d + timedelta(days=6)))
            d += timedelta(days=7)
    else:
        d = start
        while d <= end:
            out.append((d.isoformat(), d, d))
            d += timedelta(days=1)
    return out


def kpi_series(db: Session, granularity: str, start: date, end: date) -> dict:
    labels, series = [], defaultdict(list)
    for label, a, b in periods(granularity, start, min(end, clock.today())):
        labels.append(label)
        for k in compute_kpis(db, a, b):
            series[k["key"]].append(k["value"])
    return {"granularity": granularity, "labels": labels, "series": series}
