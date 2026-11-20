"""Production mode: real clock, empty database, master data, no demonstration artefacts."""
import re
from datetime import date

import pytest
from fastapi.testclient import TestClient
from helpers import ADMIN_PWD as PWD, CSRF, production_client

from app import clock
from app import models as m
from app.db import SessionLocal
from app.main import app
from app.seed.generator import reset_and_seed
from app.services.security import hash_password



@pytest.fixture(scope="module")
def prod():
    with production_client() as c:
        yield c


def test_clock_is_real_in_production(prod):
    assert not clock.is_demo()
    assert abs((clock.today() - date.today()).days) <= 1  # site time zone vs server zone
    meta = prod.get("/api/v1/meta").json()
    assert meta["mode"] == "production" and meta["disclaimer"] is None and meta["today"] == clock.today().isoformat()
    assert meta["site_configured"] is False and meta["site"] == "Site not configured"


def test_demo_reset_refused_in_production(prod):
    with pytest.raises(RuntimeError, match="BI_MODE=demo"):
        reset_and_seed()


def _concrete(path: str) -> str:
    path = path.replace("{key}.pdf", "daily.pdf").replace("{key}.csv", "daily.csv")
    path = path.replace("/masterdata/{key}", "/masterdata/site")
    return re.sub(r"\{[^}]+\}", "1", path)


def test_every_read_endpoint_works_on_an_empty_database(prod):
    """No 5xx anywhere before any data exists (dashboard, KPIs, alerts, every module, reports)."""
    paths = [p for p, ops in app.openapi()["paths"].items() if "get" in ops and p.startswith("/api/")]
    assert len(paths) > 60  # the sweep must really cover the API
    failures, ok = [], 0
    for path in paths:
        res = prod.get(_concrete(path))
        if res.status_code >= 500:
            failures.append(f"{path} → {res.status_code} {res.text[:160]}")
        ok += res.status_code == 200
    assert not failures, "\n".join(failures)
    assert ok > 30


def test_reports_on_empty_database(prod):
    for key in [x["key"] for x in prod.get("/api/v1/reports").json()]:
        for fmt in ("pdf", "csv"):
            res = prod.get(f"/api/v1/reports/{key}.{fmt}")
            assert res.status_code in (200, 404, 422), f"{key}.{fmt} → {res.status_code} {res.text[:200]}"
            if res.status_code == 200 and fmt == "csv":
                assert "DEMONSTRATION" not in res.text
            if res.status_code == 200 and fmt == "pdf":
                import io

                from pypdf import PdfReader
                text = " ".join(pg.extract_text() or "" for pg in PdfReader(io.BytesIO(res.content)).pages)
                assert "DEMONSTRATION" not in text and "DÉMONSTRATION" not in text, key


