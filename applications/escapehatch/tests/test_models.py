import json
import tempfile
import unittest
from pathlib import Path

from escapehatch.models import EscapeRun, IllegalTransition
from escapehatch.ods import build_ods
from escapehatch.pipeline import plan_dry_run
from escapehatch.report import public_run, redact_identifier, redact_url


class StatusMachineTests(unittest.TestCase):
    def test_happy_path(self) -> None:
        run = EscapeRun.create("/tmp/evidence", mode="live")
        for status in (
            "desktop_running",
            "extracted",
            "normalizing",
            "normalized",
            "portal_up",
            "filing",
            "filed",
            "cleaned",
        ):
            run.advance(status)
        self.assertEqual(run.status, "cleaned")

    def test_skip_is_illegal(self) -> None:
        run = EscapeRun.create("/tmp/evidence", mode="live")
        with self.assertRaises(IllegalTransition):
            run.advance("filed")

    def test_fail_from_mid_pipeline(self) -> None:
        run = EscapeRun.create("/tmp/evidence", mode="live")
        run.advance("desktop_running")
        run.fail("desktop exploded")
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error, "desktop exploded")

    def test_cleaned_is_terminal(self) -> None:
        run = EscapeRun.create("/tmp/evidence", mode="live")
        for status in (
            "desktop_running",
            "extracted",
            "normalizing",
            "normalized",
            "portal_up",
            "filing",
            "filed",
            "cleaned",
        ):
            run.advance(status)
        with self.assertRaises(IllegalTransition):
            run.advance("failed")


class ReportTests(unittest.TestCase):
    def test_redacts_key_shaped_strings_and_tokens(self) -> None:
        run = EscapeRun.create("/tmp/evidence", mode="live")
        run.desktop_session_id = "pool-desktop-sta:vm_7c1e:org_9f2a.YWJjZGVmZ2hpamts"
        run.portal_url = "https://abc.preview.getsolari.com/?pt_token=secret-value"
        run.metadata["note"] = "contact us with slr_live_abc123xyz"
        payload = public_run(run)
        self.assertEqual(
            payload["desktop_session_id"],
            redact_identifier(run.desktop_session_id),
        )
        self.assertNotIn("secret-value", payload["portal_url"] or "")
        dumped = json.dumps(payload)
        self.assertNotIn("slr_live_abc123xyz", dumped)
        self.assertIn("slr_live_redacted", dumped)

    def test_redact_url_keeps_host(self) -> None:
        url = redact_url("https://box.preview.getsolari.com/file?pt_token=abc")
        self.assertIsNotNone(url)
        self.assertIn("preview.getsolari.com", url or "")
        self.assertIn("redacted", url or "")


class DryRunTests(unittest.TestCase):
    def test_dry_run_writes_evidence_without_solari_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "evidence"
            run = plan_dry_run(evidence)
            report = json.loads((evidence / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run.mode, "dry-run")
            self.assertEqual(report["mode"], "dry-run")
            self.assertEqual(report["status"], "created")
            self.assertIsNone(report["desktop_session_id"])
            self.assertTrue((evidence / "normalized.json").exists())
            self.assertGreater(len(build_ods("a,b\n1,2\n")), 100)


if __name__ == "__main__":
    unittest.main()
