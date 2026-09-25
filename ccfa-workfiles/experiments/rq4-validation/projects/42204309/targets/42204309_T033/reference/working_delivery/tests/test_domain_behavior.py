
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

    def test_coded_referral_receipt_and_feedback(self):
        app = create_app()
        app.request("POST", "/api/referrals", {"owner": "chosen-holder", "code": "READ"})
        receipt = app.request("POST", "/api/mints", {
            "buyer": "reader", "amount_usd": 30, "referral_code": "READ"
        })["body"]
        self.assertEqual(receipt["transaction_status"], "confirmed")
        self.assertEqual(receipt["referral"]["commission_usd"], 12.0)
        self.assertEqual(receipt["referral"]["tickets"], 4)
        self.assertEqual(receipt["referral"]["draw_amount_usd"], 1250.0)
        self.assertEqual(receipt["feedback"]["variant"], "coded-referral")
        self.assertEqual(receipt["feedback"]["token_id"], receipt["token_id"])
        self.assertEqual(receipt["feedback"]["copy"], "$12 commission + $1,250 prize draw ticket has gone to your chosen From Workshop Floor to Fresh Start NFT holder")

    def test_no_referral_copy_is_not_used_for_coded_purchase(self):
        app = create_app()
        app.request("POST", "/api/referrals", {"owner": "chosen-holder", "code": "READ"})
        receipt = app.request("POST", "/api/mints", {
            "buyer": "reader", "amount_usd": 30, "referral_code": "READ"
        })["body"]
        self.assertNotIn("at random", receipt["feedback"]["copy"])
        content = app.request("GET", "/api/content")["body"]
        self.assertEqual(content["small_block_prize_usd"], 1250)


if __name__ == "__main__":
    unittest.main()
