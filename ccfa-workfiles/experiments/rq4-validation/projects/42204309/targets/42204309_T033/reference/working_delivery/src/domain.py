
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

from current_state import FEATURES


class DomainError(ValueError):
    pass


_FEATURES = {item["slug"]: deepcopy(item) for item in FEATURES}

BOOK_TITLE = "From Workshop Floor to Fresh Start"
REWARD_POLICY = {
    "coded": {"commission_usd": 12.0, "tickets": 4, "draw_amount_usd": 1250.0},
    "no_referral": {"commission_usd": 12.0, "tickets": 6, "draw_amount_usd": 900.0},
}
CODED_SUCCESS_COPY = "$12 commission + $1,250 prize draw ticket has gone to your chosen From Workshop Floor to Fresh Start NFT holder"
NO_REFERRAL_SUCCESS_COPY = "No referral code used. $12 commission + $1,250 prize draw ticket has gone to a From Workshop Floor to Fresh Start NFT holder at random"
PUBLIC_CONTENT = {
    "faq": "An accepted referral code gives the chosen NFT holder a $12 commission and four tickets for the $1,250 prize draw.",
    "about": "Accepted referrals reward the chosen NFT holder with a $12 commission and $1,250 prize-draw tickets; no-code rewards remain allocated by weighted draw.",
    "small_block_prize_usd": 1250,
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


class HarborQuillService:
    def __init__(self):
        self.referrals = {}
        self.accounts = {}
        self.sessions = {}
        self.mints = []
        self.holdings = {}
        self.reward_events = []

    def routes(self):
        return [
            {"method": "POST", "path": "/api/referrals"},
            {"method": "POST", "path": "/api/mints"},
            {"method": "POST", "path": "/api/auth/magic-links"},
            {"method": "POST", "path": "/api/auth/sessions"},
            {"method": "GET", "path": "/api/dashboard"},
            {"method": "GET", "path": "/api/content"},
        ]

    @staticmethod
    def _blank_account():
        return {"commission_usd": 0.0, "commission_count": 0, "tickets": {},
                "ticket_count": 0, "referrals": 0, "weighted_draw_allocations": 0}

    def _account(self, owner):
        return self.accounts.setdefault(owner, self._blank_account())

    def _weighted_owner(self, label):
        weighted = [(owner, count) for owner, count in sorted(self.holdings.items()) if count > 0]
        if not weighted:
            raise DomainError("no eligible NFT owner")
        total = sum(count for _, count in weighted)
        position = int(hashlib.sha256(str(label).encode("utf-8")).hexdigest(), 16) % total
        for owner, count in weighted:
            if position < count:
                return owner
            position -= count
        raise RuntimeError("weighted draw failed")

    def _credit(self, commission_owner, ticket_owner, reward, weighted):
        commission_account = self._account(commission_owner)
        commission_account["commission_usd"] += reward["commission_usd"]
        commission_account["commission_count"] += 1
        ticket_account = self._account(ticket_owner)
        draw = str(int(reward["draw_amount_usd"]))
        ticket_account["tickets"][draw] = ticket_account["tickets"].get(draw, 0) + reward["tickets"]
        ticket_account["ticket_count"] += reward["tickets"]
        if weighted:
            commission_account["weighted_draw_allocations"] += 1
            ticket_account["weighted_draw_allocations"] += 1

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
        self._account(owner)
        return {"owner": owner, "code": code}

    def request_magic_link(self, email):
        if not _feature("email-magic-link-authentication"):
            raise DomainError("email sign-in is not available")
        email = str(email).strip().lower()
        if "@" not in email:
            raise DomainError("a valid email is required")
        token = hashlib.sha256(("magic-link:" + email).encode("utf-8")).hexdigest()[:24]
        self.sessions[token] = email
        self._account(email)
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
        mint_id = len(self.mints) + 1
        self.holdings[buyer] = self.holdings.get(buyer, 0) + 1
        self._account(buyer)
        rewards = {"commission_usd": 0.0, "tickets": 0, "draw_amount_usd": None}
        reward_recipients = {"commission": None, "tickets": None}
        feedback_copy = "Mint confirmed"
        feedback_variant = "promotional"
        if not promotional:
            if owner:
                rewards = deepcopy(REWARD_POLICY["coded"])
                reward_recipients = {"commission": owner, "tickets": owner}
                self._account(owner)["referrals"] += 1
                weighted = False
                feedback_copy = CODED_SUCCESS_COPY
                feedback_variant = "coded-referral"
            else:
                rewards = deepcopy(REWARD_POLICY["no_referral"])
                reward_recipients = {
                    "commission": self._weighted_owner(f"mint:{mint_id}:commission"),
                    "tickets": self._weighted_owner(f"mint:{mint_id}:tickets"),
                }
                weighted = True
                feedback_copy = NO_REFERRAL_SUCCESS_COPY
                feedback_variant = "no-referral"
            self._credit(reward_recipients["commission"], reward_recipients["tickets"], rewards, weighted)
            self.reward_events.append({"mint_id": mint_id, "weighted_draw": weighted,
                                       "recipients": deepcopy(reward_recipients), **rewards})
        receipt = {
            "mint_id": mint_id,
            "token_id": mint_id,
            "buyer": buyer,
            "asset": asset,
            "charged_usd": price,
            "refund_usd_equivalent": round(supplied - price, 2),
            "referral": {"accepted": bool(owner), "owner": owner, **rewards},
            "reward_recipients": reward_recipients,
            "transaction_status": "confirmed",
            "feedback": {"title": "Mint successful", "variant": feedback_variant,
                         "copy": feedback_copy, "token_id": mint_id},
            "promotional": bool(promotional),
        }
        self.mints.append(receipt)
        return deepcopy(receipt)

    def dashboard(self, owner):
        owner = str(owner).strip()
        account = deepcopy(self.accounts.get(owner, self._blank_account())) if owner else {}
        return {"owner": owner, **account, "mint_count": len(self.mints),
                "reward_totals": {"commission_count": len(self.reward_events),
                                  "ticket_count": sum(item["tickets"] for item in self.reward_events)}}

    def content(self):
        return deepcopy(PUBLIC_CONTENT)

    def request(self, method, path, payload=None, query=None):
        payload, query = payload or {}, query or {}
        if method == "GET" and path == "/api/dashboard":
            return _ok(self.dashboard(query.get("owner", "")))
        if method == "GET" and path == "/api/content":
            return _ok(self.content())
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