def test_setup_checklist_and_master_data(prod):
    st = prod.get("/api/v1/masterdata/setup/status").json()
    assert not st["complete"] and all(not s["done"] for s in st["steps"])

    site = prod.post("/api/v1/masterdata/site", json={"code": "mtl", "name": "Mine du Nord", "region": "Abitibi"})
    assert site.status_code == 201 and site.json()["code"] == "MTL"
    assert prod.post("/api/v1/masterdata/site", json={"code": "MTL", "name": "Duplicate"}).status_code == 409
    assert prod.get("/api/v1/meta").json()["site"] == "Mine du Nord"

    area = prod.post("/api/v1/masterdata/area", json={"site_id": site.json()["id"], "code": "P1", "name": "Pit 1", "area_type": "OPEN_PIT"})
    assert area.status_code == 201 and area.json()["active"] is True and area.json()["site_id_label"].startswith("MTL")
    assert prod.post("/api/v1/masterdata/area", json={"site_id": 999, "code": "P2", "name": "x", "area_type": "OPEN_PIT"}).status_code == 422
    assert prod.post("/api/v1/masterdata/area", json={"site_id": site.json()["id"], "code": "P3", "name": "x", "area_type": "MOON"}).status_code == 422
    assert prod.post("/api/v1/masterdata/area", json={"code": "P4", "name": "missing site", "area_type": "QUARRY"}).status_code == 422
    assert prod.post("/api/v1/masterdata/area", json={"site_id": 1, "code": "P5", "name": "x", "area_type": "QUARRY", "hack": 1}).status_code == 422

    bench = prod.post("/api/v1/masterdata/bench", json={"area_id": area.json()["id"], "code": "P1-B300", "elevation_m": 300,
                                                       "bench_height_m": 12, "rock_type": "Granite"})
    assert bench.status_code == 201
    assert prod.post("/api/v1/masterdata/bench", json={"area_id": area.json()["id"], "code": "P1-X", "elevation_m": 1,
                                                      "bench_height_m": 500}).status_code == 422

    # referenced records cannot be deleted; they can be deactivated
    r = prod.delete(f"/api/v1/masterdata/area/{area.json()['id']}")
    assert r.status_code == 409 and r.json()["detail"]["used_by"] == {"bench": 1}
    assert prod.patch(f"/api/v1/masterdata/area/{area.json()['id']}", json={"active": False}).json()["active"] is False
    assert all(o["id"] != area.json()["id"] for o in prod.get("/api/v1/masterdata/area/options").json())
    prod.patch(f"/api/v1/masterdata/area/{area.json()['id']}", json={"active": True})

    ins = prod.post("/api/v1/masterdata/instrument", json={"code": "VISC-1", "name": "Viscometer", "instrument_type": "VISCOMETER",
                                                          "serial_number": "SN-1"}).json()
    assert prod.post("/api/v1/masterdata/calibration", json={"instrument_id": ins["id"], "calibrated_on": "2026-11-01",
                                                            "valid_until": "2026-10-01", "certificate_ref": "C-1",
                                                            "performed_by": "Lab"}).status_code == 422
    cal = prod.post("/api/v1/masterdata/calibration", json={"instrument_id": ins["id"], "calibrated_on": "2026-11-01",
                                                           "valid_until": "2027-11-01", "certificate_ref": "C-1", "performed_by": "Lab"})
    assert cal.status_code == 201
    # an unused record can be deleted, and the deletion is audited
    tmp = prod.post("/api/v1/masterdata/equipment", json={"code": "TMP", "name": "Temp", "equipment_type": "OTHER", "status": "AVAILABLE"}).json()
    assert prod.delete(f"/api/v1/masterdata/equipment/{tmp['id']}").status_code == 200
    with SessionLocal() as db:
        assert db.query(m.AuditLog).filter_by(entity="equipment", entity_id=tmp["id"], action="DELETE").count() == 1


def test_limits_and_targets_created_from_scratch(prod):
    assert prod.post("/api/v1/masterdata/reference-limits/new", json={
        "parameter": "PPV", "max_value": 12.5, "source_document": "DEMO PLACEHOLDER", "owner": "Eng", "effective_from": "2026-11-01"}).status_code == 422
    r = prod.post("/api/v1/masterdata/reference-limits/new", json={
        "parameter": "PPV", "scope": "*", "max_value": 12.5, "source_document": "Permit 2026-114 §4.2", "owner": "J. Engineer",
        "effective_from": "2026-11-01"})
    assert r.status_code == 201 and r.json()["unit"] == "mm/s" and r.json()["is_demo_placeholder"] is False
    assert prod.post("/api/v1/masterdata/reference-limits/new", json={
        "parameter": "PPV", "max_value": 10, "source_document": "Permit", "owner": "J. Engineer", "effective_from": "2026-11-01"}).status_code == 409
    assert prod.put("/api/v1/kpis/targets/schedule_adherence", json={"target": 92, "source": "Contract KPI annex"}).status_code == 200
    assert prod.put("/api/v1/kpis/targets/not_a_kpi", json={"target": 1, "source": "x x x"}).status_code == 404
    k = next(x for x in prod.get("/api/v1/kpis").json() if x["key"] == "schedule_adherence")
    assert k["target"] == 92


