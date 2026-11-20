"""Modules 02, 05, 06, 07, 08, 09 tests."""
import io


import pytest  # noqa: E402

from helpers import CSRF, signed_client  # noqa: E402


from app.seed.generator import reset_and_seed  # noqa: E402

H = CSRF


@pytest.fixture(scope="module")
def c():
    reset_and_seed()
    with signed_client() as client:
        yield client


def instr(c, code):
    return next(i["id"] for i in c.get("/api/v1/records/instrument", params={"limit": 100}).json()["items"] if i["code"] == code)


# ------------------------------------------------------------------ laboratory
def test_lab_summary_and_trend(c):
    s = c.get("/api/v1/lab/summary").json()
    assert any(i["code"] == "VISC-02" and i["status"] == "EXPIRED" for i in s["instruments"])
    assert s["nonconformances"]
    t = c.get("/api/v1/lab/trend", params={"test_type": "DENSITY", "product": "P-300"}).json()
    assert t["limit"]["is_demo_placeholder"] and len(t["points"]) > 5


def test_lab_record_pass_fail_and_calibration(c):
    batch = c.get("/api/v1/lab/tests", params={"test_type": "VISCOSITY", "product": "E-100"}).json()[0]["batch"]
    base = {"test_type": "VISCOSITY", "batch_code": batch, "technician_id": 7}
    r = c.post("/api/v1/lab/tests", json={**base, "instrument_id": instr(c, "VISC-01"), "value": 30000}, headers=H).json()
    assert r["result"] == "PASS"
    r = c.post("/api/v1/lab/tests", json={**base, "instrument_id": instr(c, "VISC-01"), "value": 99000}, headers=H).json()
    assert r["result"] == "FAIL" and r["nonconformance"]
    assert c.get(f"/api/v1/lab/batches/{batch}").json()["status"] == "QUARANTINE"
    r = c.post("/api/v1/lab/tests", json={**base, "instrument_id": instr(c, "VISC-02"), "value": 30000}, headers=H).json()
    assert r["result"] == "NOT_EVALUATED" and r["data_quality"] == "QUESTIONABLE"
    # wrong instrument type
    assert c.post("/api/v1/lab/tests", json={**base, "instrument_id": instr(c, "DENS-01"), "value": 1}).status_code == 422
    # VOD requires approved test reference
    assert c.post("/api/v1/lab/tests", json={"test_type": "VOD", "blast_code": "BL-26-0430", "instrument_id": instr(c, "VOD-01"),
                                             "technician_id": 3, "value": 5200}).status_code == 422


