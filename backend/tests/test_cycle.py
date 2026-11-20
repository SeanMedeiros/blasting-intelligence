"""A complete blasting cycle on a NEW production site, entirely through the API (no demonstration data).

master data → limits → work order → standard schedule → pattern → drillhole design import → drilling →
hole verification → blast → checkpoints / inventory / pre-blast checklist → external authorization →
firing → vibration import → post-blast review → detonator reconciliation → closure → KPIs and reports.
"""
from datetime import timedelta

import pytest
from helpers import production_client

from app import clock

HOLES_CSV = "\n".join(["hole_code,x,y,z,depth_m,dip_deg,azimuth_deg"] + [
    f"R{r}-{c:02d},{1000 + 4 * c + (2 if r == 2 else 0):.2f},{500 + 3.5 * (r - 1):.2f},310,13.0,90,0" for r in (1, 2) for c in range(1, 5)])


@pytest.fixture(scope="module")
def c():
    with production_client() as client:
        yield client


def ok(r, code=200):
    assert r.status_code == code, f"{r.request.method} {r.request.url.path} → {r.status_code} {r.text[:400]}"
    return r.json()


def test_full_cycle(c):
    today = clock.today()
    md = "/api/v1/masterdata"
    site = ok(c.post(f"{md}/site", json={"code": "MDN", "name": "Mine du Nord"}), 201)
    area = ok(c.post(f"{md}/area", json={"site_id": site["id"], "code": "P1", "name": "Pit 1", "area_type": "OPEN_PIT"}), 201)
    bench = ok(c.post(f"{md}/bench", json={"area_id": area["id"], "code": "P1-B310", "elevation_m": 310, "bench_height_m": 12}), 201)
    tech = ok(c.post(f"{md}/personnel", json={"code": "T1", "full_name": "Ana Tech", "role": "Mining Technician"}), 201)
    blaster = ok(c.post(f"{md}/personnel", json={"code": "B1", "full_name": "Bob Blaster", "role": "Blaster"}), 201)
    st = ok(c.post(f"{md}/monitor_station", json={"code": "V-01", "name": "Village", "station_type": "RECEPTOR", "x": 0, "y": 0}), 201)
    csv_early = f"station_code,recorded_at,ppv_mm_s,dominant_frequency_hz\nV-01,{today}T08:00:00,1.0,20\n"
    res = ok(c.post("/api/v1/vibration/import", files={"file": ("v.csv", csv_early, "text/csv")}))  # no seismograph yet: row refused, no crash
    assert res["rows_ok"] == 0 and "no seismograph" in str(res["errors"])
    seis = ok(c.post(f"{md}/instrument", json={"code": "SEIS-1", "name": "Seismograph", "instrument_type": "SEISMOGRAPH", "serial_number": "S1"}), 201)
    ok(c.patch(f"{md}/monitor_station/{st['id']}", json={"instrument_id": seis["id"]}))

    # measurements are refused until the tolerances from the approved design exist
    wo = ok(c.post("/api/v1/ops/work-orders", json={"title": "Production blast P1-B310", "area_id": area["id"], "planned_start": str(today - timedelta(days=6)),
                                                    "planned_end": str(today + timedelta(days=6)), "forecast_tonnes": 12000,
                                                    "engineering_forecast_ref": "FC-2026-47"}), 201)
    assert wo["code"] == f"WO-{today:%y}-0001" and wo["status"] == "OPEN"
    sched = ok(c.post(f"/api/v1/ops/work-orders/{wo['id']}/standard-schedule", json={"blast_date": str(today), "responsible_id": tech["id"]}), 201)
    assert len(sched["created"]) == 7
    assert ok(c.post(f"/api/v1/ops/work-orders/{wo['id']}/standard-schedule", json={"blast_date": str(today)}), 201)["created"] == []

    pat = ok(c.post("/api/v1/ops/patterns", json={"bench_id": bench["id"], "design_document_ref": "DBP-47 rev B",
                                                  "approved_by": "J. Engineer, P.Eng.", "hole_diameter_mm": 140}), 201)
    assert pat["code"].startswith("PT-P1-B310-")
    # blast refused before the design is imported
    r = c.post("/api/v1/ops/blasts", json={"work_order_id": wo["id"], "pattern_id": pat["id"], "approved_plan_ref": "BP-47", "planned_date": str(today)})
    assert r.status_code == 409

    bad = HOLES_CSV + "\nR3-01,abc,500,310,13\nR1-01,1,1,1,13\nX9,1,1,1,13"
    v = ok(c.post(f"/api/v1/ops/patterns/{pat['id']}/holes/import", files={"file": ("d.csv", bad, "text/csv")}))
    assert v["dry_run"] and v["holes"] == 8 and v["error_count"] == 3
    assert any("duplicate" in e for e in v["errors"]) and any("row is required" in e for e in v["errors"])
    assert c.post(f"/api/v1/ops/patterns/{pat['id']}/holes/import?dry_run=false", files={"file": ("d.csv", bad, "text/csv")}).status_code == 422
    imp = ok(c.post(f"/api/v1/ops/patterns/{pat['id']}/holes/import?dry_run=false", files={"file": ("d.csv", HOLES_CSV, "text/csv")}))
    assert imp["holes"] == 8 and imp["rows"] == 2
    pd = ok(c.get(f"/api/v1/drillholes/patterns/{pat['id']}"))
    assert len(pd["holes"]) == 8 and {h["row"] for h in pd["holes"]} == {1, 2}
    assert c.post(f"/api/v1/ops/patterns/{pat['id']}/drilled", json={"drilled_on": str(today + timedelta(days=1))}).status_code == 422
    ok(c.post(f"/api/v1/ops/patterns/{pat['id']}/drilled", json={"drilled_on": str(today - timedelta(days=1))}))
    ok(c.post(f"/api/v1/ops/patterns/{pat['id']}/loading-references", json={"document_ref": "ALP-47", "revision": "B",
                                                                            "approved_by": "J. Engineer", "approved_on": str(today - timedelta(days=7))}), 201)

    hole0 = pd["holes"][0]["id"]
    r = c.post(f"/api/v1/drillholes/holes/{hole0}/measurements", json={"measured_depth_m": 13.0, "technician_id": tech["id"]})
    assert r.status_code == 409 and "DEPTH_TOL" in r.text
    for p, lo, hi in (("DEPTH_TOL", -0.3, 0.3), ("DEVIATION_TOL", None, 0.5), ("PPV", None, 12.5)):
        ok(c.post(f"{md}/reference-limits/new", json={"parameter": p, "min_value": lo, "max_value": hi, "source_document": "Design DBP-47 rev B §3",
                                                     "owner": "J. Engineer", "effective_from": str(today - timedelta(days=30))}), 201)
    for h in pd["holes"]:
        ok(c.post(f"/api/v1/drillholes/holes/{h['id']}/measurements",
                  json={"measured_depth_m": 13.05, "toe_deviation_m": 0.2, "technician_id": tech["id"]}), 201)

    blast = ok(c.post("/api/v1/ops/blasts", json={"work_order_id": wo["id"], "pattern_id": pat["id"], "approved_plan_ref": "BP-47 rev B",
                                                  "planned_date": str(today), "blaster_id": blaster["id"]}), 201)
    assert blast["code"] == f"BL-{today:%y}-0001" and blast["status"] == "PLANNED"
    assert c.post("/api/v1/ops/blasts", json={"work_order_id": wo["id"], "pattern_id": pat["id"], "approved_plan_ref": "BP-dup",
                                              "planned_date": str(today)}).status_code == 409  # one blast per pattern
    bid = blast["id"]
    d = ok(c.get(f"/api/v1/blasts/{bid}"))
    assert len(d["checkpoints"]) == 16 and len(d["pre_blast_inspection"]["items"]) == 8

    def advance(to, **extra):
        return ok(c.post(f"/api/v1/blasts/{bid}/transition", json={"to_status": to, **extra}))

    def complete(stage, skip=()):
        for cp in ok(c.get(f"/api/v1/blasts/{bid}"))["checkpoints"]:
            if cp["stage"] == stage and not cp["completed"] and cp["name"] not in skip:
                ok(c.post(f"/api/v1/checkpoints/{cp['id']}/complete", json={"evidence_ref": f"DOC-{cp['id']}"}))

    advance("IN_PREPARATION")
    r = c.post(f"/api/v1/blasts/{bid}/transition", json={"to_status": "UNDER_INSPECTION"})
    assert r.status_code == 409 and "Checkpoint open" in r.text
    complete("PREPARATION")
    advance("UNDER_INSPECTION")

    ok(c.post(f"/api/v1/blasts/{bid}/inventory", json={"movement_type": "RECEIVED", "quantity": 4.0, "document_ref": "BL-1001",
                                                       "product_name": "Bulk emulsion (site product)"}), 201)
    complete("LOADING")
    complete("PRE_BLAST", skip=("External authorization reference recorded",))
    insp = ok(c.get(f"/api/v1/blasts/{bid}"))["pre_blast_inspection"]
    for it in insp["items"]:
        ok(c.patch(f"/api/v1/checklist-items/{it['id']}", json={"result": "YES"}))
    ok(c.post(f"/api/v1/inspections/{insp['id']}/complete", json={"inspector_id": blaster["id"]}))
    det = ok(c.post(f"/api/v1/ops/blasts/{bid}/detonator-record", json={"inventory_lot_ref": "LOT-77", "units_issued": 10,
                                                                         "authorized_personnel": "Bob Blaster", "procedure_ref": "PRO-EDT-01"}), 201)
    assert c.post(f"/api/v1/ops/blasts/{bid}/detonator-record", json={"inventory_lot_ref": "LOT-77", "units_issued": 10,
                                                                      "authorized_personnel": "Bob Blaster", "procedure_ref": "PRO"}).status_code == 409
    advance("AUTHORIZED", authorization_ref="AUTH-2026-112", authorized_by="Bob Blaster", authorized_role="Blaster in charge")
    advance("IN_PROGRESS")
    review = ok(c.get(f"/api/v1/postblast/reviews/{bid}"))
    assert review["stage"] == "DATA_COLLECTION"  # created automatically at firing
    advance("AWAITING_VERIFICATION")

    csv_v = f"station_code,recorded_at,ppv_mm_s,dominant_frequency_hz,blast_code\nV-01,{today}T11:05:00,3.4,18,{blast['code']}\n"
    ok(c.post("/api/v1/vibration/import", files={"file": ("v.csv", csv_v, "text/csv")}))
    ok(c.post(f"/api/v1/blasts/{bid}/inventory", json={"movement_type": "USED", "quantity": 3.6, "document_ref": "BL-1002"}), 201)
    ok(c.post(f"/api/v1/blasts/{bid}/inventory", json={"movement_type": "RETURNED", "quantity": 0.4, "document_ref": "BL-1003"}), 201)
    complete("POST_BLAST")
    advance("COMPLETED")

    ok(c.patch(f"/api/v1/detonators/{det['id']}", json={"units_used": 8, "units_returned": 2}))
    ok(c.post(f"/api/v1/detonators/{det['id']}/verify", json={"verified_by": "QSSE Advisor"}))
    ok(c.patch(f"/api/v1/postblast/reviews/{bid}", json={
        "operational_deviations": "None significant; no post-blast scan (scanner unavailable).", "plan_compliance": "Executed per BP-47 rev B.",
        "fragmentation_observation": "Good fragmentation.", "fragmentation_rating": 4, "geology_observation": "Competent granite.",
        "lessons_learned": "None."}))
    for _ in range(6):
        ok(c.post(f"/api/v1/postblast/reviews/{bid}/advance"))
    assert ok(c.get(f"/api/v1/postblast/reviews/{bid}"))["stage"] == "COMPLETED"
    advance("CLOSED")

    ok(c.patch(f"/api/v1/ops/work-orders/{wo['id']}", json={"status": "IN_PROGRESS"}))
    ok(c.patch(f"/api/v1/ops/work-orders/{wo['id']}", json={"status": "COMPLETED", "actual_tonnes": 11800}))

    kpis = {k["key"]: k for k in ok(c.get("/api/v1/kpis", params={"start": str(today - timedelta(days=29)), "end": str(today)}))}
    assert kpis["drillhole_inspection_compliance"]["value"] == 100 and kpis["drillhole_deviation_rate"]["value"] == 0
    assert kpis["vibration_monitoring_compliance"]["denominator"] >= 1
    pdf = c.get(f"/api/v1/reports/blast.pdf?blast_id={bid}")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert c.get(f"/api/v1/reports/drillholes.pdf?pattern_id={pat['id']}").status_code == 200
    for key in ("daily", "laboratory", "vibration", "qaqc", "kpi-monthly"):
        assert c.get(f"/api/v1/reports/{key}.pdf").status_code == 200, key
    with_audit = ok(c.get("/api/v1/records/blast_status_history", params={"filters": f"blast_id={bid}"}))
    assert [x["to_status"] for x in sorted(with_audit["items"], key=lambda x: x["id"])] == [
        "PLANNED", "IN_PREPARATION", "UNDER_INSPECTION", "AUTHORIZED", "IN_PROGRESS", "AWAITING_VERIFICATION", "COMPLETED", "CLOSED"]


