# Blasting Intelligence — Technical Architecture

> Current release ships with a fictional demonstration dataset (DEMONSTRATION DATA — FICTIONAL SITE). Industrialization in progress — see ROADMAP.md.

## 1. Purpose and principles

A centralized platform for the documentation, monitoring, analysis and performance evaluation of drilling and blasting services: planning, 3D face surveys, drillhole verification, blasting workflow, product QA/QC, vibration monitoring, detonator traceability, QSSE, post-blast analysis, KPIs and reporting.

1. **The software documents, tracks and analyzes. It never prescribes or authorizes.** No explosive formulation, loading quantity, stemming instruction, detonator programming, connection or firing sequence exists anywhere in the data model or the code (a unit test checks the schema). The `AUTHORIZED` blast status only records an authorization issued outside the software.
2. **No invented limits.** Every acceptance limit, tolerance, reference value and KPI target is configurable, carries its source document, and is flagged `DEMO PLACEHOLDER` until replaced. Evaluated results keep a snapshot of the limit used.
3. **Explainable analytics.** KPIs return numerator, denominator and formula. Alerts are deterministic rules that list the records involved. Generated report text is labelled as a draft.
4. **Traceability.** Every write is recorded in `audit_log` (who, when, before/after).
5. **Reliable offline demonstration.** A single local process, no internet access needed, deterministic data that can be reset.

## 2. Runtime view

```
Browser (Chrome / Edge)
  React 18 SPA · TypeScript · Tailwind CSS · Recharts · three.js (@react-three/fiber) · i18next EN/FR
        │  HTTP/JSON + binary point clouds   (http://127.0.0.1:8000)
FastAPI (uvicorn, single process)
  ├─ routers/      core · surveys · drillholes · blasting (+ detonators) · lab · vibration · safety · planning · postblast · reports
  ├─ services/     kpis (13 KPIs) · dashboard · audit
  ├─ analytics/    rules (12 detection rules)
  ├─ geometry/     face (synthetic clouds, C2C distance, mesh, sections, front-row distance)
  ├─ reports/      builder (ReportLab + matplotlib) · generators (8 reports)
  └─ seed/         generator (deterministic Lac-Boréal dataset)
        │  SQLAlchemy 2.0
SQLite  data/demo.db  or  PostgreSQL 14+ (BI_DATABASE_URL); schema managed by Alembic
data/surveys/*.npz         imported point clouds
frontend/dist/             pre-built SPA served by FastAPI at "/"
```

## 3. Technology choices

| Concern | Choice | Reason |
|---|---|---|
| UI | React 18 + TypeScript + Vite, Tailwind CSS 4 | Typed, fast build, static output served offline |
| Data fetching | TanStack Query | Caching, invalidation after writes |
| Charts | Recharts (validated categorical palette, status colours with icon + label) | Covers all needs; Plotly not required |
| 3D | three.js via @react-three/fiber + drei | Point cloud, mesh, section plane, holes, gizmo |
| API | FastAPI + Pydantic v2 | Validation, OpenAPI docs at `/docs` |
| ORM / DB | SQLAlchemy 2.0, Alembic; SQLite or PostgreSQL (psycopg 3) | SQLite for a single workstation, PostgreSQL for a shared server; same code and tests on both |
| Geometry | numpy, scipy (cKDTree), laspy, plyfile | C2C distance, LAS/PLY I/O |
| Reports | ReportLab + matplotlib | Pure Python, works on Windows (no GTK) |
| Tests | pytest + FastAPI TestClient; Playwright (end-to-end) | see TESTING_REPORT.md |

## 4. Data model (42 tables; migration 0002 adds an `active` flag to areas, benches, equipment, instruments and monitoring stations)

| Domain | Tables |
|---|---|
| Reference | site, area, bench, personnel, training_record, equipment, equipment_downtime, instrument, calibration |
| Configuration | reference_limit, kpi_target, app_setting (risk matrix), audit_log |
| Planning (02) | work_order, schedule_item, schedule_change, delay_event, delivery |
| Drilling (04) | drill_pattern, drillhole, drillhole_measurement, approved_loading_record (document reference only) |
| Blasting (05) | blast, blast_status_history, blast_checkpoint, inventory_movement |
| 3D (03) | survey, survey_comparison |
| Detonators (08) | detonator_record, traceability_exception (administrative only) |
| Laboratory (06) | product_batch, lab_test (limit snapshot), nonconformance |
| Vibration (07) | monitor_station, vibration_event |
| QSSE (09) | inspection, checklist_item, safety_observation, capa |
| Post-blast (10) | post_blast_review |

