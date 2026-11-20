"""Deterministic, explainable detection rules.

Each alert states the rule that produced it and the records involved. Alerts
inform people; they never make engineering or safety decisions.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import clock
from ..i18n import _

SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _alert(rule, severity, title, detail, module, refs=None):
    return {"rule": rule, "severity": severity, "title": title, "detail": detail, "module": module, "refs": refs or []}


def _slope(ys: list[float]) -> float:
    n = len(ys)
    if n < 3:
        return 0.0
    xm = (n - 1) / 2
    ym = sum(ys) / n
    num = sum((i - xm) * (y - ym) for i, y in enumerate(ys))
    den = sum((i - xm) ** 2 for i in range(n))
    return num / den if den else 0.0


def run_rules(db: Session, today: date | None = None) -> list[dict]:
    today = today or clock.today()
    alerts: list[dict] = []

    # --- instrument calibration
    for ins in db.scalars(select(m.Instrument)).all():
        if not ins.calibrations:
            continue
        last = max(ins.calibrations, key=lambda c: c.valid_until)
        if last.valid_until < today:
            used = db.scalars(select(m.LabTest).where(m.LabTest.instrument_id == ins.id, m.LabTest.calibration_valid.is_(False))).all()
            alerts.append(_alert("CALIBRATION_EXPIRED", "HIGH", _('Calibration expired — {code}', code=ins.code),
                                 _('{name} calibration expired on {valid_until}. {n} test(s) recorded after expiry were set to QUESTIONABLE and not evaluated.', name=ins.name, valid_until=last.valid_until, n=len(used)), "laboratory", [ins.code] + [t.code for t in used]))
        elif last.valid_until <= today + timedelta(days=30):
            alerts.append(_alert("CALIBRATION_DUE", "LOW", _('Calibration due soon — {code}', code=ins.code),
                                 _('{name} calibration valid until {valid_until}.', name=ins.name, valid_until=last.valid_until), "settings", [ins.code]))

    # --- repeated drillhole deviations per bench (last 3 measured patterns)
    rows = db.execute(select(m.Bench.code, m.DrillPattern.code, m.DrillPattern.drilled_on, m.DrillholeMeasurement.inspection_status)
                      .join(m.DrillPattern, m.DrillPattern.bench_id == m.Bench.id)
                      .join(m.Drillhole, m.Drillhole.pattern_id == m.DrillPattern.id)
                      .join(m.DrillholeMeasurement, m.DrillholeMeasurement.drillhole_id == m.Drillhole.id)).all()
    per_pattern = defaultdict(lambda: [0, 0])
    bench_patterns = defaultdict(set)
    for bench, pat, drilled, st in rows:
        per_pattern[(bench, pat, drilled)][0] += st != "WITHIN_TOLERANCE"
        per_pattern[(bench, pat, drilled)][1] += 1
        bench_patterns[bench].add((drilled, pat))
    for bench, pats in bench_patterns.items():
        last3 = sorted(pats)[-3:]
        rates = [per_pattern[(bench, p, d)][0] / per_pattern[(bench, p, d)][1] for d, p in last3]
        high = [p for (d, p), r in zip(last3, rates) if r > 0.10]
        if len(high) >= 2:
            alerts.append(_alert("REPEATED_DRILLHOLE_DEVIATION", "HIGH", _('Repeated drillhole deviations — {bench}', bench=bench),
                                 _('{n} of the last 3 patterns on {bench} exceed 10% holes out of tolerance ({v}).', n=len(high), bench=bench, v=', '.join(f'{r:.0%}' for r in rates)), "drillholes", high))

    # --- recurring laboratory non-conformances (same product + test, ≥2 FAIL in 60 days)
    fails = db.execute(select(m.ProductBatch.product_code, m.LabTest.test_type, m.LabTest.code)
                       .join(m.ProductBatch, m.ProductBatch.id == m.LabTest.batch_id)
                       .where(m.LabTest.result == "FAIL", m.LabTest.tested_at >= today - timedelta(days=60))).all()
    grp = defaultdict(list)
    for prod, tt, code in fails:
        grp[(prod, tt)].append(code)
    for (prod, tt), codes in grp.items():
        if len(codes) >= 2:
            alerts.append(_alert("RECURRING_LAB_NC", "HIGH", _('Recurring non-conformance — {prod} {v}', prod=prod, v=tt.lower()),
                                 _('{n} failed {v} tests on {prod} in the last 60 days.', n=len(codes), v=tt.lower(), prod=prod), "laboratory", codes))

    # --- vibration: exceedances (30 d) and rising trend
    lim = {s.id: s for s in db.scalars(select(m.MonitorStation)).all()}
    ev = db.scalars(select(m.VibrationEvent).where(m.VibrationEvent.data_quality == "VALID").order_by(m.VibrationEvent.recorded_at)).all()
    by_st = defaultdict(list)
    for e in ev:
        by_st[e.station_id].append(e)
        if e.compliance == "EXCEEDANCE" and e.recorded_at.date() >= today - timedelta(days=30):
            alerts.append(_alert("VIBRATION_EXCEEDANCE", "CRITICAL", _('Vibration above reference value — {code}', code=lim[e.station_id].code),
                                 _('PPV {ppv_mm_s} mm/s vs configured reference {limit_ppv_mm_s} mm/s on {recorded_at:%Y-%m-%d}.', ppv_mm_s=e.ppv_mm_s, limit_ppv_mm_s=e.limit_ppv_mm_s, recorded_at=e.recorded_at),
                                 "vibration", [e.code]))
    for sid, es in by_st.items():
        last = es[-8:]
        ys = [e.ppv_mm_s for e in last if e.ppv_mm_s is not None]
        s = _slope(ys)
        limit = last[-1].limit_ppv_mm_s or 0
        if s > 0.15 and limit and max(ys) >= 0.6 * limit:
            alerts.append(_alert("VIBRATION_TREND", "MEDIUM", _('Rising vibration trend — {code}', code=lim[sid].code),
                                 _('PPV slope +{s:.2f} mm/s per event over the last {n} valid events; peak {v:.1f} mm/s ({v2:.0%} of configured reference).', s=s, n=len(ys), v=max(ys), v2=max(ys) / limit), "vibration",
                                 [e.code for e in last]))

    # --- overdue inspections
    ov = db.scalars(select(m.Inspection).where(m.Inspection.status.in_(["OVERDUE", "SCHEDULED"]), m.Inspection.due_date < today)).all()
    if ov:
        alerts.append(_alert("OVERDUE_INSPECTIONS", "MEDIUM", _('{n} overdue inspection(s)', n=len(ov)),
                             _('Scheduled inspections past their due date without a completion record.'), "safety", [i.code for i in ov]))

    # --- overdue CAPA
    oc = db.scalars(select(m.Capa).where(m.Capa.status != "CLOSED", m.Capa.due_date < today)).all()
    if oc:
        alerts.append(_alert("OVERDUE_CAPA", "HIGH", _('{n} overdue corrective/preventive action(s)', n=len(oc)),
                             _('Open actions past their due date.'), "safety", [c.code for c in oc]))

    # --- overdue post-blast reviews
    op = db.execute(select(m.Blast.code).join(m.PostBlastReview, m.PostBlastReview.blast_id == m.Blast.id)
                    .where(m.PostBlastReview.completed_on.is_(None), m.PostBlastReview.due_date < today)).scalars().all()
    if op:
        alerts.append(_alert("OVERDUE_POST_BLAST", "MEDIUM", _('{n} post-blast review(s) overdue', n=len(op)),
                             _('Post-blast analysis not completed by its due date.'), "postblast", list(op)))

    # --- incomplete records
    inc = []
    for b in db.scalars(select(m.Blast).where(m.Blast.status.in_(["AUTHORIZED", "IN_PROGRESS", "AWAITING_VERIFICATION", "COMPLETED", "CLOSED"]))).all():
        if not b.authorization_ref:
            inc.append(b.code)
    for d in db.scalars(select(m.DetonatorRecord).where(m.DetonatorRecord.documentation_status == "INCOMPLETE")).all():
        inc.append(f"DET-{d.blast_id}")
    for s in db.scalars(select(m.Survey).where(m.Survey.quality_status == "PENDING")).all():
        inc.append(s.code)
    if inc:
        alerts.append(_alert("INCOMPLETE_RECORDS", "LOW", _('{n} record(s) incomplete', n=len(inc)),
                             _('Records missing required documentation (authorization reference, detonator documentation, survey quality review).'), "reports", inc))

    # --- repeated operational delays (same category ≥3 in 30 d)
    dl = db.scalars(select(m.DelayEvent).where(m.DelayEvent.occurred_on >= today - timedelta(days=30))).all()
    for cat, n in Counter(x.category for x in dl).items():
        if n >= 3:
            alerts.append(_alert("REPEATED_DELAYS", "MEDIUM", _('Repeated delays — {v}', v=cat.replace('_', ' ').lower()),
                                 _('{n} delay events in the last 30 days, {v:.1f} h total.', n=n, v=sum(x.hours for x in dl if x.category == cat)), "planning",
                                 [str(x.id) for x in dl if x.category == cat]))

    # --- holes still to verify for blasts in the next 7 days
    for b in db.scalars(select(m.Blast).where(m.Blast.planned_date >= today, m.Blast.planned_date <= today + timedelta(days=7))).all():
        holes = db.scalars(select(m.Drillhole).where(m.Drillhole.pattern_id == b.pattern_id)).all()
        pend = sum(1 for h in holes if not h.measurements)
        if pend and b.status != "PLANNED":
            alerts.append(_alert("PENDING_VERIFICATION", "MEDIUM", _('{pend} hole(s) pending verification — {code}', pend=pend, code=b.code),
                                 _('Blast planned {planned_date}; {v}/{n} holes measured.', planned_date=b.planned_date, v=len(holes) - pend, n=len(holes)), "drillholes", [b.code]))

    # --- training
    for t in db.scalars(select(m.TrainingRecord).where(m.TrainingRecord.expires_on <= today + timedelta(days=30))).all():
        p = db.get(m.Personnel, t.personnel_id)
        sev = "HIGH" if t.expires_on < today else "LOW"
        if t.expires_on < today:
            title, detail = _("Training expired — {name}", name=p.full_name), _("{course} expired on {date}.", course=t.course, date=t.expires_on)
        else:
            title, detail = _("Training expires soon — {name}", name=p.full_name), _("{course} expires on {date}.", course=t.course, date=t.expires_on)
        alerts.append(_alert("TRAINING", sev, title, detail, "safety", [p.code]))

    # --- equipment down
    for e in db.scalars(select(m.Equipment).where(m.Equipment.status != "AVAILABLE")).all():
        alerts.append(_alert("EQUIPMENT_DOWN", "MEDIUM", _('Equipment unavailable — {code}', code=e.code), _('{name} status {status}.', name=e.name, status=e.status), "planning", [e.code]))

    # --- HTTPS certificate of this server (real time, not the demonstration clock)
    from .. import config
    if config.HTTPS:
        from ..ops.tls import TlsError, cert_info
        try:
            info = cert_info(config.TLS_CERT)
            if info.days_left < 30:
                alerts.append(_alert("TLS_CERTIFICATE", "CRITICAL" if info.days_left < 7 else "HIGH",
                                     _("HTTPS certificate expires in {n} day(s)", n=max(info.days_left, 0)),
                                     _("The server certificate ({names}) is valid until {date}. Renew it, then restart the server; "
                                       "after expiry browsers refuse the connection.", names=", ".join(info.names), date=info.not_after.date()),
                                     "settings"))
        except TlsError:
            pass

    alerts.sort(key=lambda a: SEV_ORDER[a["severity"]])
    return alerts
