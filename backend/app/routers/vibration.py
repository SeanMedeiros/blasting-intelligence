"""Module 07 — Vibration and blast monitoring.

Reference values are configurable (reference_limit PPV, per station or '*'); none is a
regulatory value. Waveforms are SIMULATED from each event's stored PPV components and
dominant frequency.
"""
from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import clock
from ..db import get_db
from ..services.audit import limit, record
from ..services.security import require
from ..i18n import _

router = APIRouter(prefix="/api/v1/vibration", tags=["Vibration monitoring"])


def _row(e: m.VibrationEvent, stations, blasts) -> dict:
    s = stations[e.station_id]
    return {"id": e.id, "code": e.code, "station": s.code, "station_name": s.name, "station_type": s.station_type,
            "blast": blasts.get(e.blast_id), "recorded_at": e.recorded_at.isoformat(), "distance_m": e.distance_m,
            "ppv_mm_s": e.ppv_mm_s, "ppv_transverse": e.ppv_transverse, "ppv_vertical": e.ppv_vertical,
            "ppv_longitudinal": e.ppv_longitudinal, "dominant_frequency_hz": e.dominant_frequency_hz,
            "air_overpressure_db": e.air_overpressure_db, "data_quality": e.data_quality, "quality_notes": e.quality_notes,
            "limit_ppv_mm_s": e.limit_ppv_mm_s, "compliance": e.compliance,
            "pct_of_limit": round(100 * e.ppv_mm_s / e.limit_ppv_mm_s, 1) if e.ppv_mm_s and e.limit_ppv_mm_s else None}


def _maps(db):
    return ({s.id: s for s in db.scalars(select(m.MonitorStation))}, {b.id: b.code for b in db.scalars(select(m.Blast))})


@router.get("/events")
def events(station: str | None = None, quality: str | None = None, compliance: str | None = None, db: Session = Depends(get_db)):
    st, bl = _maps(db)
    rows = [_row(e, st, bl) for e in db.scalars(select(m.VibrationEvent).order_by(m.VibrationEvent.recorded_at.desc()))]
    return [r for r in rows if (not station or r["station"] == station) and (not quality or r["data_quality"] == quality)
            and (not compliance or r["compliance"] == compliance)]


@router.get("/stations")
def stations(db: Session = Depends(get_db)):
    st, bl = _maps(db)
    ins = {i.id: i for i in db.scalars(select(m.Instrument))}
    out = []
    since = datetime.combine(clock.today() - timedelta(days=30), datetime.min.time())
    ev = defaultdict(list)
    for e in db.scalars(select(m.VibrationEvent).order_by(m.VibrationEvent.recorded_at)):
        ev[e.station_id].append(e)
    for s in st.values():
        es = ev[s.id]
        recent = [e for e in es if e.recorded_at >= since]
        valid = [e for e in es if e.data_quality == "VALID" and e.ppv_mm_s is not None]
        lim = limit(db, "PPV", s.code)
        last8 = [e.ppv_mm_s for e in valid[-8:]]
        slope = float(np.polyfit(range(len(last8)), last8, 1)[0]) if len(last8) >= 3 else 0.0
        i = ins.get(s.instrument_id)
        cal = max(i.calibrations, key=lambda c: c.valid_until) if i and i.calibrations else None
        out.append({"code": s.code, "name": s.name, "type": s.station_type, "instrument": i.code if i else None,
                    "calibration_valid_until": cal.valid_until.isoformat() if cal else None,
                    "events": len(es), "events_30d": len(recent), "valid_pct": round(100 * len(valid) / len(es), 1) if es else None,
                    "max_ppv_30d": max((e.ppv_mm_s for e in recent if e.ppv_mm_s is not None and e.data_quality == "VALID"), default=None),
                    "mean_ppv": round(float(np.mean([e.ppv_mm_s for e in valid])), 2) if valid else None,
                    "exceedances": sum(1 for e in es if e.compliance == "EXCEEDANCE"),
                    "trend_slope_mm_s_per_event": round(slope, 3),
                    "limit_ppv_mm_s": lim.max_value if lim else None, "limit_source": lim.source_document if lim else None,
                    "limit_is_demo": bool(lim and lim.is_demo_placeholder)})
    return out


@router.get("/events/{eid}")
def event(eid: int, db: Session = Depends(get_db)):
    e = db.get(m.VibrationEvent, eid)
    if e is None:
        raise HTTPException(404, _('Event not found'))
    st, bl = _maps(db)
    return _row(e, st, bl)


