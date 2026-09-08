"""Controlled intake portal. Hosted in a Solari sandbox (live) or locally (dry-run)."""

from __future__ import annotations

import argparse
import json
import re
import secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

PORT = 3000
RECEIPTS: dict[str, dict[str, Any]] = {}

FORM = """<!doctype html>
<meta charset="utf-8">
<title>Pinetree Hold Intake</title>
<style>
  body { font: 16px/1.45 system-ui, sans-serif; max-width: 40rem; margin: 3rem auto; color: #17202c; }
  h1 { font-size: 1.4rem; }
  form { display: grid; gap: 0.8rem; padding: 1.2rem; border: 1px solid #d5d0c7; border-radius: 8px; }
  button { width: max-content; padding: 0.45rem 0.9rem; }
  code { background: #f4f0e8; padding: 0.1rem 0.35rem; }
</style>
<h1>Pinetree Hold Intake</h1>
<p>File a normalized nightly hold extract. The portal stores the artifact and
returns a receipt — a thank-you page is not proof of delivery.</p>
<form method="post" action="/file" enctype="multipart/form-data">
  <label>Normalized JSON <input type="file" name="artifact" accept="application/json" required></label>
  <button type="submit">File extract</button>
</form>
"""


def _utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def store_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    digest = payload.get("digest")
    rows = payload.get("rows")
    schema = payload.get("schema")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("artifact is missing a 64-character digest")
    if schema != "escapehatch.hold-log.v1":
        raise ValueError("artifact schema is not escapehatch.hold-log.v1")
    if not isinstance(rows, list) or not rows:
        raise ValueError("artifact has no rows")
    receipt_id = f"rcpt_{secrets.token_hex(8)}"
    record = {
        "id": receipt_id,
        "digest": digest,
        "rowCount": len(rows),
        "shiftDate": payload.get("shiftDate"),
        "receivedAt": _utc(),
    }
    RECEIPTS[receipt_id] = record
    return record


def _receipt_page(record: dict[str, Any]) -> str:
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Filed</title>
<h1>Extract filed</h1>
<p data-receipt="{record["id"]}">Receipt <code>{record["id"]}</code></p>
<p>Digest <code>{record["digest"]}</code></p>
<p>Rows {record["rowCount"]}</p>
"""


def _parse_multipart(content_type: str, body: bytes) -> bytes | None:
    match = re.search(r"boundary=([^;]+)", content_type)
    if not match:
        return None
    boundary = match.group(1).strip().strip('"').encode("ascii")
    marker = b"--" + boundary
    for part in body.split(marker):
        if b"name=\"artifact\"" not in part and b"name=artifact" not in part:
            continue
        header, sep, data = part.partition(b"\r\n\r\n")
        if not sep:
            header, sep, data = part.partition(b"\n\n")
        if not sep:
            continue
        if data.endswith(b"--"):
            data = data[:-2]
        return data.rstrip(b"\r\n")
    return None


class Handler(BaseHTTPRequestHandler):
    def reply(self, body: str, *, status: int = 200, content_type: str = "text/html; charset=utf-8") -> None:
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def reply_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        self.reply(json.dumps(payload), status=status, content_type="application/json")

    def do_GET(self) -> None:
        parts = urlparse(self.path)
        if parts.path == "/seen":
            receipt = (parse_qs(parts.query).get("receipt") or [""])[0]
            self.reply("yes" if receipt in RECEIPTS else "no", content_type="text/plain; charset=utf-8")
            return
        if parts.path.startswith("/receipts/"):
            receipt_id = parts.path.removeprefix("/receipts/").strip("/")
            record = RECEIPTS.get(receipt_id)
            if record is None:
                self.reply_json({"error": "unknown receipt"}, status=404)
                return
            self.reply_json(record)
            return
        if parts.path in {"/", "/file"}:
            self.reply(FORM)
            return
        self.reply("not found", status=404)

    def do_POST(self) -> None:
        parts = urlparse(self.path)
        if parts.path != "/file":
            self.reply("not found", status=404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type") or ""
        raw = _parse_multipart(content_type, body) if "multipart/form-data" in content_type else body
        if not raw:
            self.reply("missing artifact", status=400)
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
            record = store_artifact(payload)
        except (ValueError, json.JSONDecodeError) as exc:
            self.reply(f"rejected: {exc}", status=400)
            return
        self.reply(_receipt_page(record))

    def log_message(self, *_args: object) -> None:
        return


def serve(port: int = PORT) -> None:
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hold-intake portal")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)
    serve(args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
