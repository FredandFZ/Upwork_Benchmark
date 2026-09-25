
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

    def test_footer_uses_dark_purple_surface(self):
        footer = create_app().request("GET", "/api/site-shell")["body"]["footer"]
        self.assertEqual(footer["background_color"], "dark_purple")
        self.assertEqual(footer["background_hex"], "#32105c")
        self.assertIn("Privacy Policy", footer["menu_links"])


if __name__ == "__main__":
    unittest.main()
