"""EscapeHatch command line."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from .pipeline import plan_dry_run, run_live

BASE_URL = "https://api.getsolari.com"
DEFAULT_EVIDENCE = Path(__file__).resolve().parents[1] / "evidence"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="escapehatch",
        description=(
            "Extract night-shift tickets from LibreOffice Calc, normalize them "
            "in a sandbox, and file a receipt in a hosted closeout portal."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="explain the three-surface plan and run the local normalizer; no Solari calls",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument(
        "--desktop-template",
        default="default",
        help="Solari desktop template. default ships LibreOffice; office is a thicker image",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".env",
        help="read SOLARI_API_KEY from here only when the environment does not have it",
    )
    return parser


def load_key(env_file: Path) -> str:
    existing = os.environ.get("SOLARI_API_KEY", "").strip()
    if existing:
        return existing
    if env_file.exists():
        for raw_line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == "SOLARI_API_KEY":
                key = value.strip().strip('"').strip("'")
                if key:
                    return key
    raise SystemExit(
        f"SOLARI_API_KEY is not set and was not found in {env_file}. "
        "Copy .env.example to .env. Do not pass the key on the command line."
    )


def print_run(run) -> None:
    print(f"run      : {run.id}")
    print(f"mode     : {run.mode}")
    print(f"status   : {run.status}")
    if run.extract_sha256:
        print(f"extract  : {run.extract_sha256}")
    if run.normalized_sha256:
        print(f"normalized: {run.normalized_sha256}")
    if run.portal_receipt:
        print(f"receipt  : {run.portal_receipt}")
    if run.recording_url:
        print(f"recording: {run.recording_url}")
    if run.error:
        print(f"error    : {run.error}")
    if run.cleanup:
        print(f"cleanup  : {run.cleanup.detail}")
    print(f"evidence : {Path(run.evidence_dir) / 'run.json'}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.dry_run:
        run = plan_dry_run(args.output)
        print("EscapeHatch dry-run. No Solari sessions were created.")
        print()
        for step in run.steps:
            print(f"[{step['phase']}] {step['detail']}")
        print()
        local = run.metadata.get("local_normalize") or {}
        counts = local.get("counts") or {}
        print(
            f"local normalizer: accepted={counts.get('accepted')} "
            f"rejected={counts.get('rejected')} digest={local.get('digest')}"
        )
        print_run(run)
        return 0

    run = asyncio.run(
        run_live(
            args.output,
            api_key=load_key(args.env_file),
            base_url=args.base_url,
            desktop_template=args.desktop_template,
        )
    )
    print_run(run)
    ok = run.status == "cleaned" and run.cleanup is not None and run.cleanup.succeeded
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
