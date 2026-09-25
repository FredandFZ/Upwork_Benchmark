
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

from current_state import FEATURES
from platform_build import PLATFORM_BUILD


class DomainError(ValueError):
    pass


_FEATURES = {item["slug"]: deepcopy(item) for item in FEATURES}


def _feature(slug):
    return _FEATURES.get(slug)


def _attrs(slug):
    item = _feature(slug)
    return deepcopy(item.get("attributes") or {}) if item else {}


def _find(*terms):
    terms = tuple(term.lower() for term in terms)
    for slug, feature in _FEATURES.items():
        haystack = " ".join((slug, feature.get("title", ""))).lower()
        if all(term in haystack for term in terms):
            return deepcopy(feature.get("attributes") or {})
    return {}


def _has_term(term):
    term = term.lower()
    return any(term in " ".join((slug, feature.get("title", ""))).lower()
               for slug, feature in _FEATURES.items())


def _number(value, default=0.0):
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group()) if match else float(default)


def _ok(body, status=200):
    return {"status": status, "body": body}


class CurrentMobileService:
    RTL_LANGUAGES = {"ar", "fa", "he", "ur"}

    def __init__(self):
        self.locale = "en"

    def routes(self):
        return [
            {"method": "GET", "path": "/api/app/config"},
            {"method": "POST", "path": "/api/locales"},
        ]

    def config(self):
        media = _attrs("how-to-media-delivery")
        permissions = _attrs("android-permission-hygiene")
        return {
            "platforms": ["android", "ios"],
            "feature_count": len(_FEATURES),
            "tutorial_delivery": media.get("video_delivery_method"),
            "tutorial_bundled": media.get("video_delivery_method") != "external_streaming",
            "removed_permissions": [permissions["identified_permission_to_remove"]]
                if permissions.get("identified_permission_to_remove") else [],
            "locale": self.locale,
            "direction": "rtl" if self.locale.split("-")[0] in self.RTL_LANGUAGES else "ltr",
            "localization": deepcopy(PLATFORM_BUILD["localization"]),
        }

    def set_locale(self, locale):
        locale = str(locale or "").strip().lower().replace("_", "-")
        if not locale:
            raise DomainError("locale is required")
        supported = set(PLATFORM_BUILD["localization"]["android"]["locales"])
        supported.update(PLATFORM_BUILD["localization"]["ios"]["locales"])
        if locale not in {item.lower() for item in supported}:
            raise DomainError("unsupported locale")
        self.locale = locale
        return {"locale": locale,
                "direction": "rtl" if locale.split("-")[0] in self.RTL_LANGUAGES else "ltr"}

    def request(self, method, path, payload=None, query=None):
        payload = payload or {}
        if method == "GET" and path == "/api/app/config":
            return _ok(self.config())
        if method == "POST" and path == "/api/locales":
            return _ok(self.set_locale(payload.get("locale")))
        return {"status": 404, "body": {"error": "route not found"}}


def make_service():
    return CurrentMobileService()