Key relations: `bench → drill_pattern → drillhole → drillhole_measurement`; `blast → work_order, pattern, checkpoints, inventory, detonator_record, vibration_event, survey, post_blast_review, inspection (pre-blast)`; `lab_test → batch | blast, instrument (calibration)`; `capa ← observation | non-conformance | drillhole | vibration`.

## 5. Business rules enforced in the backend

| Area | Rule |
|---|---|
| Blast workflow | Planned → In Preparation → Under Inspection → Authorized → In Progress → Awaiting Verification → Completed → Closed. One step at a time; each step checks: pattern drilled; preparation checkpoints + all holes verified + no unresolved out-of-tolerance hole; loading & pre-blast checkpoints + completed pre-blast checklist with no "NO"; external authorization reference, issuer and role; post-blast checkpoints + inventory balance = 0; completed post-blast review + verified detonator documentation + no open exception. |
| Drillholes | Status from configurable tolerances; shortfall > 2× tolerance or collapsed hole → redrill request; instrument must be a probe with valid calibration; records locked after firing; engineering acceptance only recorded (decision taken outside). |
| Laboratory | Instrument type must match the test; expired calibration → `QUESTIONABLE`, not evaluated; FAIL → non-conformance + batch QC hold; VOD/NOx need an approved test reference; closing a NC requires evidence. |
| Vibration | Compliance evaluated only on `VALID` records; CSV import validates every row (station, date, ranges, peak = max component, duplicates) with a dry-run mode. |
| QSSE | Risk = likelihood × severity against configurable thresholds (re-classification audited); HIGH/CRITICAL → automatic corrective action; closure requires evidence. |
| Post-blast | Six stages with required content; any improvement proposal requires a recorded engineering review before completion. |
| Settings | Limits require a source document (placeholders refused); KPI percentage targets 0–100. |

## 6. 3D processing

- Local face system: x along strike, y horizontal towards free space (design crest at y = 0), z elevation above toe.
- Synthetic clouds: deterministic per survey (seeded by id); face, bench top, floor (and muckpile for post-blast). Display sample 160 000 points; nominal scan count stored in the survey record.
- Face vs design: exact perpendicular distance to the 75° design plane on face points.
- Survey vs survey: nearest neighbour + point-to-plane using PCA normals oriented to the scanner side.
- Mesh: 2.5D grid (0.4 m) over (x, z) with median offset per cell.
- Front-row distance: horizontal distance from each vertical front-row hole to the median face position per 0.25 m elevation bin; flags against configurable references.
- Binary transfer: `uint32 N | uint32 flags | float32 xyz[3N] | float32 intensity[N] | float32 deviation[N] | uint8 region[N]`.
- Formats: import XYZ/CSV/TXT, PLY, LAS (LAZ with `lazrs`); export PLY (binary), LAS 1.2, XYZ, CSV, OBJ (mesh).

## 7. KPI engine

13 demonstration KPIs computed for any period (day / week / month) from source records; each returns value, numerator, denominator, formula, target, direction and status (ON / NEAR / OFF target, ±5 % band). Formulas are listed in `backend/app/services/kpis.py` and printed in the monthly report.

## 8. Security and identity

Implemented in `backend/app/services/security.py` and `backend/app/routers/auth.py`.

