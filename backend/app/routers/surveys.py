"""Module 03 — 3D scanning and free-face profiling."""
from __future__ import annotations

import io
import re
from collections import OrderedDict
from datetime import date, datetime
from threading import Lock

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import clock
from ..config import SURVEY_DIR
from ..db import get_db
from ..geometry import face as g
from ..services.audit import limit, record
from ..services.security import require
from ..i18n import S_, _

router = APIRouter(prefix="/api/v1/surveys", tags=["3D scanning"])

_cache: OrderedDict[str, object] = OrderedDict()
_lock = Lock()
CACHE_MAX = 16
MAX_IMPORT_POINTS = 400_000


def _cached(key: str, fn):
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    val = fn()
    with _lock:
        _cache[key] = val
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)
    return val


# ------------------------------------------------------------------ helpers
def _context(db: Session, s: m.Survey):
    bench = db.get(m.Bench, s.bench_id) if s.bench_id else None
    blast = db.get(m.Blast, s.blast_id) if s.blast_id else None
    pattern = db.get(m.DrillPattern, blast.pattern_id) if blast else None
    return bench, blast, pattern


def _geometry_params(db: Session, s: m.Survey):
    bench, blast, pattern = _context(db, s)
    cols = max(h.col_no for h in pattern.holes) if pattern else 10
    rows = max(h.row_no for h in pattern.holes) if pattern else 4
    length = max(36.0, cols * g.SPACING_LOCAL_M + 4.0)
    height = bench.bench_height_m if bench else 11.0
    return bench, blast, pattern, length, height, rows


def load_cloud(db: Session, s: m.Survey) -> g.Cloud:
    if s.file_path:  # imported survey
        def _load():
            data = np.load(SURVEY_DIR / s.file_path)
            return g.Cloud(xyz=data["xyz"], intensity=data["intensity"], region=np.full(len(data["xyz"]), g.REGION_UNKNOWN, np.uint8))
        return _cached(f"file:{s.id}", _load)
    if not clock.is_demo():
        raise HTTPException(409, _('Survey {code} has no point-cloud file — import the scan to view or compare it', code=s.code))
    bench, blast, pattern, length, height, rows = _geometry_params(db, s)
    planted = bool(bench and bench.code == "SP-B275" and s.surveyed_at >= datetime(2026, 10, 1))
    stype = "POST_BLAST" if s.survey_type == "POST_BLAST" else "FACE_PROFILE"
    spec = g.FaceSpec(seed=s.id * 7919 + 13, length_m=length, height_m=height, survey_type=stype, rows=rows, planted=planted)
    return _cached(f"gen:{s.id}", lambda: g.generate_cloud(spec))


def _viewpoint(cloud: g.Cloud) -> np.ndarray:
    lo, hi = cloud.xyz.min(axis=0), cloud.xyz.max(axis=0)
    return np.array([(lo[0] + hi[0]) / 2, hi[1] + 40.0, (lo[2] + hi[2]) / 2])


def _default_reference(db: Session, s: m.Survey) -> str | None:
    if s.file_path:
        return None
    if s.survey_type == "POST_BLAST" and s.blast_id:
        pre = db.scalars(select(m.Survey).where(m.Survey.blast_id == s.blast_id, m.Survey.survey_type == "FACE_PROFILE",
                                                m.Survey.quality_status == "ACCEPTED")).first()
        return str(pre.id) if pre else None
    return "design"


def _reference_label(db: Session, ref: str | None) -> str:
    if ref in (None, "", "none"):
        return "None"
    if ref == "design":
        return _("Design face ({angle}° — demonstration design)", angle=f"{g.DESIGN_FACE_ANGLE_DEG:.0f}")
    r = db.get(m.Survey, int(ref))
    return f"Survey {r.code}" if r else "?"


