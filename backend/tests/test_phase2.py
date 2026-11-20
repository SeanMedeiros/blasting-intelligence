"""Module 03 (3D) and Module 04 (drillholes) tests."""
import io
import struct


import numpy as np  # noqa: E402
import pytest  # noqa: E402

from helpers import CSRF, signed_client  # noqa: E402

from app.geometry import face as g  # noqa: E402

from app.routers.drillholes import evaluate  # noqa: E402
from app.seed.generator import reset_and_seed  # noqa: E402

H = CSRF


@pytest.fixture(scope="module")
def client():
    reset_and_seed()
    with signed_client() as c:
        yield c


# ------------------------------------------------------------------ geometry unit tests
def test_cloud_is_deterministic():
    s = g.FaceSpec(seed=5, length_m=40, height_m=11, survey_type="FACE_PROFILE", display_points=20_000)
    a, b = g.generate_cloud(s), g.generate_cloud(s)
    assert np.array_equal(a.xyz, b.xyz) and len(a.xyz) == 20_000


def test_design_compared_with_itself_is_zero():
    d = g.design_cloud(40, 11, n=30_000, seed=3)
    d2 = g.design_cloud(40, 11, n=30_000, seed=4)
    dev = g.deviation_to_design(d2, d, np.array([20, 45, 5.5]), 11)
    face = dev[d2.region == g.REGION_FACE]
    assert np.abs(face).max() < 1e-9


def test_known_offset_is_measured():
    """Shift a cloud 0.30 m towards the free space: deviation to design ≈ +0.30·sin(75°) on the face."""
    d = g.design_cloud(40, 11, n=40_000, seed=3)
    shifted = g.Cloud(xyz=d.xyz + np.array([0, 0.30, 0]), intensity=d.intensity, region=d.region)
    dev = g.deviation_to_design(shifted, d, np.array([20, 45, 5.5]), 11)
    assert np.median(dev[d.region == g.REGION_FACE]) == pytest.approx(0.30 * np.sin(np.radians(75)), abs=0.005)
    c2c = g.signed_distance(shifted.xyz, d.xyz, np.array([20, 45, 5.5]))
    assert np.median(c2c[d.region == g.REGION_FACE]) == pytest.approx(0.29, abs=0.03)


def test_stats_tolerance_accounting():
    st = g.deviation_stats(np.array([-0.6, -0.2, 0.0, 0.2, 0.7]), 0.5)
    assert st["within_tolerance_pct"] == 60.0 and st["above_tolerance_pct"] == 20.0 and st["below_tolerance_pct"] == 20.0
    assert sum(st["histogram"]["counts"]) == 5


def test_planted_face_flags_front_row():
    s = g.FaceSpec(seed=11, length_m=44, height_m=11, survey_type="FACE_PROFILE", planted=True, display_points=80_000)
    res = g.front_row_distances(g.generate_cloud(s), [2 + 4 * k for k in range(10)], -3.5, 11)
    assert min(r["min_distance_m"] for r in res) < 2.8
    assert max(r["toe_distance_m"] for r in res) > 7.0


def test_mesh_indices_valid():
    s = g.FaceSpec(seed=2, length_m=36, height_m=10, survey_type="FACE_PROFILE", display_points=30_000)
    mesh = g.face_mesh(g.generate_cloud(s), None)
    nv = len(mesh["vertices"]) // 3
    assert nv > 500 and max(mesh["indices"]) < nv and len(mesh["indices"]) % 3 == 0


def test_drillhole_rules():
    tol = {"depth_min_m": -0.3, "depth_max_m": 0.3, "toe_deviation_max_m": 0.5}
    assert evaluate(0.1, 0.2, "OPEN", tol)[0] == "WITHIN_TOLERANCE"
    assert evaluate(-0.35, 0.2, "OPEN", tol)[0] == "OUT_OF_TOLERANCE"
    assert evaluate(0.0, 0.6, "OPEN", tol)[0] == "OUT_OF_TOLERANCE"
    assert evaluate(-0.7, 0.2, "OPEN", tol)[0] == "REDRILL_REQUIRED"
    assert evaluate(0.0, 0.1, "COLLAPSED", tol)[0] == "REDRILL_REQUIRED"


