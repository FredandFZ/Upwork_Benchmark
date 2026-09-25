
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from application import create_app
from runtime import build, check


class DomainSmokeTest(unittest.TestCase):
    def test_routes_are_callable(self):
        app = create_app()
        self.assertTrue(app.routes())
        for route in app.routes():
            self.assertTrue(route["path"].startswith("/api/"))

    def test_interactive_build(self):
        with tempfile.TemporaryDirectory() as directory:
            build(directory)
            result = check(directory)
            self.assertGreater(result["route_count"], 0)

    def test_store_locale_coverage_and_runtime_selection(self):
        app = create_app()
        localization = app.request("GET", "/api/app/config")["body"]["localization"]
        self.assertEqual(localization["android"]["language_count"], 77)
        self.assertEqual(len(localization["android"]["locales"]), 77)
        self.assertEqual(localization["ios"]["language_count"], 40)
        self.assertEqual(len(localization["ios"]["locales"]), 40)
        self.assertEqual(app.request("POST", "/api/locales", {"locale": "ar"})["body"]["direction"], "rtl")
        self.assertEqual(app.request("POST", "/api/locales", {"locale": "not-a-locale"})["status"], 400)


if __name__ == "__main__":
    unittest.main()
