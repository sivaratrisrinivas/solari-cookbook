import unittest

from escapehatch.redact import redact_identifier, redact_run, redact_text, redact_url


class RedactTests(unittest.TestCase):
    def test_api_keys_never_survive(self) -> None:
        self.assertEqual(
            redact_text("using slr_live_abcDEF1234567890"),
            "using slr_***",
        )

    def test_presigned_query_is_stripped(self) -> None:
        url = "https://storage.getsolari.com/org/rec.mp4?X-Amz-Signature=deadbeef&X-Amz-Expires=3600"
        self.assertEqual(
            redact_url(url),
            "https://storage.getsolari.com/org/rec.mp4",
        )

    def test_preview_token_is_stripped(self) -> None:
        url = "https://abc.preview.getsolari.com/?pt_token=secret"
        self.assertEqual(redact_url(url), "https://abc.preview.getsolari.com/")

    def test_session_ids_are_shortened(self) -> None:
        self.assertEqual(
            redact_identifier("pool-desktop-sta:vm_7c1e:org_9f2a.YWJjZGVm"),
            "pool-des…JjZGVm",
        )

    def test_run_payload_is_scrubbed(self) -> None:
        payload = redact_run(
            {
                "desktopSessionId": "pool-desktop-sta:vm_7c1e:org_9f2a.YWJjZGVm",
                "recordingUrl": "https://storage.example/rec.mp4?X-Amz-Signature=abc",
                "portalUrl": "https://x.preview.getsolari.com/form?pt_token=tok",
                "error": "failed with slr_live_supersecret",
                "cleanup": {"detail": "key slr_live_supersecret"},
            }
        )
        self.assertNotIn("supersecret", str(payload))
        self.assertNotIn("Signature=abc", str(payload))
        self.assertNotIn("pt_token=tok", str(payload))


if __name__ == "__main__":
    unittest.main()
