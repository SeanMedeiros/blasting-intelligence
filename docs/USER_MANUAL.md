# User Manual — Blasting Intelligence

> **Production** (`start.bat`): your site, real date. **Demonstration** (`start_demo.bat`): fictional site, banner *DEMONSTRATION DATA — FICTIONAL SITE*, date fixed at Friday 4 December 2026.

## General
- **Navigation:** left menu, modules 01–15.
- **Date:** the header shows the operational date (site time zone). Due dates, "overdue", "today" and default periods follow it. On small screens use the ☰ button.
- **Language:** EN / FR buttons (top right). Everything follows the chosen language: screens, alerts, KPI names and formulas, error messages and the content of PDF reports (numbers in French format: 1 234,5). Texts saved in records by the system (e.g. the note written when a blast is authorized) use the **site language** (`BI_DEFAULT_LANGUAGE`), so the records stay consistent whoever triggered them. CSV column names stay as technical codes in both languages.
- **Sign-in:** every user has a personal account. The name in the top-right menu is written in the audit trail and on reports. Use that menu to **change your password** or **sign out**. Sessions end after 2 h without activity or 12 h in total.
- **Roles:** Administrator (everything), Engineer, Technician, QSSE, Viewer (read and reports only). Buttons for actions your role cannot perform are shown with a lock and disabled.
- **Demonstration accounts** (bundled dataset only): `admin`, `jgagnon` (engineer), `eroy` and `kbouchard` (technicians), `npelletier` (QSSE), `iouellet` (viewer) — password `Demo-2026!`. Replace or deactivate them before real use.
- **Status colours** always come with an icon and a label (never colour alone).
- **Evidence files** (📎): photos (JPG, PNG, WebP), PDF, Word (.docx), Excel (.xlsx), CSV and text, up to 25 MB. Where to attach: blast (*Evidence files* tab), each checkpoint (📎 on its line), pre-blast checklist, safety observations and corrective actions (📎 column and closing dialog), laboratory non-conformances, drill patterns, detonator records, post-blast reviews, work orders, and calibration / training certificates (Master Data, when editing). Photos show as thumbnails. Each file records who attached it, when, and its SHA-256 fingerprint (checked at every download). **Files are never deleted**: the person who attached a file can void it within 24 h with a reason (an administrator at any time); a voided file stays listed, crossed out, for the audit trail. Office files with macros, executables, HTML and SVG are refused, and a file whose content does not match its extension is refused.

## 01 Dashboard — Operations Control Center
**Getting started** (new site): eleven steps with what is already recorded; each opens the screen where it is set up. It disappears once every step has at least one record. KPIs without a target show *No target set*.
KPI tiles for the last 30 days (click a tile → formula, numerator, denominator, target), today's activities, blast pipeline with hole-verification progress, alerts (each with its rule and records), vibration by station, product QA/QC, safety, deliveries, equipment availability, weekly deviation trend, 3D survey status.

## 02 Production Planning
**New work order** (title, area, type, planned dates, engineering forecast reference and tonnes; code numbered automatically WO-YY-NNNN unless entered). Click a work order to **create the standard activity sequence** around the blast date (drilling −5 d, face survey −4 d, hole verification −3 d, loading and blast 0, post-blast survey +1 d, review +5 d — the site template in Settings), add single activities, **start**, **complete** (actual tonnes) or **cancel** it (reason required; refused once a blast has started). **New delivery** (product, destination area, date, quantity, document).
- **Calendar / Gantt** (two weeks; arrows to move). Click an activity to **reschedule** (new date + cause category + description + optional delay hours) or **mark done** (blast execution is recorded in module 05).
- Forecast vs actual tonnes per week, delay Pareto, work orders, deliveries (**Receive** with date, quantity and bill of lading), schedule change log.

