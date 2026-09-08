import json
import unittest
from pathlib import Path

from escapehatch.normalizer import (
    NormalizeError,
    decode_csv_text,
    digest_payload,
    normalize_csv,
)
from escapehatch.ods import expected_csv
from escapehatch.paths import CSV_FIXTURE

FIXTURE_CSV = CSV_FIXTURE.read_text(encoding="utf-8") if CSV_FIXTURE.exists() else expected_csv()


class NormalizerTests(unittest.TestCase):
    def test_fixture_csv_normalizes_to_five_rows(self) -> None:
        payload = normalize_csv(FIXTURE_CSV)
        self.assertEqual(payload["schema"], "escapehatch.hold-log.v1")
        self.assertEqual(payload["source"], "ops-hold-workbook")
        self.assertEqual(payload["shiftDate"], "2026-09-08")
        self.assertEqual(payload["rowCount"], 5)
        self.assertEqual(len(payload["rows"]), 5)
        self.assertEqual(len(payload["digest"]), 64)

    def test_statuses_and_units_are_canonical(self) -> None:
        rows = {row["batchId"]: row for row in normalize_csv(FIXTURE_CSV)["rows"]}
        self.assertEqual(rows["B-2026-0908-014"]["status"], "hold")
        self.assertEqual(rows["B-2026-0908-021"]["status"], "hold")
        self.assertEqual(rows["B-2026-0907-198"]["status"], "released")
        self.assertEqual(rows["B-2026-0908-003"]["status"], "discarded")
        self.assertEqual(rows["B-2026-0908-030"]["status"], "pending")
        self.assertEqual(rows["B-2026-0908-014"]["unit"], "pallet")
        self.assertEqual(rows["B-2026-0908-030"]["unit"], "case")

    def test_empty_operator_becomes_unassigned(self) -> None:
        row = next(
            row
            for row in normalize_csv(FIXTURE_CSV)["rows"]
            if row["batchId"] == "B-2026-0908-030"
        )
        self.assertEqual(row["operator"], "unassigned")

    def test_offset_timestamp_is_utc(self) -> None:
        row = next(
            row
            for row in normalize_csv(FIXTURE_CSV)["rows"]
            if row["batchId"] == "B-2026-0907-198"
        )
        self.assertEqual(row["producedAt"], "2026-09-08T05:15:00Z")

    def test_exception_codes_uppercased_or_null(self) -> None:
        rows = {row["batchId"]: row for row in normalize_csv(FIXTURE_CSV)["rows"]}
        self.assertEqual(rows["B-2026-0908-014"]["exceptionCode"], "TEMP-EXCURSION")
        self.assertIsNone(rows["B-2026-0908-021"]["exceptionCode"])

    def test_digest_covers_body_not_itself(self) -> None:
        payload = normalize_csv(FIXTURE_CSV)
        body = {key: value for key, value in payload.items() if key != "digest"}
        self.assertEqual(payload["digest"], digest_payload(body))
        again = normalize_csv(FIXTURE_CSV)
        self.assertEqual(payload["digest"], again["digest"])

    def test_title_rows_are_not_data(self) -> None:
        batches = [row["batchId"] for row in normalize_csv(FIXTURE_CSV)["rows"] ]
        self.assertTrue(all(batch.startswith("B-") for batch in batches))
        self.assertNotIn("Pinetree Cold Chain — Nightly Hold Log", json.dumps(batches))

    def test_missing_header_is_an_error(self) -> None:
        with self.assertRaises(NormalizeError):
            normalize_csv("hello,world\n1,2\n")

    def test_unknown_status_is_an_error(self) -> None:
        csv = (
            "Site ID,Batch,Operator,Produced (local),Qty,UOM,Status,Exception,Notes\n"
            "PINE-SEA-01,B-2026-0908-014,M. Chen,2026-09-08 06:12,48,pallet,MAYBE,,\n"
        )
        with self.assertRaises(NormalizeError):
            normalize_csv(csv)

    def test_bad_site_id_is_an_error(self) -> None:
        csv = (
            "Site ID,Batch,Operator,Produced (local),Qty,UOM,Status,Exception,Notes\n"
            "SEA-01,B-2026-0908-014,M. Chen,2026-09-08 06:12,48,pallet,HOLD,,\n"
        )
        with self.assertRaises(NormalizeError):
            normalize_csv(csv)

    def test_expected_csv_matches_committed_fixture(self) -> None:
        if CSV_FIXTURE.exists():
            self.assertEqual(CSV_FIXTURE.read_text(encoding="utf-8"), expected_csv())

    def test_cp1252_em_dash_from_libreoffice(self) -> None:
        raw = expected_csv().replace("—", chr(0x97)).encode("latin-1")
        self.assertIn(0x97, raw)
        with self.assertRaises(UnicodeDecodeError):
            raw.decode("utf-8")
        payload = normalize_csv(decode_csv_text(raw))
        self.assertEqual(payload["rowCount"], 5)


if __name__ == "__main__":
    unittest.main()
