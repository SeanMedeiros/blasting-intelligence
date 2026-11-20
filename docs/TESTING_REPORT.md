# Testing Report — Blasting Intelligence v0.9.0

| Item | Value |
|---|---|
| Date | 20 November 2026 |
| Build | v0.9.0 (`Blasting-Intelligence-v0.9.0.zip`) |
| Data | Deterministic demonstration dataset "Lac-Boréal Mine (fictional)", demo date 2026-12-04 |
| Test environment | Linux x86-64; Python 3.13 (development) and **Python 3.11 clean virtual environment** (minimum supported); **SQLite and PostgreSQL 16**; Chromium (Playwright) with SwiftShader WebGL |
| Not yet tested | The site's own Windows workstation and server (the automated suite passes on GitHub's Windows runner). Action: run `setup.bat` (includes the backend tests) and `e2e/smoke.py`; on the server `install_service.bat` and the acceptance check of DEPLOYMENT.md §8. The PowerShell service script was parsed and its helper functions (settings, health probe, exit codes) exercised with PowerShell 7.4 on Linux; the Task Scheduler / firewall / icacls calls themselves could not be run here. |

## 1. Summary

| Suite | Result |
|---|---|
| Backend automated tests (pytest, 11 files) — SQLite | **154 passed, 1 skipped** (PostgreSQL-only copy test), Python 3.13 and 3.11 |
| Backend automated tests — PostgreSQL 16 (`BI_TEST_DATABASE_URL`, `BI_TEST_PG_URL`) | **155 / 155 passed** |
| End-to-end, demonstration (`e2e/smoke.py`, port 8001) | **34 / 34 passed** (includes French server texts, `?lang=fr` report links and a French PDF) |
| End-to-end, first start in production **over HTTPS** (`e2e/production_smoke.py https://localhost:8443`, internal-CA certificate, HTTP → HTTPS redirect listener) | **32 / 32 passed** — security headers incl. HSTS, session cookie HttpOnly + Secure, forced password change, no demo banner, real date, checklist, all 15 screens without errors on an empty database, site/area/bench from Master Data, work order, pattern with CSV design import, blast created from the interface |
| Both modes running at the same time | Passed — separate ports, folders and databases |
| HTTPS checks with curl (certificate verified against the internal CA) | Passed — valid chain for the configured names; unknown Host → 400; foreign Origin on sign-in → 403; same origin → Secure cookie; HTTP port → 308 to HTTPS |
| Reverse-proxy mode (`BI_TRUSTED_PROXIES`) | Passed — `X-Forwarded-Proto: https` gives HSTS and the Secure cookie; client address from `X-Forwarded-For` in the access log; ignored when no proxy is declared |
| Migrations 0001 → 0002 → 0003 on a populated PostgreSQL database | Passed — pre-migration backup taken at each step, data kept |
| Restore on PostgreSQL (CLI) | Passed — refused without `--yes`; safety backup taken; row added after the backup removed; migrations re-applied |
| Clean install from the package (fresh venv, Python 3.11) | Passed — data generated, tests passed, UI and PDF served |
| Continuous integration (GitHub Actions, `.github/workflows/ci.yml`) | **All 7 jobs green**: pytest on Python 3.11–3.13 (SQLite), PostgreSQL 16, **Windows (windows-latest: full backend suite, launcher check, service script parse and status)**, frontend type check and build, both end-to-end suites (production over HTTPS). The first run found a real defect, fixed (see §5). |
| Offline capability | Passed — no request left the local server during the E2E run |
| Visual inspection | All 13 modules, modals and the 8 PDF reports reviewed from screenshots / rendered pages (French monthly KPI and daily reports rendered and checked in v0.8.0); defects found were fixed (see §5) |

## 2. Coverage of the validation items

