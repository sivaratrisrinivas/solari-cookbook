import unittest

from escapehatch.models import InvalidTransition, create_run


class EscapeRunTests(unittest.TestCase):
    def test_happy_path_reaches_cleaned(self) -> None:
        run = create_run("/tmp/eh", mode="dry-run")
        self.assertEqual(run.status, "created")
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
        self.assertIsNone(run.error)

    def test_cannot_skip_ahead(self) -> None:
        run = create_run("/tmp/eh", mode="dry-run")
        with self.assertRaises(InvalidTransition):
            run.advance("filed")

    def test_fail_from_any_in_flight_status(self) -> None:
        run = create_run("/tmp/eh", mode="live")
        run.advance("desktop_running")
        run.fail("desktop exploded")
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error, "desktop exploded")

    def test_cannot_leave_failed(self) -> None:
        run = create_run("/tmp/eh", mode="live")
        run.fail("nope")
        with self.assertRaises(InvalidTransition):
            run.advance("cleaned")

    def test_to_dict_has_required_fields(self) -> None:
        run = create_run("/tmp/eh", mode="dry-run")
        payload = run.to_dict()
        for key in (
            "id",
            "status",
            "desktopSessionId",
            "extractPath",
            "extractSha256",
            "normalizedJsonPath",
            "normalizedSha256",
            "portalUrl",
            "portalReceipt",
            "browserSessionId",
            "recordingUrl",
            "evidenceDir",
            "error",
        ):
            self.assertIn(key, payload)


if __name__ == "__main__":
    unittest.main()