def deviation_for(db: Session, s: m.Survey, ref: str | None) -> tuple[np.ndarray | None, g.Cloud]:
    cloud = load_cloud(db, s)
    if ref in (None, "", "none"):
        return None, cloud
    vp = _viewpoint(cloud)

    def compute():
        if ref == "design":
            if s.file_path:
                raise HTTPException(422, _('Design comparison is only available for surveys in the local face coordinate system'))
            _b, _bl, _p, length, height, _r = _geometry_params(db, s)
            return g.deviation_to_design(cloud, g.design_cloud(length, height), vp, height)
        if not ref.isdigit():
            raise HTTPException(422, _("reference must be 'design', 'none' or a survey id"))
        r = db.get(m.Survey, int(ref))
        if r is None:
            raise HTTPException(404, _('Reference survey not found'))
        if r.id == s.id:
            raise HTTPException(422, _('A survey cannot be compared with itself'))
        return g.signed_distance(cloud.xyz, load_cloud(db, r).xyz, vp)

    return _cached(f"dev:{s.id}:{ref}", compute), cloud


def _survey(db: Session, sid: int) -> m.Survey:
    s = db.get(m.Survey, sid)
    if s is None:
        raise HTTPException(404, _('Survey not found'))
    return s


def _tol(db: Session) -> float | None:
    """Face tolerance from the reference limit FACE_TOL; None when not configured (no value is assumed)."""
    lim = limit(db, "FACE_TOL")
    return float(lim.max_value) if lim and lim.max_value else None


def _summary(db: Session, s: m.Survey, people, benches, blasts, instruments, areas) -> dict:
    return {
        "id": s.id, "code": s.code, "survey_type": s.survey_type, "surveyed_at": s.surveyed_at.isoformat(),
        "area": areas.get(s.area_id), "bench": benches.get(s.bench_id), "blast": blasts.get(s.blast_id),
        "instrument": instruments.get(s.instrument_id), "operator": people.get(s.operator_id),
        "point_count": s.point_count, "point_spacing_mm": s.point_spacing_mm, "registration_error_mm": s.registration_error_mm,
        "coordinate_system": s.coordinate_system, "file_format": s.file_format, "imported": bool(s.file_path),
        "quality_status": s.quality_status, "quality_notes": s.quality_notes,
    }


def _lookups(db: Session):
    return ({p.id: p.full_name for p in db.scalars(select(m.Personnel))},
            {b.id: b.code for b in db.scalars(select(m.Bench))},
            {b.id: b.code for b in db.scalars(select(m.Blast))},
            {i.id: f"{i.code} — {i.name}" for i in db.scalars(select(m.Instrument))},
            {a.id: a.code for a in db.scalars(select(m.Area))})


# ------------------------------------------------------------------ endpoints
@router.get("")
def list_surveys(area: str | None = None, bench: str | None = None, survey_type: str | None = None,
                 quality: str | None = None, db: Session = Depends(get_db)):
    lk = _lookups(db)
    out = [_summary(db, s, *lk) for s in db.scalars(select(m.Survey).order_by(m.Survey.surveyed_at.desc()))]
    if area:
        out = [x for x in out if x["area"] == area]
    if bench:
        out = [x for x in out if x["bench"] == bench]
    if survey_type:
        out = [x for x in out if x["survey_type"] == survey_type]
    if quality:
        out = [x for x in out if x["quality_status"] == quality]
    return out


@router.get("/{sid}")
def survey_detail(sid: int, db: Session = Depends(get_db)):
    s = _survey(db, sid)
    lk = _lookups(db)
    out = _summary(db, s, *lk)
    refs = [{"value": "none", "label": "No comparison"}]
    if not s.file_path:
        refs.append({"value": "design", "label": _reference_label(db, "design")})
    q = select(m.Survey).where(m.Survey.id != s.id)
    q = q.where(m.Survey.bench_id == s.bench_id) if s.bench_id else q
    for r in db.scalars(q.order_by(m.Survey.surveyed_at.desc())).all()[:12]:
        if bool(r.file_path) == bool(s.file_path):
            refs.append({"value": str(r.id), "label": f"{r.code} ({r.survey_type.replace('_', ' ').lower()}, {r.surveyed_at:%Y-%m-%d})"})
    out["references"] = refs
    out["default_reference"] = _default_reference(db, s) or "none"
    out["display_points"] = len(load_cloud(db, s).xyz)
    comps = db.scalars(select(m.SurveyComparison).where(m.SurveyComparison.compared_survey_id == s.id)
                       .order_by(m.SurveyComparison.id.desc())).all()
    out["comparisons"] = [{"id": c.id, "reference": c.reference_label, "within_tolerance_pct": c.within_tolerance_pct,
                           "mean_m": c.mean_m, "std_m": c.std_m, "computed_at": c.created_at.isoformat(),
                           "computed_by": c.computed_by} for c in comps]
    return out


