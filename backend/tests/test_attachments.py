"""Evidence attachments: accepted formats, content checks, permissions, integrity, voiding, backups."""
import io
import zipfile
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from helpers import CSRF, login, signed_client

from app import models as m
from app.config import ATTACHMENT_DIR
from app.db import SessionLocal
from app.main import app
from app.ops import backup as bk
from app.seed.generator import reset_and_seed

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def office(kind: str, macro: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml" if kind == "docx" else "xl/workbook.xml", "<x/>")
        if macro:
            z.writestr("word/vbaProject.bin", b"\x00")
    return buf.getvalue()


@pytest.fixture(scope="module")
def ids():
    reset_and_seed()
    with SessionLocal() as db:
        return {"blast": db.query(m.Blast).filter_by(status="AUTHORIZED").first().id,
                "obs": db.query(m.SafetyObservation).first().id,
                "cal": db.query(m.Calibration).first().id,
                "cp": db.query(m.BlastCheckpoint).first().id}


def up(c, entity, eid, name, data, desc=None):
    return c.post("/api/v1/attachments", data={"entity": entity, "entity_id": str(eid), **({"description": desc} if desc else {})},
                  files={"file": (name, data, "application/octet-stream")})


def test_accepted_formats_and_integrity(ids):
    with signed_client("eroy") as c:
        for name, data in (("photo.png", PNG), ("photo.JPG", JPG), ("certificate.pdf", PDF), ("report.docx", office("docx")),
                           ("data.xlsx", office("xlsx")), ("notes.txt", "Mesure prise à 10 h — OK".encode()), ("log.csv", b"a,b\n1,2\n")):
            r = up(c, "blast", ids["blast"], name, data, "evidence")
            assert r.status_code == 201, (name, r.text)
            a = r.json()
            assert a["sha256"] and a["size_bytes"] == len(data) and a["uploaded_by"] == "Émilie Roy"
            f = c.get(a["url"])
            assert f.status_code == 200 and f.content == data
            assert f.headers["x-content-type-options"] == "nosniff" and "sandbox" in f.headers["content-security-policy"]
            assert f.headers["content-disposition"].startswith("attachment")
        img = c.get("/api/v1/attachments", params={"entity": "blast", "entity_id": ids["blast"]}).json()
        assert len(img) == 7 and sum(x["is_image"] for x in img) == 2
        inline = c.get(img[-1]["url"] + "?inline=true")  # oldest = the PNG
        assert inline.headers["content-disposition"].startswith("inline")
        counts = c.get("/api/v1/attachments/counts", params={"entity": "blast", "ids": f"{ids['blast']},999999"}).json()
        assert counts == {str(ids["blast"]): 7}
        # tampering with the stored file is detected
        with SessionLocal() as db:
            a = db.query(m.Attachment).filter_by(filename="notes.txt").one()
            (ATTACHMENT_DIR / a.stored_name).write_bytes(b"changed")
            aid = a.id
        assert c.get(f"/api/v1/attachments/{aid}/file").status_code == 409


@pytest.mark.parametrize("name,data,code", [
    ("tool.exe", b"MZ\x90\x00", 415), ("page.html", b"<html></html>", 415), ("logo.svg", b"<svg/>", 415),
    ("fake.png", b"MZ\x90\x00 not a png", 415), ("fake.pdf", JPG, 415), ("macro.docx", office("docx", macro=True), 415),
    ("zip.docx", b"PK\x03\x04garbage", 415), ("text.txt", b"<script>alert(1)</script>", 415), ("bin.txt", b"ab\x00cd", 415),
    ("empty.pdf", b"", 422), ("noext", PDF, 415),
])
def test_refused_files(ids, name, data, code):
    with signed_client("eroy") as c:
        assert up(c, "blast", ids["blast"], name, data).status_code == code


def test_size_limit(ids, monkeypatch):
    import app.routers.attachments as att

    monkeypatch.setattr(att, "ATTACHMENT_MAX_MB", 0.001)
    with signed_client("eroy") as c:
        assert up(c, "blast", ids["blast"], "big.pdf", PDF + b"0" * 2000).status_code == 413


def test_targets_and_permissions(ids):
    with signed_client("eroy") as c:  # technician
        assert up(c, "app_user", 1, "x.pdf", PDF).status_code == 422
        assert up(c, "blast", 999999, "x.pdf", PDF).status_code == 404
        assert up(c, "calibration", ids["cal"], "cert.pdf", PDF).status_code == 201
        assert up(c, "training_record", 1, "cert.pdf", PDF).status_code == 403
    with signed_client("iouellet") as c:  # viewer: read only
        assert up(c, "safety_observation", ids["obs"], "x.pdf", PDF).status_code == 403
        assert c.get("/api/v1/attachments", params={"entity": "blast", "entity_id": ids["blast"]}).status_code == 200
        t = c.get("/api/v1/attachments/types").json()
        assert not any(v["can_attach"] for v in t["entities"].values())
    with signed_client("npelletier") as c:  # QSSE
        assert up(c, "safety_observation", ids["obs"], "site.jpg", JPG, "Barricade in place").status_code == 201
        assert up(c, "blast_checkpoint", ids["cp"], "x.pdf", PDF).status_code == 403


def test_void_rules_and_audit(ids):
    with signed_client("eroy") as c:
        a = up(c, "blast_checkpoint", ids["cp"], "wrong.pdf", PDF).json()
    with signed_client("kbouchard") as other:
        assert other.post(f"/api/v1/attachments/{a['id']}/void", json={"reason": "not mine"}).status_code == 403
    with signed_client("eroy") as c:
        assert c.post(f"/api/v1/attachments/{a['id']}/void", json={"reason": "no"}).status_code == 422
        v = c.post(f"/api/v1/attachments/{a['id']}/void", json={"reason": "Uploaded to the wrong checkpoint"}).json()
        assert v["voided"] and v["voided_by"] == "Émilie Roy"
        assert c.post(f"/api/v1/attachments/{a['id']}/void", json={"reason": "again again"}).status_code == 409
        listed = c.get("/api/v1/attachments", params={"entity": "blast_checkpoint", "entity_id": ids["cp"]}).json()
        assert listed[-1]["voided"] and c.get(listed[-1]["url"]).status_code == 200  # kept for the audit trail
        assert c.get("/api/v1/attachments/counts", params={"entity": "blast_checkpoint", "ids": str(ids["cp"])}).json() == {}
        b = up(c, "blast_checkpoint", ids["cp"], "old.pdf", PDF).json()
    with SessionLocal() as db:  # older than 24 h: only an administrator may void it
        x = db.get(m.Attachment, b["id"])
        x.created_at = x.created_at - timedelta(hours=25)
        db.commit()
        assert db.query(m.AuditLog).filter_by(entity="attachment", entity_id=a["id"]).count() == 2
    with signed_client("eroy") as c:
        assert c.post(f"/api/v1/attachments/{b['id']}/void", json={"reason": "too late now"}).status_code == 403
    with signed_client("admin") as adm:
        assert adm.post(f"/api/v1/attachments/{b['id']}/void", json={"reason": "Administrator correction"}).status_code == 200


def test_backup_and_restore_include_attachments(ids, tmp_path):
    with signed_client("eroy") as c:
        a = up(c, "blast", ids["blast"], "kept.pdf", PDF + b"kept").json()
    p = bk.create_backup(reason="att", dest_dir=tmp_path)
    import zipfile as zf

    with SessionLocal() as db:
        stored = db.get(m.Attachment, a["id"]).stored_name
    assert f"attachments/{stored}" in zf.ZipFile(p).namelist()
    (ATTACHMENT_DIR / stored).unlink()
    with TestClient(app, headers=CSRF) as c:
        login(c, "eroy")
        assert c.get(a["url"]).status_code == 410  # missing file reported, not a crash
    bk.restore_backup(p)
    with TestClient(app, headers=CSRF) as c:
        login(c, "eroy")
        r = c.get(a["url"])
        assert r.status_code == 200 and r.content == PDF + b"kept"


def test_demo_reset_clears_attachments(ids):
    reset_and_seed()
    assert not ATTACHMENT_DIR.exists() or not any(ATTACHMENT_DIR.rglob("*.*"))
