from __future__ import annotations

from copy import deepcopy


class DomainError(ValueError):
    pass


VIDEO_URL = None


class SilverPineService:
    def __init__(self):
        self.gallery_selection = "photos"

    def routes(self):
        return [
            {"method": "GET", "path": "/api/gallery"},
            {"method": "POST", "path": "/api/gallery/selection"},
            {"method": "GET", "path": "/api/media"},
            {"method": "GET", "path": "/api/navigation"},
        ]

    def media(self):
        video = {
            "id": "portfolio-video",
            "type": "video",
            "role": "temporary placeholder" if VIDEO_URL else "portfolio video slot",
            "src": VIDEO_URL,
            "placement": ["gallery", "homepage"],
        }
        gallery_items = [
            {"id": "photo-1", "type": "image", "alt": "Coastal property exterior"},
            video,
            {"id": "photo-2", "type": "image", "alt": "Twilight property exterior"},
        ]
        return {
            "gallery": {"layout": "mixed-media", "items": deepcopy(gallery_items)},
            "homepage": {"layout": "portfolio-row", "items": deepcopy(gallery_items)},
        }

    def gallery(self):
        return {
            "tabs": ["photos", "twilights", "floor_plans", "3d_tour"],
            "selected": self.gallery_selection,
            "interaction": "interactive_scrollable_gallery",
            "media": self.media()["gallery"]["items"],
        }

    def select_gallery(self, tab):
        requested = str(tab or "").strip().lower()
        if requested not in self.gallery()["tabs"]:
            raise DomainError("unknown gallery tab")
        self.gallery_selection = requested
        return self.gallery()

    def navigation(self):
        return {"links": {"gallery": "#gallery"}, "portfolio": "#home-portfolio"}

    def request(self, method, path, payload=None, query=None):
        payload = payload or {}
        if method == "GET" and path == "/api/gallery":
            return {"status": 200, "body": self.gallery()}
        if method == "POST" and path == "/api/gallery/selection":
            return {"status": 200, "body": self.select_gallery(payload.get("tab"))}
        if method == "GET" and path == "/api/media":
            return {"status": 200, "body": self.media()}
        if method == "GET" and path == "/api/navigation":
            return {"status": 200, "body": self.navigation()}
        return {"status": 404, "body": {"error": "route not found"}}


def make_service():
    return SilverPineService()

