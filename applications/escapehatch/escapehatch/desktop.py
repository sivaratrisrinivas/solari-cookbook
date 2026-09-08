"""Drive LibreOffice Calc on a real Solari desktop and export the hold log as CSV."""

from __future__ import annotations

import asyncio
from pathlib import Path

from solari_desktop import DesktopClient

from .evidence import save_bytes, screens_dir, sha256_bytes
from .models import EscapeRun
from .paths import BASE_URL, ODS_FIXTURE, REMOTE_CSV, REMOTE_DIR, REMOTE_ODS


async def _wait_ready(desktop, attempts: int = 40) -> None:
    for _ in range(attempts):
        health = await desktop.health()
        if getattr(health, "ready", False) and getattr(health, "display", False):
            return
        await asyncio.sleep(0.5)
    raise TimeoutError("Solari desktop did not become display-ready")


async def _which(desktop, names: tuple[str, ...]) -> str:
    for name in names:
        result = await desktop.exec("sh", args=["-c", f"command -v {name}"])
        found = (result.stdout or "").strip()
        if result.exitCode == 0 and found:
            return name
    raise RuntimeError(f"none of {names} are on the default desktop image")


def _looks_like_csv(data: bytes) -> bool:
    if data.startswith(b"PK"):
        return False
    text = data.decode("utf-8-sig", errors="replace")
    return "Batch" in text and "PINE-" in text


async def _shot(desktop, evidence_dir: Path, name: str, run: EscapeRun) -> None:
    path = screens_dir(evidence_dir) / name
    save_bytes(path, await desktop.screenshot(format="png"))
    run.screenshots.append(f"screens/{name}")


async def _confirm_dialogs(desktop) -> None:
    # LibreOffice asks "Use Text CSV Format?" and then opens the text-export
    # options. Enter accepts the default on both. Extra Enters are harmless
    # once the dialogs are gone.
    for _ in range(3):
        await desktop.keyboard.press("enter")
        await asyncio.sleep(0.7)


async def _export_csv(desktop, evidence_dir: Path, run: EscapeRun) -> None:
    # File → Save As. Ctrl+Shift+S is the Calc shortcut on the English UI.
    await desktop.keyboard.hotkey("ctrl", "shift", "s")
    await asyncio.sleep(2.0)
    await _shot(desktop, evidence_dir, "desktop-save-as.png", run)

    await desktop.clipboard.set(REMOTE_CSV)
    await desktop.keyboard.hotkey("ctrl", "a")
    await desktop.keyboard.hotkey("ctrl", "v")
    await asyncio.sleep(0.4)

    # Alt+T focuses the file-type list on the LibreOffice Save As dialog.
    await desktop.keyboard.hotkey("alt", "t")
    await asyncio.sleep(0.3)
    await desktop.keyboard.type("Text CSV")
    await asyncio.sleep(0.4)
    await desktop.keyboard.press("enter")
    await asyncio.sleep(0.6)
    await desktop.keyboard.press("enter")
    await asyncio.sleep(1.0)
    await _confirm_dialogs(desktop)


async def extract_csv(
    run: EscapeRun,
    *,
    api_key: str,
    evidence_dir: Path,
    base_url: str = BASE_URL,
    record: bool = True,
) -> bytes:
    """Create one desktop, export the fixture .ods via the Calc GUI, then destroy it.

    This is the only live VM during this phase. The caller must not hold a
    sandbox or browser yet — free-tier concurrency is ~2 and we need both
    slots for the next phase.
    """
    client = DesktopClient(api_key=api_key, base_url=base_url, call_timeout_ms=30_000)
    desktop = None
    session_id: str | None = None
    recording = False
    try:
        run.advance("desktop_running")
        desktop = await client.create(
            template="default",
            resolution="1280x720",
            cpu=2,
            mem_mb=2048,
            timeout_ms=10 * 60_000,
            lifecycle={"onTimeout": "kill"},
            record=record or None,
            metadata={"product": "escapehatch", "purpose": "calc-extract"},
        )
        session_id = desktop.sessionId
        run.desktopSessionId = session_id
        run.recordingUrl = desktop.recordingUrl
        await desktop.connect()
        await _wait_ready(desktop)
        if record:
            await desktop.record.start()
            recording = True

        await desktop.exec("mkdir", args=["-p", REMOTE_DIR])
        await desktop.fs.write(REMOTE_ODS, ODS_FIXTURE.read_bytes())

        binary = await _which(desktop, ("libreoffice", "soffice"))
        # --nologo / --norestore skip the splash and the "recover files?" box
        # so the first screenshot is Calc, not a modal.
        await desktop.open(binary, ["--calc", "--nologo", "--norestore", REMOTE_ODS])
        await asyncio.sleep(8.0)
        # Click inside the sheet, not screen-centre: Calc opens top-left and
        # a centre click focuses the wallpaper. Keystrokes then go nowhere.
        await desktop.mouse.click(380, 280, humanize=True)
        await asyncio.sleep(0.3)
        await desktop.keyboard.hotkey("alt", "f10")
        await asyncio.sleep(0.6)
        await _shot(desktop, evidence_dir, "desktop-calc-open.png", run)

        await _export_csv(desktop, evidence_dir, run)

        csv_bytes: bytes | None = None
        for _ in range(20):
            try:
                candidate = await desktop.fs.read(REMOTE_CSV)
            except Exception:
                candidate = b""
            if candidate and _looks_like_csv(candidate):
                csv_bytes = candidate
                break
            await asyncio.sleep(0.75)
        if csv_bytes is None:
            await _shot(desktop, evidence_dir, "desktop-export-failed.png", run)
            raise RuntimeError("Calc did not write a CSV at the export path")

        await _shot(desktop, evidence_dir, "desktop-exported.png", run)
        extract_path = evidence_dir / "extract.csv"
        save_bytes(extract_path, csv_bytes)
        run.extractPath = "extract.csv"
        run.extractSha256 = sha256_bytes(csv_bytes)
        run.advance("extracted")
        return csv_bytes
    except Exception as exc:
        run.fail(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if desktop is not None:
            if recording:
                try:
                    await desktop.record.stop()
                except Exception:
                    pass
            try:
                await desktop.close()
            except Exception:
                pass
        if session_id is not None:
            try:
                await client.destroy(session_id)
            except Exception:
                if desktop is not None:
                    try:
                        await desktop.kill()
                    except Exception:
                        pass
        await client.aclose()
