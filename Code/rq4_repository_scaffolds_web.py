from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


SUPPORTED_PROJECTS = {"42204309", "43772711", "43804272", "44035087"}


def _behavior_scaffold_is_available(project_id: str, features: list[dict]) -> bool:
    """Only emit a project-specific scaffold once all named capabilities exist.

    The source templates below intentionally contain concrete domain actions.  Emitting
    a complete template at an earlier boundary would reveal later requirements even if
    the actions were disabled at runtime.  Earlier snapshots therefore keep the neutral
    base repository until their public state contains the full scaffold vocabulary.
    """

    searchable = " ".join(
        str(value)
        for feature in features
        for value in (
            feature.get("slug", ""),
            feature.get("title", ""),
            *(feature.get("contexts") or []),
        )
    ).lower()
    requirements = {
        "42204309": (
            ("mint",),
            ("referral",),
            ("magic-link", "magic link"),
            ("eth-wallet-mint-flow",),
            ("usdc-wallet-mint-flow",),
        ),
        "43772711": (("provision", "account_provisioning"), ("sign-in", "sign_in"), ("workspace",)),
        "43804272": (("measure", "ruler", "scoliometer"), ("local", "right-to-left")),
        "44035087": (
            ("gallery",),
            ("quote", "pricing"),
            ("homepage-portfolio-tile-link",),
        ),
    }[project_id]
    return all(any(term in searchable for term in alternatives) for alternatives in requirements)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")


def _mobile_platform_model(features: list[dict]) -> dict:
    relevant = {}
    for feature in features:
        slug = str(feature.get("slug") or "")
        if any(
            term in slug
            for term in (
                "android",
                "ios",
                "local",
                "right-to-left",
                "permission",
                "privacy",
                "signing",
                "application-size",
            )
        ):
            relevant[slug] = dict(feature.get("attributes") or {})
    return {
        "schema_version": "mobile-platform-build-v1",
        "platforms": ["android", "ios"],
        "current_capabilities": relevant,
    }


DOMAIN_PREFIX = r'''
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

from current_state import FEATURES


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
'''


