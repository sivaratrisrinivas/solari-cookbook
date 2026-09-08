"""EscapeRun domain model — a status state machine, not a pile of booleans."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

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

TERMINAL: frozenset[Status] = frozenset({"cleaned", "failed"})

# Happy path plus a jump to failed from any in-flight status.
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

SCHEMA_VERSION = "escapehatch.run.v1"


class InvalidTransition(ValueError):
    """Raised when an EscapeRun is asked to skip or rewind a status."""


def new_run_id() -> str:
    return f"eh_{uuid4().hex[:16]}"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class EscapeRun:
    id: str
    status: Status
    evidenceDir: str
    desktopSessionId: str | None = None
    extractPath: str | None = None
    extractSha256: str | None = None
    normalizedJsonPath: str | None = None
    normalizedSha256: str | None = None
    portalUrl: str | None = None
    portalReceipt: str | None = None
    browserSessionId: str | None = None
    recordingUrl: str | None = None
    error: str | None = None
    mode: Literal["dry-run", "live"] = "dry-run"
    createdAt: str = field(default_factory=utc_now)
    schemaVersion: str = SCHEMA_VERSION
    screenshots: list[str] = field(default_factory=list)
    cleanup: dict[str, Any] = field(
        default_factory=lambda: {
            "attempted": False,
            "succeeded": False,
            "detail": "",
        }
    )
    sandboxId: str | None = None

    def advance(self, next_status: Status, *, error: str | None = None) -> None:
        allowed = TRANSITIONS[self.status]
        if next_status not in allowed:
            raise InvalidTransition(
                f"cannot move EscapeRun {self.id} from {self.status!r} to {next_status!r}"
            )
        self.status = next_status
        if error:
            self.error = error

    def fail(self, error: str) -> None:
        if self.status in TERMINAL:
            self.error = error
            return
        self.advance("failed", error=error)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_run(evidence_dir: str, *, mode: Literal["dry-run", "live"]) -> EscapeRun:
    return EscapeRun(
        id=new_run_id(),
        status="created",
        evidenceDir=evidence_dir,
        mode=mode,
    )
