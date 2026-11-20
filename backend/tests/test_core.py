"""Core API, KPI and rule tests. Run from backend/:  python -m pytest -q"""
from datetime import date


import pytest  # noqa: E402

from helpers import CSRF, signed_client  # noqa: E402,F401

from app.db import SessionLocal  # noqa: E402

from app.seed.generator import reset_and_seed  # noqa: E402
from app.services.kpis import KPI_DEFS, compute_kpis  # noqa: E402


@pytest.fixture(scope="session")
def client():
    reset_and_seed()
    with signed_client() as c:
        yield c


def test_seed_is_deterministic():
    a = reset_and_seed()
    b = reset_and_seed()
    assert a == b
    assert a["blast"] == 40 and a["drillhole"] > 1000 and a["lab_test"] > 200


def test_meta_has_disclaimer(client):
    r = client.get("/api/v1/meta").json()
    assert "DEMONSTRATION DATA" in r["disclaimer"] and r["today"] == "2026-12-04" and r["mode"] == "demo" and r["site"].startswith("Lac-Bor")


def test_dashboard_sections(client):
    d = client.get("/api/v1/dashboard").json()
    for k in ("activities", "pending_blasts", "deliveries", "equipment", "surveys", "laboratory", "vibration", "safety", "kpis", "alerts"):
        assert k in d
    assert len(d["kpis"]) == 13
    assert any(b["status"] == "AUTHORIZED" for b in d["pending_blasts"])


def test_every_kpi_documented_and_traceable(client):
    for k in client.get("/api/v1/kpis", params={"start": "2026-11-01", "end": "2026-11-30"}).json():
        assert k["formula"] and k["is_demonstration_kpi"] is True
        if k["value"] is not None and k["unit"] == "%":
            assert k["value"] == pytest.approx(100 * k["numerator"] / k["denominator"], abs=0.06)


def test_kpi_values_within_bounds():
    with SessionLocal() as db:
        for k in compute_kpis(db, date(2026, 8, 1), date(2026, 12, 4)):
            if k["unit"] == "%" and k["value"] is not None:
                assert 0 <= k["value"] <= 100


def test_kpi_bad_range(client):
    assert client.get("/api/v1/kpis", params={"start": "2026-12-01", "end": "2026-11-01"}).status_code == 422


def test_kpi_series(client):
    s = client.get("/api/v1/kpis/series", params={"granularity": "month"}).json()
    assert s["labels"][0] == "2026-08" and len(s["series"]) == len(KPI_DEFS)


def test_planted_alerts_detected(client):
    rules = {a["rule"] + ":" + a["title"] for a in client.get("/api/v1/alerts").json()}
    joined = " ".join(rules)
    assert "REPEATED_DRILLHOLE_DEVIATION" in joined and "SP-B275" in joined
    assert "CALIBRATION_EXPIRED" in joined and "VISC-02" in joined
    assert "RECURRING_LAB_NC" in joined and "P-300" in joined
    assert "VIBRATION_EXCEEDANCE" in joined and "V-03" in joined


def test_expired_calibration_tests_not_evaluated(client):
    items = client.get("/api/v1/records/lab_test", params={"filters": "calibration_valid=0", "limit": 500}).json()["items"]
    assert items and all(t["result"] == "NOT_EVALUATED" and t["data_quality"] == "QUESTIONABLE" for t in items)


def test_authorized_blasts_have_external_reference(client):
    items = client.get("/api/v1/records/blast", params={"limit": 500}).json()["items"]
    for b in items:
        if b["status"] in ("AUTHORIZED", "IN_PROGRESS", "AWAITING_VERIFICATION", "COMPLETED", "CLOSED"):
            assert b["authorization_ref"] and b["authorized_by"]


def test_no_loading_calculation_fields():
    from app.db import Base
    forbidden = ("charge", "powder_factor", "kg_per", "stemming_length", "delay_ms", "firing_sequence", "timing")
    for t in Base.metadata.tables.values():
        for c in t.columns:
            assert not any(f in c.name for f in forbidden), f"{t.name}.{c.name}"


def test_record_browser(client):
    assert client.get("/api/v1/records/blast", params={"q": "SP-B275"}).status_code == 200
    assert client.get("/api/v1/records/nope").status_code == 404
    assert client.get("/api/v1/records/audit_log").status_code == 404
    assert client.get("/api/v1/records/blast", params={"filters": "bad"}).status_code == 422
    assert client.get("/api/v1/records/blast/999999").status_code == 404