NFT_DOMAIN = DOMAIN_PREFIX + r'''

class HarborQuillService:
    def __init__(self):
        self.referrals = {}
        self.accounts = {}
        self.sessions = {}
        self.mints = []

    def routes(self):
        return [
            {"method": "POST", "path": "/api/referrals"},
            {"method": "POST", "path": "/api/mints"},
            {"method": "POST", "path": "/api/auth/magic-links"},
            {"method": "POST", "path": "/api/auth/sessions"},
            {"method": "GET", "path": "/api/dashboard"},
        ]

    def register_referral(self, owner, code=None):
        if not _has_term("referral"):
            raise DomainError("referrals are not available")
        owner = str(owner).strip()
        if not owner:
            raise DomainError("owner is required")
        code = str(code or owner).strip().upper()
        if not code or code in self.referrals:
            raise DomainError("referral code is unavailable")
        self.referrals[code] = owner
        self.accounts.setdefault(owner, {"commission_usd": 0.0, "tickets": {}, "referrals": 0})
        return {"owner": owner, "code": code}

    def request_magic_link(self, email):
        if not _feature("email-magic-link-authentication"):
            raise DomainError("email sign-in is not available")
        email = str(email).strip().lower()
        if "@" not in email:
            raise DomainError("a valid email is required")
        token = hashlib.sha256(("magic-link:" + email).encode("utf-8")).hexdigest()[:24]
        self.sessions[token] = email
        self.accounts.setdefault(email, {"commission_usd": 0.0, "tickets": {}, "referrals": 0})
        return {"email": email, "token": token, "delivery": "local-preview"}

    def sign_in(self, token):
        email = self.sessions.get(str(token))
        if not email:
            raise DomainError("invalid magic-link token")
        return {"authenticated": True, "account": email}

    def mint(self, buyer, amount_usd, asset="USDC", referral_code=None, promotional=False):
        if not _has_term("mint"):
            raise DomainError("minting is not available")
        buyer = str(buyer).strip()
        if not buyer:
            raise DomainError("buyer is required")
        asset = str(asset).upper()
        if asset == "ETH" and not _feature("eth-wallet-mint-flow"):
            raise DomainError("ETH payment is not available")
        if asset not in {"USDC", "ETH"}:
            raise DomainError("unsupported payment asset")
        pricing = _attrs("eth-pricing-and-excess-refund")
        price = _number(pricing.get("target_mint_price"), 30)
        supplied = _number(amount_usd)
        if supplied < price:
            raise DomainError("insufficient payment")
        accepted_code = str(referral_code or "").strip().upper()
        owner = self.referrals.get(accepted_code)
        rewards = {"commission_usd": 0.0, "tickets": 0, "draw_amount_usd": None}
        if owner and not promotional:
            commission = _attrs("coded-referral-commission")
            tickets = _attrs("coded-referral-ticket-issuance")
            rewards = {
                "commission_usd": _number(commission.get("commission_amount_usd")),
                "tickets": int(_number(tickets.get("tickets_per_coded_referral_mint"))),
                "draw_amount_usd": _number(tickets.get("reward_drawing_amount_usd")) or None,
            }
            account = self.accounts[owner]
            account["commission_usd"] += rewards["commission_usd"]
            draw = str(int(rewards["draw_amount_usd"] or 0))
            account["tickets"][draw] = account["tickets"].get(draw, 0) + rewards["tickets"]
            account["referrals"] += 1
        receipt = {
            "mint_id": len(self.mints) + 1,
            "buyer": buyer,
            "asset": asset,
            "charged_usd": price,
            "refund_usd_equivalent": round(supplied - price, 2),
            "referral": {"accepted": bool(owner), "owner": owner, **rewards},
            "promotional": bool(promotional),
        }
        self.mints.append(receipt)
        return deepcopy(receipt)

    def dashboard(self, owner):
        owner = str(owner).strip()
        account = self.accounts.get(owner, {"commission_usd": 0.0, "tickets": {}, "referrals": 0})
        return {"owner": owner, **deepcopy(account), "mint_count": len(self.mints)}

    def request(self, method, path, payload=None, query=None):
        payload, query = payload or {}, query or {}
        if method == "GET" and path == "/api/dashboard":
            return _ok(self.dashboard(query.get("owner", "")))
        if method == "POST" and path == "/api/referrals":
            return _ok(self.register_referral(payload.get("owner"), payload.get("code")), 201)
        if method == "POST" and path == "/api/mints":
            return _ok(self.mint(**payload), 201)
        if method == "POST" and path == "/api/auth/magic-links":
            return _ok(self.request_magic_link(payload.get("email")), 201)
        if method == "POST" and path == "/api/auth/sessions":
            return _ok(self.sign_in(payload.get("token")))
        return {"status": 404, "body": {"error": "route not found"}}


def make_service():
    return HarborQuillService()
'''


