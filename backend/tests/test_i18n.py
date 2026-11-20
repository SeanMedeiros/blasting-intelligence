"""Server texts in French: catalogue completeness, language selection, translated responses, site-language templates."""
import string
import sys
from pathlib import Path

import pytest
from helpers import CSRF, login, signed_client

from app import models as m
from app.db import SessionLocal
from app.i18n import _, num, pick, set_lang
from app.locales.fr import FR

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from i18n_extract import templates  # noqa: E402


def _fields(t: str) -> set[str]:
    return {f for _txt, f, _spec, _conv in string.Formatter().parse(t) if f}


def test_every_server_text_has_a_french_translation_with_the_same_fields():
    tpl = templates(str(Path(__file__).resolve().parents[1] / "app"))
    assert len(tpl) > 350
    missing = [t for t in tpl if t not in FR]
    assert not missing, f"{len(missing)} without French, e.g. {missing[:5]}"
    bad = [t for t in tpl if _fields(t) != _fields(FR[t])]
    assert not bad, f"fields differ: {bad[:5]}"


def test_french_templates_format_like_the_english_ones():
    class Any:
        def __format__(self, spec):
            return "x"

        def __repr__(self):
            return "'x'"

    for en, fr in FR.items():
        kw = {f: Any() for f in _fields(en)}
        assert fr.format(**kw) is not None


def test_language_selection_and_number_format():
    assert pick("fr", None, None) == "fr" and pick(None, "FR", "en") == "fr"
    assert pick(None, None, "fr-CA,fr;q=0.9,en;q=0.8") == "fr" and pick(None, None, "de-DE") == "en" and pick(None, None, None) == "en"
    t = set_lang("fr")
    assert _("Blast not found") == "Sautage introuvable" and num(1234.5) == "1 234,5"
    set_lang("en")
    assert _("Blast not found") == "Blast not found" and num(1234.5) == "1,234.5"
    assert t is not None


def test_api_errors_and_validation_in_french():
    with signed_client("eroy") as c:
        assert c.get("/api/v1/blasts/999999").json()["detail"] == "Blast not found"
        assert c.get("/api/v1/blasts/999999", headers={"Accept-Language": "fr-CA"}).json()["detail"] == "Sautage introuvable"
        assert c.get("/api/v1/blasts/999999?lang=fr").json()["detail"] == "Sautage introuvable"
        r = c.post("/api/v1/safety/observations", json={"obs_type": "HAZARD"}, headers={"X-Lang": "fr"})
        assert r.status_code == 422 and any("requis" in d["msg"] for d in r.json()["detail"])
        r = c.post("/api/v1/ops/work-orders", json={"title": "ab", "area_id": 1, "planned_start": "2026-12-01", "planned_end": "2026-12-02"},
                   headers={"X-Lang": "fr"})
        assert r.status_code == 422 and "au moins 3 caractères" in r.json()["detail"][0]["msg"]


def test_workflow_requirements_kpis_and_alerts_in_french():
    with SessionLocal() as db:
        bid = db.query(m.Blast).filter_by(status="IN_PREPARATION").first().id
    with signed_client("jgagnon") as c:
        h = {"X-Lang": "fr"}
        d = c.get(f"/api/v1/blasts/{bid}", headers=h).json()
        assert any(x.startswith("Point de contrôle ouvert") or "trou(s)" in x for x in d["next_requirements"])
        assert "autorisation" in d["notice"]
        k = {x["key"]: x for x in c.get("/api/v1/kpis", headers=h).json()}
        assert k["schedule_adherence"]["name"] == "Respect de l'échéancier" and "par lot : DENSITY, VISCOSITY" in k["lab_testing_completion"]["formula"]
        alerts = c.get("/api/v1/alerts", headers=h).json()
        assert alerts and all(a["title"] for a in alerts)
        assert any("Étalonnage" in a["title"] or "retard" in a["title"] or "Formation" in a["title"] for a in alerts)
        mtx = c.get("/api/v1/safety/risk-matrix", headers=h).json()
        assert "Rare" in mtx["likelihood"] or "Peu probable" in mtx["likelihood"]


