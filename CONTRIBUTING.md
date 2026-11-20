# Contributing

Thank you for your interest. Issues and pull requests are welcome.

## Ground rules

1. **Safety boundary.** The application documents, tracks and analyzes. Contributions must not add explosive-load
   calculations, loading/stemming/timing/firing instructions, detonator programming, or anything that authorizes a
   blast or declares an area safe.
2. **No invented technical values.** Limits, tolerances and targets come from configuration with a source document —
   never hard-coded defaults presented as real values.
3. **No real site data** in code, tests, issues or screenshots.

## Development setup

```bash
cd backend
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q                                # temporary SQLite database
BI_MODE=demo BI_PORT=8000 python -m app.serve      # fictional site on :8000 (the port the Vite dev server proxies to)

cd ../frontend
npm ci
npm run dev                                        # http://localhost:5173 (proxies /api to :8000)
npm run build                                      # updates frontend/dist (committed: users need no Node.js)
```

End-to-end: `pip install playwright && python -m playwright install chromium`, start a demonstration server, then
`python e2e/smoke.py`.

## Conventions

- Backend: FastAPI + SQLAlchemy 2; schema changes through an Alembic migration in `backend/migrations`.
- Server texts in English wrapped in `_()`, `N_()` or `S_()`; add the French text to `backend/app/locales/fr.py`
  (`python tools/i18n_extract.py --missing` must report 0). UI texts in `frontend/src/i18n/en.json` and `fr.json`.
- Keep `docs/` in step with behaviour (user manual, architecture, testing report).
- By submitting a contribution you agree that it is licensed under the Apache License 2.0 (see LICENSE).
