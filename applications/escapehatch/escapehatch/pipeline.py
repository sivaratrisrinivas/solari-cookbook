"""Orchestrate Desktop → Sandbox → Browser without exceeding two live VMs."""

from __future__ import annotations

import json
from pathlib import Path

from .fixture import TICKETS_CSV
from .models import CleanupEvidence, EscapeRun
from .normalize import normalize_csv, sha256_bytes, sha256_text
from .ods import build_ods
from .report import write_report

DRY_RUN_STEPS = (
    (
        "desktop",
        "Create a default-template desktop with record=true. "
        "Verify LibreOffice with command -v. Open the night-shift ODS in Calc. "
        "Save As CSV through the GUI. Screenshot. Destroy the desktop before anything else starts.",
    ),
    (
        "sandbox",
        "Create one sandbox. Write the extracted CSV. Run the strict normalizer. "
        "Start the Northline closeout portal and publish it on a preview URL.",
    ),
    (
        "browser",
        "Launch a cloud browser while the portal sandbox is still up (two sessions). "
        "Upload the normalized JSON. Read the receipt id. GET /receipts/:id and /seen?token=. "
        "Then destroy the browser and the sandbox.",
    ),
)


def plan_dry_run(evidence_dir: Path) -> EscapeRun:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    screens = evidence_dir / "screens"
    screens.mkdir(parents=True, exist_ok=True)
    run = EscapeRun.create(str(evidence_dir), mode="dry-run")
    run.metadata["surfaces"] = ["desktop", "sandbox", "browser"]
    run.metadata["concurrency"] = {
        "cap": 2,
        "phases": [
            "desktop only, then destroy",
            "sandbox normalize + portal",
            "browser concurrent with portal sandbox, then destroy all",
        ],
    }
    for surface, detail in DRY_RUN_STEPS:
        run.note(surface, detail, ran=False)

    ods = build_ods(TICKETS_CSV)
    (evidence_dir / "night-shift-tickets.ods").write_bytes(ods)
    extract_path = evidence_dir / "extract.csv"
    extract_path.write_text(TICKETS_CSV, encoding="utf-8")
    document = normalize_csv(TICKETS_CSV, source="night-shift-tickets.ods")
    normalized_path = evidence_dir / "normalized.json"
    normalized_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    run.extract_path = str(extract_path)
    run.extract_sha256 = sha256_text(TICKETS_CSV)
    run.normalized_json_path = str(normalized_path)
    run.normalized_sha256 = sha256_bytes(normalized_path.read_bytes())
    run.metadata["local_normalize"] = {
        "reason": "dry-run ran the pure normalizer on the fixture CSV; Solari was not called",
        "counts": document["counts"],
        "digest": document["digest"],
    }
    run.cleanup = CleanupEvidence(
        attempted=False,
        succeeded=True,
        detail="dry-run created no Solari sessions",
    )
    write_report(run, evidence_dir)
    return run


async def run_live(
    evidence_dir: Path,
    *,
    api_key: str,
    base_url: str,
    desktop_template: str,
) -> EscapeRun:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "screens").mkdir(parents=True, exist_ok=True)
    from .browser import file_batch
    from .desktop import extract_tickets
    from .sandbox_phase import SandboxWork, destroy_sandbox, start_normalizer_and_portal

    run = EscapeRun.create(str(evidence_dir), mode="live")
    run.metadata["desktop_template"] = desktop_template
    run.metadata["surfaces"] = ["desktop", "sandbox", "browser"]
    work: SandboxWork | None = None
    cleanup_errors: list[str] = []

    try:
        run.advance("desktop_running")
        run.note("desktop", "one live desktop; sandbox and browser are not started yet")
        extract = await extract_tickets(
            api_key=api_key,
            base_url=base_url,
            evidence_dir=evidence_dir,
            template=desktop_template,
        )
        extract_path = evidence_dir / "extract.csv"
        extract_path.write_bytes(extract.csv_bytes)
        run.desktop_session_id = extract.session_id
        run.extract_path = str(extract_path)
        run.extract_sha256 = extract.sha256
        run.recording_url = extract.recording_url
        run.metadata["desktop_screens"] = extract.screens
        run.advance("extracted")
        run.note("desktop", "desktop destroyed after extract; concurrency slot freed")

        run.advance("normalizing")
        work = await start_normalizer_and_portal(
            api_key=api_key,
            base_url=base_url,
            extract_bytes=extract.csv_bytes,
            evidence_dir=evidence_dir,
        )
        run.normalized_json_path = str(evidence_dir / "normalized.json")
        run.normalized_sha256 = work.sha256
        run.metadata["normalize_counts"] = work.document.get("counts")
        run.metadata["normalize_digest"] = work.document.get("digest")
        run.advance("normalized")

        run.portal_url = work.portal_url
        run.advance("portal_up")
        run.note("sandbox", "portal is public on preview.getsolari.com")

        run.advance("filing")
        filing = await file_batch(
            api_key=api_key,
            portal_url=work.portal_url,
            document=work.document,
            evidence_dir=evidence_dir,
        )
        run.browser_session_id = filing.session_id
        run.portal_receipt = filing.receipt_id
        run.metadata["browser_screens"] = filing.screens
        run.advance("filed")
    except Exception as exc:
        run.fail(f"{type(exc).__name__}: {exc}")
    finally:
        try:
            await destroy_sandbox(work)
        except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
            cleanup_errors.append(f"sandbox: {type(exc).__name__}: {exc}")
        destroyed = not cleanup_errors
        if run.status == "filed" and destroyed:
            run.advance("cleaned")
            detail = "destroyed desktop after extract; destroyed portal sandbox after filing"
        elif run.status == "filed":
            detail = "; ".join(cleanup_errors)
        elif destroyed:
            detail = "sessions destroyed after failure"
        else:
            detail = "; ".join(cleanup_errors) or "cleanup ran"
        run.cleanup = CleanupEvidence(
            attempted=True,
            succeeded=destroyed,
            detail=detail,
        )
        write_report(run, evidence_dir)
    return run