def test_site_language_templates_and_french_authorization_checkpoint(monkeypatch):
    import app.config as cfg
    from app.services import templates as tpl

    monkeypatch.setattr(cfg, "DEFAULT_LANGUAGE", "fr")
    cps = tpl.default("blast_checkpoints")
    assert ["PRE_BLAST", "Référence d'autorisation externe consignée"] in cps
    assert tpl.default("pre_blast_checklist")[0].startswith("Plan de sautage approuvé")
    assert tpl.is_auth("Référence d'autorisation externe consignée") and tpl.is_auth("External authorization reference recorded")
    # a French site template keeps the workflow working: the French authorization checkpoint is recognised
    with signed_client("admin") as c:
        r = c.put("/api/v1/ops/templates/blast_checkpoints", json={"items": [["PREPARATION", "Plan approuvé consigné"],
                                                                           ["PRE_BLAST", "Référence d'autorisation externe consignée"]],
                                                                 "source_document": "PRO-SAU-01 rév. 3"})
        assert r.status_code == 200
        bad = c.put("/api/v1/ops/templates/blast_checkpoints", json={"items": [["PREPARATION", "Seulement un"]], "source_document": "PRO"},
                    headers={"X-Lang": "fr"})
        assert bad.status_code == 422 and "exigé par le flux" in bad.text
    with SessionLocal() as db:
        db.query(m.AppSetting).filter(m.AppSetting.key.like("template:%")).delete(synchronize_session=False)
        db.commit()


def test_stored_notes_use_the_site_language(monkeypatch):
    import app.config as cfg
    from app.i18n import S_

    monkeypatch.setattr(cfg, "DEFAULT_LANGUAGE", "fr")
    set_lang("en")  # the requester's language does not matter for stored text
    assert S_("Blast record created") == "Dossier de sautage créé"
    monkeypatch.setattr(cfg, "DEFAULT_LANGUAGE", "en")
    set_lang("fr")
    assert S_("Blast record created") == "Blast record created"
    set_lang("en")


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_meta_and_login_errors_follow_language(lang):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, headers={**CSRF, "Accept-Language": lang}) as c:
        r = c.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})
        assert r.json()["detail"] == ("Invalid username or password" if lang == "en" else "Nom d'utilisateur ou mot de passe invalide")
        login(c, "eroy")
        assert c.get("/api/v1/meta").json()["site"]


def _pdf_text(data: bytes) -> str:
    import io

    from pypdf import PdfReader
    return " ".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)


def test_reports_in_french_and_english():
    with SessionLocal() as db:
        bid = db.query(m.Blast).filter_by(status="CLOSED").first().id
        pid = db.query(m.DrillPattern).first().id
        sid = db.query(m.Survey).filter_by(survey_type="FACE_PROFILE").first().id
    with signed_client("jgagnon") as c:
        cat = c.get("/api/v1/reports?lang=fr").json()
        assert any(x["title"] == "Rapport mensuel des indicateurs" for x in cat)
        fr = _pdf_text(c.get("/api/v1/reports/kpi-monthly.pdf", params={"month": "2026-11", "lang": "fr"}).content)
        assert "Rapport mensuel des indicateurs — novembre 2026" in fr and "Méthodes de calcul" in fr and "Indicator" not in fr
        assert "DONNÉES DE DÉMONSTRATION — SITE FICTIF" in fr and "Page 1" in fr and "Hors cible" in fr and "OFF_TARGET" not in fr
        en = _pdf_text(c.get("/api/v1/reports/kpi-monthly.pdf", params={"month": "2026-11"}).content)
        assert "Monthly KPI Report — November 2026" in en and "Calculation methods" in en
        for key, params, word in (("daily", {}, "Rapport opérationnel quotidien"), ("blast", {"blast_id": bid}, "Rapport d’activité de sautage"),
                                  ("survey", {"survey_id": sid}, "Rapport de levé 3D"), ("drillholes", {"pattern_id": pid}, "Registre des trous"),
                                  ("laboratory", {}, "Rapport du laboratoire"), ("vibration", {}, "VPP"), ("qaqc", {}, "Rapport AQ/CQ")):
            r = c.get(f"/api/v1/reports/{key}.pdf", params={**params, "lang": "fr"})
            assert r.status_code == 200, key
            assert word in _pdf_text(r.content), key


def test_code_labels_match_the_ui_catalogues():
    import subprocess

    tool = Path(__file__).resolve().parents[1] / "tools" / "i18n_codes.py"
    assert subprocess.run([sys.executable, str(tool), "--check"]).returncode == 0, "run tools/i18n_codes.py"
    from app.i18n import code_label
    set_lang("fr")
    assert code_label("IN_PROGRESS") == "En cours" and code_label("XYZ_UNKNOWN") == "XYZ_UNKNOWN"
    set_lang("en")
    assert code_label("IN_PROGRESS") == "In Progress"