@router.get("/{sid}/points")
def survey_points(sid: int, reference: str | None = None, db: Session = Depends(get_db)):
    s = _survey(db, sid)
    ref = reference if reference is not None else _default_reference(db, s)
    dev, cloud = deviation_for(db, s, ref)
    return Response(g.pack_binary(cloud, dev), media_type="application/octet-stream",
                    headers={"Cache-Control": "no-store", "X-Reference": _reference_label(db, ref).encode("ascii", "replace").decode()})


@router.get("/{sid}/stats")
def survey_stats(sid: int, reference: str | None = None, db: Session = Depends(get_db)):
    s = _survey(db, sid)
    ref = reference if reference is not None else _default_reference(db, s)
    dev, cloud = deviation_for(db, s, ref)
    if dev is None:
        return {"reference": "None", "count": 0}
    region_note = _("all points")
    d = dev
    if ref == "design":
        d = dev[cloud.region == g.REGION_FACE]
        region_note = _("face region only")
    st = g.deviation_stats(d, _tol(db))
    st.update({"reference": _reference_label(db, ref), "region": region_note,
               "tolerance_source": (limit(db, "FACE_TOL").source_document if limit(db, "FACE_TOL") else None),
               "sign_convention": _("Positive = surveyed surface in front of reference (towards free space / material present); "
                                    "negative = behind reference (overbreak / material removed).")})
    return st


class CompareIn(BaseModel):
    reference: str = Field(..., description="'design' or a survey id")


@router.post("/{sid}/comparisons", status_code=201)
def save_comparison(sid: int, body: CompareIn, db: Session = Depends(get_db), user: str = Depends(require("survey.write"))):
    s = _survey(db, sid)
    st = survey_stats(sid, body.reference, db)
    if not st.get("count"):
        raise HTTPException(422, _('No overlapping data to compare'))
    if st.get("tolerance_m") is None:
        raise HTTPException(409, _('Face tolerance (FACE_TOL) is not configured — add it in Settings before saving a comparison'))
    c = m.SurveyComparison(reference_survey_id=int(body.reference) if body.reference.isdigit() else None,
                           reference_label=st["reference"], compared_survey_id=s.id, tolerance_m=st["tolerance_m"],
                           mean_m=st["mean_m"], std_m=st["std_m"], p05_m=st["p05_m"], p95_m=st["p95_m"], max_abs_m=st["max_abs_m"],
                           within_tolerance_pct=st["within_tolerance_pct"], histogram=st["histogram"], computed_by=user)
    db.add(c)
    db.flush()
    record(db, "survey_comparison", c.id, "CREATE", user, {"survey": s.code, "reference": st["reference"]})
    db.commit()
    return {"id": c.id, **st}


@router.get("/{sid}/mesh")
def survey_mesh(sid: int, reference: str | None = None, db: Session = Depends(get_db)):
    s = _survey(db, sid)
    ref = reference if reference is not None else _default_reference(db, s)
    dev, cloud = deviation_for(db, s, ref)
    return _cached(f"mesh:{sid}:{ref}", lambda: g.face_mesh(cloud, dev))