def test_master_data_permissions(prod):
    with SessionLocal() as db:
        for u, role in (("tech1", "TECHNICIAN"), ("qsse1", "QSSE")):
            db.add(m.AppUser(username=u, full_name=u, role=role, password_hash=hash_password(PWD), must_change_password=False))
        db.commit()
    with TestClient(app, headers=CSRF) as t:
        t.post("/api/v1/auth/login", json={"username": "tech1", "password": PWD})
        assert t.post("/api/v1/masterdata/equipment", json={"code": "D1", "name": "Drill", "equipment_type": "DRILL", "status": "AVAILABLE"}).status_code == 403
        ins = t.get("/api/v1/masterdata/instrument").json()[0]
        assert t.post("/api/v1/masterdata/calibration", json={"instrument_id": ins["id"], "calibrated_on": "2026-11-02",
                                                             "valid_until": "2027-11-02", "certificate_ref": "C-2", "performed_by": "Tech"}).status_code == 201
        sch = {e["key"]: e["can_edit"] for e in t.get("/api/v1/masterdata").json()}
        assert sch["calibration"] and not sch["site"] and not sch["personnel"]
    with TestClient(app, headers=CSRF) as q:
        q.post("/api/v1/auth/login", json={"username": "qsse1", "password": PWD})
        assert q.post("/api/v1/masterdata/personnel", json={"code": "p1", "full_name": "Ana Silva", "role": "Blaster"}).status_code == 201
        assert q.post("/api/v1/masterdata/bench", json={"area_id": 1, "code": "B", "elevation_m": 1, "bench_height_m": 10}).status_code == 403


def test_no_synthetic_cloud_in_production(prod):
    with SessionLocal() as db:
        s = m.Survey(code="SV-1", area_id=1, survey_type="FACE_PROFILE", surveyed_at=clock.now(), point_count=0, quality_status="PENDING")
        db.add(s)
        db.commit()
        sid = s.id
    r = prod.get(f"/api/v1/surveys/{sid}/points")
    assert r.status_code == 409 and "import" in r.json()["detail"]


def test_dashboard_after_setup_has_no_demo_text(prod):
    d = prod.get("/api/v1/dashboard")
    assert d.status_code == 200 and "fictional" not in d.text.lower() and "Lac-Bor" not in d.text


def test_risk_matrix_on_new_site(prod):
    mtx = prod.get("/api/v1/safety/risk-matrix").json()
    assert len(mtx["likelihood"]) == 5 and len(mtx["severity"]) == 5 and "Default" in mtx["source_document"]
    r = prod.put("/api/v1/safety/risk-matrix", json={"low_max": 3, "medium_max": 8, "high_max": 15,
                                                     "source_document": "Site procedure SST-004 rev 2"})
    assert r.status_code == 200, r.text
    assert prod.get("/api/v1/safety/risk-matrix").json()["source_document"] == "Site procedure SST-004 rev 2"


def test_inventory_requires_product_on_first_movement(prod):
    with SessionLocal() as db:
        site = db.query(m.Site).first()
        area = db.query(m.Area).first()
        bench = db.query(m.Bench).first()
        wo = m.WorkOrder(code="WO-T1", title="Test", area_id=area.id, wo_type="BLAST", status="OPEN", planned_start=clock.today(),
                         planned_end=clock.today())
        db.add(wo)
        db.flush()
        pat = m.DrillPattern(code="PT-T1", bench_id=bench.id, design_document_ref="D-1", approved_by="Engineer", hole_count=1,
                             hole_diameter_mm=140, origin_x=0, origin_y=0)
        db.add(pat)
        db.flush()
        b = m.Blast(code="BL-T1", pattern_id=pat.id, work_order_id=wo.id, bench_id=bench.id, approved_plan_ref="BP-1",
                    planned_date=clock.today(), status="IN_PREPARATION")
        db.add(b)
        db.commit()
        bid = b.id
        assert site is not None
    r = prod.post(f"/api/v1/blasts/{bid}/inventory", json={"movement_type": "RECEIVED", "quantity": 5, "document_ref": "BL-1"})
    assert r.status_code == 422 and "Product" in r.text
    r = prod.post(f"/api/v1/blasts/{bid}/inventory", json={"movement_type": "RECEIVED", "quantity": 5, "document_ref": "BL-1",
                                                          "product_name": "Bulk emulsion X"})
    assert r.status_code == 201, r.text
    r = prod.post(f"/api/v1/blasts/{bid}/inventory", json={"movement_type": "USED", "quantity": 4, "document_ref": "BL-2"})
    assert r.status_code == 201
    mv = prod.get(f"/api/v1/blasts/{bid}").json()["inventory"]["movements"]
    assert {x["product"] for x in mv} == {"Bulk emulsion X"}
