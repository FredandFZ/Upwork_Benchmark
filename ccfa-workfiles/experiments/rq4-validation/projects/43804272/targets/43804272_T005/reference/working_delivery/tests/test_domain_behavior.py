
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

    def test_main_channel_upload_blocks_application_use(self):
        tutorial = create_app().request("GET", "/api/app/config")["body"]["tutorial"]
        self.assertEqual(tutorial["video_hosting_channel"], "client_main_youtube_channel")
        self.assertEqual(tutorial["integration_status"], "awaiting-main-youtube-upload")
        self.assertEqual(tutorial["candidate_video_resource"], "https://video.cedar-meadow.example/watch/e0023")
        self.assertIsNone(tutorial["playback_url"])
        self.assertFalse(tutorial["tutorial_images_required"])


if __name__ == "__main__":
    unittest.main()
