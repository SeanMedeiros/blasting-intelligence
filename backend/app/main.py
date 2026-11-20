"""Blasting Intelligence — FastAPI application.

Run:  python -m uvicorn app.main:app --port 8000   (from the backend folder)
The built frontend (frontend/dist) is served at "/" so a single process runs the demo.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text

from .config import APP_NAME, APP_VERSION, DATA_DIR, FRONTEND_DIST, IS_DEMO, MODE
from .db import SessionLocal, engine, init_db
from .i18n import LanguageMiddleware, _, validation_message
from .web import NetworkGuardMiddleware
from .services.security import bootstrap_admin, signed_in
from .routers import attachments, auth, blasting, masterdata, operations, system, core, drillholes, lab, planning, postblast, reports, safety, surveys, vibration

log = logging.getLogger("blasting")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    _startup()
    from .ops import scheduler

    scheduler.start()
    yield
    scheduler.stop()


def _startup():
    init_db()  # applies pending migrations (backup first when the database holds data)
    log.info("Mode: %s · database: %s", MODE, engine.url.render_as_string(hide_password=True))
    from .config import ROOT_DIR

    if not IS_DEMO and (ROOT_DIR / "data" / "demo.db").exists():
        log.warning("data/demo.db is the demonstration database of version 0.4 and earlier; it is no longer used "
                    "(demo mode now uses data/demo/). It can be deleted.")
    if IS_DEMO and "blast" in inspect(engine).get_table_names():
        from sqlalchemy.orm import Session

        from . import models as m
        with Session(engine) as s:
            if s.query(m.Blast).count() == 0:
                log.warning("Demo mode with an empty database — generating the demonstration dataset")
                from .seed.generator import reset_and_seed
                reset_and_seed()
    with SessionLocal() as db:
        f = bootstrap_admin(db, DATA_DIR)
        if f:
            log.warning("No user accounts found — administrator 'admin' created; initial password written to %s", f)


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan,
              description="Integrated Drilling, Blasting, 3D Scanning & Technical Performance Platform. "
                          "Documents, tracks and analyzes; never authorizes blasting.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"], allow_credentials=True)
app.include_router(auth.public)  # sign-in endpoints and /meta: no session required
app.include_router(auth.router)  # user administration (permission checked per endpoint)
app.include_router(system.router)  # database status and backups (administrators)
# Every operational endpoint requires a signed-in user; write endpoints also check a permission.
for _r in (core, masterdata, operations, attachments, surveys, drillholes, lab, vibration, blasting, safety, planning, postblast, reports):
    app.include_router(_r.router, dependencies=[Depends(signed_in)])


app.add_middleware(LanguageMiddleware)  # request language for server texts (?lang, X-Lang, Accept-Language)
app.add_middleware(NetworkGuardMiddleware)  # host and origin checks, security headers (outermost)


@app.exception_handler(RequestValidationError)
async def _invalid(request: Request, exc: RequestValidationError):
    """Input validation errors as short sentences in the request language: '<field>: <problem>'."""
    return JSONResponse(status_code=422, content={"detail": [validation_message(e) for e in exc.errors()]})


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):  # pragma: no cover
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": _("Internal error — see server log"), "path": request.url.path})


@app.get("/api/health")
def health():
    """Monitoring probe (no sign-in, no data): 200 when the database answers, 503 otherwise."""
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        log.exception("Health check: database unreachable")
        return JSONResponse(status_code=503, content={"status": "database unreachable"})
    return {"status": "ok", "version": APP_VERSION}


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = (FRONTEND_DIST / path).resolve()
        if path and f.is_file() and FRONTEND_DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html")