| Topic | Implementation |
|---|---|
| Accounts | `app_user` table: username (unique, lower-case), full name, e-mail, role, active flag, optional link to a `personnel` record. |
| Passwords | scrypt (Python standard library, N=2^14, r=8, p=1), random 16-byte salt per password, constant-time comparison. Policy: minimum length (`BI_PASSWORD_MIN_LENGTH`, default 10), letters and digits, must not contain the username. New and reset accounts must change the password at first sign-in. |
| Sessions | 256-bit random token in an `HttpOnly`, `SameSite=Strict` cookie (`Secure` when `BI_COOKIE_SECURE=1`); `Authorization: Bearer` accepted for API clients. Only the SHA-256 of the token is stored (`auth_session`). Absolute lifetime `BI_SESSION_HOURS` (12 h) and inactivity timeout `BI_SESSION_IDLE_MINUTES` (120 min). Sessions are revoked on sign-out, password change (other devices), password reset, role change and deactivation. |
| CSRF | State-changing requests authenticated by cookie must carry `X-Requested-With` (cannot be set by a cross-site form or link); together with `SameSite=Strict`. |
| Brute force | After `BI_LOGIN_MAX_ATTEMPTS` (5) consecutive failures the account is locked for `BI_LOGIN_LOCK_MINUTES` (15); an administrator can unlock it. The error message does not reveal whether a username exists and unknown usernames cost the same hashing time. |
| Authorization | Every `/api/v1` endpoint except `/meta` and `/auth/login` requires a session. Each write endpoint declares a permission (`require("lab.test")` etc.). Roles: ADMIN (all), ENGINEER, TECHNICIAN, QSSE, VIEWER (read and reports only). The matrix is `ROLE_PERMISSIONS`; the interface disables actions the role cannot perform, the server enforces independently. |
| Audit | Every write, sign-in, failed sign-in, sign-out and account change is recorded in `audit_log` with the user's name **and account id** (`user_id`). Report authors are always the signed-in user. |
| First start | If no account exists, `admin` is created with `BI_ADMIN_PASSWORD` or a generated password written to `data/initial-admin-password.txt`; it must be changed at first sign-in. |

Not yet implemented: SSO/OIDC, electronic signature of approvals, HTTPS termination (stage "deployment"). CORS is restricted to the Vite dev server. Static file serving guards against path traversal.

## 9. Deployment

| Mode | How |
|---|---|
| Single workstation (Windows) | `setup.bat` once (venv, dependencies, data, tests) → `start.bat` / `start_demo.bat` (`python -m app.serve` + browser). Node.js not needed. |
| Site server (Windows) | `server.env` → certificate (`make_certificate.bat` or `manage import-pfx`) → `install_service.bat`: scheduled task at boot with a 5-minute restart check, firewall rule, HTTPS served by the application. See `docs/DEPLOYMENT.md`. |
| Behind a reverse proxy / Linux | `BI_TRUSTED_PROXIES`, `BI_COOKIE_SECURE=1`; systemd unit and nginx example in `deploy/linux/`. |
| Development | `uvicorn app.main:app --reload` + `npm run dev` (Vite proxy to `/api`). |
| Shared database | PostgreSQL via `BI_DATABASE_URL`; migrations applied at start; built-in daily backup. |

**Launcher** (`app/serve.py`): reads `server.env` (KEY=VALUE, environment wins; loaded first thing in `config.py`), refuses to start on invalid settings (exit 2: certificate/key mismatch, expired certificate, half-configured TLS, redirect port without HTTPS), runs uvicorn with TLS, `server_header` off, `X-Forwarded-*` honoured only from `BI_TRUSTED_PROXIES`, an optional second listener that only redirects HTTP → HTTPS (308), and daily-rotated logs (`server.log`, `access.log`, 90 days). `--check` validates, `--url` prints the address.

**Network guard** (`app/web.py`, outermost ASGI middleware): Host header checked against this computer's names/IPs + `BI_PUBLIC_URL` + `BI_ALLOWED_HOSTS` (400 otherwise); state-changing requests with a foreign `Origin` refused (403); security headers added to every response unless the route set its own (attachments keep their sandbox CSP): CSP `script-src 'self'`, `frame-ancestors 'none'`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, `COOP`, and HSTS on HTTPS. `/api/health` checks the database (200/503).

**Certificates** (`app/ops/tls.py`, `cryptography`): internal CA (EC P-256, 10 years, never silently replaced) and server certificates (≤ 397 days, SAN DNS + IP, chain written with the CA); PKCS#12 import; pair/expiry check used by the launcher, the Settings card and a dashboard alert (30 / 7 days). Key files written with owner-only permissions; on Windows `install_service` restricts `data\tls` with icacls.

Configuration (environment variables): `BI_DATABASE_URL`, `BI_DATA_DIR`, `BI_DEMO_TODAY` (default 2026-12-04), `BI_FRONTEND_DIST`, security settings (section 8), backup settings (section 10).