@router.get("/{sid}/section")
def survey_section(sid: int, x: float = Query(..., description="Chainage along the face (m)"), reference: str | None = None,
                   db: Session = Depends(get_db)):
    s = _survey(db, sid)
    cloud = load_cloud(db, s)
    lo, hi = cloud.xyz[:, 0].min(), cloud.xyz[:, 0].max()
    if not lo <= x <= hi:
        raise HTTPException(422, _('x must be between {lo:.1f} and {hi:.1f} m', lo=lo, hi=hi))
    out = {"x": x, "survey": g.section(cloud, x), "reference": None, "reference_label": None, "holes": []}
    ref = reference if reference is not None else _default_reference(db, s)
    if ref == "design" and not s.file_path:
        _b, _bl, pattern, length, height, _r = _geometry_params(db, s)
        out["reference"] = g.section(g.design_cloud(length, height), x)
        out["reference_label"] = _reference_label(db, ref)
    elif ref and ref.isdigit():
        r = db.get(m.Survey, int(ref))
        if r:
            out["reference"] = g.section(load_cloud(db, r), x)
            out["reference_label"] = _reference_label(db, ref)
    if not s.file_path and s.survey_type != "POST_BLAST":
        out["holes"] = [h for h in survey_holes(sid, db) if abs(h["x"] - x) <= g.SPACING_LOCAL_M / 2]
    return out


@router.get("/{sid}/holes")
def survey_holes(sid: int, db: Session = Depends(get_db)):
    s = _survey(db, sid)
    _b, blast, pattern, _len, height, _r = _geometry_params(db, s)
    if not pattern or s.file_path:
        return []
    out = []
    for h in pattern.holes:
        last = h.measurements[-1] if h.measurements else None
        out.append({"id": h.id, "hole_code": h.hole_code, "row": h.row_no,
                    "x": round(h.planned_x - pattern.origin_x + 2.0, 2),
                    "y": round(-(g.BURDEN_LOCAL_M + h.planned_y - pattern.origin_y), 2),
                    "z": height, "depth_m": h.planned_depth_m,
                    "status": last.inspection_status if last else "NOT_MEASURED"})
    return out


@router.get("/{sid}/front-row")
def front_row(sid: int, db: Session = Depends(get_db)):
    s = _survey(db, sid)
    if s.file_path or s.survey_type == "POST_BLAST":
        raise HTTPException(422, _('Front-row distance is computed on pre-blast face profiles in the local face system'))
    holes = [h for h in survey_holes(sid, db) if h["row"] == 1]
    if not holes:
        return {"holes": []}
    _b, _bl, _p, _len, height, _r = _geometry_params(db, s)
    res = g.front_row_distances(load_cloud(db, s), [h["x"] for h in holes], holes[0]["y"], height)
    lmin, ltoe = limit(db, "FRONT_DIST_MIN"), limit(db, "TOE_DIST_MAX")
    for h, r in zip(holes, res):
        r["hole_code"] = h["hole_code"]
        flags = []
        if r.get("valid"):
            if lmin and lmin.min_value is not None and r["min_distance_m"] < lmin.min_value:
                flags.append("MIN_DISTANCE_BELOW_REFERENCE")
            if ltoe and ltoe.max_value is not None and r["toe_distance_m"] is not None and r["toe_distance_m"] > ltoe.max_value:
                flags.append("TOE_DISTANCE_ABOVE_REFERENCE")
        r["flags"] = flags
    return {"holes": res,
            "reference": {"min_distance_m": lmin.min_value if lmin else None, "toe_distance_max_m": ltoe.max_value if ltoe else None,
                          "source": lmin.source_document if lmin else None,
                          "is_demo_placeholder": bool(lmin and lmin.is_demo_placeholder)},
            "note": _("Geometric measurement from the surveyed face to each front-row hole. Flags are referred to the "
                      "drill & blast engineer; the application does not recommend loading or design changes.")}


class QualityIn(BaseModel):
    quality_status: str = Field(..., pattern="^(ACCEPTED|REVIEW|REJECTED|PENDING)$")
    quality_notes: str | None = Field(None, max_length=1000)


