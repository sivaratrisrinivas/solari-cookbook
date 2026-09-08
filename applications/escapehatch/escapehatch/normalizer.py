"""Pure CSV → hold-log JSON normalizer. Stdlib only so it also runs in a sandbox."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "escapehatch.hold-log.v1"
SOURCE = "ops-hold-workbook"

SITE_RE = re.compile(r"^PINE-[A-Z]{3}-\d{2}$")
BATCH_RE = re.compile(r"^B-\d{4}-\d{4}-\d{3}$")

STATUS_ALIASES = {
    "hold": "hold",
    "on hold": "hold",
    "released": "released",
    "release": "released",
    "cleared": "released",
    "discard": "discarded",
    "discarded": "discarded",
    "pending": "pending",
}

UNIT_ALIASES = {
    "pallet": "pallet",
    "pallets": "pallet",
    "tote": "tote",
    "totes": "tote",
    "case": "case",
    "cases": "case",
}

HEADER_ALIASES = {
    "site": "siteId",
    "site id": "siteId",
    "siteid": "siteId",
    "batch": "batchId",
    "batch id": "batchId",
    "batchid": "batchId",
    "operator": "operator",
    "produced": "producedAt",
    "produced (local)": "producedAt",
    "produced at": "producedAt",
    "qty": "quantity",
    "quantity": "quantity",
    "uom": "unit",
    "unit": "unit",
    "status": "status",
    "exception": "exceptionCode",
    "exception code": "exceptionCode",
    "notes": "notes",
    "note": "notes",
}

DATE_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %H:%M",
    "%d %b %Y %H:%M",
    "%d %B %Y %H:%M",
)


class NormalizeError(ValueError):
    """The extract does not satisfy the hold-log schema."""


def decode_csv_text(raw: bytes | str) -> str:
    """LibreOffice CSV on this desktop image is often cp1252 (em dash 0x97)."""
    if isinstance(raw, str):
        return raw
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _norm_header(cell: str) -> str:
    return re.sub(r"\s+", " ", cell.strip().lower())


def _looks_like_header(row: list[str]) -> bool:
    names = {_norm_header(cell) for cell in row if cell.strip()}
    return "batch" in names or "batch id" in names or "batchid" in names


def _map_headers(row: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, cell in enumerate(row):
        alias = HEADER_ALIASES.get(_norm_header(cell))
        if alias:
            mapping[alias] = index
    required = {"siteId", "batchId", "producedAt", "quantity", "unit", "status"}
    missing = sorted(required - set(mapping))
    if missing:
        raise NormalizeError(f"header missing columns: {', '.join(missing)}")
    return mapping


def _cell(row: list[str], mapping: dict[str, int], key: str) -> str:
    index = mapping.get(key)
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _parse_status(raw: str) -> str:
    key = re.sub(r"\s+", " ", raw.strip().lower())
    try:
        return STATUS_ALIASES[key]
    except KeyError as exc:
        raise NormalizeError(f"unknown status {raw!r}") from exc


def _parse_unit(raw: str) -> str:
    key = raw.strip().lower()
    try:
        return UNIT_ALIASES[key]
    except KeyError as exc:
        raise NormalizeError(f"unknown unit {raw!r}") from exc


def _parse_quantity(raw: str) -> int:
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise NormalizeError(f"quantity is not a number: {raw!r}") from exc
    if value != int(value) or value < 0:
        raise NormalizeError(f"quantity must be a non-negative integer: {raw!r}")
    return int(value)


def _parse_when(raw: str) -> str:
    text = raw.strip()
    if not text:
        raise NormalizeError("producedAt is empty")
    if text.endswith("Z") and "T" in text:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except ValueError:
        pass
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except ValueError:
            continue
    raise NormalizeError(f"cannot parse producedAt {raw!r}")


def _parse_exception(raw: str) -> str | None:
    code = raw.strip().upper()
    return code or None


def _shift_date(rows: Iterable[list[str]]) -> str | None:
    for row in rows:
        for cell in row:
            match = re.search(r"Shift date:\s*(\d{4}-\d{2}-\d{2})", cell)
            if match:
                return match.group(1)
    return None


def _canonical_row(row: list[str], mapping: dict[str, int]) -> dict[str, Any] | None:
    if not any(cell.strip() for cell in row):
        return None
    batch = _cell(row, mapping, "batchId")
    if not batch:
        return None
    if _looks_like_header(row):
        return None
    site = _cell(row, mapping, "siteId")
    if not SITE_RE.match(site):
        raise NormalizeError(f"invalid siteId {site!r}")
    if not BATCH_RE.match(batch):
        raise NormalizeError(f"invalid batchId {batch!r}")
    operator = _cell(row, mapping, "operator") or "unassigned"
    return {
        "siteId": site,
        "batchId": batch,
        "operator": operator,
        "producedAt": _parse_when(_cell(row, mapping, "producedAt")),
        "quantity": _parse_quantity(_cell(row, mapping, "quantity")),
        "unit": _parse_unit(_cell(row, mapping, "unit")),
        "status": _parse_status(_cell(row, mapping, "status")),
        "exceptionCode": _parse_exception(_cell(row, mapping, "exceptionCode")),
        "notes": _cell(row, mapping, "notes"),
    }


def parse_csv(text: str) -> list[list[str]]:
    sample = text.lstrip("\ufeff")
    reader = csv.reader(io.StringIO(sample))
    return [list(row) for row in reader]


def digest_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_csv(text: str) -> dict[str, Any]:
    rows = parse_csv(text)
    if not rows:
        raise NormalizeError("extract is empty")

    header_index = next((i for i, row in enumerate(rows) if _looks_like_header(row)), None)
    if header_index is None:
        raise NormalizeError("no header row with a Batch column")
    mapping = _map_headers(rows[header_index])

    records: list[dict[str, Any]] = []
    for row in rows[header_index + 1 :]:
        parsed = _canonical_row(row, mapping)
        if parsed is not None:
            records.append(parsed)
    if not records:
        raise NormalizeError("header found but no data rows")

    body = {
        "schema": SCHEMA,
        "source": SOURCE,
        "shiftDate": _shift_date(rows) or records[0]["producedAt"][:10],
        "rowCount": len(records),
        "rows": records,
    }
    return {**body, "digest": digest_payload(body)}


def normalize_path(csv_path: Path, json_path: Path) -> dict[str, Any]:
    text = decode_csv_text(csv_path.read_bytes())
    payload = normalize_csv(text)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize a hold-log CSV to strict JSON.")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("json_path", type=Path)
    args = parser.parse_args(argv)
    payload = normalize_path(args.csv_path, args.json_path)
    print(payload["digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