PRIZE_DOMAIN = DOMAIN_PREFIX + r'''

class CurrentPrizeService:
    def __init__(self):
        self.pools = {"small": 0.0, "big": 0.0}
        self.entries = {"small": {}, "big": {}}

    def routes(self):
        return [
            {"method": "GET", "path": "/api/prizes"},
            {"method": "POST", "path": "/api/prizes/contributions"},
            {"method": "POST", "path": "/api/prizes/draws"},
        ]

    def _rule(self, block):
        slug = "small-block-prize-mechanism" if block == "small" else "big-block-prize-mechanism"
        attrs = _attrs(slug)
        amount = _number(attrs.get("prize_amount_per_winner_usd") or
                         attrs.get("prize_amount_per_winner"))
        winners = int(_number(attrs.get("winner_count"), 0))
        return {"winner_count": winners, "prize_amount_usd": amount,
                "pool_target_usd": amount * winners}

    def prize_status(self):
        return {block: {"pool_usd": self.pools[block], "rule": self._rule(block),
                        "entry_count": sum(self.entries[block].values())}
                for block in ("small", "big")}

    def contribute(self, block, amount_usd, participant=None, entries=0):
        block = str(block or "").lower()
        if block not in self.pools:
            raise DomainError("unknown prize block")
        amount = _number(amount_usd)
        if amount < 0:
            raise DomainError("contribution must be non-negative")
        self.pools[block] += amount
        if participant and int(entries) > 0:
            key = str(participant)
            self.entries[block][key] = self.entries[block].get(key, 0) + int(entries)
        return self.prize_status()[block]

    def draw(self, block):
        block = str(block or "").lower()
        if block not in self.pools:
            raise DomainError("unknown prize block")
        rule = self._rule(block)
        if self.pools[block] < rule["pool_target_usd"]:
            raise DomainError("pool target has not been reached")
        ranked = sorted(self.entries[block], key=lambda key: (-self.entries[block][key], key))
        winners = ranked[:rule["winner_count"]]
        self.pools[block] = max(0.0, self.pools[block] - rule["pool_target_usd"])
        return {"block": block, "winners": winners, "rule": rule,
                "remaining_pool_usd": self.pools[block]}

    def request(self, method, path, payload=None, query=None):
        payload = payload or {}
        if method == "GET" and path == "/api/prizes":
            return _ok(self.prize_status())
        if method == "POST" and path == "/api/prizes/contributions":
            return _ok(self.contribute(**payload), 201)
        if method == "POST" and path == "/api/prizes/draws":
            return _ok(self.draw(payload.get("block")))
        return {"status": 404, "body": {"error": "route not found"}}


def make_service():
    return CurrentPrizeService()
'''


SAAS_DOMAIN = DOMAIN_PREFIX + r'''

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
        if method == "POST" and path == "/api/auth/sessions":
            return _ok(self.sign_in(payload.get("email")), 201)
        if method == "POST" and path == "/api/accounts":
            return _ok(self.provision_account(**payload), 201)
        if method == "PATCH" and path == "/api/workspace":
            return _ok(self.update_workspace(**payload))
        return {"status": 404, "body": {"error": "route not found"}}


def make_service():
    return LumenArcService()
'''


