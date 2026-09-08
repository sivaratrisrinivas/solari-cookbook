import json
import unittest
from pathlib import Path

from escapehatch.fixture import TICKETS_CSV, tickets_csv_path
from escapehatch.normalize import NormalizeError, canonical_json, normalize_csv, sha256_text

EXPECTED_DIGEST = "0b92f6f0ed70e3a40b4ea63e6e0dd9d3667320d376740a533146b067136c76a6"


class NormalizeTests(unittest.TestCase):
    def test_fixture_csv_matches_embedded_source(self) -> None:
        on_disk = tickets_csv_path().read_text(encoding="utf-8")
        self.assertEqual(on_disk, TICKETS_CSV)

    def test_fixture_csv_to_expected_json_and_digest(self) -> None:
        document = normalize_csv(TICKETS_CSV, source="night-shift-tickets.ods")
        self.assertEqual(document["schema"], "escapehatch.tickets.v1")
        self.assertEqual(
            [row["ticket_id"] for row in document["accepted"]],
            ["TKT-104221", "TKT-104222", "TKT-104225"],
        )
        self.assertEqual(
            [(row["row"], row["reason"]) for row in document["rejected"]],
            [
                (4, "qty must be greater than 0"),
                (5, "status must be one of closed, hold, scrap"),
                (7, "line must be an integer between 1 and 24"),
            ],
        )
        self.assertEqual(document["accepted"][0]["qty"], 12.5)
        self.assertEqual(document["accepted"][1]["qty"], 40)
        self.assertEqual(document["accepted"][2]["status"], "hold")
        self.assertEqual(document["counts"], {"accepted": 3, "rejected": 3, "input_rows": 6})
        payload = {
            "accepted": document["accepted"],
            "rejected": document["rejected"],
            "schema": document["schema"],
        }
        digest = sha256_text(canonical_json(payload))
        self.assertEqual(document["digest"], digest)
        expected = json.loads(
            Path(__file__).resolve().parents[1].joinpath("fixtures", "expected-normalized.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(document, expected)
        self.assertEqual(document["digest"], EXPECTED_DIGEST)

    def test_missing_column_is_fatal(self) -> None:
        csv_text = "ticket_id,line,sku,lot,qty,unit,status,operator\nTKT-104221,3,SKU-BRZ12,LOT-9F2A,1,kg,closed,m.chen\n"
        with self.assertRaises(NormalizeError) as caught:
            normalize_csv(csv_text)
        self.assertIn("closed_at", str(caught.exception))

    def test_extra_column_is_fatal(self) -> None:
        csv_text = TICKETS_CSV.replace(
            "closed_at",
            "closed_at,notes",
        )
        with self.assertRaises(NormalizeError) as caught:
            normalize_csv(csv_text)
        self.assertIn("notes", str(caught.exception))

    def test_crlf_and_bom_are_accepted(self) -> None:
        messy = "\ufeff" + TICKETS_CSV.replace("\n", "\r\n")
        document = normalize_csv(messy)
        self.assertEqual(document["counts"]["accepted"], 3)


if __name__ == "__main__":
    unittest.main()
