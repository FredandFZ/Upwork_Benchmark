from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from application import create_app


class ReferenceBehaviorTest(unittest.TestCase):
    def test_quote_page_contract_and_submission(self):
        app = create_app()
        page = app.request("GET", "/api/quote-page")["body"]
        self.assertIsNone(page["calendar_integration"])
        fields = {item["name"]: item for item in page["fields"]}
        self.assertEqual(set(fields), {"name", "company", "phone_number", "email", "job_description"})
        self.assertFalse(fields["company"]["required"])
        response = app.request("POST", "/api/quote-requests", {
            "name": "Alex", "company": "", "phone_number": "555-0100",
            "email": "alex@example.test", "job_description": "Twilight shoot"
        })
        self.assertEqual(response["status"], 201)
        self.assertEqual(response["body"]["status"], "received")

    def test_book_session_points_to_quote(self):
        app = create_app()
        self.assertEqual(app.request("GET", "/api/navigation")["body"]["links"]["book_session"], "/quote")


if __name__ == "__main__":
    unittest.main()

