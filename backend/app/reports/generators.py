"""Automated technical reports (PDF + CSV). Each generator returns (pdf_bytes, csv_rows)."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

import matplotlib.pyplot as plt
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..analytics.rules import run_rules
from .. import clock
from ..services.site import site_name
from ..services.kpis import compute_kpis, kpi_series
from .builder import CRIT, GOOD, MUTED, SERIES, WARN, Report, ax_style, esc, fmt
from ..i18n import N_, _, long_date, month_year

mm = 72 / 25.4


def _d(s: str | None, default: date) -> date:
    return date.fromisoformat(s) if s else default


# ------------------------------------------------------------------ narrative drafting (deterministic)
def kpi_narrative(kpis: list[dict], prev: dict[str, float | None]) -> list[str]:
    out = []
    off = [k for k in kpis if k["status"] == "OFF_TARGET"]
    on = [k for k in kpis if k["status"] == "ON_TARGET"]
    out.append(_('{n} of {n2} indicators met their target; {n3} were off target.', n=len(on), n2=len(kpis), n3=len(off)))
    for k in off:
        p = prev.get(k["key"])
        trend = ""
        if p is not None and k["value"] is not None:
            better = (k["value"] > p) if k["direction"] == "HIGHER" else (k["value"] < p)
            trend = (_(" (improving vs previous period: {prev} {unit})", prev=fmt(p), unit=k["unit"]) if better
                     else _(" (deteriorating vs previous period: {prev} {unit})", prev=fmt(p), unit=k["unit"]))
        out.append(_('<b>{v}</b>: {v2} {unit} against a target of {v3} {v4} {unit}{trend}.', v=esc(k['name']), v2=fmt(k['value']), unit=k['unit'], v3='≤' if k['direction'] == 'LOWER' else '≥', v4=fmt(k['target']), trend=trend))
    return out


# ------------------------------------------------------------------ KPI monthly
def kpi_monthly(db: Session, month: str | None, user: str):
    month = month or clock.today().strftime("%Y-%m")
    y, mo = map(int, month.split("-"))
    start = date(y, mo, 1)
    end = date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)
    pstart = date(y - (mo == 1), (mo - 2) % 12 + 1, 1)
    kpis = compute_kpis(db, start, end)
    prev = {k["key"]: k["value"] for k in compute_kpis(db, pstart, start - timedelta(days=1))}
    partial = end > clock.today()
    r = Report(_('Monthly KPI Report — {month}', month=month_year(start)), _('{v} · period {start} to {v2}{v3} · KPIs with configurable targets', v=site_name(db), start=start, v2=min(end, clock.today()), v3=_(' (month to date)') if partial else ''), user)
    r.h2(_('Summary'))
    r.bullets(kpi_narrative(kpis, prev))
    r.draft_notice()
    r.h2(_('Indicators'))
    rows = [[k["name"], f"{fmt(k['value'])} {k['unit']}", f"{'≤' if k['direction'] == 'LOWER' else '≥'} {fmt(k['target'])}",
             f"{fmt(prev.get(k['key']))}", f"{fmt(k['numerator'])} / {fmt(k['denominator'])}", k["status"]] for k in kpis]
    r.table([_('Indicator'), _('Actual'), _('Target'), _('Prev. month'), _('Num / Den'), _('Status')], rows,
            widths=[55 * mm, 24 * mm, 20 * mm, 22 * mm, 32 * mm, 27 * mm], status_col=5)
    ser = kpi_series(db, "month", date(start.year - (start.month <= 4), (start.month - 5) % 12 + 1, 1), end)  # 5 months
    fig, axes = plt.subplots(3, 5, figsize=(10, 5.6))
    for ax, k in zip(axes.flat, kpis):
        v = ser["series"][k["key"]]
        ax.plot(ser["labels"], v, color=SERIES[0], marker="o", ms=3, lw=1.6)
        if k["target"] is not None:
            ax.axhline(k["target"], color=MUTED, ls="--", lw=0.8)
        ax.set_title(k["name"], fontsize=7, color="#0b1220")
        ax_style(ax)
        ax.tick_params(axis="x", labelsize=6, rotation=45)
    for ax in list(axes.flat)[len(kpis):]:
        ax.axis("off")
    fig.tight_layout()
    r.figure(fig, title=_('Monthly trends (dashed line = target)'))
    r.h2(_('Calculation methods'))
    r.table([_('Indicator'), _('Formula')], [[k["name"], k["formula"]] for k in kpis],
            widths=[50 * mm, 130 * mm])
    if clock.is_demo():
        r.p(_('All indicators are DEMONSTRATION KPIs; targets are configurable placeholders unless replaced with authorized values.'), "note")
    else:
        r.p(_('Targets are the values configured in Settings; each must trace to an authorized site or client document.'), "note")
    return r.build(), [{"indicator": k["name"], "actual": k["value"], "unit": k["unit"], "target": k["target"], "previous": prev.get(k["key"]),
                        "numerator": k["numerator"], "denominator": k["denominator"], "status": k["status"], "formula": k["formula"]} for k in kpis]


# ------------------------------------------------------------------ daily operations
def daily(db: Session, day: str | None, user: str):
    d = _d(day, clock.today())
    people = {p.id: p.full_name for p in db.scalars(select(m.Personnel))}
    wos = {w.id: w.code for w in db.scalars(select(m.WorkOrder))}
    items = db.scalars(select(m.ScheduleItem).where(m.ScheduleItem.planned_date == d)).all()
    blasts = db.scalars(select(m.Blast).where(m.Blast.planned_date >= d - timedelta(days=3), m.Blast.planned_date <= d + timedelta(days=7))).all()
    dl = db.scalars(select(m.Delivery).where(m.Delivery.planned_date == d)).all()
    day0, day1 = datetime.combine(d, datetime.min.time()), datetime.combine(d + timedelta(days=1), datetime.min.time())
    meas = db.scalars(select(m.DrillholeMeasurement).where(m.DrillholeMeasurement.measured_at >= day0, m.DrillholeMeasurement.measured_at < day1)).all()
    tests = db.scalars(select(m.LabTest).where(m.LabTest.tested_at >= day0, m.LabTest.tested_at < day1)).all()
    vib = db.scalars(select(m.VibrationEvent).where(m.VibrationEvent.recorded_at >= day0, m.VibrationEvent.recorded_at < day1)).all()
    obs = db.scalars(select(m.SafetyObservation).where(m.SafetyObservation.observed_at >= day0, m.SafetyObservation.observed_at < day1)).all()
    downs = [e for e in db.scalars(select(m.Equipment)) if e.status != "AVAILABLE"]
    r = Report(_('Daily Operational Report — {day}', day=long_date(d)), _('{v} · drilling, blasting, QA/QC and QSSE', v=site_name(db)), user)
    r.h2(_('Summary'))
    r.bullets([_('Planned activities completed: {v} of {n}.', v=sum(1 for i in items if i.status == 'DONE'), n=len(items)),
               _('{n} drillhole measurement(s) recorded; {v} outside tolerance.', n=len(meas), v=sum(1 for x in meas if x.inspection_status != 'WITHIN_TOLERANCE')),
               _('{n} product test(s); {v} out of specification.', n=len(tests), v=sum(1 for t in tests if t.result == 'FAIL')),
               _('{n} vibration record(s); {v} above the configured reference.', n=len(vib), v=sum(1 for v in vib if v.compliance == 'EXCEEDANCE')),
               _('{n} safety observation(s) raised. Equipment unavailable: {v}.', n=len(obs), v=', '.join(e.code for e in downs) or _('none'))])
    r.draft_notice()
    r.h2(_('Planned activities'))
    r.table([_('Work order'), _('Activity'), _('Status'), _('Responsible'), _('Resources')],
            [[wos[i.work_order_id], i.activity.replace("_", " ").title(), i.status, people.get(i.responsible_id), i.resources] for i in items],
            widths=[30 * mm, 40 * mm, 25 * mm, 40 * mm, 45 * mm], status_col=2)
    r.h2(_('Blast pipeline'))
    r.table([_('Blast'), _('Planned'), _('Status'), _('Approved plan'), _('External authorization')],
            [[b.code, b.planned_date.isoformat(), b.status, b.approved_plan_ref, b.authorization_ref or "—"] for b in blasts],
            widths=[30 * mm, 25 * mm, 40 * mm, 40 * mm, 45 * mm])
    r.h2(_('Deliveries'))
    r.table([_('Delivery'), _('Product'), _('Planned (t)'), _('Delivered (t)'), _('Status')],
            [[x.code, x.product_name, fmt(x.planned_qty), fmt(x.delivered_qty), x.status] for x in dl], widths=[25 * mm, 70 * mm, 25 * mm, 25 * mm, 35 * mm])
    r.h2(_('Open alerts'))
    al = run_rules(db, clock.today())
    r.table([_('Severity'), _('Alert'), _('Detail')], [[a["severity"], a["title"], a["detail"]] for a in al], widths=[20 * mm, 55 * mm, 105 * mm], max_rows=15)
    return r.build(), [{"work_order": wos[i.work_order_id], "activity": i.activity, "planned_date": i.planned_date, "status": i.status,
                        "responsible": people.get(i.responsible_id)} for i in items]


# ------------------------------------------------------------------ blast activity
def blast_report(db: Session, blast_id: int, user: str):
    from ..routers.blasting import blast_detail
    from ..routers.postblast import collected

    d = blast_detail(blast_id, db)
    b = db.get(m.Blast, blast_id)
    c = collected(db, b)
    review = db.scalars(select(m.PostBlastReview).where(m.PostBlastReview.blast_id == b.id)).first()
    r = Report(_('Blasting Activity Report — {code}', code=d['code']), _('{bench} · planned {planned_date} · status {status} · approved plan {approved_plan_ref}', bench=d['bench'], planned_date=d['planned_date'], status=d['status'], approved_plan_ref=d['approved_plan_ref']), user)
    r.p(d["notice"], "note")
    r.h2(_('Identification'))
    a = d["authorization"]
    r.kv([(_('Work order'), d["work_order"]["code"]), (_('Pattern'), d["pattern"]), (_('Supervisor'), d["supervisor"]), (_('Blaster'), d["blaster"]),
          (_('Equipment'), d["equipment"]), (_('Fired at'), d["fired_at"] or "—"), (_('External authorization'), a["ref"] or "—"),
          (_('Issued by'), f"{a['by'] or '—'} ({a['role'] or '—'})"), (_('Engineering forecast'), d["work_order"]["engineering_forecast_ref"]),
          (_('Forecast / actual (t)'), f"{fmt(d['work_order']['forecast_tonnes'], 0)} / {fmt(d['work_order']['actual_tonnes'], 0)}")])
    r.h2(_('Quality checkpoints'))
    r.table([_('Stage'), _('Checkpoint'), _('Done'), _('By'), _('Evidence')],
            [[x["stage"], x["name"], "YES" if x["completed"] else "OPEN", x["completed_by"] or "", x["evidence_ref"] or ""] for x in d["checkpoints"]],
            widths=[25 * mm, 75 * mm, 15 * mm, 30 * mm, 35 * mm])
    inv = d["inventory"]
    r.h2(_('Product inventory reconciliation (administrative)'))
    r.kv([(_('Received'), f"{inv['received']} {inv['unit']}"), (_('Used'), f"{inv['used']} {inv['unit']}"), (_('Returned'), f"{inv['returned']} {inv['unit']}"),
          (_('Balance'), f"{inv['balance']} {inv['unit']} — {_('reconciled') if inv['reconciled'] else _('NOT reconciled')}")])
    r.h2(_('Verification and monitoring'))
    dh = c["drillholes"]
    r.bullets([_('Drillholes: {measured}/{holes} measured, {out_of_tolerance} outside tolerance ({v}%).', measured=dh['measured'], holes=dh['holes'], out_of_tolerance=dh['out_of_tolerance'], v=fmt(dh['deviation_rate_pct'])),
               _('Surveys: {v}.', v=', '.join(s['code'] + ' (' + s['quality'] + ')' for s in c['surveys']) or _('none')),
               _("Vibration: {v}.", v="; ".join("%s %s mm/s %s" % (v["station"], fmt(v["ppv_mm_s"], 2), v["compliance"]) for v in c["vibration"]) or _("none")),
               _("Delays: {v}.", v="; ".join("%s %s h" % (x["category"], fmt(x["hours"])) for x in c["delays"]) or _("none"))])
    if review:
        r.h2(_('Post-blast review'))
        r.kv([(_('Stage'), review.stage), (_('Fragmentation (1–5)'), review.fragmentation_rating), (_('Fragmentation'), review.fragmentation_observation),
              (_('Geology'), review.geology_observation), (_('Deviations'), review.operational_deviations), (_('Lessons learned'), review.lessons_learned),
              (_('Improvement proposal'), review.improvement_proposal), (_('Engineering review'), review.engineering_review_status)], cols=1)
    r.h2(_('Status history'))
    r.table([_('From'), _('To'), _('At'), _('By'), _('Note')], [[h["from"] or "", h["to"], h["at"][:16], h["by"], h["note"] or ""] for h in d["history"]],
            widths=[30 * mm, 30 * mm, 28 * mm, 30 * mm, 62 * mm])
    return r.build(), [{"stage": x["stage"], "checkpoint": x["name"], "completed": x["completed"], "by": x["completed_by"], "evidence": x["evidence_ref"]}
                       for x in d["checkpoints"]]


# ------------------------------------------------------------------ 3D survey
def survey_report(db: Session, survey_id: int, user: str):
    from ..geometry import face as g
    from ..routers import surveys as sv

    d = sv.survey_detail(survey_id, db)
    st = sv.survey_stats(survey_id, None, db)
    r = Report(_('3D Survey Report — {code}', code=d['code']), _('{v} · {area} {v2} · {v3}', v=d['survey_type'].replace('_', ' ').title(), area=d['area'], v2=d['bench'] or '', v3=d['surveyed_at'][:16]), user)
    r.h2(_('Survey identification and quality'))
    r.kv([(_('Instrument'), d["instrument"]), (_('Operator'), d["operator"]), (_('Scanned points'), fmt(d["point_count"])),
          (_('Displayed sample'), fmt(d["display_points"])), (_('Point spacing'), f"{fmt(d['point_spacing_mm'])} mm"),
          (_('Registration error'), f"{fmt(d['registration_error_mm'])} mm"), (_('Coordinates'), d["coordinate_system"]),
          (_('Quality status'), d["quality_status"]), (_('Linked blast'), d["blast"] or "—"), (_('Quality notes'), d["quality_notes"] or "—")])
    if st.get("count"):
        r.h2(_('Geometric deviation — {reference}', reference=st['reference']))
        tol = st["tolerance_m"]
        r.p(_("Region: {region}. ", region=st['region']) + (_("Tolerance ±{tol} m ({source}). ", tol=fmt(tol, 2), source=esc(st['tolerance_source'])) if tol else
                                                            _("Face tolerance not configured (FACE_TOL in Settings). ")) + esc(st['sign_convention']), "small")
        r.kv([(_('Within tolerance'), f"{st['within_tolerance_pct']} %" if tol else "—"), (_('Mean'), f"{st['mean_m']} m"), (_('Std deviation'), f"{st['std_m']} m"),
              (_('P5 / P95'), f"{st['p05_m']} / {st['p95_m']} m"), (_('Max |deviation|'), f"{st['max_abs_m']} m"),
              (_('In front / behind beyond tolerance'), f"{st['above_tolerance_pct']} % / {st['below_tolerance_pct']} %" if tol else "—")])
        e, cts = st["histogram"]["edges"], st["histogram"]["counts"]
        fig, ax = plt.subplots(figsize=(7, 2.2))
        mids = [(e[i] + e[i + 1]) / 2 for i in range(len(cts))]
        ax.bar(mids, cts, width=0.09, color=[MUTED if not tol else (CRIT if x > tol else (SERIES[0] if x < -tol else MUTED)) for x in mids])
        for t in ((-tol, tol) if tol else ()):
            ax.axvline(t, color="#0b1220", ls="--", lw=0.8)
        ax.set_xlabel(_('Signed deviation (m)'), fontsize=7)
        ax_style(ax)
        r.figure(fig, 150)
    if not d["imported"] and d["survey_type"] != "POST_BLAST":
        cloud = sv.load_cloud(db, db.get(m.Survey, survey_id))
        xs = cloud.xyz[:, 0]
        x0 = float((xs.min() + xs.max()) / 2)
        sec = g.section(cloud, x0)
        _b, _bl, _p, length, height, _r = sv._geometry_params(db, db.get(m.Survey, survey_id))
        des = g.section(g.design_cloud(length, height), x0)
        fig, ax = plt.subplots(figsize=(7, 2.6))
        ax.scatter([p[0] for p in des], [p[1] for p in des], s=1, color=SERIES[1], label=_('Design face'))
        ax.scatter([p[0] for p in sec], [p[1] for p in sec], s=1, color=SERIES[0], label=_('Surveyed'))
        ax.set_aspect("equal")
        ax.set_xlabel(_('Horizontal distance from design crest (m)'), fontsize=7)
        ax.set_ylabel(_('Elevation above toe (m)'), fontsize=7)
        ax.legend(fontsize=7, markerscale=6, frameon=False)
        ax_style(ax)
        r.figure(fig, 150, title=_('Face profile — vertical section at x = {x0} m', x0=fmt(x0, 1)))
        fr = sv.front_row(survey_id, db)
        r.h2(_('Front-row distance to free face (geometric measurement)'))
        r.table([_('Hole'), _('x (m)'), _('Crest (m)'), _('Minimum (m) @ z'), _('Toe (m)'), _('Reference check')],
                [[h["hole_code"], h["x"], fmt(h.get("crest_distance_m"), 2), f"{fmt(h.get('min_distance_m'), 2)} @ {fmt(h.get('min_at_z_m'), 1)}",
                  fmt(h.get("toe_distance_m"), 2), ", ".join(h["flags"]) or _("In range")] for h in fr["holes"]],
                widths=[20 * mm, 18 * mm, 25 * mm, 35 * mm, 22 * mm, 60 * mm])
        r.p(esc(fr["note"]), "note")
    r.p((_("Synthetic demonstration survey. ") if not d["imported"] else "")
        + _("Limitations: decimated display sample; nearest-neighbour point-to-plane comparison; no registration of imported data."), "note")
    return r.build(), [{"metric": k, "value": v} for k, v in st.items() if k not in ("histogram",)]


# ------------------------------------------------------------------ drillhole verification
def drillhole_report(db: Session, pattern_id: int, user: str):
    from ..routers.drillholes import pattern_detail

    d = pattern_detail(pattern_id, db)
    s, t = d["stats"], d["tolerances"]
    r = Report(_('Drillhole Verification Report — {code}', code=d['code']), _('{bench} · {rock_type} · design {design_document_ref}', bench=d['bench'], rock_type=d['rock_type'], design_document_ref=d['design_document_ref']), user)
    r.h2(_('Summary'))
    r.bullets([_('{measured} of {holes} holes verified ({v} %); {outstanding} outstanding.', measured=s['measured'], holes=s['holes'], v=fmt(s['inspected_pct']), outstanding=s['outstanding']),
               _('{deviations} hole(s) outside tolerance ({v} % of measured); {redrill} redrill request(s); {accepted_by_engineer} accepted by engineer.', deviations=s['deviations'], v=fmt(s['deviation_rate_pct']), redrill=s['redrill'], accepted_by_engineer=s['accepted_by_engineer']),
               _('Average |Δ depth| {v} m; average toe deviation {v2} m; {water_holes} hole(s) with water.', v=fmt(s['avg_abs_depth_diff_m'], 2), v2=fmt(s['avg_toe_deviation_m'], 2), water_holes=s['water_holes']),
               (_("Tolerances: depth {dmin} / +{dmax} m, toe deviation ≤ {toe} m — source: {source}.", dmin=fmt(t['depth_min_m'], 2), dmax=fmt(t['depth_max_m'], 2),
                  toe=fmt(t['toe_deviation_max_m'], 2), source=esc(t['source']))
                if t["configured"] else _("Tolerances: not configured (DEPTH_TOL / DEVIATION_TOL in Settings)."))])
    r.draft_notice()
    holes = [h for h in d["holes"] if h["depth_diff_m"] is not None]
    if holes:
        fig, ax = plt.subplots(figsize=(7.5, 2.3))
        col = {"WITHIN_TOLERANCE": GOOD, "OUT_OF_TOLERANCE": CRIT, "REDRILL_REQUIRED": "#ec835a", "ACCEPTED_BY_ENGINEER": WARN}
        ax.bar(range(len(holes)), [h["depth_diff_m"] for h in holes], color=[col.get(h["status"], MUTED) for h in holes])
        if t["configured"]:
            ax.axhspan(t["depth_min_m"], t["depth_max_m"], color=GOOD, alpha=0.08)
        ax.axhline(0, color="#c3c2b7", lw=0.8)
        ax.set_ylabel(_('Δ depth (m)'), fontsize=7)
        ax.set_xticks(range(len(holes)), [h["hole_code"] for h in holes], rotation=90, fontsize=5)
        ax_style(ax)
        r.figure(fig, title=_('Measured − planned depth per hole (band = tolerance)'))
    r.h2(_('Approved loading parameters (document reference only)'))
    r.table([_('Document'), _('Rev'), _('Approved by'), _('Date'), _('Note')], [[a["document_ref"], a["revision"], a["approved_by"], a["approved_on"], a["notes"]] for a in d["approved_loading_records"]],
            widths=[25 * mm, 12 * mm, 40 * mm, 22 * mm, 81 * mm])
    r.h2(_('Hole register'))
    r.table([_('Hole'), _('Planned (m)'), _('Measured (m)'), _('Δ (m)'), _('Toe dev (m)'), _('Water'), _('Status'), _('Technician')],
            [[h["hole_code"], fmt(h["planned_depth_m"], 2), fmt(h["measured_depth_m"], 2), fmt(h["depth_diff_m"], 2), fmt(h["toe_deviation_m"], 2),
              "yes" if h["water_present"] else "", h["status"], h["technician"] or ""] for h in d["holes"]],
            widths=[15 * mm, 20 * mm, 22 * mm, 16 * mm, 20 * mm, 13 * mm, 40 * mm, 34 * mm], status_col=6)
    if d["capa"]:
        r.h2(_('Corrective actions'))
        r.table([_('Action'), _('Description'), _('Owner'), _('Due'), _('Status')], [[c["code"], c["description"], c["owner"], c["due_date"], c["status"]] for c in d["capa"]],
                widths=[22 * mm, 90 * mm, 30 * mm, 20 * mm, 18 * mm])
    return r.build(), d["holes"]


# ------------------------------------------------------------------ laboratory
def lab_report(db: Session, start: str | None, end: str | None, user: str):
    from ..routers.lab import list_tests, summary

    e = _d(end, clock.today())
    s = _d(start, e - timedelta(days=29))
    tests = list_tests(start=s, end=e, db=db)
    sm = summary(db)
    r = Report(_('Product Laboratory Report'), _('Period {s} to {e} · viscosity, density, VOD, flowability, NOx', s=s, e=e), user)
    by = defaultdict(Counter)
    for t in tests:
        by[t["test_type"]][t["result"]] += 1
    r.h2(_('Summary'))
    fails = [t for t in tests if t["result"] == "FAIL"]
    inval = [t for t in tests if not t["calibration_valid"]]
    r.bullets([_('{n} tests recorded; {n2} out of specification; {n3} recorded on an instrument with expired calibration (not evaluated).', n=len(tests), n2=len(fails), n3=len(inval)),
               _('Open non-conformances: {v}; batches on QC hold: {v2}.', v=sum(1 for n in sm['nonconformances'] if n['status'] == 'OPEN'), v2=', '.join(b['code'] for b in sm['batches_on_hold']) or _('none')),
               _('Specifications applied are the configured reference limits; any flagged DEMO PLACEHOLDER must be replaced from authorized documents.')])
    r.draft_notice()
    types = ["VISCOSITY", "DENSITY", "VOD", "FLOWABILITY", "NOX"]
    fig, ax = plt.subplots(figsize=(7, 2.2))
    bottom = [0] * 5
    for res, c in (("PASS", SERIES[0]), ("FAIL", CRIT), ("NOT_EVALUATED", MUTED)):
        vals = [by[tt][res] for tt in types]
        ax.bar(types, vals, bottom=bottom, color=c, label=res.replace("_", " ").title(), edgecolor="white", linewidth=1)
        bottom = [a + b for a, b in zip(bottom, vals)]
    ax.legend(fontsize=7, frameon=False, ncols=3)
    ax_style(ax)
    r.figure(fig, 150, title=_('Results by test type'))
    r.h2(_('Out-of-specification and not-evaluated results'))
    r.table([_('Test'), _('Date'), _('Type'), _('Batch/blast'), _('Value'), _('Limit'), _('Instrument'), _('Result')],
            [[t["code"], t["tested_at"][:10], t["test_type"], t["batch"] or t["blast"], f"{fmt(t['value'], 3)} {t['unit']}",
              f"{fmt(t['limit_min'])}–{fmt(t['limit_max'])}", t["instrument"], t["result"]] for t in tests if t["result"] != "PASS"],
            widths=[22 * mm, 18 * mm, 22 * mm, 24 * mm, 26 * mm, 24 * mm, 18 * mm, 26 * mm], status_col=7)
    r.h2(_('Instrument calibration status'))
    r.table([_('Instrument'), _('Name'), _('Certificate'), _('Valid until'), _('Status')],
            [[i["code"], i["name"], i.get("certificate", ""), i["valid_until"], i["status"]] for i in sm["instruments"]],
            widths=[22 * mm, 60 * mm, 40 * mm, 25 * mm, 33 * mm], status_col=4)
    r.h2(_('Non-conformances'))
    r.table([_('NC'), _('Raised'), _('Batch'), _('Description'), _('Disposition'), _('Status')],
            [[n["code"], n["raised_on"], n["batch"] or "", n["description"], n["disposition"] or "", n["status"]] for n in sm["nonconformances"]],
            widths=[18 * mm, 20 * mm, 24 * mm, 76 * mm, 24 * mm, 18 * mm])
    return r.build(), tests


# ------------------------------------------------------------------ vibration
def vibration_report(db: Session, start: str | None, end: str | None, user: str):
    from ..routers.vibration import events, stations

    e = _d(end, clock.today())
    s = _d(start, e - timedelta(days=29))
    ev = [x for x in events(db=db) if s.isoformat() <= x["recorded_at"][:10] <= e.isoformat()]
    stn = stations(db)
    r = Report(_('Vibration Monitoring Report'), _('Period {s} to {e} · peak particle velocity, frequency and data quality', s=s, e=e), user)
    r.h2(_('Summary'))
    exc = [x for x in ev if x["compliance"] == "EXCEEDANCE"]
    nq = [x for x in ev if x["data_quality"] != "VALID"]
    rising = [x["code"] for x in stn if x["trend_slope_mm_s_per_event"] > 0.15]
    r.bullets([_('{n} monitoring records; {n2} above the configured reference value; {n3} not valid (no trigger / questionable / invalid).', n=len(ev), n2=len(exc), n3=len(nq)),
               _('Stations with a rising trend over the last valid events: {v}.', v=', '.join(rising) or _('none')),
               _('Reference values are the configured limits (source document shown in Settings); applicable limits come from the site permit, client requirements or regulation.')])
    for x in exc:
        r.bullets([_('<b>{code}</b> at {station}: {ppv_mm_s} mm/s vs {limit_ppv_mm_s} mm/s ({pct_of_limit} %), {dominant_frequency_hz} Hz.', code=x['code'], station=x['station'], ppv_mm_s=x['ppv_mm_s'], limit_ppv_mm_s=x['limit_ppv_mm_s'], pct_of_limit=x['pct_of_limit'], dominant_frequency_hz=x['dominant_frequency_hz'])])
    r.draft_notice()
    fig, ax = plt.subplots(figsize=(7.5, 2.6))
    for i, sc in enumerate(sorted({x["station"] for x in ev})):
        pts = sorted([x for x in ev if x["station"] == sc and x["ppv_mm_s"] is not None], key=lambda x: x["recorded_at"])
        ax.plot([p["recorded_at"][5:10] for p in pts], [p["ppv_mm_s"] for p in pts], marker="o", ms=3, lw=1.2, label=sc,
                color=(SERIES + ["#e87ba4"])[i % 4])
    lim = next((x["limit_ppv_mm_s"] for x in stn if x["limit_ppv_mm_s"]), None)
    if lim:
        ax.axhline(lim, color="#0b1220", ls="--", lw=0.8)
    ax.set_ylabel(_('PPV (mm/s)'), fontsize=7)
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=7, frameon=False, ncols=4)
    ax.tick_params(axis="x", rotation=60, labelsize=6)
    ax_style(ax)
    r.figure(fig, title=_('PPV by station (dashed = configured reference)'))
    r.h2(_('Station summary'))
    r.table([_('Station'), _('Name'), _('Events'), _('Valid %'), _('Max PPV 30 d'), _('Exceedances'), _('Trend (mm/s/event)')],
            [[x["code"], x["name"], x["events"], fmt(x["valid_pct"]), fmt(x["max_ppv_30d"], 2), x["exceedances"], fmt(x["trend_slope_mm_s_per_event"], 3)] for x in stn],
            widths=[16 * mm, 58 * mm, 16 * mm, 18 * mm, 24 * mm, 22 * mm, 26 * mm])
    r.h2(_('Monitoring records'))
    r.table([_('Event'), _('Date'), _('Station'), _('Blast'), _('PPV'), _('Hz'), _('Quality'), _('Compliance')],
            [[x["code"], x["recorded_at"][:16], x["station"], x["blast"] or "", fmt(x["ppv_mm_s"], 2), fmt(x["dominant_frequency_hz"]), x["data_quality"], x["compliance"]] for x in ev],
            widths=[30 * mm, 26 * mm, 16 * mm, 24 * mm, 16 * mm, 14 * mm, 26 * mm, 28 * mm], status_col=7, max_rows=60)
    return r.build(), ev


# ------------------------------------------------------------------ QA/QC
def qaqc_report(db: Session, start: str | None, end: str | None, user: str):
    e = _d(end, clock.today())
    s = _d(start, e - timedelta(days=29))
    k = {x["key"]: x for x in compute_kpis(db, s, e)}
    day0, day1 = datetime.combine(s, datetime.min.time()), datetime.combine(e + timedelta(days=1), datetime.min.time())
    surveys = db.scalars(select(m.Survey).where(m.Survey.surveyed_at >= day0, m.Survey.surveyed_at < day1)).all()
    vib = db.scalars(select(m.VibrationEvent).where(m.VibrationEvent.recorded_at >= day0, m.VibrationEvent.recorded_at < day1)).all()
    ncs = db.scalars(select(m.NonConformance)).all()
    capa = db.scalars(select(m.Capa).where(m.Capa.status != "CLOSED")).all()
    r = Report(_('QA/QC Report'), _('Period {s} to {e} · drillholes, 3D surveys, product testing, monitoring data and documentation', s=s, e=e), user)
    r.h2(_('Quality indicators'))
    keys = ["drillhole_inspection_compliance", "drillhole_deviation_rate", "survey_completion", "product_qaqc_compliance", "lab_testing_completion",
            "vibration_monitoring_compliance", "documentation_completeness", "capa_closure_rate"]
    r.table([_('Indicator'), _('Actual'), _('Target'), _('Num / Den'), _('Status')],
            [[k[x]["name"], f"{fmt(k[x]['value'])} {k[x]['unit']}", fmt(k[x]["target"]), f"{fmt(k[x]['numerator'])} / {fmt(k[x]['denominator'])}", k[x]["status"]] for x in keys],
            widths=[65 * mm, 25 * mm, 20 * mm, 40 * mm, 30 * mm], status_col=4)
    r.h2(_('Data quality'))
    r.bullets([_("3D surveys: {n} — {detail}.", n=len(surveys), detail=", ".join(f"{q} {n}" for q, n in Counter(x.quality_status for x in surveys).items())),
               _("Vibration records: {n} — {detail}.", n=len(vib), detail=", ".join(f"{q} {n}" for q, n in Counter(x.data_quality for x in vib).items())),
               _('Non-conformances open: {v}; corrective actions open: {n} ({v2} overdue).', v=sum(1 for n in ncs if n.status == 'OPEN'), n=len(capa), v2=sum(1 for c in capa if c.due_date < clock.today()))])
    r.h2(_('Detected issues'))
    al = [a for a in run_rules(db, clock.today()) if a["rule"] not in ("TRAINING", "EQUIPMENT_DOWN")]
    r.table([_('Severity'), _('Rule'), _('Finding'), _('Records')], [[a["severity"], a["rule"], a["detail"], ", ".join(a["refs"][:5])] for a in al],
            widths=[18 * mm, 42 * mm, 80 * mm, 40 * mm])
    r.draft_notice()
    return r.build(), [{"indicator": k[x]["name"], "actual": k[x]["value"], "target": k[x]["target"], "status": k[x]["status"]} for x in keys]


CATALOG = {
    "daily": {"title": N_("Daily operational report"), "params": ["day"], "fn": lambda db, p, u: daily(db, p.get("day"), u)},
    "blast": {"title": N_("Blasting activity report"), "params": ["blast_id"], "fn": lambda db, p, u: blast_report(db, int(p["blast_id"]), u)},
    "survey": {"title": N_("3D survey report"), "params": ["survey_id"], "fn": lambda db, p, u: survey_report(db, int(p["survey_id"]), u)},
    "drillholes": {"title": N_("Drillhole verification report"), "params": ["pattern_id"], "fn": lambda db, p, u: drillhole_report(db, int(p["pattern_id"]), u)},
    "laboratory": {"title": N_("Product laboratory report"), "params": ["start", "end"], "fn": lambda db, p, u: lab_report(db, p.get("start"), p.get("end"), u)},
    "vibration": {"title": N_("Vibration monitoring report"), "params": ["start", "end"], "fn": lambda db, p, u: vibration_report(db, p.get("start"), p.get("end"), u)},
    "qaqc": {"title": N_("QA/QC report"), "params": ["start", "end"], "fn": lambda db, p, u: qaqc_report(db, p.get("start"), p.get("end"), u)},
    "kpi-monthly": {"title": N_("Monthly KPI report"), "params": ["month"], "fn": lambda db, p, u: kpi_monthly(db, p.get("month"), u)},
}
