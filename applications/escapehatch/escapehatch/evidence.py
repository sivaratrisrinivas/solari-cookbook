"""Write evidence/run.json and keep screenshots next to it."""

from __future__ import annotations

import json
from pathlib import Path

from .models import EscapeRun
from .redact import redact_run

# 1x1 PNG — used only when a dry-run has no real screen to capture.
PLACEHOLDER_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def write_run(run: EscapeRun, evidence_dir: Path) -> Path:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / "run.json"
    path.write_text(
        json.dumps(redact_run(run.to_dict()), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def screens_dir(evidence_dir: Path) -> Path:
    path = evidence_dir / "screens"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()
