"""Writes THIRD_PARTY_NOTICES.md: licences of the npm packages bundled into frontend/dist (production dependencies).

    python frontend/scripts/third_party_notices.py      (after `npm ci` in frontend/)
"""
import json
from pathlib import Path

FRONT = Path(__file__).resolve().parents[1]
OUT = FRONT.parent / "THIRD_PARTY_NOTICES.md"
lock = json.loads((FRONT / "package-lock.json").read_text(encoding="utf-8"))
rows, texts = [], []
for key, meta in sorted(lock["packages"].items()):
    if not key or meta.get("dev") or meta.get("devOptional"):
        continue
    name = key.split("node_modules/")[-1]
    lic = meta.get("license") or "see package"
    rows.append(f"| {name} | {meta.get('version', '')} | {lic} |")
    folder = FRONT / key
    files = sorted(p for p in folder.glob("*") if p.is_file() and p.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")))
    for f in files:
        body = f.read_text(encoding="utf-8", errors="replace").strip()
        texts.append(f"### {name} — {f.name}\n\n```text\n{body}\n```\n")
OUT.write_text(
    "# Third-party notices\n\n"
    "The pre-built interface (`frontend/dist`) bundles the open-source packages below. Their licences are reproduced "
    "after the table. Python packages are not redistributed: `setup.bat` installs them from PyPI under their own licences "
    "(see `backend/requirements.txt`).\n\n"
    "| Package | Version | Licence |\n|---|---|---|\n" + "\n".join(rows) + "\n\n## Licence texts\n\n" + "\n".join(texts),
    encoding="utf-8")
print(f"{OUT}: {len(rows)} packages, {len(texts)} licence files")
