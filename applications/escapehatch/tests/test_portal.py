import json
import threading
import unittest
from http.client import HTTPConnection

from escapehatch import portal_server
from escapehatch.normalizer import normalize_csv
from escapehatch.ods import expected_csv


class PortalTests(unittest.TestCase):
    def setUp(self) -> None:
        portal_server.RECEIPTS.clear()
        self.server = portal_server.ThreadingHTTPServer(
            ("127.0.0.1", 0), portal_server.Handler
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _request(self, method: str, path: str, body: bytes | None = None, content_type: str | None = None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    def test_multipart_upload_returns_receipt_and_seen(self) -> None:
        payload = normalize_csv(expected_csv())
        raw = json.dumps(payload).encode("utf-8")
        boundary = "----test"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="artifact"; filename="n.json"\r\n'
            "Content-Type: application/json\r\n\r\n"
        ).encode("utf-8") + raw + f"\r\n--{boundary}--\r\n".encode("ascii")
        status, html = self._request(
            "POST",
            "/file",
            body,
            f"multipart/form-data; boundary={boundary}",
        )
        self.assertEqual(status, 200)
        text = html.decode("utf-8")
        self.assertIn("data-receipt=", text)
        receipt = text.split('data-receipt="', 1)[1].split('"', 1)[0]

        status, seen = self._request("GET", f"/seen?receipt={receipt}")
        self.assertEqual(status, 200)
        self.assertEqual(seen.decode(), "yes")

        status, record_raw = self._request("GET", f"/receipts/{receipt}")
        record = json.loads(record_raw.decode())
        self.assertEqual(status, 200)
        self.assertEqual(record["digest"], payload["digest"])
        self.assertEqual(record["rowCount"], 5)

    def test_unknown_receipt_is_not_seen(self) -> None:
        status, seen = self._request("GET", "/seen?receipt=rcpt_missing")
        self.assertEqual(status, 200)
        self.assertEqual(seen.decode(), "no")

    def test_rejects_wrong_schema(self) -> None:
        status, _ = self._request(
            "POST",
            "/file",
            json.dumps({"schema": "nope", "digest": "a" * 64, "rows": [{}]}).encode(),
            "application/json",
        )
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
