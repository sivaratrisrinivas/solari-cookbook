"""EscapeRun domain model: one pipeline, one typed status machine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

RunMode = Literal["dry-run", "live"]

Status = Literal[
    "created",
    "desktop_running",
    "extracted",
    "normalizing",
    "normalized",
    "portal_up",
    "filing",
    "filed",
    "cleaned",
    "failed",
]

TRANSITIONS: dict[Status, frozenset[Status]] = {
    "created": frozenset({"desktop_running", "failed"}),
    "desktop_running": frozenset({"extracted", "failed"}),
    "extracted": frozenset({"normalizing", "failed"}),
    "normalizing": frozenset({"normalized", "failed"}),
    "normalized": frozenset({"portal_up", "failed"}),
    "portal_up": frozenset({"filing", "failed"}),
    "filing": frozenset({"filed", "failed"}),
    "filed": frozenset({"cleaned", "failed"}),
    "cleaned": frozenset(),
    "failed": frozenset(),
}


class IllegalTransition(ValueError):
    """Raised when a status change is not in the machine."""


@dataclass
class CleanupEvidence:
    attempted: bool
    succeeded: bool
    detail: str


@dataclass
class EscapeRun:
    """One extract → normalize → file attempt across three Solari surfaces."""

    id: str
    status: Status
    mode: RunMode
    created_at: str
    evidence_dir: str
    desktop_session_id: str | None = None
    extract_path: str | None = None
    extract_sha256: str | None = None
    normalized_json_path: str | None = None
    normalized_sha256: str | None = None
    portal_url: str | None = None
    portal_receipt: str | None = None
    browser_session_id: str | None = None
    recording_url: str | None = None
    error: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    cleanup: CleanupEvidence | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, evidence_dir: str, *, mode: RunMode) -> EscapeRun:
        return cls(
            id=f"eh_{uuid4().hex[:12]}",
            status="created",
            mode=mode,
            created_at=datetime.now(timezone.utc).isoformat(),
            evidence_dir=evidence_dir,
        )

    def advance(self, status: Status) -> None:
        allowed = TRANSITIONS[self.status]
        if status not in allowed:
            raise IllegalTransition(f"{self.status} -> {status} is not allowed")
        self.status = status

    def fail(self, message: str) -> None:
        if self.status != "failed":
            if "failed" not in TRANSITIONS[self.status]:
                raise IllegalTransition(f"{self.status} cannot fail")
            self.status = "failed"
        self.error = message

    def note(self, phase: str, detail: str, **extra: Any) -> None:
        entry = {"phase": phase, "detail": detail, **extra}
        self.steps.append(entry)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
