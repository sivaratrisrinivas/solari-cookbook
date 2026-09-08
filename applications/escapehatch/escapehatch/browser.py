"""File the normalized artifact through a Solari cloud browser and assert the receipt."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.request import urlopen

from solari_browser import Solari

from .evidence import save_bytes, screens_dir
from .models import EscapeRun
from .sandbox import preview_at


async def file_artifact(
    run: EscapeRun,
    *,
    api_key: str,
    portal_url: str,
    json_path: Path,
    evidence_dir: Path,
    expected_digest: str,
) -> str:
    solari = Solari(api_key=api_key)
    browser = None
    try:
        run.advance("filing")
        browser = await solari.launch()
        run.browserSessionId = browser.id
        page = await browser.new_page()
        await page.goto(preview_at(portal_url, "/"), wait_until="domcontentloaded")
        await page.set_input_files('input[name="artifact"]', str(json_path))
        await _shot(page, evidence_dir, "browser-portal.png", run)
        await page.click("button[type=submit]")
        receipt_el = page.locator("[data-receipt]")
        await receipt_el.wait_for(timeout=15_000)
        receipt = (await receipt_el.get_attribute("data-receipt") or "").strip()
        if not receipt:
            raise RuntimeError("portal thank-you page had no receipt id")
        await _shot(page, evidence_dir, "browser-receipt.png", run)

        seen = preview_at(portal_url, "/seen", receipt=receipt)
        with urlopen(seen, timeout=10) as response:
            arrived = response.read().decode("utf-8").strip()
        if arrived != "yes":
            raise RuntimeError(f"/seen did not confirm receipt {receipt}")

        receipts = preview_at(portal_url, f"/receipts/{receipt}")
        with urlopen(receipts, timeout=10) as response:
            record = json.loads(response.read().decode("utf-8"))
        if record.get("id") != receipt or record.get("digest") != expected_digest:
            raise RuntimeError(f"receipt {receipt} does not match the filed digest")

        run.portalReceipt = receipt
        run.advance("filed")
        return receipt
    except Exception as exc:
        run.fail(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        await solari.close()


async def _shot(page, evidence_dir: Path, name: str, run: EscapeRun) -> None:
    path = screens_dir(evidence_dir) / name
    save_bytes(path, await page.screenshot(type="png", full_page=True))
    run.screenshots.append(f"screens/{name}")
