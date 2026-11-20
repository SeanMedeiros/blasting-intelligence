## What and why

## Checks
- [ ] `cd backend && python -m pytest -q` passes
- [ ] Server texts wrapped in `_()` / `N_()` / `S_()` and translated (`python tools/i18n_extract.py --missing` shows 0)
- [ ] Interface built (`cd frontend && npm run build`) if `frontend/src` changed — `frontend/dist` is committed
- [ ] Docs updated (user manual, architecture, testing report) where behaviour changed
- [ ] No explosive-load calculation, loading/firing instruction or blasting authorization introduced
