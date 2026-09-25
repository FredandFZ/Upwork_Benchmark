
from __future__ import annotations

from domain import DomainError, make_service


class Application:
    def __init__(self, service=None):
        self.service = service or make_service()

    def routes(self):
        return self.service.routes()

    def request(self, method, path, payload=None, query=None):
        try:
            return self.service.request(str(method).upper(), path, payload or {}, query or {})
        except DomainError as exc:
            return {"status": 400, "body": {"error": str(exc)}}
        except TypeError as exc:
            return {"status": 400, "body": {"error": "invalid request", "detail": str(exc)}}


def create_app():
    return Application()