@router.get("/events/{eid}/waveform")
def waveform(eid: int, db: Session = Depends(get_db)):
    """SIMULATED three-component particle-velocity waveform consistent with the stored peaks."""
    e = db.get(m.VibrationEvent, eid)
    if e is None:
        raise HTTPException(404, _('Event not found'))
    if e.ppv_mm_s is None:
        return {"simulated": True, "available": False, "reason": _("No waveform — data quality {quality}", quality=e.data_quality)}
    fs, dur = 512, 2.0
    t = np.arange(int(fs * dur)) / fs
    rng = np.random.default_rng(e.waveform_seed or e.id)
    f0 = e.dominant_frequency_hz or 20.0
    out = {}
    for name, peak in (("transverse", e.ppv_transverse), ("vertical", e.ppv_vertical), ("longitudinal", e.ppv_longitudinal)):
        sig = np.zeros_like(t)
        for k in range(rng.integers(3, 6)):
            t0 = 0.25 + rng.uniform(0, 0.35)
            f = f0 * rng.uniform(0.7, 1.35)
            tau = rng.uniform(0.08, 0.22)
            env = np.where(t >= t0, np.exp(-(t - t0) / tau) * (1 - np.exp(-(t - t0) / 0.01)), 0)
            sig += rng.uniform(0.4, 1.0) * env * np.sin(2 * math.pi * f * (t - t0) + rng.uniform(0, 6.28))
        sig += rng.normal(0, 0.01, len(t))
        sig = sig / np.abs(sig).max() * (peak or 0)
        out[name] = [round(float(v), 3) for v in sig]
    return {"simulated": True, "available": True, "sample_rate_hz": fs, "duration_s": dur, "unit": "mm/s",
            "t": [round(float(v), 4) for v in t], **out}


class QualityIn(BaseModel):
    data_quality: str = Field(..., pattern="^(VALID|QUESTIONABLE|NO_TRIGGER|INVALID)$")
    quality_notes: str = Field(..., min_length=5, max_length=500)


def _compliance(ppv: float | None, quality: str, lim: float | None) -> str:
    if quality != "VALID" or ppv is None or lim is None:
        return "NOT_EVALUATED"
    return "EXCEEDANCE" if ppv > lim else "COMPLIANT"


@router.patch("/events/{eid}/quality")
def set_quality(eid: int, body: QualityIn, db: Session = Depends(get_db), user: str = Depends(require("vibration.write"))):
    e = db.get(m.VibrationEvent, eid)
    if e is None:
        raise HTTPException(404, _('Event not found'))
    before = {"data_quality": e.data_quality, "compliance": e.compliance}
    e.data_quality, e.quality_notes = body.data_quality, body.quality_notes
    e.compliance = _compliance(e.ppv_mm_s, e.data_quality, e.limit_ppv_mm_s)
    record(db, "vibration_event", e.id, "UPDATE", user, {"before": before, "after": {**body.model_dump(), "compliance": e.compliance}})
    db.commit()
    return {"id": e.id, "data_quality": e.data_quality, "compliance": e.compliance}


SAMPLE = ("station_code,recorded_at,ppv_mm_s,ppv_transverse,ppv_vertical,ppv_longitudinal,dominant_frequency_hz,"
          "air_overpressure_db,distance_m,blast_code\n"
          "V-01,2026-12-04T12:01:00,2.35,2.35,1.80,1.42,18.5,112.0,1450,BL-26-0436\n"
          "V-03,2026-12-04T12:01:00,4.10,3.20,4.10,2.95,14.0,115.5,1720,BL-26-0436\n")


