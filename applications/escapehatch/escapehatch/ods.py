"""Build the fixture .ods — a real OpenDocument spreadsheet, not a renamed CSV."""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

# Title + shift banner, then a header, then the messy nightly hold log.
# Dates and statuses are deliberately inconsistent — that is the point of
# the normalizer.
SHEET_ROWS: tuple[tuple[str, ...], ...] = (
    ("Pinetree Cold Chain — Nightly Hold Log",),
    ("Shift date: 2026-09-08", "Shift: Night", "Facility: SEA-01"),
    (),
    (
        "Site ID",
        "Batch",
        "Operator",
        "Produced (local)",
        "Qty",
        "UOM",
        "Status",
        "Exception",
        "Notes",
    ),
    (
        "PINE-SEA-01",
        "B-2026-0908-014",
        "M. Chen",
        "2026-09-08 06:12",
        "48",
        "pallet",
        "HOLD",
        "TEMP-EXCURSION",
        "Dock 3 probe 2.1C",
    ),
    (
        "PINE-PDX-04",
        "B-2026-0908-021",
        "A. Rahman",
        "9/8/2026 5:40 AM",
        "12",
        "tote",
        "hold",
        "",
        "Cycle count pending",
    ),
    (
        "PINE-SEA-01",
        "B-2026-0907-198",
        "M. Chen",
        "2026-09-07T22:15:00-07:00",
        "6",
        "pallet",
        "Released",
        "",
        "Cleared after reinspect",
    ),
    (
        "PINE-SFO-02",
        "B-2026-0908-003",
        "J. Ortiz",
        "07 Sep 2026 23:04",
        "1",
        "tote",
        "DISCARD",
        "SEAL-BROKEN",
        "Inbound seal mismatch",
    ),
    (
        "PINE-PDX-04",
        "B-2026-0908-030",
        "",
        "2026-09-08 07:01",
        "24",
        "case",
        "pending",
        "LABEL-MISMATCH",
        "Reprint requested",
    ),
)


def _cell(value: str) -> str:
    return (
        '<table:table-cell office:value-type="string">'
        f"<text:p>{escape(value)}</text:p>"
        "</table:table-cell>"
    )


def _row(values: tuple[str, ...]) -> str:
    if not values:
        return "<table:table-row/>"
    cells = "".join(_cell(value) for value in values)
    return f"<table:table-row>{cells}</table:table-row>"


def content_xml() -> bytes:
    rows = "".join(_row(row) for row in SHEET_ROWS)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  office:version="1.2">
  <office:body>
    <office:spreadsheet>
      <table:table table:name="Hold Log">{rows}</table:table>
    </office:spreadsheet>
  </office:body>
</office:document-content>
"""
    return xml.encode("utf-8")


def styles_xml() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'office:version="1.2"/>'
    ).encode("utf-8")


def meta_xml() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'office:version="1.2"><office:meta/></office:document-meta>'
    ).encode("utf-8")


def manifest_xml() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
  <manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/>
  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>
</manifest:manifest>
"""


def write_ods(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/manifest.xml", manifest_xml())
        archive.writestr("content.xml", content_xml())
        archive.writestr("styles.xml", styles_xml())
        archive.writestr("meta.xml", meta_xml())
    return path


def expected_csv() -> str:
    """What LibreOffice Calc emits for SHEET_ROWS when saved as Text CSV."""
    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for row in SHEET_ROWS:
        writer.writerow(row)
    return buf.getvalue()
