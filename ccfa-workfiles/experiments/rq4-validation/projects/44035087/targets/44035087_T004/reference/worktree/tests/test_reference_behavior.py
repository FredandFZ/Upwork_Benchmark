from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from application import create_app


class ReferenceBehaviorTest(unittest.TestCase):
    def test_predefined_four_by_four_matrix(self):
        app = create_app()
        pricing = app.request("GET", "/api/pricing")["body"]
        self.assertEqual(pricing["model"], "predefined")
        self.assertEqual([c["key"] for c in pricing["categories"]], [
            "under_1200_sqft", "1201_2400_sqft", "2401_3600_sqft", "3600_plus_sqft"
        ])
        self.assertEqual(len(pricing["packages"]), 4)
        self.assertTrue(all(len(p["prices_by_square_footage"]) == 4 for p in pricing["packages"]))

    def test_exact_category_boundaries(self):
        app = create_app()
        expected = [(1200, "under_1200_sqft"), (1201, "1201_2400_sqft"),
                    (2400, "1201_2400_sqft"), (2401, "2401_3600_sqft"),
                    (3600, "2401_3600_sqft"), (3601, "3600_plus_sqft")]
        for area, category in expected:
            result = app.request("POST", "/api/quotes", {"square_feet": area, "package": "basic"})
            self.assertEqual(result["body"]["category"], category)


if __name__ == "__main__":
    unittest.main()

