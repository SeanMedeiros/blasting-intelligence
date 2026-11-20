"""Evidence files attached to records.

Rules
* Only document and image formats are accepted, recognised from their CONTENT (magic bytes / structure),
  not only from the extension. Executables, scripts, HTML and SVG are refused; Office files with macros too.
* Each file is stored under data/attachments/yyyy/mm/<uuid>.<ext>; its SHA-256 is recorded at upload and
  checked again at every download.
* Attachments are never deleted. They can be voided with a reason (uploader within 24 h, or an
  administrator); voided files stay listed and downloadable for the audit trail.
* Attaching requires one of the permissions of the record type (see ATTACHABLE).
"""
from __future__ import annotations

import hashlib
import io
import re
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from .. import models as m
from ..config import ATTACHMENT_DIR, ATTACHMENT_MAX_MB
from ..db import get_db
from ..services.audit import record
from ..services.security import Actor, permissions_for, signed_in
from ..i18n import _

router = APIRouter(prefix="/api/v1/attachments", tags=["Attachments"])

# record type → (model, permissions that allow attaching)
ATTACHABLE: dict[str, tuple[type, tuple[str, ...]]] = {
    "work_order": (m.WorkOrder, ("planning.write",)),
    "drill_pattern": (m.DrillPattern, ("pattern.manage", "drillhole.measure")),
    "drillhole_measurement": (m.DrillholeMeasurement, ("drillhole.measure",)),
    "blast": (m.Blast, ("blast.operate",)),
    "blast_checkpoint": (m.BlastCheckpoint, ("blast.operate",)),
    "inspection": (m.Inspection, ("blast.operate", "safety.report")),
    "detonator_record": (m.DetonatorRecord, ("detonator.record", "detonator.verify")),
    "post_blast_review": (m.PostBlastReview, ("postblast.edit", "postblast.review")),
    "survey": (m.Survey, ("survey.write",)),
    "lab_test": (m.LabTest, ("lab.test",)),
    "nonconformance": (m.NonConformance, ("lab.test", "lab.disposition")),
    "vibration_event": (m.VibrationEvent, ("vibration.write",)),
    "safety_observation": (m.SafetyObservation, ("safety.report", "safety.close")),
    "capa": (m.Capa, ("capa.create", "safety.close")),
    "calibration": (m.Calibration, ("calibration.record",)),
    "training_record": (m.TrainingRecord, ("personnel.manage",)),
    "delivery": (m.Delivery, ("planning.write",)),
}

ZIP_MAGIC = b"PK\x03\x04"
TYPES = {  # extension → (content type, kind)
    ".jpg": ("image/jpeg", "jpeg"), ".jpeg": ("image/jpeg", "jpeg"), ".png": ("image/png", "png"), ".webp": ("image/webp", "webp"),
    ".pdf": ("application/pdf", "pdf"),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    ".csv": ("text/csv; charset=utf-8", "text"), ".txt": ("text/plain; charset=utf-8", "text"),
}
INLINE = {"jpeg", "png", "webp", "pdf"}  # may be displayed in the browser; everything else is downloaded


def _sniff(kind: str, data: bytes) -> bool:
    if kind == "jpeg":
        return data[:3] == b"\xff\xd8\xff"
    if kind == "png":
        return data[:8] == b"\x89PNG\r\n\x1a\n"
    if kind == "webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if kind == "pdf":
        return data[:5] == b"%PDF-"
    if kind in ("docx", "xlsx"):
        if data[:4] != ZIP_MAGIC:
            return False
        try:
            names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
        except zipfile.BadZipFile:
            return False
        if any(n.lower().endswith("vbaproject.bin") for n in names):
            raise HTTPException(415, _('Office files containing macros are not accepted'))
        return "[Content_Types].xml" in names and any(n.startswith("word/" if kind == "docx" else "xl/") for n in names)
    if kind == "text":
        head = data[:65536]
        if b"\x00" in head or head.lstrip()[:1] == b"<":
            return False
        try:
            head.decode("utf-8")
        except UnicodeDecodeError:
            try:
                head.decode("cp1252")
            except UnicodeDecodeError:
                return False
        return True
    return False


def _clean_name(name: str) -> str:
    base = Path(name or "file").name
    base = re.sub(r"[^\w.\- ()À-ÿ]", "_", base).strip(" .") or "file"
    return base[-200:]


def _target(db: Session, entity: str, entity_id: int):
    spec = ATTACHABLE.get(entity)
    if spec is None:
        raise HTTPException(422, _("Files cannot be attached to '{entity}'. Allowed: {v}", entity=entity, v=', '.join(sorted(ATTACHABLE))))
    obj = db.get(spec[0], entity_id)
    if obj is None:
        raise HTTPException(404, _('{entity} {entity_id} not found', entity=entity, entity_id=entity_id))
    return spec, obj


def _out(a: m.Attachment) -> dict:
    kind = TYPES.get(Path(a.stored_name).suffix, ("", ""))[1]
    return {"id": a.id, "entity": a.entity, "entity_id": a.entity_id, "filename": a.filename, "content_type": a.content_type,
            "size_bytes": a.size_bytes, "sha256": a.sha256, "description": a.description, "uploaded_by": a.uploaded_by,
            "uploaded_at": a.created_at.isoformat(timespec="seconds") + "Z", "is_image": kind in ("jpeg", "png", "webp"),
            "voided": a.voided, "void_reason": a.void_reason, "voided_by": a.voided_by,
            "voided_at": a.voided_at.isoformat(timespec="seconds") if a.voided_at else None,
            "url": f"/api/v1/attachments/{a.id}/file"}