QUOTE_DOMAIN = DOMAIN_PREFIX + r'''

class SilverPineService:
    def __init__(self):
        self.gallery_selection = None
        self.quotes = []

    def routes(self):
        return [
            {"method": "GET", "path": "/api/gallery"},
            {"method": "POST", "path": "/api/gallery/selection"},
            {"method": "POST", "path": "/api/quotes"},
            {"method": "GET", "path": "/api/navigation"},
        ]

    def gallery(self):
        config = _attrs("gallery-browsing-and-organization")
        tabs = list(config.get("main_gallery_tabs") or [])
        return {"tabs": tabs, "selected": self.gallery_selection or (tabs[0] if tabs else None),
                "interaction": config.get("interaction_mode")}

    def select_gallery(self, tab):
        tab = str(tab).strip().lower()
        tabs = [str(item).lower() for item in self.gallery()["tabs"]]
        if tab not in tabs:
            raise DomainError("unknown gallery tab")
        self.gallery_selection = tab
        return self.gallery()

    @staticmethod
    def _category(square_feet):
        value = int(square_feet)
        if value < 1:
            raise DomainError("square_feet must be positive")
        if value <= 1200:
            return "under_1200_sqft"
        if value <= 2400:
            return "1201_2400_sqft"
        if value <= 3600:
            return "2401_3600_sqft"
        return "3600_plus_sqft"

    def quote(self, square_feet, package="basic", extras=None):
        pricing = _attrs("package-pricing-by-square-footage")
        key = self._category(square_feet)
        matrix = pricing.get(f"{str(package).lower()}_package_prices_by_square_footage")
        if matrix is None and str(package).lower() == "basic":
            matrix = pricing.get("basic_package_prices_by_square_footage")
        if not isinstance(matrix, dict) or key not in matrix:
            raise DomainError("the requested package has no configured price")
        base = _number(matrix[key])
        extras = list(extras or [])
        quote = {"quote_id": len(self.quotes) + 1, "package": str(package).lower(),
                 "square_feet": int(square_feet), "category": key, "base_price_usd": base,
                 "extras": extras, "total_usd": base}
        self.quotes.append(quote)
        return deepcopy(quote)

    def navigation(self):
        links = _attrs("homepage-section-button-links").get("button_destinations") or {}
        return {"links": deepcopy(links), "portfolio": _attrs("homepage-portfolio-tile-link").get("link_destination")}

    def request(self, method, path, payload=None, query=None):
        payload = payload or {}
        if method == "GET" and path == "/api/gallery":
            return _ok(self.gallery())
        if method == "POST" and path == "/api/gallery/selection":
            return _ok(self.select_gallery(payload.get("tab")))
        if method == "POST" and path == "/api/quotes":
            return _ok(self.quote(**payload), 201)
        if method == "GET" and path == "/api/navigation":
            return _ok(self.navigation())
        return {"status": 404, "body": {"error": "route not found"}}


def make_service():
    return SilverPineService()
'''


QUOTE_CORE_DOMAIN = DOMAIN_PREFIX + r'''

class CurrentGalleryQuoteService:
    def __init__(self):
        self.gallery_selection = None
        self.quotes = []

    def routes(self):
        return [
            {"method": "GET", "path": "/api/gallery"},
            {"method": "POST", "path": "/api/gallery/selection"},
            {"method": "POST", "path": "/api/quotes"},
        ]

    def gallery(self):
        config = _attrs("gallery-browsing-and-organization")
        tabs = list(config.get("main_gallery_tabs") or [])
        return {"tabs": tabs, "selected": self.gallery_selection or (tabs[0] if tabs else None),
                "interaction": config.get("interaction_mode")}

    def select_gallery(self, tab):
        tab = str(tab).strip().lower()
        tabs = [str(item).lower() for item in self.gallery()["tabs"]]
        if tab not in tabs:
            raise DomainError("unknown gallery tab")
        self.gallery_selection = tab
        return self.gallery()

    @staticmethod
    def _category(square_feet):
        area = _number(square_feet)
        if area <= 1200:
            return "under_1200_sqft"
        if area <= 2400:
            return "1201_2400_sqft"
        if area <= 3600:
            return "2401_3600_sqft"
        return "3600_plus_sqft"

    def quote(self, square_feet, package="basic", extras=None):
        pricing = _attrs("package-pricing-by-square-footage")
        table = pricing.get(f"{package}_package_prices_by_square_footage") or {}
        category = self._category(square_feet)
        raw = table.get(category)
        if raw is None:
            raise DomainError("package or square-footage band is unavailable")
        base = _number(raw)
        extras = list(extras or [])
        quote = {"quote_id": len(self.quotes) + 1, "square_feet": _number(square_feet),
                 "category": category, "package": package, "base_usd": base,
                 "extras": extras, "total_usd": base}
        self.quotes.append(quote)
        return deepcopy(quote)

    def request(self, method, path, payload=None, query=None):
        payload = payload or {}
        if method == "GET" and path == "/api/gallery":
            return _ok(self.gallery())
        if method == "POST" and path == "/api/gallery/selection":
            return _ok(self.select_gallery(payload.get("tab")))
        if method == "POST" and path == "/api/quotes":
            return _ok(self.quote(**payload), 201)
        return {"status": 404, "body": {"error": "route not found"}}


def make_service():
    return CurrentGalleryQuoteService()
'''


