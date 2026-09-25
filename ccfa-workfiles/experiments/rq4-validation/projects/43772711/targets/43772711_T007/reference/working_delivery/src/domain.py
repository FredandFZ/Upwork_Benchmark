
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

from current_state import FEATURES


class DomainError(ValueError):
    pass


_FEATURES = {item["slug"]: deepcopy(item) for item in FEATURES}

SITE_SHELL = {
    "footer": {
        "background_color": "dark_purple",
        "background_hex": "#32105c",
        "organization": {
            "identity": "LumenArc Intelligence",
            "location": ["Harbor Glen", "Oregon, USA"],
            "email": "hello@lumenarc-demo.example",
            "phone": "(202) 555-0146",
        },
        "menu_links": [
            "Home", "Contact Us", "Support", "Cookie Notice",
            "Privacy Policy", "Terms of Use", "Legal",
        ],
        "social_links": ["LinkedIn", "X"],
        "copyright": "Copyright (c) 2032 LumenArc Systems LLC. All rights reserved",
    }
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


class LumenArcService:
    def __init__(self):
        self.sessions = {}
        self.accounts = {}
        shell = _attrs("admin-workspace-shell-styling")
        modes = shell.get("theme_modes") or ["light"]
        self.workspace = {"theme": modes[0], "navigation_collapsed": False}

    def routes(self):
        return [
            {"method": "GET", "path": "/api/pages"},
            {"method": "GET", "path": "/api/site-shell"},
            {"method": "POST", "path": "/api/auth/sessions"},
            {"method": "POST", "path": "/api/accounts"},
            {"method": "PATCH", "path": "/api/workspace"},
        ]

    def pages(self):
        pages = {"landing"}
        for feature in _FEATURES.values():
            contexts = {str(item).lower() for item in feature.get("contexts") or []}
            if "sign_in_page" in contexts:
                pages.add("sign-in")
            if "account_provisioning" in contexts:
                pages.add("account-provisioning")
            if "admin_workspace" in contexts:
                pages.add("admin-workspace")
        structure = _attrs("landing-page-content-structure")
        return {"pages": sorted(pages), "landing_sections": structure.get("section_order") or ["Hero"]}

    def site_shell(self):
        return deepcopy(SITE_SHELL)

    def sign_in(self, email):
        email = str(email).strip().lower()
        if "@" not in email:
            raise DomainError("a valid email is required")
        if "sign-in" not in self.pages()["pages"]:
            raise DomainError("sign-in is not available")
        token = hashlib.sha256(("session:" + email).encode("utf-8")).hexdigest()[:20]
        self.sessions[token] = email
        return {"authenticated": True, "email": email, "session": token}

    def provision_account(self, administrator, company, role="assistant", voice="default"):
        if "account-provisioning" not in self.pages()["pages"]:
            raise DomainError("account provisioning is not available")
        administrator, company = str(administrator).strip(), str(company).strip()
        if not administrator or not company:
            raise DomainError("administrator and company are required")
        account_id = "acct-" + hashlib.sha256((administrator + "|" + company).encode("utf-8")).hexdigest()[:10]
        account = {"account_id": account_id, "administrator": administrator, "company": company,
                   "agent": {"role": str(role), "voice": str(voice)}, "status": "provisioned"}
        self.accounts[account_id] = account
        return deepcopy(account)

    def update_workspace(self, theme=None, navigation_collapsed=None):
        modes = _attrs("admin-workspace-shell-styling").get("theme_modes") or ["light"]
        if theme is not None:
            if theme not in modes:
                raise DomainError("unsupported theme")
            self.workspace["theme"] = theme
        panel = _attrs("admin-workspace-panel-navigation").get("shell_navigation_panel") or {}
        if navigation_collapsed is not None:
            if navigation_collapsed and not panel.get("collapsible", False):
                raise DomainError("navigation is not collapsible")
            self.workspace["navigation_collapsed"] = bool(navigation_collapsed)
        return deepcopy(self.workspace)

    def request(self, method, path, payload=None, query=None):
        payload = payload or {}
        if method == "GET" and path == "/api/pages":
            return _ok(self.pages())
        if method == "GET" and path == "/api/site-shell":
            return _ok(self.site_shell())
        if method == "POST" and path == "/api/auth/sessions":
            return _ok(self.sign_in(payload.get("email")), 201)
        if method == "POST" and path == "/api/accounts":
            return _ok(self.provision_account(**payload), 201)
        if method == "PATCH" and path == "/api/workspace":
            return _ok(self.update_workspace(**payload))
        return {"status": 404, "body": {"error": "route not found"}}


def make_service():
    return LumenArcService()
