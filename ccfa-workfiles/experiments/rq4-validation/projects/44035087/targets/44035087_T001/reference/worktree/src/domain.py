from __future__ import annotations

from copy import deepcopy

from current_state import FEATURES


class DomainError(ValueError):
    pass


_FEATURES = {item["slug"]: deepcopy(item) for item in FEATURES}


class CurrentGalleryQuoteService:
    """Gallery service after the instant-quote experience has been deferred."""

    def __init__(self):
        self.gallery_selection = None

    def routes(self):
        return [
            {"method": "GET", "path": "/api/gallery"},
            {"method": "POST", "path": "/api/gallery/selection"},
        ]

    def gallery(self):
        feature = _FEATURES.get("gallery-browsing-and-organization") or {}
        config = feature.get("attributes") or {}
        tabs = list(config.get("main_gallery_tabs") or [])
        return {
            "tabs": tabs,
            "selected": self.gallery_selection or (tabs[0] if tabs else None),
            "interaction": config.get("interaction_mode"),
        }

    def select_gallery(self, tab):
        requested = str(tab or "").strip().lower()
        tabs = [str(item).lower() for item in self.gallery()["tabs"]]
        if requested not in tabs:
            raise DomainError("unknown gallery tab")
        self.gallery_selection = requested
        return self.gallery()

    def request(self, method, path, payload=None, query=None):
        payload = payload or {}
        if method == "GET" and path == "/api/gallery":
            return {"status": 200, "body": self.gallery()}
        if method == "POST" and path == "/api/gallery/selection":
            return {"status": 200, "body": self.select_gallery(payload.get("tab"))}
        return {"status": 404, "body": {"error": "route not found"}}


def make_service():
    return CurrentGalleryQuoteService()

