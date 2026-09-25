
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

    def test_shell_has_scoped_components_and_two_themes(self):
        app = create_app()
        shell = app.request("GET", "/api/ui-shell")["body"]
        self.assertEqual(shell["included_components"], ["header", "side navigation panel", "footer"])
        self.assertEqual(shell["theme_modes"], ["light", "dark"])
        self.assertEqual(shell["canvas"]["style_scope"], "separate")
        dark = app.request("PATCH", "/api/ui-shell/theme", {"theme": "dark"})
        self.assertEqual(dark["body"]["theme"], "dark")
        self.assertEqual(dark["body"]["tokens"]["background"], "#17131e")


if __name__ == "__main__":
    unittest.main()
