"""Fixture and remote paths shared by the live surfaces."""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PACKAGE_ROOT / "fixtures"
ODS_FIXTURE = FIXTURES / "ops-hold-log.ods"
CSV_FIXTURE = FIXTURES / "ops-hold-log.csv"

REMOTE_DIR = "/tmp/escapehatch"
REMOTE_ODS = f"{REMOTE_DIR}/ops-hold-log.ods"
REMOTE_CSV = f"{REMOTE_DIR}/ops-hold-log.csv"
REMOTE_JSON = f"{REMOTE_DIR}/normalized.json"
REMOTE_NORMALIZER = f"{REMOTE_DIR}/normalizer.py"
REMOTE_PORTAL = f"{REMOTE_DIR}/portal_server.py"

PORTAL_PORT = 3000
BASE_URL = "https://api.getsolari.com"
