"""Phase C: file the normalized batch through a Solari cloud browser."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

from solari_browser import Solari

from .sandbox_phase import portal_at


@dataclass
class BrowserFiling:
    session_id: str
    receipt_id: str
    screens: list[str]


async def _wait_for_portal(url: str, attempts: int = 20) -> None:
    last_error = "not attempted"
    for _ in range(attempts):
        await asyncio.sleep(1)
        try:
            with urlopen(url, timeout=5) as response:
                if 200 <= response.status < 300:
                    return
                last_error = f"HTTP {response.status}"
        except Exception as exc:  # noqa: BLE001 - preview routing is not up yet
            last_error = f"{type(exc).__name__}: {exc}"
    raise TimeoutError(f"portal never came up at {url}: {last_error}")


def _assert_receipt(portal_url: str, receipt_id: str, digest: str) -> None:
    receipt_url = portal_at(portal_url, f"/receipts/{receipt_id}")
    with urlopen(receipt_url, timeout=10) as response:
        body = json.loads(response.read().decode("utf-8"))
    if body.get("id") != receipt_id:
        raise AssertionError(f"receipt {receipt_id} missing: {body!r}")
    if body.get("digest") != digest:
        raise AssertionError("receipt digest does not match the filed batch")
    seen_url = portal_at(portal_url, "/seen", token=receipt_id)
    with urlopen(seen_url, timeout=10) as response:
        seen = response.read().decode("utf-8").strip()
    if seen != "yes":
        raise AssertionError(f"/seen?token={receipt_id} returned {seen!r}")


async def file_batch(
    *,
    api_key: str,
    portal_url: str,
    document: dict,
    evidence_dir: Path,
) -> BrowserFiling:
    screens = evidence_dir / "screens"
    screens.mkdir(parents=True, exist_ok=True)
    batch_path = evidence_dir / "portal-batch.json"
    batch_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    form_url = portal_at(portal_url, "/")
    await _wait_for_portal(form_url)

    solari = Solari(api_key=api_key)
    browser = None
    try:
        browser = await solari.launch(recording=True)
        page = await browser.new_page()
        await page.goto(form_url, wait_until="domcontentloaded")
        await page.locator("h1").wait_for()
        await page.screenshot(path=str(screens / "browser-portal.png"), full_page=True)
        await page.set_input_files('input[name="batch"]', str(batch_path))
        await page.click("button")
        receipt = page.locator("#receipt-id")
        await receipt.wait_for(timeout=15_000)
        receipt_id = (await receipt.inner_text()).strip()
        if not receipt_id.startswith("RCPT-"):
            raise AssertionError(f"portal did not return a receipt id: {receipt_id!r}")
        await page.screenshot(path=str(screens / "browser-receipt.png"), full_page=True)
        await asyncio.sleep(2)
        _assert_receipt(portal_url, receipt_id, document["digest"])
        return BrowserFiling(
            session_id=browser.id,
            receipt_id=receipt_id,
            screens=["screens/browser-portal.png", "screens/browser-receipt.png"],
        )
    finally:
        if browser is not None:
            await browser.close()
        closer = getattr(solari, "close", None)
        if closer is not None:
            await closer()
