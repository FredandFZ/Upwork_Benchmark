from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from application import create_app


class ReferenceBehaviorTest(unittest.TestCase):
    def test_each_package_varies_across_square_footage(self):
        app = create_app()
        pricing = app.request("GET", "/api/pricing")["body"]
        self.assertEqual(len(pricing["packages"]), 4)
        self.assertEqual(len(pricing["categories"]), 4)
        for package in pricing["packages"]:
            values = list(package["prices_by_square_footage"].values())
            self.assertEqual(len(values), 4)
            self.assertEqual(len(set(values)), 4)

    def test_boundary_changes_price(self):
        app = create_app()
        low = app.request("POST", "/api/quotes", {"square_feet": 1200, "package": "basic"})["body"]
        high = app.request("POST", "/api/quotes", {"square_feet": 1201, "package": "basic"})["body"]
        self.assertNotEqual(low["base_price_usd"], high["base_price_usd"])


if __name__ == "__main__":
    unittest.main()

