
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

from current_state import FEATURES
from platform_build import HOW_TO, PLATFORM_BUILD


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


class MeasurementService:
    RTL_LANGUAGES = {"ar", "fa", "he", "ur"}

    def __init__(self):
        self.measurements = []
        self.locale = "en"

    def routes(self):
        return [
            {"method": "GET", "path": "/api/app/config"},
            {"method": "POST", "path": "/api/measurements"},
            {"method": "POST", "path": "/api/locales"},
        ]

    def config(self):
        permissions = _attrs("android-permission-hygiene")
        return {
            "measurement_steps": _attrs("how-to-measurement-instructions").get("measurement_sequence") or [],
            "tutorial_delivery": HOW_TO["delivery_method"],
            "tutorial_bundled": False,
            "tutorial": deepcopy(HOW_TO),
            "platform_build": deepcopy(PLATFORM_BUILD),
            "removed_permissions": [permissions["identified_permission_to_remove"]]
                if permissions.get("identified_permission_to_remove") else [],
            "locale": self.locale,
            "direction": "rtl" if self.locale.split("-")[0] in self.RTL_LANGUAGES else "ltr",
        }

    def measure(self, samples):
        if not (_has_term("measurement") or _has_term("scoliometer")):
            raise DomainError("measurement is not available")
        values = [float(item) for item in samples]
        if not values:
            raise DomainError("at least one sample is required")
        peak = max(values, key=lambda item: abs(item))
        result = {"measurement_id": len(self.measurements) + 1, "peak_degrees": abs(peak),
                  "sample_count": len(values), "unit": "degrees"}
        self.measurements.append(result)
        return deepcopy(result)

    def set_locale(self, locale):
        locale = str(locale).strip().lower().replace("_", "-")
        if not locale:
            raise DomainError("locale is required")
        self.locale = locale
        return {"locale": locale, "direction": "rtl" if locale.split("-")[0] in self.RTL_LANGUAGES else "ltr"}

    def request(self, method, path, payload=None, query=None):
        payload = payload or {}
        if method == "GET" and path == "/api/app/config":
            return _ok(self.config())
        if method == "POST" and path == "/api/measurements":
            return _ok(self.measure(payload.get("samples") or []), 201)
        if method == "POST" and path == "/api/locales":
            return _ok(self.set_locale(payload.get("locale")))
        return {"status": 404, "body": {"error": "route not found"}}


def make_service():
    return MeasurementService()
