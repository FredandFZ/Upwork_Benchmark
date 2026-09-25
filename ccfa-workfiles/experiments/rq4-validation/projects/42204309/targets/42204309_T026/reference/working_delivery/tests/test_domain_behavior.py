
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

    def test_each_non_promotional_mint_registers_one_commission_and_ticket(self):
        app = create_app()
        app.request("POST", "/api/referrals", {"owner": "referrer", "code": "READ"})
        app.request("POST", "/api/mints", {"buyer": "a", "amount_usd": 30, "referral_code": "READ"})
        no_code = app.request("POST", "/api/mints", {"buyer": "b", "amount_usd": 30})["body"]
        app.request("POST", "/api/mints", {"buyer": "promo", "amount_usd": 30, "promotional": True})
        self.assertEqual(no_code["referral"]["tickets"], 1)
        self.assertTrue(no_code["reward_recipients"]["commission"])
        dashboard = app.request("GET", "/api/dashboard", query={})["body"]
        self.assertEqual(dashboard["eligible_mint_count"], 2)
        self.assertEqual(dashboard["reward_totals"]["commission_count"], 2)
        self.assertEqual(dashboard["reward_totals"]["ticket_count"], 2)
        self.assertEqual(dashboard["reward_totals"]["weighted_draw_distribution_count"], 1)

    def test_public_copy_matches_reward_ledger_rule(self):
        content = create_app().request("GET", "/api/content")["body"]
        self.assertIn("one commission and one prize ticket", content["faq"])
        self.assertIn("Promotional mints are excluded", content["about"])


if __name__ == "__main__":
    unittest.main()
