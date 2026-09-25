from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from application import create_app
from domain import VIDEO_URL


class ReferenceBehaviorTest(unittest.TestCase):
    def test_temporary_placeholder_is_used_in_gallery_and_homepage(self):
        app = create_app()
        media = app.request("GET", "/api/media")["body"]
        self.assertTrue(VIDEO_URL.endswith("Coastal-Aerial-Narration.mp4?dl=0"))
        for placement in ("gallery", "homepage"):
            videos = [item for item in media[placement]["items"] if item["type"] == "video"]
            self.assertEqual(len(videos), 1)
            self.assertEqual(videos[0]["src"], VIDEO_URL)
            self.assertEqual(videos[0]["role"], "temporary placeholder")


if __name__ == "__main__":
    unittest.main()

