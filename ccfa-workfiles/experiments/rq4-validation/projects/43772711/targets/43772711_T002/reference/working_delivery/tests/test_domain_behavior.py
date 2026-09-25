
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

    def test_design_guidance_is_public_behavior(self):
        guidance = create_app().request("GET", "/api/design-guidance")["body"]
        self.assertTrue(guidance["landing_page"]["responsive"])
        self.assertFalse(guidance["website_pages"]["user_switchable_theme"])
        self.assertEqual(guidance["website_pages"]["theme_assignment"], "per-page")
        self.assertIn("canvas", guidance["dashboard"]["shell_regions"])


if __name__ == "__main__":
    unittest.main()
