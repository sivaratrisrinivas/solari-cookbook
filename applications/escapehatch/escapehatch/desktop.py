"""Phase A: drive LibreOffice Calc on a real Solari desktop and export CSV."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from solari_desktop import DesktopClient

from .fixture import TICKETS_CSV
from .normalize import sha256_bytes
from .ods import build_ods

REMOTE_DIR = "/tmp/escapehatch"
REMOTE_ODS = f"{REMOTE_DIR}/night-shift-tickets.ods"
REMOTE_CSV = f"{REMOTE_DIR}/extract.csv"


@dataclass
class DesktopExtract:
    session_id: str
    csv_bytes: bytes
    sha256: str
    recording_url: str | None
    screens: list[str]


async def _wait_ready(desktop, attempts: int = 40) -> None:
    for _ in range(attempts):
        health = await desktop.health()
        if getattr(health, "ready", False):
            return
        await asyncio.sleep(1)
    raise TimeoutError("desktop did not become ready")


async def _app_on_path(desktop, name: str) -> bool:
    result = await desktop.exec("command", args=["-v", name])
    return result.exitCode == 0 and bool(result.stdout.strip())


async def _calc_binary(desktop) -> str:
    for name in ("libreoffice", "soffice"):
        if await _app_on_path(desktop, name):
            return name
    raise RuntimeError(
        "LibreOffice is not on PATH. The default template should ship it; "
        "retry with --desktop-template office if this host image is thinner."
    )


async def _wait_for_calc(desktop, attempts: int = 30) -> None:
    for _ in range(attempts):
        processes = await desktop.process.list()
        names = " ".join((proc.name or "").lower() for proc in processes)
        if "soffice" in names or "libreoffice" in names:
            await asyncio.sleep(4)
            return
        await asyncio.sleep(1)
    raise TimeoutError("LibreOffice Calc did not start")


async def _shot(desktop, path: Path) -> None:
    path.write_bytes(await desktop.screenshot(format="png"))


async def _export_csv(desktop) -> None:
    # Calc opens top-left. Click the sheet, not the empty desktop behind it.
    await desktop.mouse.click(420, 300, humanize=True)
    await asyncio.sleep(0.4)
    await desktop.keyboard.hotkey("ctrl", "shift", "s")
    await asyncio.sleep(1.5)
    await desktop.keyboard.type(REMOTE_CSV)
    await asyncio.sleep(0.4)
    await desktop.keyboard.hotkey("enter")
    await asyncio.sleep(1.2)
    # Confirm Text CSV, then accept the export-options dialog.
    await desktop.keyboard.hotkey("enter")
    await asyncio.sleep(1.0)
    await desktop.keyboard.hotkey("enter")
    await asyncio.sleep(1.5)


async def _read_extract(desktop, attempts: int = 20) -> bytes:
    for _ in range(attempts):
        probe = await desktop.exec("test", args=["-f", REMOTE_CSV])
        if probe.exitCode == 0:
            data = await desktop.fs.read(REMOTE_CSV)
            if data.strip():
                return data
        await desktop.keyboard.hotkey("enter")
        await asyncio.sleep(1)
    listed = await desktop.exec("ls", args=["-la", REMOTE_DIR])
    raise RuntimeError(f"Calc did not write {REMOTE_CSV}: {listed.stdout}")


async def extract_tickets(
    *,
    api_key: str,
    base_url: str,
    evidence_dir: Path,
    template: str,
) -> DesktopExtract:
    screens = evidence_dir / "screens"
    screens.mkdir(parents=True, exist_ok=True)
    client = DesktopClient(api_key=api_key, base_url=base_url, call_timeout_ms=30_000)
    desktop = None
    session_id: str | None = None
    recording_url: str | None = None
    try:
        desktop = await client.create(
            template=template,
            resolution="1280x720",
            cpu=2,
            mem_mb=2048,
            timeout_ms=10 * 60_000,
            record=True,
            lifecycle={"onTimeout": "kill"},
            metadata={"product": "escapehatch", "purpose": "calc-extract"},
        )
        session_id = desktop.sessionId
        recording_url = desktop.recordingUrl
        await desktop.connect()
        await _wait_ready(desktop)
        try:
            await desktop.record.start()
        except Exception:
            # create(record=True) already reserved a playback URL on golden boots.
            pass

        await desktop.exec("mkdir", args=["-p", REMOTE_DIR])
        await desktop.fs.write(REMOTE_ODS, build_ods(TICKETS_CSV))
        binary = await _calc_binary(desktop)
        await desktop.open(binary, ["--calc", "--nologo", REMOTE_ODS])
        await _wait_for_calc(desktop)
        await _shot(desktop, screens / "desktop-calc-open.png")
        await _export_csv(desktop)
        csv_bytes = await _read_extract(desktop)
        await _shot(desktop, screens / "desktop-exported.png")
        try:
            await desktop.record.stop()
        except Exception:
            pass
        recording_url = desktop.recordingUrl or recording_url
        return DesktopExtract(
            session_id=session_id,
            csv_bytes=csv_bytes,
            sha256=sha256_bytes(csv_bytes),
            recording_url=recording_url,
            screens=[
                "screens/desktop-calc-open.png",
                "screens/desktop-exported.png",
            ],
        )
    finally:
        try:
            if desktop is not None:
                await desktop.close()
        finally:
            try:
                if session_id is not None:
                    await client.destroy(session_id)
            finally:
                await client.aclose()
