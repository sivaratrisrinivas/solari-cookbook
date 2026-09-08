"""Build a minimal ODS workbook LibreOffice Calc can open."""

from __future__ import annotations

import csv
import io
import zipfile
from xml.sax.saxutils import escape

MIMETYPE = "application/vnd.oasis.opendocument.spreadsheet"

MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
  <manifest:file-entry manifest:full-path="/" manifest:version="1.2" manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/>
  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
</manifest:manifest>
"""


def _cell_xml(value: str, header: str) -> str:
    text = escape(value)
    if header in {"line", "qty"}:
        try:
            number = float(value)
        except ValueError:
            pass
        else:
            return (
                f'<table:table-cell office:value-type="float" '
                f'office:value="{number}"><text:p>{text}</text:p></table:table-cell>'
            )
    return (
        f'<table:table-cell office:value-type="string">'
        f"<text:p>{text}</text:p></table:table-cell>"
    )


def _content_xml(csv_text: str) -> str:
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    if reader.fieldnames is None:
        raise ValueError("CSV has no header")
    headers = [name.strip() for name in reader.fieldnames]
    rows = [headers]
    for raw in reader:
        rows.append([(raw.get(name) or "").strip() for name in headers])

    table_rows: list[str] = []
    for row in rows:
        cells = "".join(
            _cell_xml(value, headers[index] if index < len(headers) else "")
            for index, value in enumerate(row)
        )
        table_rows.append(f"<table:table-row>{cells}</table:table-row>")

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2">'
        "<office:body><office:spreadsheet>"
        '<table:table table:name="Tickets">'
        + "".join(table_rows)
        + "</table:table></office:spreadsheet></office:body></office:document-content>"
    )


def build_ods(csv_text: str) -> bytes:
    content = _content_xml(csv_text)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", MIMETYPE, compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/manifest.xml", MANIFEST)
        archive.writestr("content.xml", content)
    return buffer.getvalue()