def test_codes_deliveries_cancellation_and_deletion(c):
    today = clock.today()
    area = ok(c.get("/api/v1/masterdata/area/options"))[0]
    bench = ok(c.get("/api/v1/masterdata/bench/options"))[0]
    wo2 = ok(c.post("/api/v1/ops/work-orders", json={"title": "Second blast", "area_id": area["id"], "planned_start": str(today),
                                                     "planned_end": str(today + timedelta(days=9))}), 201)
    assert wo2["code"].endswith("-0002")
    assert c.post("/api/v1/ops/work-orders", json={"code": wo2["code"].lower(), "title": "dup", "area_id": area["id"],
                                                   "planned_start": str(today), "planned_end": str(today)}).status_code == 409
    assert c.post("/api/v1/ops/work-orders", json={"title": "bad dates", "area_id": area["id"], "planned_start": str(today),
                                                   "planned_end": str(today - timedelta(days=1))}).status_code == 422
    dl = ok(c.post("/api/v1/ops/deliveries", json={"product_name": "Bulk emulsion", "destination_area_id": area["id"],
                                                   "planned_date": str(today + timedelta(days=2)), "planned_qty": 18}), 201)
    assert dl["code"] == f"DL-{today:%y}-001"
    assert any(x["code"] == dl["code"] for x in ok(c.get("/api/v1/planning/deliveries")))
    item = ok(c.post(f"/api/v1/ops/work-orders/{wo2['id']}/schedule-items", json={"activity": "DRILLING", "planned_date": str(today)}), 201)
    assert c.post(f"/api/v1/ops/work-orders/{wo2['id']}/schedule-items", json={"activity": "DANCING", "planned_date": str(today)}).status_code == 422
    ok(c.post(f"/api/v1/ops/schedule-items/{item['id']}/cancel", json={"reason": "Pattern moved to next week"}))

    p2 = ok(c.post("/api/v1/ops/patterns", json={"bench_id": bench["id"], "design_document_ref": "DBP-48", "approved_by": "J. Engineer",
                                                 "hole_diameter_mm": 140}), 201)
    ok(c.post(f"/api/v1/ops/patterns/{p2['id']}/holes/import?dry_run=false", files={"file": ("d.csv", HOLES_CSV, "text/csv")}))
    b2 = ok(c.post("/api/v1/ops/blasts", json={"work_order_id": wo2["id"], "pattern_id": p2["id"], "approved_plan_ref": "BP-48",
                                               "planned_date": str(today + timedelta(days=7))}), 201)
    assert c.delete(f"/api/v1/ops/patterns/{p2['id']}").status_code == 409  # used by a blast
    ok(c.delete(f"/api/v1/ops/blasts/{b2['id']}"))  # untouched planned blast: deletable
    ok(c.delete(f"/api/v1/ops/patterns/{p2['id']}"))
    assert c.patch(f"/api/v1/ops/work-orders/{wo2['id']}", json={"status": "CANCELLED"}).status_code == 422  # reason required
    ok(c.patch(f"/api/v1/ops/work-orders/{wo2['id']}", json={"status": "CANCELLED", "reason": "Client postponed the bench"}))
    assert c.patch(f"/api/v1/ops/work-orders/{wo2['id']}", json={"status": "IN_PROGRESS"}).status_code == 409


