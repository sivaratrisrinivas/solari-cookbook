"""Strip secrets before anything lands in evidence/run.json."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

# Live keys look like slr_live_…; scrub any slr_ prefix we see.
_KEY = re.compile(r"slr_[a-z]+_[A-Za-z0-9._\-]+")
# Presigned query strings carry AWS signatures; keep the path, drop the query.
_SIG_QUERY = re.compile(
    r"([?&])(X-Amz-[^=]+|Signature|token|pt_token)=[^&]*",
    re.IGNORECASE,
)


def redact_text(value: str) -> str:
    cleaned = _KEY.sub("slr_***", value)
    cleaned = _SIG_QUERY.sub(lambda m: f"{m.group(1)}{m.group(2)}=***", cleaned)
    return cleaned


def redact_url(value: str | None) -> str | None:
    if not value:
        return value
    parts = urlsplit(value)
    if not parts.query:
        return redact_text(value)
    return redact_text(urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")))


def redact_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= 18:
        return value
    return f"{value[:8]}…{value[-6:]}"


def redact_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy safe to write: keys gone, session ids shortened, URLs stripped."""
    out = dict(payload)
    for key in ("desktopSessionId", "browserSessionId", "sandboxId"):
        if out.get(key):
            out[key] = redact_identifier(str(out[key]))
    if out.get("recordingUrl"):
        out["recordingUrl"] = redact_url(str(out["recordingUrl"]))
    if out.get("portalUrl"):
        out["portalUrl"] = redact_url(str(out["portalUrl"]))
    if out.get("error"):
        out["error"] = redact_text(str(out["error"]))
    cleanup = out.get("cleanup")
    if isinstance(cleanup, dict) and cleanup.get("detail"):
        cleanup = dict(cleanup)
        cleanup["detail"] = redact_text(str(cleanup["detail"]))
        out["cleanup"] = cleanup
    return out
