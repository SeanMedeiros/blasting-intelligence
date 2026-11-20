# Installation Guide (Windows)

## Requirements
- Windows 10 or 11, 8 GB RAM recommended.
- **Python 3.11 or newer** (3.12 recommended) from https://www.python.org/downloads/ — during installation tick **"Add python.exe to PATH"**.
- Google Chrome or Microsoft Edge (WebGL enabled — default).
- Internet is needed **only once** for `setup.bat` (Python packages). The demonstration runs fully offline.
- Node.js is **not** required (the interface is shipped pre-built in `frontend/dist`).

## Steps
1. Unzip the package to a short path without special characters, e.g. `C:\BlastingIntelligence\`.
2. Double-click **`setup.bat`**. It:
   - creates a virtual environment `.venv`,
   - installs the Python packages from `backend\requirements.txt`,
   - runs the 155 automated tests on a temporary database (all must pass; one PostgreSQL-only test is skipped),
   - creates or upgrades the **production** database `data\blasting.db` — it **never deletes data** (an existing database is backed up before any upgrade),
   - if no account exists, **asks for the first administrator** (username, full name, password).
3. Double-click **`start.bat`**. A console window opens (keep it open) and the browser opens http://127.0.0.1:8000. Sign in with the administrator account; the dashboard shows a **Getting started** checklist (site, areas, benches, personnel, equipment, instruments, calibrations, monitoring stations, reference limits, KPI targets, user accounts).
4. To stop: close the console window (or Ctrl + C).
5. **Other computers on the site network:** see **[DEPLOYMENT.md](DEPLOYMENT.md)** — HTTPS certificate, `server.env`, `install_service.bat` (runs at Windows start-up without anyone signed in).
6. **Demonstration** (training, presentations): **`start_demo.bat`** → http://127.0.0.1:8001, fictional site, separate folder `data\demo\`. **`reset_demo.bat`** regenerates it. Demo and production can run at the same time and never share data.

### Production and demonstration modes
| | Production (`start.bat`) | Demonstration (`start_demo.bat`) |
|---|---|---|
| Date | Real date in `BI_TIMEZONE` (default `America/Toronto`) | Fixed `BI_DEMO_TODAY` (2026-12-04) |
| Database | `data\blasting.db` (or `BI_DATABASE_URL`) | `data\demo\demo.db` |
| Empty database | Stays empty; first administrator from `setup.bat`, `BI_ADMIN_PASSWORD` or a generated password file | Fictional site generated automatically |
| Banner / report marking | none | "DEMONSTRATION DATA — FICTIONAL SITE" |
| 3D surveys | Imported point clouds only | Generated point clouds for the fictional site |
| Reset | not available (the reset refuses to run) | `reset_demo.bat` |

**Upgrading from 0.4 or earlier:** `data\demo.db` was the demonstration database and is no longer used (a warning is logged); delete it. Real data entered in an earlier version can be moved with `python -m app.manage copy-db --from sqlite:///…/data/demo.db --to sqlite:///…/data/blasting.db` (server stopped, target empty).

## Signing in
- Production: the administrator created by `setup.bat`. Create one account per person in **Users & Access**.
- Demonstration: accounts `admin`, `jgagnon`, `eroy`, `kbouchard`, `npelletier`, `iouellet`, password **`Demo-2026!`** (set `BI_DEMO_PASSWORD` before `reset_demo.bat` to change it).
- On a database without any account, the first start creates `admin` with the password in `BI_ADMIN_PASSWORD` or, if not set, a generated password written to `data\initial-admin-password.txt`. It must be changed at first sign-in; delete the file afterwards.

