from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from application import create_app


class ReferenceBehaviorTest(unittest.TestCase):
    def test_video_is_mixed_with_photos_in_both_placements(self):
        app = create_app()
        media = app.request("GET", "/api/media")["body"]
        for placement in ("gallery", "homepage"):
            types = [item["type"] for item in media[placement]["items"]]
            self.assertIn("video", types)
            self.assertIn("image", types)
        page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertGreaterEqual(page.count("<video"), 2)


if __name__ == "__main__":
    unittest.main()

