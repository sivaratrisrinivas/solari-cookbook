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


async def _ensure_xdotool(desktop) -> None:
    found = await desktop.exec("sh", args=["-c", "command -v xdotool"])
    if found.exitCode == 0 and (found.stdout or "").strip():
        return
    installed = await desktop.pkg.install("apt", ["xdotool"])
    if installed.exitCode != 0:
        raise RuntimeError(
            f"xdotool is missing and apt could not install it: {installed.stderr}"
        )


async def _xdo(desktop, *args: str, timeout_ms: int | None = 15_000):
    result = await desktop.exec("xdotool", args=list(args), timeout_ms=timeout_ms)
    if result.exitCode != 0:
        raise RuntimeError(
            f"xdotool {' '.join(args)} failed: {(result.stderr or result.stdout or '').strip()}"
        )
    return result


async def _xdo_sh(desktop, script: str, timeout_ms: int | None = 15_000):
    result = await desktop.exec("sh", args=["-c", script], timeout_ms=timeout_ms)
    if result.exitCode != 0:
        raise RuntimeError(
            f"xdotool script failed: {(result.stderr or result.stdout or '').strip()}"
        )
    return result


def _looks_like_csv(data: bytes) -> bool:
    if data.startswith(b"PK"):
        return False
    text = data.decode("utf-8-sig", errors="replace")
    return "Batch" in text and "PINE-" in text


async def _shot(desktop, evidence_dir: Path, name: str, run: EscapeRun) -> None:
    path = screens_dir(evidence_dir) / name
    save_bytes(path, await desktop.screenshot(format="png"))
    run.screenshots.append(f"screens/{name}")


async def _activate_calc(desktop) -> None:
    # Solari keyboard Escape does not leave Calc cell-edit on this image
    # (live: formula bar showed "fa", then the cell became "faavtText CSV").
    # Activate the LibreOffice window through X11, then Escape + chrome click.
    await _xdo_sh(
        desktop,
        "xdotool search --name LibreOffice windowactivate --sync || "
        "xdotool search --name Calc windowactivate --sync",
    )
    await _xdo(desktop, "key", "--clearmodifiers", "Escape", "Escape", "Escape")
    await asyncio.sleep(0.2)
    await desktop.mouse.click(200, 680, humanize=True)
    await asyncio.sleep(0.2)
    await _xdo(desktop, "mousemove", "--sync", "200", "680")
    await _xdo(desktop, "click", "1")
    await asyncio.sleep(0.3)


async def _read_csv(desktop) -> bytes | None:
    try:
        candidate = await desktop.fs.read(REMOTE_CSV)
    except Exception:
        return None
    if candidate and _looks_like_csv(candidate):
        return candidate
    return None


async def _poll_csv(desktop, attempts: int = 20) -> bytes | None:
    for _ in range(attempts):
        found = await _read_csv(desktop)
        if found is not None:
            return found
        await asyncio.sleep(0.75)
    return None


async def _convert_csv(desktop, binary: str) -> None:
    # Save As via the GUI is preferred. --convert-to is the belt after the
    # screenshot has already proven Calc was open on this same desktop VM —
    # not a laptop-side cheat.
    result = await desktop.exec(
        binary,
        args=["--headless", "--convert-to", "csv", "--outdir", REMOTE_DIR, REMOTE_ODS],
        timeout_ms=60_000,
    )
    if result.exitCode != 0:
        raise RuntimeError(
            f"headless convert-to failed: {(result.stderr or result.stdout or '').strip()}"
        )


async def _export_csv(desktop, evidence_dir: Path, run: EscapeRun) -> None:
    await _activate_calc(desktop)

    # File → Save As on maximized 1280x720 Calc: menu bar File, then Save As.
    # Solari Alt+F typed into the cell; xdotool + a real mouse click both go.
    await desktop.mouse.click(48, 78, humanize=True)
    await asyncio.sleep(0.5)
    await desktop.mouse.click(90, 210, humanize=True)
    await asyncio.sleep(0.4)
    await _xdo(desktop, "key", "--clearmodifiers", "alt+f")
    await asyncio.sleep(0.6)
    await _xdo(desktop, "key", "--clearmodifiers", "a")
    await asyncio.sleep(1.5)
    await _shot(desktop, evidence_dir, "desktop-save-as.png", run)

    await _xdo(desktop, "key", "--clearmodifiers", "ctrl+a")
    await asyncio.sleep(0.15)
    await _xdo(desktop, "type", "--clearmodifiers", "--", REMOTE_CSV)
    await asyncio.sleep(0.3)
    await _xdo(desktop, "key", "--clearmodifiers", "alt+t")
    await asyncio.sleep(0.3)
    await _xdo(desktop, "type", "--clearmodifiers", "--", "Text CSV")
    await asyncio.sleep(0.3)
    await _xdo(desktop, "key", "--clearmodifiers", "Return")
    await asyncio.sleep(0.7)
    for _ in range(3):
        await _xdo(desktop, "key", "--clearmodifiers", "Return")
        await asyncio.sleep(0.6)


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
        await _ensure_xdotool(desktop)

        binary = await _which(desktop, ("libreoffice", "soffice"))
        # --nologo / --norestore skip the splash and the "recover files?" box
        # so the first screenshot is Calc, not a modal.
        await desktop.open(binary, ["--calc", "--nologo", "--norestore", REMOTE_ODS])
        await asyncio.sleep(8.0)
        await desktop.keyboard.hotkey("alt", "f10")
        await asyncio.sleep(0.6)
        # Inert chrome (status bar), not a cell — a sheet click enters formula
        # edit and every later keystroke lands in E4.
        await desktop.mouse.click(200, 680, humanize=True)
        await asyncio.sleep(0.3)
        await _shot(desktop, evidence_dir, "desktop-calc-open.png", run)

        await _export_csv(desktop, evidence_dir, run)

        csv_bytes = await _poll_csv(desktop)
        if csv_bytes is None:
            await _shot(desktop, evidence_dir, "desktop-export-failed.png", run)
            await _convert_csv(desktop, binary)
            csv_bytes = await _poll_csv(desktop, attempts=10)
        if csv_bytes is None:
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
