"""Module 12 — Automated technical reports (PDF and CSV)."""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..reports.generators import CATALOG
from .. import clock
from ..services.audit import record
from ..services.security import signed_in
from ..i18n import _

router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])


@router.get("")
def catalog():
    return [{"key": k, "title": _(v["title"]), "params": v["params"]} for k, v in CATALOG.items()]


def _run(key: str, request: Request, db: Session, user: str):
    if key not in CATALOG:
        raise HTTPException(404, _('Unknown report'))
    params = dict(request.query_params)
    params.pop("by", None)  # the author is always the signed-in user
    missing = [p for p in CATALOG[key]["params"] if p.endswith("_id") and not params.get(p)]
    if missing:
        raise HTTPException(422, _('Missing parameter(s): {v}', v=', '.join(missing)))
    try:
        return CATALOG[key]["fn"](db, params, user)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/{key}.pdf")
def pdf(key: str, request: Request, db: Session = Depends(get_db), user: str = Depends(signed_in)):
    data, _rows = _run(key, request, db, user)
    record(db, "report", 0, "CREATE", user, {"report": key, "format": "pdf", "params": dict(request.query_params)})
    db.commit()
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="BI_{key}.pdf"'})


@router.get("/{key}.csv")
def csv_export(key: str, request: Request, db: Session = Depends(get_db), user: str = Depends(signed_in)):
    _data, rows = _run(key, request, db, user)
    buf = io.StringIO()
    if clock.banner():
        buf.write("# DEMONSTRATION DATA - FICTIONAL SITE\n")
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()})
    return Response("﻿" + buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="BI_{key}.csv"'})
