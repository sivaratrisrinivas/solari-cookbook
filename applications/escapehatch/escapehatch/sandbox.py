"""Sandbox: normalize the CSV, then host the intake portal on a public preview URL."""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from solari_sandbox import SandboxClient

from .evidence import save_bytes, sha256_bytes
from .models import EscapeRun
from .normalizer import normalize_csv
from .paths import (
    BASE_URL,
    PORTAL_PORT,
    REMOTE_CSV,
    REMOTE_DIR,
    REMOTE_JSON,
    REMOTE_NORMALIZER,
    REMOTE_PORTAL,
)


def preview_at(preview_url: str, path: str, **params: str) -> str:
    """previewUrl already carries ?pt_token=. Never concatenate a path onto it."""
    parts = urlparse(preview_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({k: v for k, v in params.items() if v})
    return urlunparse(parts._replace(path=path, query=urlencode(query)))


async def wait_for_server(target: str, attempts: int = 20) -> None:
    import urllib.error
    import urllib.request

    for _ in range(attempts):
        await asyncio.sleep(1)
        try:
            with urllib.request.urlopen(target, timeout=5) as response:
                if 200 <= response.status < 300:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    raise TimeoutError(f"portal never came up at {target}")


def _package_file(name: str) -> str:
    return (Path(__file__).resolve().parent / name).read_text(encoding="utf-8")


async def normalize_and_host(
    run: EscapeRun,
    csv_bytes: bytes,
    *,
    api_key: str,
    evidence_dir: Path,
    base_url: str = BASE_URL,
):
    """Create the sandbox, normalize inside it, start the portal. Caller destroys."""
    client = SandboxClient(api_key=api_key, base_url=base_url, call_timeout_ms=30_000)
    sandbox = None
    try:
        run.advance("normalizing")
        sandbox = await client.create(
            template="base",
            timeout_ms=10 * 60_000,
            lifecycle={"onTimeout": "kill"},
            metadata={"product": "escapehatch", "purpose": "normalize-portal"},
        )
        run.sandboxId = sandbox.sandboxId
        await sandbox.connect()
        await sandbox.commands.run("mkdir", args=["-p", REMOTE_DIR])
        await sandbox.files.write(REMOTE_CSV, csv_bytes)
        await sandbox.files.write(REMOTE_NORMALIZER, _package_file("normalizer.py"))
        await sandbox.files.write(REMOTE_PORTAL, _package_file("portal_server.py"))

        command = await sandbox.commands.run(
            "python3",
            args=[REMOTE_NORMALIZER, REMOTE_CSV, REMOTE_JSON],
            timeout_ms=30_000,
        )
        if command.exitCode != 0:
            raise RuntimeError(
                f"sandbox normalizer failed: {command.stderr.strip() or command.stdout.strip()}"
            )

        remote_json = await sandbox.files.read_text(REMOTE_JSON)
        # Re-parse locally so a poisoned guest cannot hand us a different digest
        # than the CSV we just wrote. The guest did the work; we check the result.
        expected = normalize_csv(csv_bytes.decode("utf-8-sig"))
        import json

        observed = json.loads(remote_json)
        if observed.get("digest") != expected["digest"]:
            raise RuntimeError("sandbox digest does not match the local normalizer")

        json_path = evidence_dir / "normalized.json"
        save_bytes(json_path, remote_json.encode("utf-8"))
        run.normalizedJsonPath = "normalized.json"
        run.normalizedSha256 = sha256_bytes(remote_json.encode("utf-8"))
        run.advance("normalized")

        await sandbox.commands.run(
            "sh",
            args=["-c", f"nohup python3 {REMOTE_PORTAL} --port {PORTAL_PORT} >/tmp/escapehatch/portal.log 2>&1 &"],
        )
        preview = await sandbox.preview_url(PORTAL_PORT)
        portal_url = preview["url"]
        form_url = preview_at(portal_url, "/")
        await wait_for_server(form_url)
        run.portalUrl = form_url
        run.advance("portal_up")
        return sandbox, client, portal_url, expected
    except Exception as exc:
        run.fail(f"{type(exc).__name__}: {exc}")
        if sandbox is not None:
            try:
                await sandbox.kill()
            except Exception:
                if run.sandboxId:
                    try:
                        await client.kill(run.sandboxId)
                    except Exception:
                        pass
            sandbox = None
        await client.aclose()
        raise