# ------------------------------------------------------------------ API: surveys
def _face_survey(client):
    return next(s for s in client.get("/api/v1/surveys", params={"survey_type": "FACE_PROFILE", "quality": "ACCEPTED"}).json())


def test_survey_list_and_detail(client):
    s = _face_survey(client)
    d = client.get(f"/api/v1/surveys/{s['id']}").json()
    assert d["default_reference"] == "design" and d["display_points"] > 100_000
    assert any(r["value"] == "design" for r in d["references"])


def test_points_binary_layout(client):
    s = _face_survey(client)
    r = client.get(f"/api/v1/surveys/{s['id']}/points")
    n, flags = struct.unpack("<II", r.content[:8])
    assert flags == 1 and len(r.content) == 8 + 12 * n + 4 * n + 4 * n + n


def test_stats_and_saved_comparison(client):
    s = _face_survey(client)
    st = client.get(f"/api/v1/surveys/{s['id']}/stats").json()
    assert st["region"] == "face region only" and 0 <= st["within_tolerance_pct"] <= 100
    r = client.post(f"/api/v1/surveys/{s['id']}/comparisons", json={"reference": "design"}, headers=H)
    assert r.status_code == 201
    d = client.get(f"/api/v1/surveys/{s['id']}").json()
    assert d["comparisons"][0]["computed_by"] == "Administrator"


def test_section_mesh_front_row(client):
    s = _face_survey(client)
    sec = client.get(f"/api/v1/surveys/{s['id']}/section", params={"x": 10}).json()
    assert len(sec["survey"]) > 50 and sec["reference"]
    assert client.get(f"/api/v1/surveys/{s['id']}/section", params={"x": 999}).status_code == 422
    assert len(client.get(f"/api/v1/surveys/{s['id']}/mesh").json()["indices"]) > 100
    fr = client.get(f"/api/v1/surveys/{s['id']}/front-row").json()
    assert fr["holes"] and "does not recommend" in fr["note"]


def test_post_blast_vs_pre(client):
    post = client.get("/api/v1/surveys", params={"survey_type": "POST_BLAST", "quality": "ACCEPTED"}).json()[3]
    st = client.get(f"/api/v1/surveys/{post['id']}/stats").json()
    assert st["count"] > 0 and "Survey SV-" in st["reference"]


def test_quality_review_requires_reason(client):
    s = _face_survey(client)
    assert client.patch(f"/api/v1/surveys/{s['id']}/quality", json={"quality_status": "REJECTED"}, headers=H).status_code == 422
    assert client.patch(f"/api/v1/surveys/{s['id']}/quality", json={"quality_status": "ACCEPTED", "quality_notes": "ok"}, headers=H).status_code == 200


@pytest.mark.parametrize("fmt", ["ply", "xyz", "csv", "obj", "las"])
def test_exports(client, fmt):
    s = _face_survey(client)
    r = client.get(f"/api/v1/surveys/{s['id']}/export", params={"fmt": fmt})
    assert r.status_code == 200 and len(r.content) > 1000
    assert "SIMULATED" in r.headers["content-disposition"]


def test_export_import_roundtrip(client):
    s = _face_survey(client)
    for fmt in ("ply", "las", "csv"):
        raw = client.get(f"/api/v1/surveys/{s['id']}/export", params={"fmt": fmt}).content
        r = client.post("/api/v1/surveys/import", headers=H,
                        files={"file": (f"roundtrip.{fmt}", io.BytesIO(raw))},
                        data={"area_id": "1", "survey_type": "FACE_PROFILE", "surveyed_on": "2026-12-04"})
        assert r.status_code == 201, r.text
        new = r.json()
        assert new["points"] > 100_000
        st = client.get(f"/api/v1/surveys/{new['id']}/stats", params={"reference": "none"}).json()
        assert st["count"] == 0
        assert client.get(f"/api/v1/surveys/{new['id']}/points").status_code == 200


def test_import_rejects_garbage(client):
    r = client.post("/api/v1/surveys/import", files={"file": ("x.xyz", io.BytesIO(b"hello\nworld\n"))},
                    data={"area_id": "1", "surveyed_on": "2026-12-04"})
    assert r.status_code == 422
    r = client.post("/api/v1/surveys/import", files={"file": ("x.dwg", io.BytesIO(b"abc"))},
                    data={"area_id": "1", "surveyed_on": "2026-12-04"})
    assert r.status_code == 415


