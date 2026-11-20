"""End-to-end check of a FIRST START in production mode (empty database).

Start the server on an empty production database with a known initial administrator password:
    set BI_MODE=production & set BI_ADMIN_PASSWORD=First-start-2026 & start.bat     (Windows)
    BI_MODE=production BI_ADMIN_PASSWORD=First-start-2026 uvicorn app.main:app      (from backend/)
then:  python e2e/production_smoke.py [base_url] [initial_password]
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
INITIAL = sys.argv[2] if len(sys.argv) > 2 else "First-start-2026"
NEW = "Mine-du-Nord-2026"
ROUTES = ["/", "/planning", "/scanning", "/drillholes", "/blasting", "/laboratory", "/vibration", "/detonators", "/safety",
          "/postblast", "/kpi", "/reports", "/settings", "/masterdata", "/users"]
results: list[dict] = []


def check(name: str, ok: bool, detail: str = ""):
    results.append({"check": name, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        # HTTPS with the site's internal CA: the certificate itself is checked separately (curl --cacert); here only the application
        page = await (await browser.new_context(viewport={"width": 1500, "height": 950}, ignore_https_errors=BASE.startswith("https"))).new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(BASE + "/")

        # 1. first sign-in forces a password change
        await page.get_by_label("Username").fill("admin")
        await page.get_by_label("Password").fill(INITIAL)
        await page.get_by_role("button", name="Sign in").click()
        try:
            await page.get_by_role("heading", name="Change password").wait_for(timeout=10000)
            forced = True
        except Exception:
            forced = False
        check("first sign-in forces a password change", forced)
        await page.get_by_label("Current password").fill(INITIAL)
        await page.locator("input[autocomplete=new-password]").nth(0).fill(NEW)
        await page.locator("input[autocomplete=new-password]").nth(1).fill(NEW)
        await page.get_by_role("button", name="Change password").click()
        await page.get_by_test_id("user-menu").wait_for(timeout=10000)
        check("password changed, application opens", True)

        # 2. production look: no demo banner, real date, setup checklist
        check("no demonstration banner", await page.get_by_text("DEMONSTRATION DATA").count() == 0)
        resp = await page.request.get(BASE + "/api/v1/meta")
        meta = await resp.json()
        h = resp.headers
        check("security headers (CSP, no framing, nosniff" + (", HSTS" if BASE.startswith("https") else "") + ")",
              "frame-ancestors 'none'" in h.get("content-security-policy", "") and h.get("x-content-type-options") == "nosniff"
              and (not BASE.startswith("https") or "max-age" in h.get("strict-transport-security", "")))
        cookies = await page.context.cookies()
        check("session cookie HttpOnly" + (" and Secure" if BASE.startswith("https") else ""),
              any(c["name"] == "bi_session" and c["httpOnly"] and (c["secure"] or not BASE.startswith("https")) for c in cookies))
        check("real operational date in header", meta["mode"] == "production" and await page.get_by_test_id("today").count() == 1, meta["today"])
        check("site shown as not configured", await page.get_by_text("Site not configured").count() > 0)
        try:
            await page.get_by_test_id("setup-checklist").wait_for(timeout=10000)
            ok = True
        except Exception:
            ok = False
        check("getting-started checklist on the dashboard", ok)

        # 3. every screen renders on an empty database without JavaScript errors
        for r in ROUTES:
            n = len(errors)
            await page.goto(BASE + r)
            await page.wait_for_timeout(1200)
            body = await page.inner_text("body")
            check(f"empty database: {r} renders", len(errors) == n and "Internal error" not in body,
                  "; ".join(errors[n:])[:200])

        # 4. create the site and an area through Master Data
        await page.goto(BASE + "/masterdata?entity=site")
        await page.get_by_role("button", name="New", exact=True).click()
        dlg = page.get_by_role("dialog")
        await dlg.get_by_label("Code *").fill("mdn")
        await dlg.get_by_label("Name *").fill("Mine du Nord")
        await dlg.get_by_role("button", name="Save").click()
        await page.get_by_role("cell", name="MDN").wait_for(timeout=10000)
        check("site created from Master Data (code upper-cased)", True)
        await page.get_by_role("tab", name="Areas").click()
        await page.get_by_role("button", name="New", exact=True).click()
        dlg = page.get_by_role("dialog")
        await dlg.get_by_label("Site *").select_option(label="MDN — Mine du Nord")
        await dlg.get_by_label("Code *").fill("P1")
        await dlg.get_by_label("Name *").fill("Pit 1")
        await dlg.get_by_label("Area type *").select_option(label="Open pit")
        await dlg.get_by_role("button", name="Save").click()
        await page.get_by_role("cell", name="Pit 1").wait_for(timeout=10000)
        check("area created with a reference to the site", True)
        await page.goto(BASE + "/")
        await page.wait_for_timeout(1000)
        check("header shows the configured site", await page.get_by_text("Mine du Nord").count() > 0)
        check("checklist reflects progress", await page.get_by_text("2 of 11 set up", exact=False).count() > 0)

        # 5. operational records from the interface: bench → work order → pattern + design import → blast
        await page.goto(BASE + "/masterdata?entity=bench")
        await page.get_by_role("button", name="New", exact=True).click()
        dlg = page.get_by_role("dialog")
        await dlg.get_by_label("Area *").select_option(index=1)
        await dlg.get_by_label("Code *").fill("P1-B310")
        await dlg.get_by_label("Elevation (m) *").fill("310")
        await dlg.get_by_label("Bench height (m) *").fill("12")
        await dlg.get_by_role("button", name="Save").click()
        await page.get_by_role("cell", name="P1-B310").wait_for(timeout=10000)

        await page.goto(BASE + "/planning")
        await page.get_by_role("button", name="New work order").click()
        dlg = page.get_by_role("dialog")
        await dlg.get_by_label("Title").fill("Production blast P1-B310")
        await dlg.locator("select").first.select_option(index=1)
        await dlg.get_by_role("button", name="Save").click()
        try:
            await page.get_by_role("cell", name=re.compile(r"WO-\d\d-0001")).wait_for(timeout=10000)
            ok = True
        except Exception:
            ok = False
        check("work order created from Production Planning (automatic code)", ok)

        await page.goto(BASE + "/drillholes")
        await page.get_by_role("button", name="New pattern").click()
        dlg = page.get_by_role("dialog")
        await dlg.locator("select").first.select_option(index=1)
        await dlg.locator("input[type=number]").fill("140")
        await dlg.get_by_label("Approved design document").fill("DBP-47 rev B")
        await dlg.get_by_label("Approved by").fill("J. Engineer")
        await dlg.get_by_role("button", name="Create, then import the holes").click()
        await page.get_by_role("button", name="Import drillhole design").first.click()
        dlg = page.get_by_role("dialog")
        csv_path = Path(tempfile.gettempdir()) / "bi_holes.csv"
        csv_path.write_text("hole_code,x,y,z,depth_m\n" + "\n".join(
            f"R{r}-{c:02d},{1000 + 4 * c},{500 + 3.5 * (r - 1)},310,13" for r in (1, 2) for c in range(1, 6)), encoding="utf-8")
        await dlg.locator("input[type=file]").set_input_files(str(csv_path))
        await dlg.get_by_role("button", name="Validate only").click()
        await dlg.get_by_text("File valid").wait_for(timeout=10000)
        await dlg.get_by_role("button", name="Import", exact=True).click()
        await dlg.get_by_text("10 holes imported").wait_for(timeout=10000)
        await dlg.get_by_role("button", name="Close").last.click()
        await page.wait_for_timeout(800)
        check("pattern created and drillhole design imported (10 holes on the plan)",
              await page.locator('g[aria-label$="NOT_MEASURED"]').count() == 10)
        check("tolerance warning shown until DEPTH_TOL / DEVIATION_TOL are configured",
              await page.get_by_text("Drillhole tolerances are not configured").count() > 0)

        await page.goto(BASE + "/blasting")
        await page.get_by_role("button", name="New blast").click()
        dlg = page.get_by_role("dialog")
        await dlg.locator("select").nth(0).select_option(index=1)
        await dlg.locator("select").nth(1).select_option(index=1)
        await dlg.get_by_label("Approved blast plan reference").fill("BP-47 rev B")
        await dlg.get_by_role("button", name="Save").click()
        try:
            await page.get_by_text("Approved blast plan reference recorded").first.wait_for(timeout=10000)
            ok = True
        except Exception:
            ok = False
        check("blast created as Planned with the site checkpoints", ok and await page.get_by_role("heading", name=re.compile(r"BL-\d\d-0001")).count() > 0)

        check("no JavaScript errors during the run", not errors, "; ".join(errors[:3]))
        await browser.close()

    passed = sum(r["ok"] for r in results)
    print(json.dumps({"passed": passed, "failed": len(results) - passed, "total": len(results)}))
    sys.exit(0 if passed == len(results) else 1)


asyncio.run(main())
