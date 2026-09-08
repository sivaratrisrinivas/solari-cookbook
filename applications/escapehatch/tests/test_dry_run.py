import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from escapehatch.cli import main
from escapehatch.pipeline import run_dry
from escapehatch.redact import redact_text


class DryRunTests(unittest.TestCase):
    def test_dry_run_writes_evidence_for_all_three_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            run = asyncio.run(run_dry(evidence))

            self.assertEqual(run.status, "cleaned")
            self.assertEqual(run.mode, "dry-run")
            self.assertIsNotNone(run.portalReceipt)
            self.assertTrue((evidence / "run.json").exists())
            self.assertTrue((evidence / "extract.csv").exists())
            self.assertTrue((evidence / "normalized.json").exists())
            payload = json.loads((evidence / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "cleaned")
            self.assertEqual(payload["extractSha256"], run.extractSha256)
            self.assertEqual(payload["normalizedSha256"], run.normalizedSha256)
            self.assertTrue(payload["portalReceipt"].startswith("rcpt_"))
            self.assertIn("screens/desktop-calc-open.png", payload["screenshots"])
            self.assertIn("screens/browser-receipt.png", payload["screenshots"])
            self.assertNotIn("slr_live_", json.dumps(payload))
            self.assertEqual(redact_text(json.dumps(payload)), json.dumps(payload))

    def test_cli_dry_run_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            code = main(["--dry-run", "--output", directory])
            self.assertEqual(code, 0)
            self.assertTrue((Path(directory) / "run.json").exists())


if __name__ == "__main__":
    unittest.main()