@router.get("/import/sample.csv")
def sample():
    return Response(SAMPLE, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="vibration_import_sample.csv"'})


@router.post("/import")
async def import_csv(file: UploadFile = File(...), dry_run: bool = False, db: Session = Depends(get_db), user: str = Depends(require("vibration.write"))):
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    need = {"station_code", "recorded_at", "ppv_mm_s", "dominant_frequency_hz"}
    if not reader.fieldnames or not need <= set(reader.fieldnames):
        raise HTTPException(422, _('Required columns: {v}', v=', '.join(sorted(need))))
    st = {s.code: s for s in db.scalars(select(m.MonitorStation))}
    blasts = {b.code: b for b in db.scalars(select(m.Blast))}
    accepted, errors = [], []

    def num(v, name, lo, hi, required=False):
        if v in (None, ""):
            if required:
                raise ValueError(_('{name} is required', name=name))
            return None
        x = float(v)
        if not lo <= x <= hi:
            raise ValueError(_('{name}={x} outside plausible range {lo}–{hi}', name=name, x=x, lo=lo, hi=hi))
        return x

    for i, r in enumerate(reader, start=2):
        try:
            s = st.get((r.get("station_code") or "").strip())
            if s is None:
                raise ValueError(_("unknown station '{v}'", v=r.get('station_code')))
            if s.instrument_id is None:
                raise ValueError(_('station {code} has no seismograph assigned (Master Data → Monitoring stations)', code=s.code))
            when = datetime.fromisoformat(r["recorded_at"].strip())
            if when.date() > clock.today() + timedelta(days=1):
                raise ValueError(_('recorded_at is in the future'))
            ppv = num(r.get("ppv_mm_s"), "ppv_mm_s", 0, 300, True)
            comps = [num(r.get(k), k, 0, 300) for k in ("ppv_transverse", "ppv_vertical", "ppv_longitudinal")]
            if all(c is not None for c in comps) and abs(max(comps) - ppv) > 0.05 * max(ppv, 0.1) + 0.01:
                raise ValueError(_('ppv_mm_s must equal the largest component (peak component velocity)'))
            freq = num(r.get("dominant_frequency_hz"), "dominant_frequency_hz", 0.5, 300, True)
            aop = num(r.get("air_overpressure_db"), "air_overpressure_db", 60, 180)
            dist = num(r.get("distance_m"), "distance_m", 1, 50_000)
            bcode = (r.get("blast_code") or "").strip()
            if bcode and bcode not in blasts:
                raise ValueError(_("unknown blast '{bcode}'", bcode=bcode))
            code = f"VE-IMP-{s.code}-{when:%y%m%d%H%M}"
            if db.scalars(select(m.VibrationEvent).where(m.VibrationEvent.code == code)).first() or any(a["code"] == code for a in accepted):
                raise ValueError(_('duplicate event {code}', code=code))
            lim = limit(db, "PPV", s.code)
            accepted.append({"code": code, "station": s, "when": when, "ppv": ppv, "comps": comps, "freq": freq, "aop": aop,
                             "dist": dist, "blast": blasts.get(bcode), "limit": lim.max_value if lim else None})
        except (ValueError, KeyError) as ex:
            errors.append({"row": i, "error": str(ex)})
    created = []
    if not dry_run:
        for a in accepted:
            c = a["comps"]
            e = m.VibrationEvent(code=a["code"], blast_id=a["blast"].id if a["blast"] else None, station_id=a["station"].id,
                                 instrument_id=a["station"].instrument_id, recorded_at=a["when"], distance_m=a["dist"], ppv_mm_s=a["ppv"],
                                 ppv_transverse=c[0], ppv_vertical=c[1], ppv_longitudinal=c[2], dominant_frequency_hz=a["freq"],
                                 air_overpressure_db=a["aop"], data_quality="VALID", quality_notes=f"Imported from {file.filename}",
                                 limit_ppv_mm_s=a["limit"], compliance=_compliance(a["ppv"], "VALID", a["limit"]), waveform_seed=hash(a["code"]) % 10**6)
            db.add(e)
            db.flush()
            record(db, "vibration_event", e.id, "CREATE", user, {"import": file.filename})
            created.append({"code": e.code, "compliance": e.compliance})
        db.commit()
    return {"rows_ok": len(accepted), "rows_rejected": len(errors), "errors": errors, "created": created, "dry_run": dry_run}


@router.get("/report.csv")
def report(station: str | None = None, db: Session = Depends(get_db)):
    rows = events(station=station, db=db)
    buf = io.StringIO()
    w = csv.writer(buf)
    if clock.banner():
        w.writerow(["# DEMONSTRATION DATA - FICTIONAL SITE"])
    w.writerow(["# " + _("Vibration monitoring report"), _("generated {when}", when=f"{clock.now():%Y-%m-%d %H:%M}"),
                _("reference values as configured in Settings")])
    cols = ["code", "station", "blast", "recorded_at", "distance_m", "ppv_mm_s", "ppv_transverse", "ppv_vertical", "ppv_longitudinal",
            "dominant_frequency_hz", "air_overpressure_db", "data_quality", "limit_ppv_mm_s", "compliance", "quality_notes"]
    w.writerow(cols)
    for r in rows:
        w.writerow([r[c] for c in cols])
    return Response("﻿" + buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="vibration_report.csv"'})
