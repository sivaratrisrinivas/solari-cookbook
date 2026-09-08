import json
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from escapehatch import portal_server
from escapehatch.normalize import normalize_csv
from escapehatch.fixture import TICKETS_CSV


def _multipart(payload: bytes, filename: str = "batch.json") -> tuple[bytes, str]:
    boundary = "----EscapeHatchTestBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="batch"; filename="{filename}"\r\n'
        "Content-Type: application/json\r\n"
        "\r\n"
    ).encode("utf-8") + payload + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


class PortalTests(unittest.TestCase):
    def setUp(self) -> None:
        portal_server.RECEIPTS.clear()
        self.server = HTTPServer(("127.0.0.1", 0), portal_server.Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        portal_server.RECEIPTS.clear()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def test_file_batch_then_read_receipt(self) -> None:
        document = normalize_csv(TICKETS_CSV, source="night-shift-tickets.ods")
        raw = json.dumps(document).encode("utf-8")
        body, content_type = _multipart(raw)
        request = Request(
            self._url("/file"),
            data=body,
            method="POST",
            headers={"Content-Type": content_type},
        )
        with urlopen(request, timeout=5) as response:
            html = response.read().decode("utf-8")
        receipt_id = "RCPT-" + document["digest"][:12].upper()
        self.assertIn(receipt_id, html)
        with urlopen(self._url(f"/receipts/{receipt_id}"), timeout=5) as response:
            receipt = json.loads(response.read().decode("utf-8"))
        self.assertEqual(receipt["id"], receipt_id)
        self.assertEqual(receipt["digest"], document["digest"])
        self.assertEqual(receipt["accepted"], 3)
        with urlopen(self._url(f"/seen?token={receipt_id}"), timeout=5) as response:
            self.assertEqual(response.read().decode("utf-8"), "yes")
        with urlopen(self._url("/seen?token=RCPT-MISSING"), timeout=5) as response:
            self.assertEqual(response.read().decode("utf-8"), "no")

    def test_expected_fixture_digest_is_what_portal_stamps(self) -> None:
        expected = json.loads(
            Path(__file__).resolve().parents[1].joinpath(
                "fixtures", "expected-normalized.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            "RCPT-" + expected["digest"][:12].upper(),
            "RCPT-0B92F6F0ED70",
        )


if __name__ == "__main__":
    unittest.main()
