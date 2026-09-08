"""EscapeHatch CLI — `--dry-run` never calls Solari; live mode needs SOLARI_API_KEY."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from .paths import BASE_URL, PACKAGE_ROOT
from .pipeline import run_pipeline

DEFAULT_EVIDENCE = PACKAGE_ROOT / "evidence"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="escapehatch",
        description=(
            "Extract a nightly hold log from LibreOffice Calc, normalize it in a "
            "sandbox, and file it through a hosted portal."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run the state machine on fixtures; no Solari API calls",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_EVIDENCE,
        help="evidence directory (default: ./evidence)",
    )
    parser.add_argument(
        "--base-url",
        default=BASE_URL,
        help=f"Solari API base URL (default: {BASE_URL})",
    )
    parser.add_argument(
        "--record",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="record the desktop session (live only; default: on)",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=PACKAGE_ROOT / ".env",
        help="local env file used only when SOLARI_API_KEY is absent",
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
                return value.strip().strip('"').strip("'")
    raise SystemExit(
        f"SOLARI_API_KEY is not set and was not found in {env_file}. "
        "Do not pass the key on the command line."
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.dry_run:
        run = asyncio.run(
            run_pipeline(
                args.output,
                mode="dry-run",
                base_url=args.base_url,
                record=False,
            )
        )
    else:
        run = asyncio.run(
            run_pipeline(
                args.output,
                mode="live",
                api_key=load_key(args.env_file),
                base_url=args.base_url,
                record=args.record,
            )
        )
    print(f"run      : {run.id}")
    print(f"status   : {run.status}")
    print(f"mode     : {run.mode}")
    print(f"receipt  : {run.portalReceipt or '—'}")
    print(f"evidence : {args.output / 'run.json'}")
    if run.error:
        print(f"error    : {run.error}")
    return 0 if run.status == "cleaned" else 1
