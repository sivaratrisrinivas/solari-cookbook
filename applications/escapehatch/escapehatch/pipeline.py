"""One EscapeRun: desktop extract → destroy; sandbox + browser → destroy all."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from .browser import file_artifact
from .desktop import extract_csv
from .evidence import PLACEHOLDER_PNG, save_bytes, screens_dir, sha256_bytes, write_run
from .models import EscapeRun, create_run
from .normalizer import normalize_csv
from .ods import expected_csv
from .paths import CSV_FIXTURE
from .sandbox import normalize_and_host


def _placeholder_shots(run: EscapeRun, evidence_dir: Path, names: tuple[str, ...]) -> None:
    folder = screens_dir(evidence_dir)
    for name in names:
        save_bytes(folder / name, PLACEHOLDER_PNG)
        run.screenshots.append(f"screens/{name}")


def _dry_file(run: EscapeRun, json_path: Path, digest: str) -> str:
    """File through a local portal — no Solari browser, no Solari sandbox."""
    import threading
    from http.client import HTTPConnection

    from . import portal_server

    portal_server.RECEIPTS.clear()
    server = portal_server.ThreadingHTTPServer(
        ("127.0.0.1", 0), portal_server.Handler
    )
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        run.portalUrl = f"http://127.0.0.1:{port}/"
        run.advance("portal_up")
        run.advance("filing")
        boundary = "----escapehatch"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="artifact"; filename="normalized.json"\r\n'
            "Content-Type: application/json\r\n\r\n"
        ).encode("utf-8") + json_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("ascii")
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request(
            "POST",
            "/file",
            body=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
        )
        response = conn.getresponse()
        html = response.read().decode("utf-8")
        conn.close()
        if response.status != 200:
            raise RuntimeError(f"local portal rejected the artifact: HTTP {response.status}")
        marker = 'data-receipt="'
        if marker not in html:
            raise RuntimeError("local portal returned no receipt")
        receipt = html.split(marker, 1)[1].split('"', 1)[0]
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", f"/seen?receipt={receipt}")
        seen = conn.getresponse().read().decode("utf-8").strip()
        conn.close()
        if seen != "yes":
            raise RuntimeError("local /seen did not confirm the receipt")
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", f"/receipts/{receipt}")
        record = json.loads(conn.getresponse().read().decode("utf-8"))
        conn.close()
        if record.get("digest") != digest:
            raise RuntimeError("local receipt digest mismatch")
        run.portalReceipt = receipt
        run.advance("filed")
        return receipt
    finally:
        server.shutdown()
        server.server_close()


async def run_dry(evidence_dir: Path) -> EscapeRun:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    run = create_run(str(evidence_dir), mode="dry-run")
    try:
        run.advance("desktop_running")
        csv_text = CSV_FIXTURE.read_text(encoding="utf-8") if CSV_FIXTURE.exists() else expected_csv()
        csv_bytes = csv_text.encode("utf-8")
        save_bytes(evidence_dir / "extract.csv", csv_bytes)
        run.extractPath = "extract.csv"
        run.extractSha256 = sha256_bytes(csv_bytes)
        _placeholder_shots(
            run,
            evidence_dir,
            (
                "desktop-calc-open.png",
                "desktop-save-as.png",
                "desktop-exported.png",
                "browser-portal.png",
                "browser-receipt.png",
            ),
        )
        run.advance("extracted")

        run.advance("normalizing")
        payload = normalize_csv(csv_text)
        json_bytes = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        save_bytes(evidence_dir / "normalized.json", json_bytes)
        run.normalizedJsonPath = "normalized.json"
        run.normalizedSha256 = sha256_bytes(json_bytes)
        run.advance("normalized")

        _dry_file(run, evidence_dir / "normalized.json", payload["digest"])
        run.advance("cleaned")
        run.cleanup = {
            "attempted": True,
            "succeeded": True,
            "detail": "dry-run: no Solari sessions created",
        }
    except Exception as exc:
        run.fail(f"{type(exc).__name__}: {exc}")
        run.cleanup = {
            "attempted": True,
            "succeeded": True,
            "detail": "dry-run: no Solari sessions created",
        }
    write_run(run, evidence_dir)
    return run


async def run_live(
    evidence_dir: Path,
    *,
    api_key: str,
    base_url: str,
    record: bool,
) -> EscapeRun:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    run = create_run(str(evidence_dir), mode="live")
    sandbox = None
    sandbox_client = None
    cleanup_errors: list[str] = []
    try:
        csv_bytes = await extract_csv(
            run,
            api_key=api_key,
            evidence_dir=evidence_dir,
            base_url=base_url,
            record=record,
        )
        # Desktop is already destroyed. Now one sandbox + one browser.
        sandbox, sandbox_client, portal_url, payload = await normalize_and_host(
            run,
            csv_bytes,
            api_key=api_key,
            evidence_dir=evidence_dir,
            base_url=base_url,
        )
        try:
            await file_artifact(
                run,
                api_key=api_key,
                portal_url=portal_url,
                json_path=evidence_dir / "normalized.json",
                evidence_dir=evidence_dir,
                expected_digest=payload["digest"],
            )
        finally:
            if sandbox is not None:
                try:
                    await sandbox.kill()
                except Exception as exc:
                    cleanup_errors.append(f"sandbox.kill: {type(exc).__name__}: {exc}")
                    if run.sandboxId and sandbox_client is not None:
                        try:
                            await sandbox_client.kill(run.sandboxId)
                        except Exception as exc:
                            cleanup_errors.append(
                                f"client.kill: {type(exc).__name__}: {exc}"
                            )
                sandbox = None
        if run.status == "filed":
            run.advance("cleaned")
        run.cleanup = {
            "attempted": True,
            "succeeded": not cleanup_errors,
            "detail": (
                "destroyed desktop, then sandbox + browser"
                if not cleanup_errors
                else "; ".join(cleanup_errors)
            ),
        }
    except Exception as exc:
        if run.status != "failed":
            run.fail(f"{type(exc).__name__}: {exc}")
        if sandbox is not None:
            try:
                await sandbox.kill()
            except Exception as kill_exc:
                cleanup_errors.append(f"sandbox.kill: {type(kill_exc).__name__}: {kill_exc}")
        run.cleanup = {
            "attempted": True,
            "succeeded": not cleanup_errors,
            "detail": (
                "destroyed remaining VMs after failure"
                if not cleanup_errors
                else "; ".join(cleanup_errors)
            ),
        }
    finally:
        if sandbox_client is not None:
            try:
                await sandbox_client.aclose()
            except Exception:
                pass
        write_run(run, evidence_dir)
    return run


async def run_pipeline(
    evidence_dir: Path,
    *,
    mode: Literal["dry-run", "live"],
    api_key: str | None = None,
    base_url: str,
    record: bool = True,
) -> EscapeRun:
    if mode == "dry-run":
        return await run_dry(evidence_dir)
    if not api_key:
        raise SystemExit("SOLARI_API_KEY is required for a live run")
    return await run_live(
        evidence_dir, api_key=api_key, base_url=base_url, record=record
    )
