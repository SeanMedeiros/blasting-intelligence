# Future Development Roadmap

The demonstration covers the full operational scope with simulated data. A real deployment would need the following, in this order.

## Phase A — Validation with the team (first weeks)
- Review every workflow with a blaster in charge, a drill & blast engineer, the QC lead and QSSE; align statuses, checklists and fields with company procedures and forms.
- Replace every `DEMO PLACEHOLDER` with values from authorized documents (product specifications, site permits, client contracts, Directive 019 criteria as applicable).
- Agree the KPI list, formulas and targets with management and the client.

## Phase B — Production foundations
- ~~Authentication and role-based permissions~~ — **done in v0.3.0** (local accounts, five roles, sessions, lockout, audit). Remaining: company SSO / OIDC, additional roles if required (blaster, QC lead, client viewer), electronic signature for approvals.
- ~~PostgreSQL, Alembic migrations, automated backups~~ — **done in v0.4.0** (both databases tested, migration history, daily verified backups, restore, SQLite → PostgreSQL copy). Remaining: HTTPS, hosting on the company network or cloud, off-site copy of backups.
- Full French localization of server-generated texts and PDF reports.
- Mobile / tablet field forms with offline synchronization (hole measurements, checklists, observations, photos).
- Attachments (photos, certificates, signed documents) linked to records.

## Phase C — Integrations
- Import from the 3D scanner / drone processing software actually used on site (registered LAS/LAZ/E57), with control-point registration.
- Import from seismograph software (event files and waveforms) and frequency-dependent compliance curves configured from the applicable criteria.
- Import from the electronic initiation system and the product delivery units (MMU) logs — administrative and reconciliation data only.
- Laboratory instrument exports (viscometer, balance) and the calibration provider's certificates.
- Drill navigation / MWD data for hole positions and depths.

## Phase D — Advanced analytics (always under engineering review)
- Octree / level-of-detail streaming for multi-million-point clouds; volume and muckpile displacement.
- Fragmentation analysis from photos (measured size distribution) to replace the visual rating.
- Correlations between hole deviation, geology, vibration and fragmentation across blasts; site-specific vibration attenuation analysis by the engineer.
- AI-assisted drafting of report narratives and anomaly summaries, with mandatory human review and traceable sources.

## Done in v0.5.0
- Production mode with the real date and an empty start; demonstration fully separated (own folder, port and database; reset refused in production).
- Master data editable from the interface with validation, deactivation and audit; first-run checklist; reference limits and KPI targets created from scratch.

## Done in v0.6.0
- Work orders, activity sequence, deliveries, drill patterns with drillhole design import (CSV), drilling completion, loading document references, blasts with templated checkpoints/checklist, detonator issue records, automatic post-blast review; editable record templates.
- Hole measurements refused without configured tolerances; no assumed face tolerance.

## Done in v0.7.0
- Evidence attachments on 17 record types, content-checked, hashed, never deleted, included in backups.

## Done in v0.8.0
- Server texts in French: errors and validation messages, alerts, KPI names and formulas, workflow requirements, risk matrix, record templates, PDF reports (all 8) and CSV comment lines; site language for stored texts; laboratory sampling plan as an editable template.

## Done in v0.9.0
- Site-server deployment: HTTPS served by the application (internal CA or certificate from IT), HTTP → HTTPS redirect, `server.env`, Windows background server (scheduled task, restart check, firewall, key-folder ACL), host/origin checks, security headers, health probe, certificate-expiry alert, server status in Settings; reverse-proxy and Linux (systemd) options.

## Next candidates
- Product codes as master data (today a free code on batches and limits).
- Single sign-on (Active Directory / Entra ID) instead of local accounts.
- Validation on the target Windows server: run `install_service.bat`, the acceptance check of DEPLOYMENT.md §8 and `e2e/production_smoke.py` from a workstation.
- Image downscaling / preview generation for very large photos; antivirus scan hook for uploads where the site requires it.

## Known limitations
- Editing a work order's details after creation is limited to status, dates, references and tonnes through the API; the interface offers status changes.
- Demo mode: synthetic 3D surveys and simulated waveforms. Imported clouds are not registered (both modes). Vibration waveforms are reconstructed from the stored peaks, not imported.
- Local accounts only (no SSO); the role matrix is fixed in code; one application server (several workstations through HTTPS), no load balancing.
- Checkpoint and checklist texts already stored in records are site data and are shown as written; CSV column names are technical codes in both languages.
- Not yet validated on the target Windows workstations and server — run `setup.bat` and `e2e/smoke.py` on each; the Windows service scripts were syntax-checked and their helper functions exercised with PowerShell 7 on Linux only.
