import zipfile
import unittest

from escapehatch.paths import ODS_FIXTURE


class OdsFixtureTests(unittest.TestCase):
    def test_fixture_is_a_real_opendocument(self) -> None:
        self.assertTrue(ODS_FIXTURE.exists())
        with zipfile.ZipFile(ODS_FIXTURE) as archive:
            self.assertEqual(
                archive.read("mimetype"),
                b"application/vnd.oasis.opendocument.spreadsheet",
            )
            self.assertIn("content.xml", archive.namelist())
            content = archive.read("content.xml").decode("utf-8")
            self.assertIn("PINE-SEA-01", content)
            self.assertIn("B-2026-0908-014", content)
            self.assertIn("Hold Log", content)


if __name__ == "__main__":
    unittest.main()
