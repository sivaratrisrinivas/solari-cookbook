"""Northline closeout portal. Uploaded into a Solari sandbox and served there.

This file is self-contained so the guest Python can run it without the package.
"""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

PORT = 8765
RECEIPTS: dict[str, dict] = {}

FORM = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>Northline Closeout</title>
<style>
  body { font-family: ui-sans-serif, system-ui, sans-serif; max-width: 42rem;
         margin: 3rem auto; color: #1a1a1a; background: #f6f4ef; }
  h1 { font-size: 1.35rem; margin-bottom: 0.35rem; }
  .meta { color: #555; font-size: 0.95rem; }
  .card { background: #fff; border: 1px solid #d4cfc4; padding: 1.25rem; }
  label { display: block; margin: 0.85rem 0 0.35rem; font-weight: 600; }
  button { margin-top: 1rem; padding: 0.55rem 1rem; background: #1f3d2b;
           color: #fff; border: 0; cursor: pointer; }
  code, strong { font-family: ui-monospace, monospace; }
</style>
<h1>Northline Metals — Shift Closeout</h1>
<p class="meta">File a schema-checked ticket batch. Untyped screenshots stop here.</p>
<div class="card">
  <form method="post" action="/file" enctype="multipart/form-data">
    <label for="batch">Normalized batch (JSON)</label>
    <input id="batch" name="batch" type="file" accept="application/json,.json" required>
    <button type="submit">File batch</button>
  </form>
</div>
"""


def _receipt_page(receipt: dict) -> str:
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>Northline Closeout</title>
<style>
  body {{ font-family: ui-sans-serif, system-ui, sans-serif; max-width: 42rem;
         margin: 3rem auto; color: #1a1a1a; background: #f6f4ef; }}
  .card {{ background: #fff; border: 1px solid #d4cfc4; padding: 1.25rem; }}
  code, #receipt-id {{ font-family: ui-monospace, monospace; }}
</style>
<h1>Batch accepted</h1>
<div class="card">
  <p>Receipt <strong id="receipt-id">{receipt["id"]}</strong></p>
  <p>Digest <code id="digest">{receipt["digest"]}</code></p>
  <p>Tickets filed: {receipt["accepted"]}</p>
</div>
"""


def _parse_multipart(body: bytes, content_type: str) -> bytes:
    match = re.search(r"boundary=([^;]+)", content_type or "")
    if not match:
        return body
    boundary = match.group(1).strip().strip('"').encode("ascii")
    parts = body.split(b"--" + boundary)
    for part in parts:
        header_blob, sep, payload = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        if b'name="batch"' not in header_blob:
            continue
        return payload.rsplit(b"\r\n", 1)[0]
    raise ValueError("multipart body had no batch file")


class Handler(BaseHTTPRequestHandler):
    def reply(self, body: str, *, status: int = 200, content_type: str = "text/html; charset=utf-8") -> None:
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parts = urlparse(self.path)
        if parts.path == "/seen":
            token = (parse_qs(parts.query).get("token") or [""])[0]
            self.reply("yes" if token in RECEIPTS else "no", content_type="text/plain; charset=utf-8")
            return
        if parts.path.startswith("/receipts/"):
            receipt_id = parts.path.rsplit("/", 1)[-1]
            receipt = RECEIPTS.get(receipt_id)
            if receipt is None:
                self.reply(json.dumps({"ok": False}), status=404, content_type="application/json")
                return
            self.reply(json.dumps(receipt), content_type="application/json")
            return
        self.reply(FORM)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if urlparse(self.path).path != "/file":
            self.reply("not found", status=404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        try:
            raw = _parse_multipart(body, self.headers.get("Content-Type") or "")
            document = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.reply(f"bad batch: {exc}", status=400)
            return
        if document.get("schema") != "escapehatch.tickets.v1":
            self.reply("unknown schema", status=400)
            return
        digest = str(document.get("digest") or "")
        if not digest:
            self.reply("missing digest", status=400)
            return
        accepted = document.get("accepted") or []
        receipt_id = "RCPT-" + digest[:12].upper()
        receipt = {
            "id": receipt_id,
            "digest": digest,
            "accepted": len(accepted),
            "rejected": len(document.get("rejected") or []),
        }
        RECEIPTS[receipt_id] = receipt
        self.reply(_receipt_page(receipt))

    def log_message(self, *_args) -> None:
        return


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
