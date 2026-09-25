
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

    def test_no_referral_mint_allocates_six_tickets_and_commission(self):
        app = create_app()
        receipt = app.request("POST", "/api/mints", {
            "buyer": "reader@example.test", "amount_usd": 30
        })["body"]
        self.assertFalse(receipt["referral"]["accepted"])
        self.assertEqual(receipt["referral"]["tickets"], 6)
        self.assertEqual(receipt["referral"]["commission_usd"], 18.0)
        self.assertTrue(receipt["reward_recipients"]["commission"])
        totals = app.request("GET", "/api/dashboard", query={})["body"]["reward_totals"]
        self.assertEqual(totals, {"commission_count": 1, "ticket_count": 6})

    def test_public_copy_explains_weighted_draw(self):
        content = create_app().request("GET", "/api/content")["body"]
        self.assertIn("six tickets", content["faq"])
        self.assertIn("weighted draw", content["about"])


if __name__ == "__main__":
    unittest.main()