## 03 3D Scanning
1. Select a survey in **Scan history** (filters by type and bench).
2. Toolbar: colour by **Deviation / Elevation / Intensity**; display **Points / Mesh / Both**; **Compare with** the design face or another survey; show the reference surface; show planned holes; point size.
3. Mouse: drag = rotate, right-drag = pan, wheel = zoom. Gizmo axes are the local face system (x, z up, −y).
4. **Vertical section** slider → profile chart below. Click a row of the **front-row distance** table to move the section to that hole.
5. **Geometric deviation** card: statistics and histogram; **Save to database** stores the comparison with your name.
6. **Quality review**: Accepted / Under review / Rejected (reason required) / Pending.
7. **Export** PLY, LAS, XYZ, CSV (with deviation) or OBJ (mesh). **Import survey** (XYZ/CSV/TXT, PLY, LAS) — data must already be in a common coordinate system.

## 04 Drillhole Verification
**New pattern** (bench, hole diameter, approved design document, approved by) then **Import drillhole design**: CSV exported from the design software, one line per hole — `hole_code, x, y, z, depth_m` required; `dip_deg, azimuth_deg, row, col` optional (row 1 = front row, nearest the free face; codes like `R2-07` give the row). *Validate only* lists every error with its line; nothing is stored until **Import**. The design can be replaced until the first measurement. **Record drilling completed** (date) is required before the blast can enter preparation. **Add approved loading reference** stores the document reference and revision only — never its content. Measurements are refused until the tolerances DEPTH_TOL and DEVIATION_TOL from the approved design are entered in Settings (a banner says so).
Select a pattern → plan view (circle = within tolerance, diamond = out of tolerance / redrill, hollow = not measured, blue dot = water). Click a hole → details and history → **Record measurement** (depth, toe deviation, collar offset, condition, water, technician, probe). The result and its reasons are shown. For an out-of-tolerance hole, **Record engineering acceptance** (name, role, justification). Also: depth chart with tolerance band, bench deviation history, approved loading document reference, **Corrective action**, **CSV**, link to the face survey. Records are locked once the blast is fired.

## 05 Blasting Operations
**New blast**: blast work order, a pattern of the same area with its design imported (one blast per pattern), approved plan reference, planned date, supervisor, blaster, equipment. The blast is created *Planned* with the site's checkpoints and pre-blast checklist (Settings → Record templates). A planned blast with nothing recorded can be deleted. The post-blast review is created automatically when the blast is recorded as fired (due 5 days later, `BI_POST_BLAST_REVIEW_DAYS`).
Board of eight statuses. Select a blast → workflow bar, **Next step** box with the unmet conditions, **Record next status** (for *Authorized*: authorization reference, issuer, role — the software does not authorize). Tabs: **Checkpoints** (mark done with an evidence reference), **Pre-blast checklist** (YES / NO / N/A — NO needs a comment — then **Complete checklist**), **Inventory** (received / used / returned; balance must be 0), **Linked records**, **Status history**.

## 06 Product Laboratory
**Overview**: tests, failures, tests on expired calibration, non-conformances (click an open one to record the disposition and close with evidence), batches on hold, instrument calibration register. **Viscosity / Density / VOD / Flowability / NOx** tabs: product selector, history chart against the specification, records (click a batch for traceability), **Record test**.

## 07 Vibration Monitoring
Station cards (max PPV in 30 days, % of reference, rising-trend flag). Click a card → PPV history and PPV vs frequency. Events table with filters; click an event → components, frequency, air overpressure, simulated waveform; **Validate data** changes data quality (with notes). Tick up to three events → comparison table. **Import CSV** (download the sample, *Validate only* first, then *Import*). **Monitoring report (CSV)**.

## 08 Detonator Traceability
**Record detonator issue** for a blast: inventory lot, units issued, equipment asset tag, authorized personnel, procedure reference — administrative only. Units used / returned and verification follow as before; a verified record is required to close the blast.
Administrative records per blast: lot, units issued / used / returned, unaccounted units, inspection, documentation. Select a record → reconcile units, close exceptions with a resolution, **Verify documentation** (refused while anything is open), audit trail. No programming, wiring or firing information.