## 10. Database, migrations and backups

**Databases.** SQLite (file `data/demo.db`, WAL mode) for a single workstation; PostgreSQL 14+ for a shared server (`BI_DATABASE_URL=postgresql+psycopg://user:password@host:5432/db`). Connections to PostgreSQL are checked before use (`pool_pre_ping`). The whole automated test suite runs on both (CI target: SQLite by default, PostgreSQL with `BI_TEST_DATABASE_URL`). Tests always use their own temporary database and ignore `BI_DATABASE_URL`.

**Migrations (Alembic, `backend/migrations`).** Revision `0001` is the v0.3.0 schema. At start the server (or `python -m app.manage db-upgrade`) brings the database to the latest revision:
- empty database → all migrations;
- database created by v0.2/v0.3 (no `alembic_version`) → aligned with the baseline (`audit_log.user_id`, account tables) and stamped, data kept;
- pending migrations on a database holding data → **backup first** (`pre-migration-…`), then upgrade.

A test compares the models with the migrated schema, so a model change without a migration fails the build. Developers create migrations with `alembic revision --autogenerate -m "…"` from `backend/` (SQLite uses batch mode for ALTER).

**Backups (`app/ops/backup.py`).** One zip per backup in `data/backups` (`BI_BACKUP_DIR`): `manifest.json` (version, schema revision, database type, reason, row counts, SHA-256), the database (SQLite: online copy through the SQLite backup API, integrity-checked; PostgreSQL: `pg_dump -Fc`), and imported point clouds. Written to a temporary name then renamed, then verified. Taken while the server runs. Triggers: daily at `BI_BACKUP_DAILY_AT` (02:30, inside the server process), **Back up now** (administrators, Settings), `backup.bat` / `python -m app.manage backup`, before every migration, before every restore, before `reset_demo.bat`. Retention: the newest `BI_BACKUP_KEEP` (30); pre-migration and pre-restore copies are never deleted automatically. **Copy the backup folder to another disk or server** — a backup on the same disk does not protect against disk loss.

**Restore.** Server stopped → `restore.bat FILE` (or `python -m app.manage restore FILE --yes`): verifies the archive, backs up the current data, replaces database and point clouds (PostgreSQL: `pg_restore --clean --single-transaction`), then applies migrations if the backup is older. A backup can only be restored into the same database type.

**SQLite → PostgreSQL.** `python -m app.manage copy-db --to postgresql+psycopg://…` creates the schema in an empty PostgreSQL database, copies every table in dependency order, resets the id sequences and compares row counts.

## 11. Operating modes and clock

`BI_MODE` selects **production** (default) or **demo**. The mode decides the data folder (`data/` vs `data/demo/`), the database file (`blasting.db` vs `demo.db`), whether an empty database is filled with the fictional site, the demo banner on screens/PDF/CSV, and whether synthetic point clouds may be generated (demo only — in production a survey without an imported file answers 409). `reset_and_seed()` refuses to run outside demo mode.

All dates come from `app/clock.py`: `today()` / `now()` give the local date/time in `BI_TIMEZONE` (IANA name; `tzdata` is bundled for Windows) in production, and the fixed `BI_DEMO_TODAY` with the real time of day in demo. Nothing captures the date at import time; the interface reads it from `/api/v1/meta` (refreshed every 10 minutes) — there is no hard-coded date or record id in the frontend.

## 12. Master data

`app/routers/masterdata.py` declares each reference entity once (fields, kinds, required, length, choices, references, ranges, uniqueness, permission). The same definition validates the API (unknown fields refused, references checked, codes upper-cased, cross-field checks such as *valid until after calibrated on*) and drives the generic editor in the interface (`GET /api/v1/masterdata`). Deletion is refused while any foreign key in the schema points to the record (computed from the metadata, so new tables are covered automatically); entities with `active` are retired instead. `GET /api/v1/masterdata/setup/status` feeds the *Getting started* checklist. Reference limits can be created (`POST /masterdata/reference-limits/new`, placeholder sources refused) and KPI targets are created on first edit.

## 13. Operational records

