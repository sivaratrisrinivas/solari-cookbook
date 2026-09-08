"""Canonical evidence writer. Redact secrets. Never copy the API key."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import EscapeRun

SECRET_KEY_RE = re.compile(r"(api[_-]?key|authorization|token|secret|password)", re.I)
SECRET_VALUE_RE = re.compile(r"slr_live_[A-Za-z0-9]+")


def redact_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= 18:
        return value
    return f"{value[:8]}…{value[-6:]}"


def redact_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    query = [
        (key, "redacted")
        if SECRET_KEY_RE.search(key)
        else (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    cleaned = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )
    return SECRET_VALUE_RE.sub("slr_live_redacted", cleaned)


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, inner in value.items():
            if SECRET_KEY_RE.search(str(key)):
                cleaned[key] = "redacted"
            else:
                cleaned[key] = _scrub(inner)
        return cleaned
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, str):
        return SECRET_VALUE_RE.sub("slr_live_redacted", value)
    return value


def public_run(run: EscapeRun) -> dict[str, Any]:
    payload = run.to_dict()
    payload["desktop_session_id"] = redact_identifier(run.desktop_session_id)
    payload["browser_session_id"] = redact_identifier(run.browser_session_id)
    payload["portal_url"] = redact_url(run.portal_url)
    payload["recording_url"] = redact_url(run.recording_url)
    payload["metadata"] = _scrub(run.metadata)
    return _scrub(payload)


def write_report(run: EscapeRun, evidence_dir: Path) -> Path:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / "run.json"
    path.write_text(
        json.dumps(public_run(run), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