def test_templates_are_site_editable(c):
    t = ok(c.get("/api/v1/ops/templates"))
    assert t["pre_blast_checklist"]["is_default"]
    r = c.put("/api/v1/ops/templates/blast_checkpoints", json={"items": [["PREPARATION", "Only one"]], "source_document": "SOP-1"})
    assert r.status_code == 422 and "External authorization" in r.text  # the workflow's checkpoint cannot be removed
    ok(c.put("/api/v1/ops/templates/pre_blast_checklist", json={"items": ["Guards posted", "Siren sounded", "Area clear"],
                                                                "source_document": "Site SOP BL-03 rev 4"}))
    today = clock.today()
    area = ok(c.get("/api/v1/masterdata/area/options"))[0]
    bench = ok(c.get("/api/v1/masterdata/bench/options"))[0]
    wo = ok(c.post("/api/v1/ops/work-orders", json={"title": "Template check", "area_id": area["id"], "planned_start": str(today),
                                                    "planned_end": str(today)}), 201)
    p = ok(c.post("/api/v1/ops/patterns", json={"bench_id": bench["id"], "design_document_ref": "DBP-49", "approved_by": "J. Engineer",
                                                "hole_diameter_mm": 115}), 201)
    ok(c.post(f"/api/v1/ops/patterns/{p['id']}/holes/import?dry_run=false", files={"file": ("d.csv", HOLES_CSV, "text/csv")}))
    b = ok(c.post("/api/v1/ops/blasts", json={"work_order_id": wo["id"], "pattern_id": p["id"], "approved_plan_ref": "BP-49",
                                              "planned_date": str(today)}), 201)
    items = ok(c.get(f"/api/v1/blasts/{b['id']}"))["pre_blast_inspection"]["items"]
    assert [i["text"] for i in items] == ["Guards posted", "Siren sounded", "Area clear"]