# ------------------------------------------------------------------ API: drillholes
def _pattern(client, status):
    return next(p for p in client.get("/api/v1/drillholes/patterns").json() if p["blast_status"] == status)


def test_patterns_and_detail(client):
    pats = client.get("/api/v1/drillholes/patterns").json()
    sp = [p for p in pats if p["bench"] == "SP-B275" and p["measured"]]
    assert max(p["deviation_rate_pct"] for p in sp) > 30
    d = client.get(f"/api/v1/drillholes/patterns/{sp[0]['id']}").json()
    assert d["approved_loading_records"] and "Not reproduced or calculated" in d["approved_loading_records"][0]["notes"]
    assert d["locked"] is True


def test_record_measurement_flow(client):
    p = _pattern(client, "IN_PREPARATION")
    d = client.get(f"/api/v1/drillholes/patterns/{p['id']}").json()
    hole = next(h for h in d["holes"] if h["status"] == "NOT_MEASURED")
    probe = next(i for i in client.get("/api/v1/records/instrument").json()["items"] if i["code"] == "PRB-01")
    body = {"measured_depth_m": hole["planned_depth_m"] - 0.45, "toe_deviation_m": 0.2, "technician_id": 3, "instrument_id": probe["id"]}
    r = client.post(f"/api/v1/drillholes/holes/{hole['id']}/measurements", json=body, headers=H)
    assert r.status_code == 201 and r.json()["status"] == "OUT_OF_TOLERANCE"
    mid = r.json()["id"]
    bad = client.post(f"/api/v1/drillholes/measurements/{mid}/engineering-acceptance", json={"reviewer_name": "x", "reviewer_role": "y", "justification": "z"}, headers=H)
    assert bad.status_code == 422
    ok = client.post(f"/api/v1/drillholes/measurements/{mid}/engineering-acceptance",
                     json={"reviewer_name": "J. Gagnon", "reviewer_role": "Drill & Blast Engineer", "justification": "Within design intent for this row"}, headers=H)
    assert ok.status_code == 200 and ok.json()["status"] == "ACCEPTED_BY_ENGINEER"
    audit = client.get("/api/v1/drillholes/holes/%d" % hole["id"]).json()
    assert audit["status"] == "ACCEPTED_BY_ENGINEER"


def test_measurement_validation(client):
    p = _pattern(client, "IN_PREPARATION")
    hole = client.get(f"/api/v1/drillholes/patterns/{p['id']}").json()["holes"][0]
    url = f"/api/v1/drillholes/holes/{hole['id']}/measurements"
    assert client.post(url, json={"measured_depth_m": -1, "technician_id": 3}).status_code == 422
    assert client.post(url, json={"measured_depth_m": 10, "technician_id": 9999}).status_code == 422
    seis = next(i for i in client.get("/api/v1/records/instrument").json()["items"] if i["code"] == "SEIS-01")
    assert client.post(url, json={"measured_depth_m": 10, "technician_id": 3, "instrument_id": seis["id"]}).status_code == 422


def test_fired_blast_holes_locked(client):
    p = _pattern(client, "CLOSED")
    hole = client.get(f"/api/v1/drillholes/patterns/{p['id']}").json()["holes"][0]
    r = client.post(f"/api/v1/drillholes/holes/{hole['id']}/measurements", json={"measured_depth_m": 10, "technician_id": 3})
    assert r.status_code == 409


def test_capa_and_csv(client):
    p = _pattern(client, "IN_PREPARATION")
    r = client.post(f"/api/v1/drillholes/patterns/{p['id']}/capa", headers=H,
                    json={"description": "Re-verify short holes before loading", "owner_id": 3, "due_date": "2026-12-07"})
    assert r.status_code == 201
    assert client.post(f"/api/v1/drillholes/patterns/{p['id']}/capa", json={"description": "Re-verify short holes", "owner_id": 3, "due_date": "2026-01-01"}).status_code == 422
    csv_ = client.get(f"/api/v1/drillholes/patterns/{p['id']}/export.csv").text
    assert "DEMONSTRATION DATA" in csv_ and "hole_code" in csv_
    assert client.get("/api/v1/drillholes/trend", params={"bench": "SP-B275"}).json()
    assert client.get("/api/v1/drillholes/outstanding").json()