## Security settings (environment variables)
| Variable | Default | Purpose |
|---|---|---|
| `BI_SESSION_HOURS` | 12 | Maximum session length |
| `BI_SESSION_IDLE_MINUTES` | 120 | Sign-out after inactivity |
| `BI_LOGIN_MAX_ATTEMPTS` / `BI_LOGIN_LOCK_MINUTES` | 5 / 15 | Account lock after failed sign-ins |
| `BI_PASSWORD_MIN_LENGTH` | 10 | Password policy |
| `BI_COOKIE_SECURE` | automatic | On automatically with built-in HTTPS; set `1` behind an HTTPS reverse proxy |
| `BI_ADMIN_PASSWORD` | — | Initial administrator password on an empty database |
| `BI_ATTACHMENT_MAX_MB` | 25 | Maximum size of an evidence file |
| `BI_HOST` / `BI_PORT` / `BI_TLS_CERT` / `BI_TLS_KEY` … | 127.0.0.1 / 8000 | Network and HTTPS — see [DEPLOYMENT.md](DEPLOYMENT.md). All settings can be written in `server.env` (template `server.env.example`) instead of environment variables. |
| `BI_DEFAULT_LANGUAGE` | `en` | Site language (`en` or `fr`): default record templates and the texts the system writes into records. Each user still chooses EN / FR for screens and reports. Set it before the first start of a French-speaking site. |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Python 3.11+ is required` | Install Python and tick "Add to PATH"; reopen the folder and run `setup.bat` again. |
| `pip` errors behind a proxy / no internet | Run `setup.bat` on a network with internet access; afterwards the demo works offline. |
| Browser shows "This site can't be reached" | Wait 5 s and refresh; check the console window is still open; port 8000 may be used — close other servers or reboot. |
| Port 8000 already in use | Set another port in `server.env` (`BI_PORT=8010`); the demonstration uses 8001 (`BI_PORT` in `start_demo.bat`). |
| "The server was not started. Fix the settings…" | `start.bat` / the service checked `server.env` and found a problem (shown above the message): fix it; `cd backend` → `python -m app.serve --check` re-checks. |
| 3D view is black | Update the graphics driver or use Chrome; check `chrome://gpu` shows WebGL "Hardware accelerated". |
| Forgot the administrator password | Another administrator resets it in **Users & Access**, or from `backend\` with the virtual environment active: `python -m app.manage set-password admin` (also unlocks the account). |
| Tests fail in setup | Delete `.venv` and `data\demo.db`, then run `setup.bat` again. |
| LAZ import refused | Optional: `.venv\Scripts\pip install lazrs`. |
| Windows SmartScreen warning on .bat | "More info" → "Run anyway" (scripts are plain text and can be opened in Notepad). |

## Developer setup (optional)
```bash
cd backend && python -m uvicorn app.main:app --reload --port 8000
cd frontend && npm install && npm run dev        # http://localhost:5173
npm run build                                     # rebuild frontend/dist
python -m pytest -q                               # backend tests (from backend/)
python e2e/smoke.py                               # end-to-end (needs: pip install playwright; python -m playwright install chromium)
```

## Backups and restore
- **Automatic:** every day at 02:30 while the server is running (`BI_BACKUP_DAILY_AT`, empty to disable), into `data\backups` (`BI_BACKUP_DIR`), last 30 kept (`BI_BACKUP_KEEP`). Administrators can also click **Back up now** in *Settings → Database & backups*.
- **Manual / Task Scheduler:** `backup.bat` (can run while the server is running). Example: `schtasks /create /tn "Blasting Intelligence backup" /sc daily /st 02:30 /tr "C:\BlastingIntelligence\backup.bat"` (then set `BI_BACKUP_DAILY_AT=` to avoid two daily copies).
- **Keep a copy elsewhere:** copy `data\backups` regularly to a network share or another disk.
- Backups contain the database **and** the files folders (`data\attachments`, `data\surveys`). When moving to PostgreSQL with `copy-db`, also copy these two folders to the new data folder.
- **Restore:** close the server window, then `restore.bat bi-backup-YYYYMMDD-HHMMSS-reason.zip`. Without an argument it lists the backups. The current data is backed up first (`…-pre-restore.zip`).
- Other commands (from `backend\`, virtual environment active): `python -m app.manage backups | verify FILE | db-current | db-upgrade`.

## Using PostgreSQL (shared server)
1. Install PostgreSQL 14 or newer (include the *Command Line Tools*, needed for backups). Create a login and an empty database, e.g. in `psql`:
   `CREATE ROLE blasting LOGIN PASSWORD '…'; CREATE DATABASE blasting OWNER blasting;`
2. Set the connection (System → Environment variables, or before `start_demo.bat`):
   `BI_DATABASE_URL=postgresql+psycopg://blasting:PASSWORD@SERVER:5432/blasting`
   If `pg_dump` is not on the PATH: `BI_PG_BIN=C:\Program Files\PostgreSQL\16\bin`.
3. **Moving existing data from SQLite:** stop the server, then from `backend\`:
   `python -m app.manage copy-db --to postgresql+psycopg://blasting:PASSWORD@SERVER:5432/blasting`
   (copies every table, checks row counts). Then set `BI_DATABASE_URL` as above and start the server.
   **Starting empty instead:** just start the server — the schema is created (the demonstration dataset is generated on an empty database in this version).
4. Check with `python -m app.manage db-current` or in *Settings → Database & backups*.