def test_nc_disposition(c):
    nc = next(n for n in c.get("/api/v1/lab/summary").json()["nonconformances"] if n["status"] == "OPEN")
    assert c.patch(f"/api/v1/lab/nonconformances/{nc['id']}", json={"disposition": "REJECT", "close": True, "decided_by": "QC Lead"}).status_code == 422
    r = c.patch(f"/api/v1/lab/nonconformances/{nc['id']}", json={"disposition": "REJECT", "close": True, "closure_note": "Batch destroyed per procedure", "decided_by": "QC Lead"}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "CLOSED"


# ------------------------------------------------------------------ vibration
def test_vibration_stations_and_waveform(c):
    st = {s["code"]: s for s in c.get("/api/v1/vibration/stations").json()}
    assert st["V-03"]["exceedances"] == 1 and st["V-03"]["limit_is_demo"]
    ev = c.get("/api/v1/vibration/events", params={"station": "V-03", "compliance": "EXCEEDANCE"}).json()[0]
    w = c.get(f"/api/v1/vibration/events/{ev['id']}/waveform").json()
    assert w["simulated"] and max(abs(v) for v in w["transverse"] + w["vertical"] + w["longitudinal"]) == pytest.approx(ev["ppv_mm_s"], abs=0.01)


def test_vibration_quality_reclassifies(c):
    ev = c.get("/api/v1/vibration/events", params={"station": "V-01", "quality": "VALID"}).json()[0]
    r = c.patch(f"/api/v1/vibration/events/{ev['id']}/quality", json={"data_quality": "QUESTIONABLE", "quality_notes": "Coupling check failed"}, headers=H)
    assert r.json()["compliance"] == "NOT_EVALUATED"


def test_vibration_import(c):
    sample = c.get("/api/v1/vibration/import/sample.csv").content
    dry = c.post("/api/v1/vibration/import", params={"dry_run": True}, files={"file": ("s.csv", io.BytesIO(sample))}).json()
    assert dry["rows_ok"] == 2 and not dry["created"]
    bad = sample + b"V-99,2026-12-04T12:00:00,1,,,,10,,,\nV-01,2026-12-04T12:00:00,-3,,,,10,,,\nV-02,2026-12-04T12:00:00,5,1,1,1,10,,,\n"
    r = c.post("/api/v1/vibration/import", files={"file": ("s.csv", io.BytesIO(bad))}, headers=H).json()
    assert r["rows_ok"] == 2 and r["rows_rejected"] == 3 and len(r["created"]) == 2
    again = c.post("/api/v1/vibration/import", files={"file": ("s.csv", io.BytesIO(sample))}).json()
    assert again["rows_ok"] == 0 and all("duplicate" in e["error"] for e in again["errors"])
    assert c.post("/api/v1/vibration/import", files={"file": ("x.csv", io.BytesIO(b"a,b\n1,2\n"))}).status_code == 422
    assert "DEMONSTRATION DATA" in c.get("/api/v1/vibration/report.csv").text


# ------------------------------------------------------------------ blasting workflow
def blast_by_status(c, s):
    return next(b for b in c.get("/api/v1/blasts").json()["blasts"] if b["status"] == s)


def test_board_and_detail(c):
    b = c.get("/api/v1/blasts").json()
    assert b["flow"][3] == "AUTHORIZED"
    d = c.get(f"/api/v1/blasts/{blast_by_status(c, 'AUTHORIZED')['id']}").json()
    assert d["authorization"]["ref"] and "outside this software" in d["notice"]


def test_transition_rules(c):
    b = blast_by_status(c, "IN_PREPARATION")
    d = c.get(f"/api/v1/blasts/{b['id']}").json()
    assert d["next_status"] == "UNDER_INSPECTION" and d["next_requirements"]
    r = c.post(f"/api/v1/blasts/{b['id']}/transition", json={"to_status": "UNDER_INSPECTION"}, headers=H)
    assert r.status_code == 409 and r.json()["detail"]["unmet"]
    # skipping steps is refused
    r = c.post(f"/api/v1/blasts/{b['id']}/transition", json={"to_status": "AUTHORIZED"}, headers=H)
    assert r.status_code == 409


def test_authorization_requires_external_reference(c):
    a = blast_by_status(c, "AUTHORIZED")
    r = c.post(f"/api/v1/blasts/{a['id']}/transition", json={"to_status": "IN_PROGRESS", "note": "Fired at window"}, headers=H)
    assert r.status_code == 200
    r = c.post(f"/api/v1/blasts/{a['id']}/transition", json={"to_status": "AWAITING_VERIFICATION"}, headers=H)
    assert r.status_code == 200
    d = c.get(f"/api/v1/blasts/{a['id']}").json()
    assert any("Checkpoint open" in u for u in d["next_requirements"]) or any("inventory" in u.lower() for u in d["next_requirements"])
    for cp in d["checkpoints"]:
        if not cp["completed"]:
            assert c.post(f"/api/v1/checkpoints/{cp['id']}/complete", json={"evidence_ref": "DOC-TEST"}, headers=H).status_code == 200
    inv = d["inventory"]
    if not inv["reconciled"] and inv["balance"] > 0:
        c.post(f"/api/v1/blasts/{a['id']}/inventory", json={"movement_type": "RETURNED", "quantity": inv["balance"], "document_ref": "RET-1"}, headers=H)
    d = c.get(f"/api/v1/blasts/{a['id']}").json()
    assert d["inventory"]["reconciled"]
    assert c.post(f"/api/v1/blasts/{a['id']}/transition", json={"to_status": "COMPLETED"}, headers=H).status_code == 200
    r = c.post(f"/api/v1/blasts/{a['id']}/transition", json={"to_status": "CLOSED"}, headers=H)
    assert r.status_code == 409  # post-blast review + detonator verification still open


def test_inventory_overdraw_refused(c):
    b = blast_by_status(c, "AWAITING_VERIFICATION")
    assert c.post(f"/api/v1/blasts/{b['id']}/inventory", json={"movement_type": "USED", "quantity": 999, "document_ref": "X1"}).status_code == 422


def test_checklist_no_requires_comment(c):
    b = blast_by_status(c, "IN_PREPARATION")
    insp = c.get(f"/api/v1/blasts/{b['id']}").json()["pre_blast_inspection"]
    item = insp["items"][0]
    assert c.patch(f"/api/v1/checklist-items/{item['id']}", json={"result": "NO"}).status_code == 422
    assert c.patch(f"/api/v1/checklist-items/{item['id']}", json={"result": "YES"}, headers=H).status_code == 200
    assert c.post(f"/api/v1/inspections/{insp['id']}/complete", json={"inspector_id": 1}).status_code == 422  # items missing


# ------------------------------------------------------------------ detonators
def test_detonator_reconciliation_and_verify(c):
    recs = c.get("/api/v1/detonators").json()
    assert "no programming" in recs["notice"]
    planted = next(r for r in recs["records"] if r["exceptions"])
    assert planted["unaccounted"] == 1
    pending = next(r for r in recs["records"] if r["documentation_status"] == "INCOMPLETE" and r["units_used"] is not None)
    r = c.patch(f"/api/v1/detonators/{pending['id']}", json={"units_used": pending["units_issued"] - 3, "units_returned": 2}, headers=H)
    assert r.status_code == 200 and r.json()["unaccounted"] == 1
    assert c.post(f"/api/v1/detonators/{pending['id']}/verify", json={"verified_by": "N. Pelletier"}).status_code == 409
    exc = next(x for x in next(r for r in c.get("/api/v1/detonators").json()["records"] if r["id"] == pending["id"])["exceptions"] if x["status"] == "OPEN")
    c.patch(f"/api/v1/detonators/{pending['id']}", json={"units_used": pending["units_issued"] - 2, "units_returned": 2}, headers=H)
    assert c.post(f"/api/v1/traceability-exceptions/{exc['id']}/close", json={"resolution": "Recount confirmed, log corrected"}, headers=H).status_code == 200
    assert c.post(f"/api/v1/detonators/{pending['id']}/verify", json={"verified_by": "N. Pelletier"}, headers=H).status_code == 200
    assert c.get(f"/api/v1/detonators/{pending['id']}/audit").json()
    assert c.patch(f"/api/v1/detonators/{pending['id']}", json={"units_used": 1, "units_returned": 1}).status_code == 409


# ------------------------------------------------------------------ safety
def test_observation_requires_fields_and_creates_capa(c):
    base = {"obs_type": "HAZARD", "description": "Unsupported crest near pattern", "observed_at": "2026-12-04T09:00:00", "area_id": 1,
            "location_detail": "NP-B310", "responsible_id": 1, "likelihood": 4, "severity": 4}
    assert c.post("/api/v1/safety/observations", json=base).status_code == 422  # missing corrective action
    r = c.post("/api/v1/safety/observations", json={**base, "corrective_action": "Barricade and scale crest"}, headers=H).json()
    assert r["risk_level"] == "HIGH" and r["capa"]
    assert c.post(f"/api/v1/safety/observations/{r['id']}/close", json={"closure_evidence": "short"}).status_code == 422
    assert c.post(f"/api/v1/safety/observations/{r['id']}/close", json={"closure_evidence": "Photo of berm and sign-off"}, headers=H).status_code == 200


def test_risk_matrix_configurable(c):
    assert c.put("/api/v1/safety/risk-matrix", json={"low_max": 9, "medium_max": 5, "high_max": 16, "source_document": "x doc"}).status_code == 422
    r = c.put("/api/v1/safety/risk-matrix", json={"low_max": 3, "medium_max": 8, "high_max": 15, "source_document": "QSSE-PR-02 (fictional)"}, headers=H)
    assert r.status_code == 200 and r.json()["reclassified_observations"] >= 0
    c.put("/api/v1/safety/risk-matrix", json={"low_max": 4, "medium_max": 9, "high_max": 16, "source_document": "restore"}, headers=H)


def test_capa_close_and_lists(c):
    capa = next(x for x in c.get("/api/v1/safety/capa").json() if x["status"] != "CLOSED")
    assert c.post(f"/api/v1/safety/capa/{capa['id']}/close", json={"closure_evidence": "Training records attached"}, headers=H).status_code == 200
    assert c.get("/api/v1/safety/inspections", params={"inspection_type": "PRE_BLAST"}).json()
    assert any(t["status"] == "EXPIRED" for t in c.get("/api/v1/safety/training").json())
    assert c.get("/api/v1/safety/summary").json()["open_observations"] >= 0


# ------------------------------------------------------------------ planning
def test_planning_views(c):
    s = c.get("/api/v1/planning/schedule").json()
    assert s["items"] and s["gantt"]
    assert c.get("/api/v1/planning/work-orders").json()[0]["code"].startswith("WO-")
    assert c.get("/api/v1/planning/production").json()
    assert c.get("/api/v1/planning/delays").json()["pareto"]
    assert c.get("/api/v1/planning/schedule", params={"start": "2026-01-01", "end": "2026-12-31"}).status_code == 422


def test_reschedule_records_change(c):
    item = next(i for i in c.get("/api/v1/planning/schedule").json()["items"] if i["status"] in ("PLANNED", "DELAYED") and i["activity"] != "BLAST")
    r = c.post(f"/api/v1/planning/items/{item['id']}/reschedule", json={"new_date": "2026-12-10", "cause_category": "WEATHER", "cause": "Freezing rain forecast", "delay_hours": 4}, headers=H)
    assert r.status_code == 200
    ch = c.get("/api/v1/planning/delays").json()["changes"][0]
    assert ch["cause"] == "Freezing rain forecast" and ch["by"] == "Administrator"
    assert c.post(f"/api/v1/planning/items/{item['id']}/reschedule", json={"new_date": "2026-12-11", "cause_category": "BAD", "cause": "xxxxx"}).status_code == 422
    assert c.post(f"/api/v1/planning/items/{item['id']}/complete", json={"actual_date": "2026-12-04"}, headers=H).status_code == 200


def test_receive_delivery(c):
    d = next(x for x in c.get("/api/v1/planning/deliveries").json() if x["status"] == "SCHEDULED")
    assert c.post(f"/api/v1/planning/deliveries/{d['id']}/receive", json={"actual_date": "2026-12-30", "delivered_qty": 10, "document_ref": "BOL"}).status_code == 422
    r = c.post(f"/api/v1/planning/deliveries/{d['id']}/receive", json={"actual_date": "2026-12-04", "delivered_qty": d["planned_qty"], "document_ref": "BOL-T1"}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "DELIVERED"