## 09 Safety & QSSE
**New observation** (all fields required; risk = likelihood × severity; high risk opens a corrective action). Tabs: observations (close with evidence), corrective & preventive actions (overdue in red), inspections (pre-blast, pre-task, PPE; click to see the checklist), training (expired / expiring). **Risk matrix** with open observations; **Configure thresholds** (source document required).

## 10 Post-Blast Analysis
Select a review → six-stage workflow with requirements, data collected automatically, analysis fields (save, then **Next stage**). An improvement proposal requires **Record engineering review**. Tick 2–4 blasts and click **Compare**. **PDF** = blasting activity report.

## 11 KPI Intelligence
Month selector, indicator table (actual, target, previous month, Δ, numerator / denominator, status). ⓘ = calculation method; ✎ = set target (source required, audited). Trends: monthly, weekly or daily. **Monthly report PDF / CSV**.

## 12 Reports
**Report generator**: daily, blasting activity, 3D survey, drillhole verification, laboratory, vibration, QA/QC, monthly KPI — PDF (opens in a new tab) or CSV. **Operational database**: browse every table, search, export the current page.

## 13 Settings
**Record templates** (engineers, administrators): blast checkpoints (`STAGE | text`; the external-authorization checkpoint cannot be removed), pre-blast checklist (one item per line), standard activity sequence (`ACTIVITY | days`), **laboratory sampling plan** (`BATCH | TEST TYPE` or `BLAST | TEST TYPE` — which tests each product batch received and each blast fired require; used by the *Laboratory testing completion* KPI). The external-authorization checkpoint is recognised in English or French. A source document is required; changes apply to records created afterwards.
**Server, database & backups** (administrators) also shows how users reach the server: address, HTTPS on/off, certificate validity and names, accepted server names. An orange/red certificate badge — and a dashboard alert 30 days before expiry — means the certificate must be renewed (see DEPLOYMENT.md).
Reference limits (✎ to replace a placeholder with the value from the authorized document: min / max, effective date, source document, owner). KPI targets (read-only here; edit in module 11). **Database & backups** (administrators): database type, schema version, automatic backup schedule, latest backups and **Back up now**. Restoring is done with `restore.bat` while the server is stopped (see the installation guide).

## 14 Master Data
Reference records used everywhere, grouped: **Site** (site, areas, benches), **People** (personnel, training), **Equipment & instruments** (equipment, instruments, calibrations, monitoring stations), **Products** (product batches). **New** opens a form built from the record definition (required fields marked *, choices and references as lists). Codes are stored in capitals and must be unique. A record that other records refer to **cannot be deleted** — the message lists where it is used — but areas, benches, equipment, instruments, stations and personnel can be **deactivated**: they disappear from selection lists and stay in history. *Show inactive* lists them again. Who can edit: site/areas/benches/equipment/instruments/stations — engineers and administrators; personnel and training — also QSSE; calibrations — also technicians; product batches — roles that record laboratory tests. Every change is audited.

New **reference limits** are added in **Settings → New limit** (parameter, scope `*` / product code / station code, min and/or max, source document, owner, effective date). **KPI targets** are set in **KPI Intelligence** (✎).

**Blasting inventory:** each movement records the product name (pre-filled with the last product of the blast).

## 15 Users & Access (administrators)
List of accounts with role, status (active, locked, password change pending, inactive), last sign-in and open sessions; role permission matrix. **New user**: username, full name, e-mail, role, optional link to the personnel roster, temporary password (the user must change it at first sign-in). Click an account to edit it, change its role or deactivate it (the user is signed out of every session), unlock it after failed attempts, reset its password, or review its recent activity. You cannot change your own role or deactivate yourself, and at least one active administrator must remain.