def test_operational_permissions(c):
    from helpers import ADMIN_PWD
    from fastapi.testclient import TestClient
    from helpers import CSRF, login

    from app.main import app

    ok(c.post("/api/v1/users", json={"username": "viewer1", "full_name": "View Only", "role": "VIEWER", "password": ADMIN_PWD}), 201)
    ok(c.post("/api/v1/users", json={"username": "qsse2", "full_name": "Q Two", "role": "QSSE", "password": ADMIN_PWD}), 201)
    for u in ("viewer1", "qsse2"):
        with TestClient(app, headers=CSRF) as v:
            login(v, u, ADMIN_PWD)
            v.post("/api/v1/auth/change-password", json={"current_password": ADMIN_PWD, "new_password": "Other-pass-2026"})
            area = v.get("/api/v1/masterdata/area/options").json()[0]
            r = v.post("/api/v1/ops/work-orders", json={"title": "No", "area_id": area["id"], "planned_start": "2026-01-01", "planned_end": "2026-01-02"})
            assert r.status_code == 403
            assert v.post("/api/v1/ops/patterns", json={"bench_id": 1, "design_document_ref": "x", "approved_by": "xxx", "hole_diameter_mm": 100}).status_code == 403


def test_hole_template_download(c):
    r = c.get("/api/v1/ops/patterns/holes-template.csv")
    assert r.status_code == 200 and "hole_code,x,y,z,depth_m" in r.text
