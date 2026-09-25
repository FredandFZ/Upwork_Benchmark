
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

    def test_ios_images_are_replaced_by_youtube_delivery(self):
        config = create_app().request("GET", "/api/app/config")["body"]
        self.assertFalse(config["tutorial_bundled"])
        self.assertEqual(config["tutorial"]["media_format"], "youtube_video")
        self.assertEqual(config["tutorial"]["media_platforms"], ["ios"])
        self.assertFalse(config["tutorial"]["tutorial_images_required"])
        self.assertIsNone(config["tutorial"]["video_url"])


if __name__ == "__main__":
    unittest.main()
