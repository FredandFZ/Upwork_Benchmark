from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from application import create_app


class ReferenceBehaviorTest(unittest.TestCase):
    def test_basic_package_approved_prices(self):
        app = create_app()
        expected = [(1200, 390), (1201, 620), (2401, 860), (3601, 1120)]
        for area, price in expected:
            result = app.request("POST", "/api/quotes", {"square_feet": area, "package": "basic"})
            self.assertEqual(result["status"], 201)
            self.assertEqual(result["body"]["base_price_usd"], price)


if __name__ == "__main__":
    unittest.main()

