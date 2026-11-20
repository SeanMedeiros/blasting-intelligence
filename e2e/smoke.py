"""End-to-end smoke test of the running application (Playwright, Chromium).

Usage (DEMO mode server — start_demo.bat serves http://127.0.0.1:8001 — demo data freshly reset):
    pip install playwright && python -m playwright install chromium
    python e2e/smoke.py [base_url]

Prints one line per check and a JSON summary; exit code 1 if any check fails.
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
import tempfile
import time
from pathlib import Path

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"
ROUTES = {
    "dashboard": ("/", "Operations Control Center"), "planning": ("/planning", "Production & Delivery Planning"),
    "scanning": ("/scanning", "3D Scanning & Free-Face Profiling"), "drillholes": ("/drillholes", "Drillhole Verification"),
    "blasting": ("/blasting", "Blasting Operations"), "laboratory": ("/laboratory", "Product Laboratory — QA/QC"),
    "vibration": ("/vibration", "Vibration & Blast Monitoring"), "detonators": ("/detonators", "Electronic Detonator Traceability"),
    "safety": ("/safety", "Safety & QSSE"), "postblast": ("/postblast", "Post-Blast Analysis"),
    "kpi": ("/kpi", "KPI & Performance Intelligence"), "reports": ("/reports", "Reports & Operational Database"), "settings": ("/settings", "Settings"),
    "users": ("/users", "Users & Access"),
}
results: list[dict] = []
DEMO_PASSWORD = "Demo-2026!"


def check(name: str, ok: bool, detail: str = ""):
    results.append({"check": name, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        ctx = await browser.new_context(viewport={"width": 1600, "height": 1000}, ignore_https_errors=BASE.startswith("https"))
        page = await ctx.new_page()
        errors: list[str] = []
        external: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: external.append(r.url) if not r.url.startswith(BASE) and not r.url.startswith("data:") and not r.url.startswith("blob:") else None)
        await page.goto(BASE + "/")
        await page.evaluate("localStorage.clear(); sessionStorage.clear()")

        async def sign_in(user: str, pwd: str = DEMO_PASSWORD):
            await page.get_by_role("heading", name="Sign in").wait_for(timeout=10000)
            await page.get_by_label("Username").fill(user)
            await page.get_by_label("Password").fill(pwd)
            await page.get_by_role("button", name="Sign in").click()

        # 0. sign-in screen, wrong password refused, then admin signs in
        await page.goto(BASE + "/")
        await sign_in("admin", "wrong-password-1")
        try:
            await page.get_by_text("Invalid username or password").wait_for(timeout=5000)
            refused = True
        except Exception:
            refused = False
        check("sign-in refuses a wrong password", refused)
        await sign_in("admin")
        try:
            await page.get_by_role("heading", name="Operations Control Center", exact=True).wait_for(timeout=10000)
            signed = True
        except Exception:
            signed = False
        check("admin signs in", signed)
        anon = await browser.new_context(ignore_https_errors=BASE.startswith("https"))
        r = await anon.request.get(BASE + "/api/v1/dashboard")
        check("API refuses requests without a session", r.status == 401, str(r.status))
        await anon.close()

        # 1. every module loads, in English, without JavaScript errors
        for key, (path, title) in ROUTES.items():
            n = len(errors)
            t0 = time.time()
            await page.goto(BASE + path)
            try:
                await page.get_by_role("heading", name=title, exact=True).wait_for(timeout=15000)
                ok = True
            except Exception:
                ok = False
            await page.wait_for_timeout(600)
            check(f"route {path} renders '{title}'", ok and len(errors) == n, f"{time.time() - t0:.1f}s" + (f" errors: {errors[n:]}" if len(errors) > n else ""))

        # 2. simulated-data banner always visible
        check("simulated-data banner", await page.get_by_text("DEMONSTRATION DATA — FICTIONAL SITE").count() > 0)

        # 3. French localization
        await page.goto(BASE + "/")
        await page.get_by_role("button", name="fr", exact=True).click()
        try:
            await page.get_by_role("heading", name="Centre de contrôle des opérations").wait_for(timeout=5000)
            fr = True
        except Exception:
            fr = False
        check("French interface", fr)
        # server texts follow the UI language (KPI names come from the API) and downloads carry ?lang=fr
        await page.goto(BASE + "/")
        try:
            await page.get_by_role("button", name="Taux de déviation des trous").first.click()
            await page.get_by_text("Trous dont la dernière mesure").first.wait_for(timeout=8000)  # formula text comes from the server
            await page.keyboard.press("Escape")
            await page.goto(BASE + "/kpi")
            href = await page.locator("a[href*='kpi-monthly.pdf']").first.get_attribute("href", timeout=8000)
            frsrv = "lang=fr" in (href or "")
        except Exception:
            frsrv = False
        check("French server texts and report links", frsrv)
        r = await page.request.get(BASE + "/api/v1/reports/kpi-monthly.pdf?month=2026-11&lang=fr")
        check("French monthly KPI PDF generated", r.ok and (await r.body())[:4] == b"%PDF")
        await page.goto(BASE + "/")
        await page.get_by_role("button", name="en", exact=True).click()

        # 4. KPI formula dialog
        await page.get_by_role("button", name="Drillhole deviation rate").first.click()
        try:
            await page.get_by_text("Holes whose latest measurement").first.wait_for(timeout=8000)
            okf = True
        except Exception:
            okf = False
        check("KPI calculation method dialog", okf)
        await page.keyboard.press("Escape")

        # 5. 3D viewer (WebGL canvas) and statistics
        await page.goto(BASE + "/scanning")
        try:
            await page.locator("canvas").first.wait_for(timeout=20000)
            await page.get_by_text("within ±0.5 m").first.wait_for(timeout=20000)
            ok3d = True
        except Exception:
            ok3d = False
        check("3D viewer canvas + deviation statistics", ok3d)

        # 6. drillhole measurement form (rule-based status)
        await page.goto(BASE + "/drillholes")
        await page.wait_for_timeout(1500)
        hole = page.locator('g[aria-label$="NOT_MEASURED"]').first
        if await hole.count():
            await hole.click()
            await page.get_by_role("button", name="Record measurement").click()
            dlg = page.get_by_role("dialog")
            await dlg.locator("input[type=number]").nth(0).fill("13.05")
            await dlg.locator("input[type=number]").nth(1).fill("0.20")
            await dlg.get_by_role("button", name="Save").click()
            await page.wait_for_timeout(1000)
            check("drillhole measurement recorded", await dlg.get_by_text("Inspection result").count() > 0)
            await dlg.get_by_role("button", name="Close").last.click()
        else:
            check("drillhole measurement recorded", False, "no unmeasured hole found")

        # 7. laboratory test with out-of-spec result → non-conformance
        await page.goto(BASE + "/laboratory")
        await page.get_by_role("tab", name="Viscosity").click()
        await page.get_by_role("button", name="Record test").click()
        dlg = page.get_by_role("dialog")
        await dlg.locator("input").nth(0).fill("E100-261203")
        await dlg.locator("input").nth(1).fill("50000")
        await dlg.locator("select").nth(0).select_option(label="VISC-01 — Rotational viscometer")
        await dlg.get_by_role("button", name="Save").click()
        await page.wait_for_timeout(1000)
        check("lab test → automatic non-conformance", await dlg.get_by_text("Non-conformance").count() > 0)
        await dlg.get_by_role("button", name="Close").last.click()

        # 8. safety observation with high risk → automatic corrective action
        await page.goto(BASE + "/safety")
        await page.get_by_role("button", name="New observation").click()
        dlg = page.get_by_role("dialog")
        await dlg.locator("textarea").nth(0).fill("Loose rock on the crest of NP-B310 near the access ramp")
        await dlg.locator("input").nth(1).fill("NP-B310 crest")
        await dlg.locator("select").nth(1).select_option(index=1)  # area (no default: must be chosen)
        await dlg.locator("select").nth(2).select_option(index=1)  # responsible person
        await dlg.locator("select").nth(3).select_option("4")
        await dlg.locator("select").nth(4).select_option("4")
        await dlg.locator("textarea").nth(1).fill("Barricade the crest and request scaling")
        await dlg.get_by_role("button", name="Save").click()
        await page.wait_for_timeout(1000)
        check("high-risk observation → corrective action", await dlg.get_by_text("Corrective action created").count() > 0)
        await dlg.get_by_role("button", name="Close").last.click()

        # 9. blasting workflow refuses an incomplete transition (button disabled)
        await page.goto(BASE + "/blasting")
        await page.wait_for_timeout(1500)
        await page.get_by_role("button", name="BL-26-0437").first.click()
        await page.wait_for_timeout(1200)
        btn = page.get_by_role("button", name="Record next status")
        check("blast workflow blocks step with unmet conditions", await btn.is_disabled())

        # 9b. evidence photo attached to the blast (stored with its SHA-256, thumbnail shown)
        png = Path(tempfile.gettempdir()) / "bi_evidence.png"
        png.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
        await page.get_by_role("tab", name="Evidence files").click()
        panel = page.get_by_test_id("attachments-blast")
        await panel.locator("input[type=file]").set_input_files(str(png))
        await panel.get_by_placeholder("Description (optional)").fill("Exclusion zone barricade")
        await panel.get_by_role("button", name="Attach").click()
        try:
            await panel.get_by_alt_text("bi_evidence.png").wait_for(timeout=10000)
            okp = True
        except Exception:
            okp = False
        check("evidence photo attached to a blast (thumbnail)", okp)

        # 10. PDF report generation
        r = await page.request.get(BASE + "/api/v1/reports/kpi-monthly.pdf?month=2026-11")
        body = await r.body()
        check("monthly KPI PDF generated", r.ok and body[:4] == b"%PDF", f"{len(body) // 1024} KB")

        # 10b. administrator: database status and an on-demand backup
        await page.goto(BASE + "/settings")
        await page.get_by_role("button", name="Back up now").click()
        try:
            await page.get_by_text("-manual.zip").first.wait_for(timeout=20000)
            okb = True
        except Exception:
            okb = False
        check("admin: on-demand backup listed in Settings", okb and await page.get_by_text("Up to date").count() > 0)

        # 11. sign out; a viewer cannot see user administration and write buttons are locked
        await page.get_by_test_id("user-menu").click()
        await page.get_by_role("menuitem", name="Sign out").click()
        await sign_in("iouellet")
        await page.get_by_test_id("user-menu").wait_for(timeout=10000)
        check("viewer: no Users & Access menu", await page.get_by_role("link", name="Users & Access").count() == 0)
        await page.goto(BASE + "/safety")
        await page.get_by_role("heading", name="Safety & QSSE", exact=True).wait_for(timeout=10000)
        check("viewer: 'New observation' locked", await page.get_by_role("button", name="New observation").is_disabled())

        # 12. offline: no request left the local server
        check("no external network requests (offline capable)", not external, ", ".join(sorted(set(external))[:5]))
        check("no JavaScript errors during the run", not errors, "; ".join(errors[:3]))
        await browser.close()

    passed = sum(r["ok"] for r in results)
    print(json.dumps({"passed": passed, "failed": len(results) - passed, "total": len(results)}))
    with open("e2e_results.json", "w") as f:
        json.dump(results, f, indent=2)
    sys.exit(0 if passed == len(results) else 1)


asyncio.run(main())
