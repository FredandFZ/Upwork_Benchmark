from __future__ import annotations

from copy import deepcopy
import re


class DomainError(ValueError):
    pass


class SilverPineService:
    def __init__(self):
        self.quote_requests = []

    def routes(self):
        return [
            {"method": "GET", "path": "/api/navigation"},
            {"method": "GET", "path": "/api/quote-page"},
            {"method": "POST", "path": "/api/quote-requests"},
        ]

    def navigation(self):
        return {
            "links": {"book_session": "/quote", "get_quote": "/quote"},
            "portfolio": "/gallery",
        }

    def quote_page(self):
        return {
            "path": "/quote",
            "title": "Get a Quote",
            "calendar_integration": None,
            "fields": [
                {"name": "name", "label": "Name", "required": True},
                {"name": "company", "label": "Company", "required": False},
                {"name": "phone_number", "label": "Phone Number", "required": True},
                {"name": "email", "label": "Email", "required": True},
                {"name": "job_description", "label": "Job Description", "required": True},
            ],
        }

    def submit_quote_request(self, **payload):
        cleaned = {key: str(value or "").strip() for key, value in payload.items()}
        required = ("name", "phone_number", "email", "job_description")
        missing = [key for key in required if not cleaned.get(key)]
        if missing:
            raise DomainError("missing required fields: " + ", ".join(missing))
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", cleaned["email"]):
            raise DomainError("email is invalid")
        record = {
            "request_id": len(self.quote_requests) + 1,
            "name": cleaned["name"],
            "company": cleaned.get("company", ""),
            "phone_number": cleaned["phone_number"],
            "email": cleaned["email"],
            "job_description": cleaned["job_description"],
            "status": "received",
        }
        self.quote_requests.append(record)
        return deepcopy(record)

    def request(self, method, path, payload=None, query=None):
        payload = payload or {}
        if method == "GET" and path == "/api/navigation":
            return {"status": 200, "body": self.navigation()}
        if method == "GET" and path == "/api/quote-page":
            return {"status": 200, "body": self.quote_page()}
        if method == "POST" and path == "/api/quote-requests":
            return {"status": 201, "body": self.submit_quote_request(**payload)}
        return {"status": 404, "body": {"error": "route not found"}}


def make_service():
    return SilverPineService()

