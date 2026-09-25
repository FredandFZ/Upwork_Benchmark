
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

from current_state import FEATURES


class DomainError(ValueError):
    pass


_FEATURES = {item["slug"]: deepcopy(item) for item in FEATURES}

DESIGN_GUIDANCE = {
    "landing_page": {
        "responsive": True,
        "layout": "fluid content grid",
        "viewports": {"compact_max_px": 639, "medium_min_px": 640, "wide_min_px": 1024},
    },
    "website_pages": {
        "shared_header": True,
        "shared_footer": True,
        "theme_assignment": "per-page",
        "user_switchable_theme": False,
        "available_styles": ["dark", "light"],
    },
    "dashboard": {
        "shell_regions": ["header", "side navigation panel", "canvas", "footer"],
        "canvas_layout": "responsive main content region",
    },
}


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


class CurrentInterfaceService:
    def __init__(self):
        shell = _attrs("admin-workspace-shell-styling")
        modes = list(shell.get("theme_modes") or ["light"])
        self.theme = modes[0]

    def routes(self):
        return [
            {"method": "GET", "path": "/api/pages"},
            {"method": "GET", "path": "/api/ui-shell"},
            {"method": "GET", "path": "/api/design-guidance"},
            {"method": "PATCH", "path": "/api/ui-shell/theme"},
        ]

    def pages(self):
        pages = {"landing"}
        for feature in _FEATURES.values():
            contexts = {str(item).lower() for item in feature.get("contexts") or []}
            pages.update(context.replace("_page", "").replace("_", "-")
                         for context in contexts if context.endswith("_page"))
        return {"pages": sorted(pages)}

    def ui_shell(self):
        shell = _attrs("admin-workspace-shell-styling")
        navigation = _attrs("admin-workspace-panel-navigation")
        return {
            "theme": self.theme,
            "theme_modes": list(shell.get("theme_modes") or ["light"]),
            "header": shell.get("header") or {},
            "footer": shell.get("footer") or {},
            "navigation": navigation.get("shell_navigation_panel") or {},
        }

    def set_theme(self, theme):
        theme = str(theme or "").strip().lower()
        modes = [str(item).lower() for item in self.ui_shell()["theme_modes"]]
        if theme not in modes:
            raise DomainError("unsupported theme")
        self.theme = theme
        return self.ui_shell()

    def design_guidance(self):
        return deepcopy(DESIGN_GUIDANCE)

    def request(self, method, path, payload=None, query=None):
        payload = payload or {}
        if method == "GET" and path == "/api/pages":
            return _ok(self.pages())
        if method == "GET" and path == "/api/ui-shell":
            return _ok(self.ui_shell())
        if method == "GET" and path == "/api/design-guidance":
            return _ok(self.design_guidance())
        if method == "PATCH" and path == "/api/ui-shell/theme":
            return _ok(self.set_theme(payload.get("theme")))
        return {"status": 404, "body": {"error": "route not found"}}


def make_service():
    return CurrentInterfaceService()