MOBILE_DOMAIN = DOMAIN_PREFIX + r'''

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
        media = _attrs("how-to-media-delivery")
        permissions = _attrs("android-permission-hygiene")
        return {
            "measurement_steps": _attrs("how-to-measurement-instructions").get("measurement_sequence") or [],
            "tutorial_delivery": media.get("video_delivery_method"),
            "tutorial_bundled": media.get("video_delivery_method") != "external_streaming",
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
'''


UI_SHELL_DOMAIN = DOMAIN_PREFIX + r'''

class CurrentInterfaceService:
    def __init__(self):
        shell = _attrs("admin-workspace-shell-styling")
        modes = list(shell.get("theme_modes") or ["light"])
        self.theme = modes[0]

    def routes(self):
        return [
            {"method": "GET", "path": "/api/pages"},
            {"method": "GET", "path": "/api/ui-shell"},
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

    def request(self, method, path, payload=None, query=None):
        payload = payload or {}
        if method == "GET" and path == "/api/pages":
            return _ok(self.pages())
        if method == "GET" and path == "/api/ui-shell":
            return _ok(self.ui_shell())
        if method == "PATCH" and path == "/api/ui-shell/theme":
            return _ok(self.set_theme(payload.get("theme")))
        return {"status": 404, "body": {"error": "route not found"}}


def make_service():
    return CurrentInterfaceService()
'''


MOBILE_PLATFORM_DOMAIN = DOMAIN_PREFIX + r'''

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
        }

    def set_locale(self, locale):
        locale = str(locale or "").strip().lower().replace("_", "-")
        if not locale:
            raise DomainError("locale is required")
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
'''


APPLICATION_SOURCE = r'''
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
'''


RUNTIME_SOURCE = r'''
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil

from application import create_app
from current_state import FEATURES, PROJECT


def feature_catalog():
    return deepcopy(FEATURES)


def get_feature(slug):
    for feature in FEATURES:
        if feature["slug"] == slug:
            return deepcopy(feature)
    raise KeyError(slug)


def simulate(slug):
    feature = get_feature(slug)
    execution = feature.get("execution") or {}
    return {"slug": slug, "status": execution.get("status", "AVAILABLE"),
            "observed_behavior": execution.get("observed_behavior"),
            "attributes": deepcopy(feature.get("attributes") or {})}


def build(output="dist"):
    output = Path(output)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    assets = Path(__file__).resolve().parents[1] / "web"
    page = "mobile-preview.html" if PROJECT["renderer"] == "mobile" else "index.html"
    shutil.copyfile(assets / "index.html", output / page)
    shutil.copyfile(assets / "app.js", output / "app.js")
    catalog_name = "app-config.json" if PROJECT["renderer"] == "mobile" else "catalog.json"
    payload = {"project": {"title": PROJECT["title"], "renderer": PROJECT["renderer"]},
               "routes": create_app().routes(), "features": feature_catalog()}
    (output / catalog_name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def check(output="dist"):
    output = Path(output)
    expected = [output / item.removeprefix("dist/") for item in PROJECT["primary_artifacts"]]
    missing = [str(path) for path in expected if not path.is_file() or not path.stat().st_size]
    if missing:
        raise RuntimeError(f"missing build artifacts: {missing}")
    page = output / ("mobile-preview.html" if PROJECT["renderer"] == "mobile" else "index.html")
    if "app.js" not in page.read_text(encoding="utf-8"):
        raise RuntimeError("interactive application script is missing")
    return {"renderer": PROJECT["renderer"], "artifact_count": len(expected),
            "feature_count": len(FEATURES), "route_count": len(create_app().routes())}
'''