@router.get("/types")
def types(actor: Actor = Depends(signed_in)):
    perms = permissions_for(actor.role)
    return {"extensions": sorted(TYPES), "max_mb": ATTACHMENT_MAX_MB,
            "entities": {k: {"can_attach": bool(set(v[1]) & perms)} for k, v in ATTACHABLE.items()}}


def _can_void(a: m.Attachment, actor: Actor) -> bool:
    if a.voided:
        return False
    return actor.role == "ADMIN" or (a.user_id == actor.user_id and datetime.now(UTC).replace(tzinfo=None) - a.created_at <= timedelta(hours=24))


@router.get("")
def list_attachments(entity: str, entity_id: int, db: Session = Depends(get_db), actor: Actor = Depends(signed_in)):
    _target(db, entity, entity_id)
    rows = db.scalars(select(m.Attachment).where(m.Attachment.entity == entity, m.Attachment.entity_id == entity_id)
                      .order_by(m.Attachment.voided, m.Attachment.id.desc()))
    return [_out(a) | {"can_void": _can_void(a, actor)} for a in rows]


@router.get("/counts")
def counts(entity: str, ids: str = Query(..., max_length=4000), db: Session = Depends(get_db)):
    """Number of valid attachments per record, for badges in lists."""
    try:
        id_list = [int(x) for x in ids.split(",") if x.strip()][:500]
    except ValueError:
        raise HTTPException(422, _('ids must be comma-separated integers')) from None
    rows = db.execute(select(m.Attachment.entity_id, func.count()).where(
        m.Attachment.entity == entity, m.Attachment.entity_id.in_(id_list or [-1]), m.Attachment.voided.is_(False))
        .group_by(m.Attachment.entity_id))
    return {str(i): n for i, n in rows}


@router.post("", status_code=201)
async def upload(entity: str = Form(...), entity_id: int = Form(...), description: str | None = Form(None),
                 file: UploadFile = File(...), db: Session = Depends(get_db), actor: Actor = Depends(signed_in)):
    spec, _obj = _target(db, entity, entity_id)
    if not set(spec[1]) & permissions_for(actor.role):
        raise HTTPException(403, _('Your role ({role}) cannot attach files to {entity} ({v})', role=actor.role, entity=entity, v=' or '.join(spec[1])))
    if description and len(description) > 300:
        raise HTTPException(422, _('Description: at most 300 characters'))
    name = _clean_name(file.filename or "")
    ext = Path(name).suffix.lower()
    if ext not in TYPES:
        raise HTTPException(415, _('File type {v} not accepted. Accepted: {v2}', v=ext or '(none)', v2=', '.join(sorted(TYPES))))
    limit = int(ATTACHMENT_MAX_MB * 1024 * 1024)
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, _('File larger than {ATTACHMENT_MAX_MB:g} MB', ATTACHMENT_MAX_MB=ATTACHMENT_MAX_MB))
    if not data:
        raise HTTPException(422, _('The file is empty'))
    ctype, kind = TYPES[ext]
    if not _sniff(kind, data):
        raise HTTPException(415, _('The content of {name} does not match a {ext} file', name=name, ext=ext))
    now = clock.now()
    stored = f"{now:%Y}/{now:%m}/{uuid.uuid4().hex}{ext}"
    path = ATTACHMENT_DIR / stored
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    a = m.Attachment(entity=entity, entity_id=entity_id, filename=name, stored_name=stored, content_type=ctype, size_bytes=len(data),
                     sha256=hashlib.sha256(data).hexdigest(), description=(description or "").strip() or None,
                     uploaded_by=str(actor), user_id=actor.user_id)
    db.add(a)
    db.flush()
    record(db, "attachment", a.id, "CREATE", actor, {"entity": entity, "entity_id": entity_id, "filename": name,
                                                     "sha256": a.sha256, "size_bytes": a.size_bytes})
    try:
        db.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return _out(a)


@router.get("/{aid}/file")
def download(aid: int, inline: bool = False, db: Session = Depends(get_db)):
    a = db.get(m.Attachment, aid)
    if a is None:
        raise HTTPException(404, _('Attachment not found'))
    path = ATTACHMENT_DIR / a.stored_name
    if not path.is_file():
        raise HTTPException(410, _('The file is missing from storage — restore it from a backup'))
    if hashlib.sha256(path.read_bytes()).hexdigest() != a.sha256:
        raise HTTPException(409, _('Integrity check failed: the stored file differs from the one uploaded — restore it from a backup'))
    kind = TYPES.get(Path(a.stored_name).suffix, ("", ""))[1]
    disposition = "inline" if inline and kind in INLINE else "attachment"
    return FileResponse(path, media_type=a.content_type, filename=a.filename, content_disposition_type=disposition,
                        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self'; object-src 'self'",
                                 "Cache-Control": "private, max-age=300"})


class VoidIn(BaseModel):
    reason: str = Field(..., min_length=5, max_length=300)


@router.post("/{aid}/void")
def void(aid: int, body: VoidIn, db: Session = Depends(get_db), actor: Actor = Depends(signed_in)):
    a = db.get(m.Attachment, aid)
    if a is None:
        raise HTTPException(404, _('Attachment not found'))
    if a.voided:
        raise HTTPException(409, _('Already voided'))
    if not _can_void(a, actor):
        raise HTTPException(403, _('Only the person who uploaded the file (within 24 h) or an administrator can void it'))
    a.voided, a.void_reason, a.voided_by, a.voided_at = True, body.reason.strip(), str(actor), clock.now()
    record(db, "attachment", a.id, "STATUS", actor, {"voided": True, "reason": a.void_reason, "filename": a.filename})
    db.commit()
    return _out(a)