@router.patch("/{sid}/quality")
def set_quality(sid: int, body: QualityIn, db: Session = Depends(get_db), user: str = Depends(require("survey.write"))):
    s = _survey(db, sid)
    if body.quality_status == "REJECTED" and not (body.quality_notes or "").strip():
        raise HTTPException(422, _('A reason is required to reject a survey'))
    before = {"quality_status": s.quality_status, "quality_notes": s.quality_notes}
    s.quality_status, s.quality_notes = body.quality_status, body.quality_notes
    record(db, "survey", s.id, "UPDATE", user, {"before": before, "after": body.model_dump()})
    db.commit()
    return {"id": s.id, "quality_status": s.quality_status}


# ------------------------------------------------------------------ export
@router.get("/{sid}/export")
def export(sid: int, fmt: str = Query("ply", pattern="^(ply|xyz|csv|obj|las)$"), reference: str | None = None,
           db: Session = Depends(get_db)):
    s = _survey(db, sid)
    ref = reference if reference is not None else _default_reference(db, s)
    dev, cloud = deviation_for(db, s, ref) if fmt != "obj" else (None, load_cloud(db, s))
    xyz = cloud.xyz
    name = f"{s.code}_SIMULATED" if clock.banner() else s.code
    header = ("DEMONSTRATION DATA - FICTIONAL SITE | " if clock.banner() else "") + f"{s.code} | {s.coordinate_system} (m)"
    if fmt in ("xyz", "csv"):
        sep = "," if fmt == "csv" else " "
        buf = io.StringIO()
        buf.write(f"# {header}\n")
        cols = ["x", "y", "z", "intensity"] + (["deviation_m"] if dev is not None else [])
        buf.write(sep.join(cols) + "\n")
        arr = np.c_[xyz, cloud.intensity] if dev is None else np.c_[xyz, cloud.intensity, dev]
        np.savetxt(buf, arr, fmt="%.4f", delimiter=sep)
        return Response(buf.getvalue(), media_type="text/plain",
                        headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})
    if fmt == "ply":
        n = len(xyz)
        props = "property float x\nproperty float y\nproperty float z\nproperty float intensity\n"
        if dev is not None:
            props += "property float deviation\n"
        head = f"ply\nformat binary_little_endian 1.0\ncomment {header}\nelement vertex {n}\n{props}end_header\n".encode()
        cols = [xyz.astype("<f4"), cloud.intensity.astype("<f4")[:, None]]
        if dev is not None:
            cols.append(dev.astype("<f4")[:, None])
        body = np.hstack(cols).astype("<f4").tobytes()
        return Response(head + body, media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{name}.ply"'})
    if fmt == "obj":
        mesh = survey_mesh(sid, "none", db)
        v = mesh["vertices"]
        lines = [f"# {header}", "# 2.5D face mesh (grid over x,z)"]
        lines += [f"v {v[i]} {v[i + 1]} {v[i + 2]}" for i in range(0, len(v), 3)]
        ix = mesh["indices"]
        lines += [f"f {ix[i] + 1} {ix[i + 1] + 1} {ix[i + 2] + 1}" for i in range(0, len(ix), 3)]
        return Response("\n".join(lines) + "\n", media_type="text/plain",
                        headers={"Content-Disposition": f'attachment; filename="{name}_mesh.obj"'})
    # LAS 1.2, point format 0
    import laspy

    hdr = laspy.LasHeader(point_format=0, version="1.2")
    hdr.scales = np.array([0.001, 0.001, 0.001])
    hdr.offsets = xyz.min(axis=0)
    las = laspy.LasData(hdr)
    las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    las.intensity = (cloud.intensity * 65535).astype(np.uint16)
    out = io.BytesIO()
    las.write(out)
    return Response(out.getvalue(), media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name}.las"'})


# ------------------------------------------------------------------ import
def _parse_upload(name: str, raw: bytes) -> tuple[np.ndarray, np.ndarray]:
    ext = name.lower().rsplit(".", 1)[-1]
    if ext in ("xyz", "csv", "txt"):
        rows = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = re.split(r"[,;\s]+", line)
            try:
                vals = [float(p) for p in parts[:4]]
            except ValueError:
                continue  # header row
            if len(vals) >= 3:
                rows.append(vals + [np.nan] * (4 - len(vals)))
        if not rows:
            raise HTTPException(422, _('No numeric x y z rows found'))
        a = np.array(rows, float)
        inten = a[:, 3]
        if np.isnan(inten).all():
            inten = np.full(len(a), 0.5)
        else:
            lo, hi = np.nanmin(inten), np.nanmax(inten)
            inten = np.nan_to_num((inten - lo) / (hi - lo) if hi > lo else np.full(len(a), 0.5), nan=0.5)
        return a[:, :3], inten.astype(np.float32)
    if ext == "ply":
        from plyfile import PlyData

        v = PlyData.read(io.BytesIO(raw))["vertex"]
        xyz = np.c_[v["x"], v["y"], v["z"]].astype(float)
        names = v.data.dtype.names
        inten = np.asarray(v["intensity"], float) if "intensity" in names else np.full(len(xyz), 0.5)
        if inten.max() > 1:
            inten = inten / inten.max()
        return xyz, inten.astype(np.float32)
    if ext in ("las", "laz"):
        import laspy

        try:
            las = laspy.read(io.BytesIO(raw))
        except Exception as e:  # LAZ needs a backend (lazrs or laszip)
            raise HTTPException(422, _("Could not read {v} file: {e}. For LAZ install 'lazrs' (pip install lazrs).", v=ext.upper(), e=e)) from e
        xyz = np.c_[las.x, las.y, las.z].astype(float)
        inten = np.asarray(las.intensity, float)
        inten = inten / inten.max() if inten.max() > 0 else np.full(len(xyz), 0.5)
        return xyz, inten.astype(np.float32)
    raise HTTPException(415, _('Supported formats: XYZ, CSV, TXT, PLY, LAS (LAZ with lazrs)'))


@router.post("/import", status_code=201)
async def import_survey(file: UploadFile = File(...), area_id: int = Form(...), bench_id: int | None = Form(None),
                        survey_type: str = Form("FACE_PROFILE"), surveyed_on: date = Form(...),
                        db: Session = Depends(get_db), user: str = Depends(require("survey.write"))):
    if db.get(m.Area, area_id) is None:
        raise HTTPException(422, _('Unknown area'))
    if bench_id is not None and db.get(m.Bench, bench_id) is None:
        raise HTTPException(422, _('Unknown bench'))
    if survey_type not in ("FACE_PROFILE", "POST_BLAST", "MUCKPILE"):
        raise HTTPException(422, _('Invalid survey type'))
    raw = await file.read()
    if len(raw) > 200 * 1024 * 1024:
        raise HTTPException(413, _('File larger than 200 MB'))
    xyz, inten = _parse_upload(file.filename or "upload.xyz", raw)
    finite = np.isfinite(xyz).all(axis=1)
    xyz, inten = xyz[finite], inten[finite]
    nominal = len(xyz)
    if nominal < 100:
        raise HTTPException(422, _('At least 100 valid points are required'))
    if nominal > MAX_IMPORT_POINTS:  # uniform decimation for browser display; documented limitation
        idx = np.random.default_rng(0).choice(nominal, MAX_IMPORT_POINTS, replace=False)
        xyz, inten = xyz[idx], inten[idx]
    n = db.query(m.Survey).filter(m.Survey.code.like("SV-IMP-%")).count() + 1
    code = f"SV-IMP-{n:03d}"
    SURVEY_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(SURVEY_DIR / f"{code}.npz", xyz=xyz, intensity=inten)
    s = m.Survey(code=code, area_id=area_id, bench_id=bench_id, survey_type=survey_type,
                 surveyed_at=datetime.combine(surveyed_on, datetime.min.time()), point_count=nominal,
                 coordinate_system=S_("As imported (no registration applied)"), file_path=f"{code}.npz",
                 file_format=(file.filename or "").rsplit(".", 1)[-1].upper()[:10], quality_status="PENDING",
                 quality_notes=f"Imported from {file.filename} by {user}")
    db.add(s)
    db.flush()
    record(db, "survey", s.id, "CREATE", user, {"import": file.filename, "points": nominal})
    db.commit()
    return {"id": s.id, "code": code, "points": nominal, "displayed_points": len(xyz)}