SERVER_SOURCE = r'''
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from application import create_app
from runtime import build

APP = create_app()
build(ROOT / "dist")


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        payload = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _api(self):
        parsed = urlsplit(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length)) if length else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(400, {"error": "invalid JSON"})
            return
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        result = APP.request(self.command, parsed.path, payload, query)
        self._send(result["status"], result["body"])

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._api(); return
        name = "app.js" if self.path == "/app.js" else ("mobile-preview.html" if (ROOT / "dist" / "mobile-preview.html").exists() else "index.html")
        path = ROOT / "dist" / name
        if self.path not in {"/", "/app.js"} or not path.is_file():
            self.send_error(404); return
        kind = "application/javascript; charset=utf-8" if name == "app.js" else "text/html; charset=utf-8"
        self._send(200, path.read_bytes(), kind)

    def do_POST(self):
        self._api()

    def do_PATCH(self):
        self._api()


ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
'''


HTML_BY_PROJECT = {
    "42204309": ("Harbor Quill", "Mint an ebook", "Mint", "/api/mints"),
    "43772711": ("LumenArc", "Provision an AI colleague", "Provision", "/api/accounts"),
    "43804272": ("Measurement App", "Record a measurement", "Measure", "/api/measurements"),
    "44035087": ("Silver Pine Media", "Build a property quote", "Quote", "/api/quotes"),
}


