"""Modules 10, 11, 12 tests: post-blast workflow, KPI targets, automated reports."""


import pytest  # noqa: E402

from helpers import CSRF, signed_client  # noqa: E402


from app.seed.generator import reset_and_seed  # noqa: E402

H = CSRF


@pytest.fixture(scope="module")
def c():
    reset_and_seed()
    with signed_client() as client:
        yield client


def review(c, stage):
    return next(r for r in c.get("/api/v1/postblast/reviews").json()["reviews"] if r["stage"] == stage)


def test_reviews_list_and_detail(c):
    d = c.get("/api/v1/postblast/reviews").json()
    assert d["stages"][0] == "DATA_COLLECTION" and any(r["overdue"] for r in d["reviews"])
    det = c.get(f"/api/v1/postblast/reviews/{d['reviews'][0]['blast_id']}").json()
    assert "drillholes" in det["collected"] and "qualified engineer" in det["notice"]


def test_workflow_requirements_and_engineering_review(c):
    r = review(c, "INTERPRETATION")
    bid = r["blast_id"]
    url = f"/api/v1/postblast/reviews/{bid}"
    # clear the geology field: advancing must be refused
    c.patch(url, json={"geology_observation": ""}, headers=H)
    res = c.post(f"{url}/advance", headers=H)
    assert res.status_code == 409 and res.json()["detail"]["unmet"]
    c.patch(url, json={"geology_observation": "Sheared mafic volcanic, water along east wall", "fragmentation_rating": 3,
                       "fragmentation_observation": "Oversize at toe"}, headers=H)
    assert c.post(f"{url}/advance", headers=H).json()["stage"] == "IMPROVEMENT_PROPOSAL"
    c.patch(url, json={"lessons_learned": "Re-verify holes within 24 h of loading", "improvement_proposal": "Propose earlier re-verification"}, headers=H)
    assert c.post(f"{url}/advance", headers=H).json()["stage"] == "DOCUMENTATION"
    blocked = c.post(f"{url}/advance", headers=H)
    assert blocked.status_code == 409 and "qualified engineer" in blocked.json()["detail"]["unmet"][0]
    assert c.post(f"{url}/engineering-review", json={"reviewer": "J. Gagnon", "decision": "ACCEPTED", "comment": "Agreed for trial"}, headers=H).status_code == 200
    assert c.post(f"{url}/advance", headers=H).json()["stage"] == "COMPLETED"
    assert c.patch(url, json={"lessons_learned": "x"}).status_code == 409


def test_validation(c):
    bid = review(c, "COMPLETED")["blast_id"]
    assert c.patch(f"/api/v1/postblast/reviews/{bid}", json={"fragmentation_rating": 9}).status_code == 422
    assert c.get("/api/v1/postblast/reviews/99999").status_code == 404


def test_compare(c):
    ids = [r["blast_id"] for r in c.get("/api/v1/postblast/reviews").json()["reviews"][:3]]
    rows = c.get("/api/v1/postblast/compare", params={"blasts": ",".join(map(str, ids))}).json()
    assert len(rows) == 3 and "max_ppv_mm_s" in rows[0]
    assert c.get("/api/v1/postblast/compare", params={"blasts": str(ids[0])}).status_code == 422


def test_kpi_targets_configurable(c):
    assert c.put("/api/v1/kpis/targets/schedule_adherence", json={"target": 150, "source": "x doc"}).status_code == 422
    r = c.put("/api/v1/kpis/targets/schedule_adherence", json={"target": 85, "source": "Client contract KPI schedule (fictional)"}, headers=H)
    assert r.status_code == 200
    k = next(x for x in c.get("/api/v1/kpis").json() if x["key"] == "schedule_adherence")
    assert k["target"] == 85 and k["target_is_demo"] is False
    assert c.put("/api/v1/kpis/targets/nope", json={"target": 1, "source": "abc"}).status_code == 404
    s = c.get("/api/v1/kpis/series", params={"granularity": "day", "start": "2026-11-01", "end": "2026-11-30"}).json()
    assert len(s["labels"]) == 30


@pytest.mark.parametrize("key,params", [
    ("daily", {}), ("laboratory", {}), ("vibration", {}), ("qaqc", {}), ("kpi-monthly", {"month": "2026-11"}),
])
def test_period_reports(c, key, params):
    r = c.get(f"/api/v1/reports/{key}.pdf", params=params)
    assert r.status_code == 200 and r.content[:4] == b"%PDF" and len(r.content) > 3000
    csv = c.get(f"/api/v1/reports/{key}.csv", params=params)
    assert csv.status_code == 200 and "DEMONSTRATION DATA" in csv.text


def test_record_reports(c):
    b = next(x for x in c.get("/api/v1/blasts").json()["blasts"] if x["status"] == "CLOSED")
    s = next(x for x in c.get("/api/v1/surveys", params={"survey_type": "FACE_PROFILE"}).json() if x["quality_status"] == "ACCEPTED")
    p = c.get("/api/v1/drillholes/patterns").json()[5]
    for key, params in (("blast", {"blast_id": b["id"]}), ("survey", {"survey_id": s["id"]}), ("drillholes", {"pattern_id": p["id"]})):
        r = c.get(f"/api/v1/reports/{key}.pdf", params=params)
        assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert c.get("/api/v1/reports/blast.pdf").status_code == 422
    assert c.get("/api/v1/reports/unknown.pdf").status_code == 404
    assert len(c.get("/api/v1/reports").json()) == 8


def test_reference_limit_configuration(c):
    lim = next(x for x in c.get("/api/v1/records/reference_limit", params={"limit": 100}).json()["items"] if x["parameter"] == "PPV")
    url = f"/api/v1/settings/limits/{lim['id']}"
    body = {"max_value": 12.0, "source_document": "Site permit condition 4.2 (fictional)", "owner": "QSSE manager", "effective_from": "2026-12-04"}
    assert c.put(url, json={**body, "source_document": "DEMO PLACEHOLDER x"}).status_code == 422
    assert c.put(url, json={**body, "min_value": 20.0}).status_code == 422
    assert c.put(url, json=body, headers=H).status_code == 200
    st = {s["code"]: s for s in c.get("/api/v1/vibration/stations").json()}
    assert st["V-03"]["limit_ppv_mm_s"] == 12.0 and st["V-03"]["limit_is_demo"] is False