`app/routers/operations.py` (`/api/v1/ops`) creates work orders, schedule items (single or the standard sequence), deliveries, drill patterns, the drillhole design (CSV import with a validating dry run; replace allowed until the first measurement), drilling completion, approved-loading **document references**, blasts and detonator issue records. Codes are numbered per prefix and year (`WO-26-0001`, `BL-26-0001`, `DL-26-001`, `PT-<bench>-26-0001`) unless entered. Integrity rules: references must exist and be active; one blast per pattern; pattern and work order in the same area; blast work orders only; work-order status machine (open → in progress → completed, cancel with reason before any blast starts); deletion only of untouched records (a generic foreign-key scan decides). A new blast receives its checkpoints and pre-blast checklist from the site templates (`app/services/templates.py`, stored in `app_setting`, versioned through the audit trail); the post-blast review is created when the blast is fired.

**No invented technical values.** When the drillhole tolerances (DEPTH_TOL, DEVIATION_TOL) are not configured, hole measurements are refused (409) instead of being judged against assumed numbers; when the face tolerance (FACE_TOL) is not configured, 3D statistics are shown without a within-tolerance figure and comparisons cannot be saved. The application stores no explosive quantities, loading, stemming, timing or firing data.

## 14. Evidence attachments

Table `attachment` (migration 0003): record type + id, original (sanitised) file name, stored name `yyyy/mm/<uuid>.<ext>` under `data/attachments`, content type, size, **SHA-256**, description, uploader (name and account id), void flag with reason, who and when. `app/routers/attachments.py`:
- **Accepted formats** recognised from content: JPEG, PNG, WebP (magic bytes), PDF (`%PDF-`), DOCX/XLSX (ZIP with the Office structure; files containing `vbaProject.bin` refused), CSV/TXT (decodable text without NUL bytes, not markup). Everything else — executables, scripts, HTML, SVG, mismatched content — is refused (415). Size limit `BI_ATTACHMENT_MAX_MB` (413).
- **Permissions** per record type (e.g. blast checkpoints: `blast.operate`; corrective actions: `capa.create` or `safety.close`; calibrations: `calibration.record`); reading is open to every signed-in role.
- **Download** re-checks the SHA-256 (409 if the stored file changed, 410 if missing) and is served with `X-Content-Type-Options: nosniff`, a sandboxing `Content-Security-Policy`, and `Content-Disposition: attachment` except images/PDF requested inline.
- **No deletion.** Voiding (uploader within 24 h, administrator any time) keeps the file and the row; uploads and voids are in the audit trail.
- **Backups** include `data/attachments` (and `data/surveys`) and restore them; the demonstration reset clears them.

## 15. Languages (English / French)

- **Request language** (`app/i18n.py`): a pure ASGI middleware reads `?lang=`, then `X-Lang`, then `Accept-Language` and stores `en`/`fr` in a context variable for the request. The interface sends `X-Lang` on every call and adds `?lang=` to PDF/CSV links; a language change cancels and refetches every query.
- **Catalogue:** server texts are written in English inside `_("…{field}…", field=…)` (translated now), `N_("…")` (marked, translated where displayed — KPI names, default templates, risk-matrix labels) or `S_("…")` (texts **stored** in records — written in the site language `BI_DEFAULT_LANGUAGE`). French in `app/locales/fr.py` (≈ 630 entries, Québec mining vocabulary: sautage, boutefeu, gradin, levé, VPP, AQ/CQ). Validation errors (422) are translated per field.
- **Codes are not translated in data:** statuses and types travel as codes (`IN_PROGRESS`); the UI and the PDF show their labels. `app/locales/codes.py` is generated from the UI catalogues by `tools/i18n_codes.py`, so reports and screens use the same words.
- **PDF reports:** headings, tables, narrative, figure titles, footer and page numbers in the request language; numbers formatted with `num()` (1,234.5 / 1 234,5), months and days in words via `month_year()` / `long_date()`. CSV keys stay technical (stable for spreadsheets and scripts).
- **Developer tools** (`backend/tools/`): `i18n_mark.py` wraps messages in `_()` (`--dicts`, `--reports` modes); `i18n_scan.py` lists English sentences still unwrapped; `i18n_extract.py --missing` lists templates without French. `test_i18n.py` fails if any template lacks French, if a French text has different `{fields}`, or if the code labels are out of date.