| Requirement | How it was tested | Result |
|---|---|---|
| Test every module | E2E: each of the 13 routes renders its title without JavaScript errors; backend tests per module | Pass |
| Test navigation | E2E route sweep | Pass |
| Test database persistence | Writes followed by reads in tests (measurements, tests, observations, transitions, targets, limits, comparisons); audit trail entries | Pass |
| Test calculations | KPI numerator/denominator consistency and bounds; geometry against known answers (design vs itself = 0, known 0.30 m offset measured to ±5 mm); tolerance accounting; drillhole rules; risk classification | Pass |
| Test data filtering | Record browser filters/search; lab, vibration, survey and observation filters; KPI period and granularity | Pass |
| Test all forms | Validation errors (422) and successful submissions for every write endpoint; E2E form submissions (drillhole, laboratory, safety) | Pass |
| Test exports | PLY, XYZ, CSV, OBJ, LAS exports; export → import round-trip (PLY, LAS, CSV); 8 PDF reports + CSV; vibration report CSV | Pass |
| Test 3D visualization | E2E: WebGL canvas and deviation statistics render; binary point layout test; mesh index validity | Pass |
| Test offline operation | Network requests monitored during the E2E run: none external | Pass |

## 3. Backend test inventory (155)

| File | Tests | Scope |
|---|---|---|
| `test_core.py` | 12 | Deterministic seed; disclaimer; dashboard sections; KPI traceability and bounds; KPI series; planted alerts detected; expired calibration not evaluated; authorized blasts carry an external reference; **no loading-calculation fields in the schema**; record browser errors (404/422) |
| `test_phase2.py` | 25 | Geometry unit tests (determinism, zero self-distance, known offset, statistics, front-row flags, mesh); drillhole rules; survey API (list, binary layout, saved comparison, section, mesh, front-row, post- vs pre-blast); quality review requires a reason; 5 export formats; import round-trip; garbage import refused; drillhole measurement flow, validation, engineering acceptance, lock after firing, CAPA, CSV |
| `test_phase3.py` | 18 | Laboratory (summary, trend, PASS/FAIL, calibration, wrong instrument, VOD reference, NC disposition); vibration (stations, waveform peak = stored PPV, quality re-classification, CSV import with rejected rows and duplicates, report); blasting workflow (board, refused transitions, authorization reference, checkpoints, inventory reconciliation, closure prerequisites, overdraw refused, checklist NO requires comment); detonators (reconciliation, exception, verify refused then accepted, lock); QSSE (required fields, auto-CAPA, closure evidence, configurable matrix, CAPA close, inspections, training); planning (views, reschedule with cause, complete, receive delivery) |
| `test_phase4.py` | 12 | Post-blast workflow requirements and engineering review; validation; comparison; configurable KPI targets; daily KPI series; 5 period reports and 3 record reports (PDF + CSV); reference-limit configuration (placeholder source refused) |
| `test_security.py` | 14 | Password hashing and policy; public vs protected endpoints (401); HttpOnly/SameSite cookie; generic sign-in error; CSRF header required on cookie writes; Bearer token; sign-out revokes session; viewer read-only; technician cannot accept holes, close blasts or change targets; QSSE may close observations; user creation, forced password change, deactivation revokes sessions; audit carries account id; admin safeguards (self, last admin); lockout and unlock; password reset; first-start administrator bootstrap |
| `test_ops.py` | 15 | Models identical to the migrated schema; fresh database via CLI; v0.2 database adopted with data kept; backup create / verify / list; tampered and invalid archives refused; retention keeps protected copies; restore replaces data and keeps a safety copy; restore refuses another database type; copy to empty SQLite and refusal when not empty; copy to PostgreSQL with sequences (PostgreSQL only); console password reset; system API administrator-only; record browser hides credentials and sessions; daily schedule logic; backup before pending migration |; first administrator created by `ensure-admin`
| `test_production.py` | 11 | Real clock and meta in production; demo reset refused; **every GET endpoint (69, from the OpenAPI document) without a server error on an empty database**; every report on an empty database without demo marking; setup checklist; master data create / validate / unique / unknown fields / references / ranges / deactivate / delete refused when used / delete audited; calibration date check; limits and KPI targets created from scratch; master-data permissions by role; no synthetic cloud in production; risk matrix on a new site; product required on the first inventory movement |
| `test_cycle.py` | 5 | **Complete blasting cycle on a new production site through the API** (master data → limits → work order → standard schedule → pattern → design import with validation errors → drilling → measurements refused without tolerances, then recorded → blast with 16 checkpoints / 8 checklist items → every workflow step and its refusals → authorization recorded → firing creates the post-blast review → vibration import → inventory reconciliation → detonator issue, reconciliation, verification → review through 6 stages → closure → work order completed → KPIs and all reports); automatic codes; duplicates and date checks; deliveries; activity cancel; one blast per pattern; deletion of untouched blast / pattern; cancellation rules; site templates applied to new blasts; operational permissions |
| `test_network.py` | 15 | Security headers on API and pages, HSTS only on HTTPS; attachment sandbox CSP kept; unknown host names refused (loopback, public URL, `*`); cross-site writes refused, same origin and no-Origin accepted, development origin only on this computer; Secure cookie with HTTPS; health 200/503; HTTP → HTTPS redirect (port, public URL, host check); `server.env` parsing (environment wins, invalid line refused); internal CA + server certificate (names, chain, owner-only key files, CA reused, offline CA key refused, > 397 days refused, invalid IP); mismatched key and expired certificate refused; PFX import (wrong password refused); `manage make-cert` / `cert-info`; launcher refuses bad settings, proxy headers off by default, log folder; status card data (administrators only); certificate-expiry alert |
| `test_i18n.py` | 11 | Every server text has French with the same `{fields}`; French templates format; language selection (`?lang`, `X-Lang`, `Accept-Language`) and number format; errors and validation (422) in French; workflow requirements, KPIs, alerts and risk matrix in French; site-language templates and the French authorization checkpoint recognised; stored notes in the site language, not the requester's; sign-in errors and meta; **all 8 PDF reports generated in French, text extracted and checked** (titles, month in words, status labels, no English headers); code labels in sync with the UI |
| `test_attachments.py` | 17 | Seven accepted formats uploaded and downloaded byte-identical with security headers; inline only for images/PDF; counts; **tampered stored file detected**; 11 refused files (executable, HTML, SVG, fake PNG/PDF, macro DOCX, broken ZIP, markup text, binary text, empty, no extension); size limit; unknown record type / record; permissions by role and record type; viewer read-only; void rules (reason, own within 24 h, administrator after), voided kept and downloadable, audit; **backup contains the files and restore brings a deleted file back**; missing file reported (410); demo reset clears files |

