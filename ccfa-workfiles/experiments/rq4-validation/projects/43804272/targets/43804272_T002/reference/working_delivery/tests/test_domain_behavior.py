
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

    def test_size_optimized_shared_asset_strategy(self):
        strategy = create_app().request("GET", "/api/app/config")["body"]["package_optimization"]
        self.assertEqual(strategy["optimization_priority"], "smallest-possible-app-size")
        self.assertFalse(strategy["asset_strategy"]["localized_tutorial_images"])
        self.assertTrue(strategy["asset_strategy"]["translatable_text_rendered_by_app"])
        self.assertTrue(strategy["android_packaging"]["language_splits"])
        self.assertTrue(strategy["ios_packaging"]["dead_code_stripping"])


if __name__ == "__main__":
    unittest.main()