def _html(project_id: str) -> str:
    title, heading, action, endpoint = HTML_BY_PROJECT[project_id]
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
:root{{--ink:#172033;--accent:#3659d9;--paper:#f4f7fb}}*{{box-sizing:border-box}}body{{margin:0;font:16px/1.5 system-ui;background:var(--paper);color:var(--ink)}}
header,main{{max-width:960px;margin:auto;padding:1.5rem}}header{{display:flex;justify-content:space-between;align-items:center}}.panel{{background:#fff;border:1px solid #d7deea;border-radius:16px;padding:1.5rem;box-shadow:0 12px 30px #17203312}}
form{{display:grid;gap:.8rem;max-width:560px}}label{{font-weight:650}}input{{padding:.8rem;border:1px solid #aab5c6;border-radius:8px}}button{{width:max-content;padding:.75rem 1.2rem;border:0;border-radius:9px;background:var(--accent);color:#fff;font-weight:700;cursor:pointer}}pre{{white-space:pre-wrap;background:#101827;color:#e8eefb;padding:1rem;border-radius:10px;min-height:5rem}}
</style></head><body data-project="{project_id}" data-endpoint="{endpoint}"><header><strong>{title}</strong><span>Offline preview</span></header>
<main><section class="panel"><h1>{heading}</h1><p>The form exercises the local application API. It does not require a network service.</p>
<form id="action-form"><div id="fields"></div><button type="submit">{action}</button></form><h2>Result</h2><pre id="result" aria-live="polite">Ready</pre></section></main><script src="app.js"></script></body></html>'''


JAVASCRIPT_SOURCE = r'''
const project = document.body.dataset.project;
const endpoint = document.body.dataset.endpoint;
const fieldSets = {
  "42204309": [["buyer", "Buyer", "reader@example.test"], ["amount_usd", "Amount (USD)", "30"], ["referral_code", "Referral code", ""]],
  "43772711": [["administrator", "Administrator", "admin@example.test"], ["company", "Company", "Example Co"], ["role", "Agent role", "assistant"]],
  "43804272": [["samples", "Angle samples", "2,8,5"]],
  "44035087": [["square_feet", "Square feet", "1800"], ["package", "Package", "basic"]]
};
const fields = document.querySelector("#fields");
for (const [name, label, value] of fieldSets[project]) {
  const wrapper = document.createElement("label");
  wrapper.textContent = label;
  const input = document.createElement("input"); input.name = name; input.value = value;
  wrapper.appendChild(input); fields.appendChild(wrapper);
}
document.querySelector("#action-form").addEventListener("submit", async event => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.currentTarget));
  if (project === "43804272") data.samples = data.samples.split(",").map(Number);
  if (data.amount_usd) data.amount_usd = Number(data.amount_usd);
  if (data.square_feet) data.square_feet = Number(data.square_feet);
  const response = await fetch(endpoint, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(data)});
  document.querySelector("#result").textContent = JSON.stringify(await response.json(), null, 2);
});
'''


GENERATED_TEST_SOURCE = r'''
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from application import create_app
from runtime import build, check


class DomainSmokeTest(unittest.TestCase):
    def test_routes_are_callable(self):
        app = create_app()
        self.assertTrue(app.routes())
        for route in app.routes():
            self.assertTrue(route["path"].startswith("/api/"))

    def test_interactive_build(self):
        with tempfile.TemporaryDirectory() as directory:
            build(directory)
            result = check(directory)
            self.assertGreater(result["route_count"], 0)


if __name__ == "__main__":
    unittest.main()
'''


DOMAIN_BY_PROJECT = {
    "42204309": NFT_DOMAIN,
    "43772711": SAAS_DOMAIN,
    "43804272": MOBILE_DOMAIN,
    "44035087": QUOTE_DOMAIN,
}


PUBLIC_CONTRACTS = {
    "42204309": {
        "domain": "referral_minting",
        "service": "domain.HarborQuillService",
        "actions": ["register_referral", "request_magic_link", "sign_in", "mint", "dashboard"],
        "routes": [
            {"method": "POST", "path": "/api/referrals"},
            {"method": "POST", "path": "/api/mints"},
            {"method": "POST", "path": "/api/auth/magic-links"},
            {"method": "POST", "path": "/api/auth/sessions"},
            {"method": "GET", "path": "/api/dashboard"},
        ],
    },
    "43772711": {
        "domain": "saas_provisioning",
        "service": "domain.LumenArcService",
        "actions": ["pages", "sign_in", "provision_account", "update_workspace"],
        "routes": [
            {"method": "GET", "path": "/api/pages"},
            {"method": "POST", "path": "/api/auth/sessions"},
            {"method": "POST", "path": "/api/accounts"},
            {"method": "PATCH", "path": "/api/workspace"},
        ],
    },
    "43804272": {
        "domain": "mobile_measurement",
        "service": "domain.MeasurementService",
        "actions": ["config", "measure", "set_locale"],
        "routes": [
            {"method": "GET", "path": "/api/app/config"},
            {"method": "POST", "path": "/api/measurements"},
            {"method": "POST", "path": "/api/locales"},
        ],
    },
    "44035087": {
        "domain": "media_quote",
        "service": "domain.SilverPineService",
        "actions": ["gallery", "select_gallery", "quote", "navigation"],
        "routes": [
            {"method": "GET", "path": "/api/gallery"},
            {"method": "POST", "path": "/api/gallery/selection"},
            {"method": "POST", "path": "/api/quotes"},
            {"method": "GET", "path": "/api/navigation"},
        ],
    },
}


def augment_web_repository(
    destination: Path,
    project_id: str,
    features: list[dict],
    profile: Mapping,
) -> None:
    """Add an offline, behavior-oriented application layer to a generated repository.

    ``features`` is the already replayed pre-task state.  It is used for validation here;
    generated domain code reads the same state from ``src/current_state.py`` at runtime.
    """
    destination = Path(destination)
    if project_id not in SUPPORTED_PROJECTS:
        raise ValueError(f"unsupported project_id: {project_id}")
    expected_renderer = "mobile" if project_id == "43804272" else "web"
    if profile.get("renderer") != expected_renderer:
        raise ValueError(f"project {project_id} requires renderer {expected_renderer}")
    if not destination.is_dir() or not (destination / "src" / "current_state.py").is_file():
        raise ValueError("destination must be a materialized repository")
    if not isinstance(features, list) or any(not isinstance(item, dict) for item in features):
        raise TypeError("features must be a list of dictionaries")
    slugs = [item.get("slug") for item in features]
    if any(not slug for slug in slugs) or len(slugs) != len(set(slugs)):
        raise ValueError("features must have unique non-empty slugs")
    full_scaffold = _behavior_scaffold_is_available(project_id, features)
    domain_source = DOMAIN_BY_PROJECT[project_id]
    contract = dict(PUBLIC_CONTRACTS[project_id])
    if not full_scaffold and project_id == "42204309":
        domain_source = PRIZE_DOMAIN
        contract = {
            "domain": "current_prize_system",
            "service": "domain.CurrentPrizeService",
            "actions": ["prize_status", "contribute", "draw"],
            "routes": [
                {"method": "GET", "path": "/api/prizes"},
                {"method": "POST", "path": "/api/prizes/contributions"},
                {"method": "POST", "path": "/api/prizes/draws"},
            ],
        }
    elif not full_scaffold and project_id == "43772711":
        domain_source = UI_SHELL_DOMAIN
        contract = {
            "domain": "current_interface_shell",
            "service": "domain.CurrentInterfaceService",
            "actions": ["pages", "ui_shell", "set_theme"],
            "routes": [
                {"method": "GET", "path": "/api/pages"},
                {"method": "GET", "path": "/api/ui-shell"},
                {"method": "PATCH", "path": "/api/ui-shell/theme"},
            ],
        }
    elif not full_scaffold and project_id == "43804272":
        domain_source = MOBILE_PLATFORM_DOMAIN
        contract = {
            "domain": "mobile_platform_configuration",
            "service": "domain.CurrentMobileService",
            "actions": ["config", "set_locale"],
            "routes": [
                {"method": "GET", "path": "/api/app/config"},
                {"method": "POST", "path": "/api/locales"},
            ],
        }
    elif not full_scaffold and project_id == "44035087":
        domain_source = QUOTE_CORE_DOMAIN
        contract = {
            "domain": "current_gallery_quote",
            "service": "domain.CurrentGalleryQuoteService",
            "actions": ["gallery", "select_gallery", "quote"],
            "routes": [
                {"method": "GET", "path": "/api/gallery"},
                {"method": "POST", "path": "/api/gallery/selection"},
                {"method": "POST", "path": "/api/quotes"},
            ],
        }

    _write(destination / "src" / "domain.py", domain_source)
    _write(destination / "src" / "application.py", APPLICATION_SOURCE)
    _write(destination / "src" / "runtime.py", RUNTIME_SOURCE)
    _write(destination / "scripts" / "serve.py", SERVER_SOURCE)
    _write(destination / "web" / "index.html", _html(project_id))
    _write(destination / "web" / "app.js", JAVASCRIPT_SOURCE)
    _write(destination / "tests" / "test_domain_behavior.py", GENERATED_TEST_SOURCE)
    if project_id == "43804272":
        _write(
            destination / "src" / "platform_build.py",
            "PLATFORM_BUILD = "
            + repr(_mobile_platform_model(features))
            + "\n",
        )
    contract = {
        "schema_version": "rq4-public-behavior-contract-v1",
        "project_id": project_id,
        **contract,
        "application_factory": "application.create_app",
        "request_interface": "Application.request(method, path, payload=None, query=None)",
        "availability": "Actions are enabled only by the current pre-task feature state.",
        "offline": True,
        "artifacts": list(profile.get("primary_artifacts") or []),
        "platform_build_model": (
            "src/platform_build.py:PLATFORM_BUILD"
            if project_id == "43804272"
            else None
        ),
        "observable_surfaces": (
            [
                "native_or_equivalent_app_model",
                "resource_and_locale_model",
                "app_interaction",
                "platform_build_metadata",
            ]
            if project_id == "43804272"
            else ["domain_behavior", "routes", "dom_semantics", "browser_interaction"]
        ),
    }
    _write(
        destination / "behavior_contract.json",
        json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True),
    )
