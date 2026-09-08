"""Strict night-shift ticket normalizer. Pure function. No Solari."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

SCHEMA = "escapehatch.tickets.v1"
REQUIRED_COLUMNS = (
    "ticket_id",
    "line",
    "sku",
    "lot",
    "qty",
    "unit",
    "status",
    "operator",
    "closed_at",
)

TICKET_RE = re.compile(r"^TKT-\d{6}$")
SKU_RE = re.compile(r"^SKU-[A-Z0-9]{4,8}$")
LOT_RE = re.compile(r"^LOT-[A-Z0-9]{4,8}$")
OPERATOR_RE = re.compile(r"^[a-z]\.[a-z]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UNITS = frozenset({"kg", "ea", "L"})
STATUSES = frozenset({"closed", "hold", "scrap"})
LINE_MIN, LINE_MAX = 1, 24


class NormalizeError(ValueError):
    """The CSV is not a ticket extract we can even begin to validate."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _cell(row: dict[str, str | None], name: str) -> str:
    raw = row.get(name)
    return "" if raw is None else str(raw).strip()


def _qty_value(raw: str) -> int | float:
    qty = Decimal(raw)
    if qty <= 0:
        raise ValueError("qty must be greater than 0")
    if qty > Decimal("1000000"):
        raise ValueError("qty exceeds 1000000")
    if qty.as_tuple().exponent < -3:
        raise ValueError("qty has more than 3 decimal places")
    if qty == qty.to_integral_value():
        return int(qty)
    return float(qty)


def _validate_row(row: dict[str, str | None]) -> dict[str, Any]:
    ticket_id = _cell(row, "ticket_id")
    if not TICKET_RE.fullmatch(ticket_id):
        raise ValueError("ticket_id must match TKT-######")

    line_raw = _cell(row, "line")
    if not line_raw.isdigit() or not (LINE_MIN <= int(line_raw) <= LINE_MAX):
        raise ValueError(f"line must be an integer between {LINE_MIN} and {LINE_MAX}")

    sku = _cell(row, "sku")
    if not SKU_RE.fullmatch(sku):
        raise ValueError("sku must match SKU-[A-Z0-9]{4,8}")

    lot = _cell(row, "lot")
    if not LOT_RE.fullmatch(lot):
        raise ValueError("lot must match LOT-[A-Z0-9]{4,8}")

    try:
        qty = _qty_value(_cell(row, "qty"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(str(exc) if str(exc) else "qty must be a number") from exc

    unit = _cell(row, "unit")
    if unit not in UNITS:
        raise ValueError("unit must be one of kg, ea, L")

    status = _cell(row, "status")
    if status not in STATUSES:
        raise ValueError("status must be one of closed, hold, scrap")

    operator = _cell(row, "operator")
    if not OPERATOR_RE.fullmatch(operator):
        raise ValueError("operator must look like m.chen")

    closed_at = _cell(row, "closed_at")
    if not DATE_RE.fullmatch(closed_at):
        raise ValueError("closed_at must be YYYY-MM-DD")

    return {
        "ticket_id": ticket_id,
        "line": int(line_raw),
        "sku": sku,
        "lot": lot,
        "qty": qty,
        "unit": unit,
        "status": status,
        "operator": operator,
        "closed_at": closed_at,
    }


def _reader(text: str) -> csv.DictReader:
    sample = text.lstrip("\ufeff")
    if not sample.strip():
        raise NormalizeError("CSV is empty")
    try:
        dialect = csv.Sniffer().sniff(sample[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return csv.DictReader(io.StringIO(sample), dialect=dialect)


def normalize_csv(text: str, *, source: str = "extract.csv") -> dict[str, Any]:
    """Validate columns and types. Keep good rows. Reject bad ones with reasons."""
    reader = _reader(text)
    if reader.fieldnames is None:
        raise NormalizeError("CSV has no header")

    columns = [name.strip() for name in reader.fieldnames if name]
    missing = [name for name in REQUIRED_COLUMNS if name not in columns]
    extra = [name for name in columns if name not in REQUIRED_COLUMNS]
    if missing:
        raise NormalizeError(f"missing columns: {', '.join(missing)}")
    if extra:
        raise NormalizeError(f"unexpected columns: {', '.join(extra)}")

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, raw in enumerate(reader, start=2):
        if raw is None or all(not (value or "").strip() for value in raw.values()):
            continue
        try:
            accepted.append(_validate_row(raw))
        except ValueError as exc:
            rejected.append(
                {
                    "row": index,
                    "reason": str(exc),
                    "ticket_id": _cell(raw, "ticket_id") or None,
                }
            )

    payload = {"accepted": accepted, "rejected": rejected, "schema": SCHEMA}
    digest = sha256_text(canonical_json(payload))
    return {
        "schema": SCHEMA,
        "source": source,
        "accepted": accepted,
        "rejected": rejected,
        "counts": {
            "accepted": len(accepted),
            "rejected": len(rejected),
            "input_rows": len(accepted) + len(rejected),
        },
        "digest": digest,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Normalize a ticket CSV.")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("json_path", type=Path)
    args = parser.parse_args(argv)
    document = normalize_csv(
        args.csv_path.read_text(encoding="utf-8"),
        source=args.csv_path.name,
    )
    args.json_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(document["digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
