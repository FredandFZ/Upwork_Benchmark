from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from application import create_app


class ReferenceBehaviorTest(unittest.TestCase):
    def test_instant_quote_is_not_exposed(self):
        app = create_app()
        routes = {(item["method"], item["path"]) for item in app.routes()}
        self.assertNotIn(("POST", "/api/quotes"), routes)
        self.assertEqual(app.request("POST", "/api/quotes", {"square_feet": 1200})["status"], 404)
        page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("<form", page)
        self.assertNotIn("data-endpoint", page)


if __name__ == "__main__":
    unittest.main()

