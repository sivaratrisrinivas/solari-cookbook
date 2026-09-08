"""Phase B: normalize the extract in a sandbox and host the closeout portal."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from solari_sandbox import SandboxClient

from .normalize import sha256_bytes

REMOTE_DIR = "/tmp/escapehatch"
REMOTE_CSV = f"{REMOTE_DIR}/extract.csv"
REMOTE_JSON = f"{REMOTE_DIR}/normalized.json"
REMOTE_NORMALIZER = f"{REMOTE_DIR}/normalize.py"
REMOTE_PORTAL = f"{REMOTE_DIR}/portal_server.py"
PORT = 8765


@dataclass
class SandboxWork:
    sandbox_id: str
    document: dict
    json_bytes: bytes
    sha256: str
    portal_url: str
    sandbox: object
    client: SandboxClient


def portal_at(preview: str, path: str, **params: str) -> str:
    """previewUrl already has ?pt_token=. Build paths through URL parts."""
    parts = urlsplit(preview)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(params)
    return urlunsplit(
        (parts.scheme, parts.netloc, path, urlencode(query), parts.fragment)
    )


async def start_normalizer_and_portal(
    *,
    api_key: str,
    base_url: str,
    extract_bytes: bytes,
    evidence_dir: Path,
) -> SandboxWork:
    package = Path(__file__).resolve().parent
    client = SandboxClient(api_key=api_key, base_url=base_url, call_timeout_ms=30_000)
    sandbox = await client.create(
        template="base",
        timeout_ms=10 * 60_000,
        lifecycle={"onTimeout": "kill"},
        metadata={"product": "escapehatch", "purpose": "normalize-portal"},
    )
    try:
        await sandbox.connect()
        await sandbox.commands.run("mkdir", args=["-p", REMOTE_DIR])
        await sandbox.files.write(REMOTE_CSV, extract_bytes)
        await sandbox.files.write(
            REMOTE_NORMALIZER, (package / "normalize.py").read_bytes()
        )
        command = await sandbox.commands.run(
            "python3",
            args=[REMOTE_NORMALIZER, REMOTE_CSV, REMOTE_JSON],
            timeout_ms=30_000,
        )
        if command.exitCode != 0:
            raise RuntimeError(
                f"sandbox normalizer failed: {command.stderr.strip() or command.stdout}"
            )
        json_bytes = await sandbox.files.read(REMOTE_JSON)
        document = json.loads(json_bytes.decode("utf-8"))
        if not document.get("accepted"):
            raise RuntimeError("normalizer accepted zero ticket rows")
        (evidence_dir / "normalized.json").write_bytes(json_bytes)

        await sandbox.files.write(
            REMOTE_PORTAL, (package / "portal_server.py").read_bytes()
        )
        # commands.run waits for exit; background the portal with an explicit shell.
        await sandbox.commands.run(
            "sh",
            args=["-c", f"nohup python3 {REMOTE_PORTAL} >/tmp/escapehatch/portal.log 2>&1 &"],
        )
        preview = await sandbox.preview_url(PORT)
        portal_url = preview.get("url") if isinstance(preview, dict) else None
        if not portal_url:
            raise RuntimeError(f"sandbox previewUrl returned no url: {preview!r}")
        return SandboxWork(
            sandbox_id=sandbox.sandboxId,
            document=document,
            json_bytes=json_bytes,
            sha256=sha256_bytes(json_bytes),
            portal_url=portal_url,
            sandbox=sandbox,
            client=client,
        )
    except Exception:
        try:
            await sandbox.kill()
        finally:
            await client.aclose()
        raise


async def destroy_sandbox(work: SandboxWork | None) -> None:
    if work is None:
        return
    try:
        await work.sandbox.kill()
    finally:
        try:
            await work.sandbox.close()
        finally:
            await work.client.aclose()