Run: `cd backend && python -m pytest -q`

## 4. End-to-end checks (34)

Sign-in refuses a wrong password · admin signs in · API refuses requests without a session · 14 route renders · demonstration-data banner · French interface · French server texts (KPI formula from the API) and `?lang=fr` on report links · French monthly KPI PDF · KPI calculation dialog · 3D canvas + statistics · drillhole measurement form · laboratory test → automatic non-conformance · high-risk observation → corrective action · blast workflow blocks a step with unmet conditions · monthly KPI PDF · on-demand backup listed in Settings · sign-out, viewer sees no user administration and write buttons locked · no external network requests · no JavaScript errors.

Both scripts accept an `https://` address; in v0.9.0 the demonstration suite was also run over HTTPS (34/34, with the Content-Security-Policy active — 3D viewer included, no JavaScript or policy errors).

Run: demonstration server (`start_demo.bat`, port 8001) after `reset_demo.bat` → `python e2e/smoke.py`; empty production server with `BI_ADMIN_PASSWORD=First-start-2026` → `python e2e/production_smoke.py`.

## 5. Defects found and fixed during testing (selection)

| Defect | Fix |
|---|---|
| **v0.9.0 (first CI run):** restore failed when the PostgreSQL client tools were newer than the server (pg_restore 17+ writes `SET transaction_timeout`, refused by PostgreSQL 16) | Restore goes through a SQL script that drops settings unknown to the server; unit test added |
| **v0.9.0:** `X-Forwarded-For` / `X-Forwarded-Proto` were trusted from 127.0.0.1 by default (uvicorn default), so a local process could spoof the client address | Forwarded headers honoured only from `BI_TRUSTED_PROXIES` |
| **v0.9.0:** `BI_COOKIE_SECURE` had to be set by hand when serving HTTPS | Automatic with built-in HTTPS |
| **v0.8.0:** After switching language, a request still in flight from the first page load was reused, so server texts could stay in the previous language | In-flight requests cancelled, then everything refetched; KPI dialogs follow the refreshed data |
| **v0.8.0:** The laboratory KPI formula named fictional product codes and the required tests were fixed in code | Laboratory sampling plan is an editable site template (Settings) |
| **v0.8.0:** Automatic record codes used a fixed year ("-26-") and counted rows (could repeat after a deletion) | Codes from the operational date's year and the highest existing number |
| **v0.8.0:** Production PDFs were marked "(simulated)" in their properties and the monthly KPI report always said "DEMONSTRATION KPIs"; the record-browser CSV was named `_SIMULATED` in production | Demonstration wording only in demonstration mode |
| **v0.8.0:** "Default template" indicator wrong on a French site (compared with the English defaults) | Compared with the defaults in the site language |
| **v0.7.0:** Hole measurements were judged against built-in tolerances (±0.30 m / 0.50 m) when none was configured; 3D statistics assumed a 0.50 m face tolerance | Measurements refused until DEPTH_TOL / DEVIATION_TOL exist; no face-tolerance figure until FACE_TOL exists |
| **v0.7.0:** Vibration import crashed (500) for a station without a seismograph | Row refused with a clear message |
| **v0.7.0:** Post-blast review existed only in demonstration data | Created when the blast is fired |
| **v0.7.0:** Safety screen crashed on a new site (risk matrix without labels); configuring the matrix failed when none was stored | Complete default matrix; first configuration creates it |
| **v0.7.0:** KPIs without a target were flagged as "demo target" | Flag only when a placeholder target exists; *No target set* shown |
| **v0.7.0:** Inventory movements always recorded a fixed fictional product | Product entered (pre-filled from the last movement) |
| **v0.7.0:** The first route-sweep test only reached one route (nested routers) | Sweep built from the OpenAPI document; asserts coverage |
| **Security (v0.7.0):** the read-only record browser listed the account and session tables (password hashes, session hashes) to any signed-in user | Credential, session and migration tables excluded; test added |
| Record filters on yes/no columns returned nothing on PostgreSQL (text comparison) | Filter values converted to the column type; invalid values → 422 |
| `setup.bat` regenerated the demonstration data on every run (would erase real data) and tests could follow `BI_DATABASE_URL` | Setup only migrates; tests always use a temporary database |
| Today's blast showed "Done" before firing in the schedule | Blast activity of the demo day kept as Planned |
| Quarantined batches with closed non-conformances | Closed NCs set the batch to Rejected |
| Weekly trend line overshot below 0 % (spline) | Linear lines everywhere |
| Header encoding error (non-ASCII in HTTP header) | ASCII-safe header value |
| Schedule changes dated in the future | Change date limited to the demo date |
| Today's authorized blast had no inventory records | USED/RECEIVED recorded at loading; returns after firing |
| Python 3.12-only f-string syntax in report generator | Rewritten; all sources compiled with Python 3.11 |
| Reference limits not editable | Added audited limit editor with source document validation |
| Several layout issues (wrapping codes, full-width selects, orphan PDF headings) | Fixed and re-inspected |

## 6. Known limitations (not defects)

- 3D surveys are synthetic; waveforms are simulated; imported clouds are not registered; no LOD for very large clouds.
- Checkpoint and checklist texts already stored in records are shown as written (site data); CSV column names are technical codes in both languages.
- Local accounts only (no SSO); the role matrix is fixed in code.
- Reference limits and KPI targets are demonstration placeholders until replaced.
