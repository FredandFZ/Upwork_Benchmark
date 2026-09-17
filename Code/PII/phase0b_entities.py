"""Phase 0B: LLM PII discovery, with local identity resolution.

Two decisions shape this module.

**Policy is not the model's choice.**  ``TYPE_POLICY`` maps each entity type to
exactly one policy and the validator enforces it, so the v7 reversal -- public
third parties such as GitHub, Stripe, AWS and Brevo are *preserved*, not
replaced -- lives in code.  A prompt regression cannot resurrect v6's brand
replacement.

**Global ids are assigned locally.**  The model returns message-local
occurrences plus a ``normalized_value`` and an optional ``link_hint``; entity
ids and identity bundles are derived deterministically here.  v6 let the model
allocate global placeholder indices and checked them against a running counter
(``Code/PII_Clean.py:505-568``, ``:2350-2361``), which forced strictly
sequential batches and made resume so fragile that it had to stop checkpointing
at the first hole (``:3514-3531``).  Deriving ids from the merged records makes
them a pure function of the per-message results: a gap poisons nothing, and the
registry hash is stable across runs.
"""

from __future__ import annotations

import re

from typing import Any, Mapping, Sequence

from .errors import PiiValidationError, marked
from .models import IdentityBundle, PiiEntity, PiiEntityRegistry, PiiOccurrence, SafeMessage
from .textutil import (
    ANGLE_URL_RE,
    EMAIL_RE,
    HANDLE_RE,
    INTERNAL_TOKEN_RE,
    PHONE_RE,
    URL_RE,
    WALLET_ADDRESS_RE,
    find_terms_outside_pii,
    literal_term_pattern,
    overlaps_any,
)

# --------------------------------------------------------------------------- #
# Taxonomy
# --------------------------------------------------------------------------- #

POLICY_SYNTHESIZE = "SYNTHESIZE"
POLICY_PRESERVE = "PRESERVE"
POLICY_PROTECTED = "PROTECTED"
POLICIES: tuple[str, ...] = (POLICY_SYNTHESIZE, POLICY_PRESERVE, POLICY_PROTECTED)

TYPE_POLICY: Mapping[str, str] = {
    # Directly identifying a person
    "PERSON": POLICY_SYNTHESIZE,
    "EMAIL": POLICY_SYNTHESIZE,
    "PHONE": POLICY_SYNTHESIZE,
    "PERSONAL_USERNAME": POLICY_SYNTHESIZE,
    "SOCIAL_ACCOUNT": POLICY_SYNTHESIZE,
    # Identifying a private project or organization
    "PROJECT_NAME": POLICY_SYNTHESIZE,
    "PRIVATE_ORGANIZATION": POLICY_SYNTHESIZE,
    "PRIVATE_DOMAIN": POLICY_SYNTHESIZE,
    "PRIVATE_REPOSITORY": POLICY_SYNTHESIZE,
    "PRIVATE_URL": POLICY_SYNTHESIZE,
    "MEETING_URL": POLICY_SYNTHESIZE,
    # Place and personal circumstance
    "LOCATION": POLICY_SYNTHESIZE,
    "ADDRESS": POLICY_SYNTHESIZE,
    "PERSONAL_CONTEXT": POLICY_SYNTHESIZE,
    "UNIQUE_BIOGRAPHICAL_DETAIL": POLICY_SYNTHESIZE,
    # Accounts and chain identifiers
    "ACCOUNT_IDENTIFIER": POLICY_SYNTHESIZE,
    "WALLET_ADDRESS": POLICY_SYNTHESIZE,
    # Credentials -- already shielded in phase 0A, rendered in phase 6A
    "SECRET": POLICY_PROTECTED,
    "SECRET_CANDIDATE": POLICY_PROTECTED,
    # Not PII merely by being named
    "PUBLIC_THIRD_PARTY": POLICY_PRESERVE,
    "PUBLIC_TECHNOLOGY": POLICY_PRESERVE,
    "NON_PII": POLICY_PRESERVE,
}

ENTITY_TYPES: tuple[str, ...] = tuple(TYPE_POLICY)

CONFIDENCES = frozenset({"HIGH", "MEDIUM", "LOW"})

# Bundle grouping.  A bundle is synthesized as a unit so a person and their
# address, or an organization and its domain, cannot drift apart.
PERSON_BUNDLE_TYPES = frozenset(
    {"PERSON", "EMAIL", "PHONE", "PERSONAL_USERNAME", "SOCIAL_ACCOUNT", "ACCOUNT_IDENTIFIER"}
)
ORG_BUNDLE_TYPES = frozenset(
    {
        "PROJECT_NAME",
        "PRIVATE_ORGANIZATION",
        "PRIVATE_DOMAIN",
        "PRIVATE_REPOSITORY",
        "PRIVATE_URL",
        "MEETING_URL",
    }
)
BUNDLE_KIND_PERSON = "PERSON_IDENTITY"
BUNDLE_KIND_ORG = "ORGANIZATION_IDENTITY"
BUNDLE_KIND_SINGLETON = "SINGLETON"

# Public names that are requirement content, not PII.  v6's two lists
# (``PII_Clean.py:152`` preserved terms and ``:177`` public services, which it
# force-replaced) merge into one preserve allowlist here, plus the entries the
# v7 specification names but v6 lacked.
PUBLIC_ALLOWLIST: tuple[str, ...] = (
    # Public companies and services
    "AWS", "Amazon Web Services", "Microsoft Azure", "Azure", "Microsoft",
    "Google", "Google Cloud Platform", "Google Drive", "Gmail", "GoDaddy",
    "Apple", "Meta", "Facebook", "Instagram", "WhatsApp", "GitHub", "GitLab",
    "OpenAI", "ChatGPT", "Anthropic", "Claude", "MongoDB", "Firebase",
    "Supabase", "Coinbase Commerce", "Coinbase Pay", "Coinbase", "Stripe",
    "Brevo", "Sendgrid", "Mailgun", "Mailchimp", "Twilio", "MoonPay",
    "Ramp Network", "Wyre", "Transak", "Uniswap", "Alchemy", "Infura",
    "Pinata", "Filecoin", "IPFS", "Lit Protocol", "Aave", "Basescan",
    "OpenSea", "Visa", "Mastercard", "PayPal", "Shopify", "Slack", "Zoom",
    "Cloudflare", "Vercel", "Netlify", "Heroku", "DigitalOcean", "Atlassian",
    "Jira", "Trello", "Notion", "Figma", "Canva", "Dropbox", "OneDrive",
    "YouTube", "LinkedIn", "IBM", "SAP", "JLCPCB", "LCSC", "EasyEDA", "Upwork",
    # Public technologies, protocols and domain concepts
    "gamification mechanics", "gameification mechanics", "Visual Studio Code",
    "React Native", "Ruby on Rails", "JavaScript", "TypeScript", "WordPress",
    "Docker", "Kubernetes", "FastAPI", "GraphQL", "PostgreSQL", "Solidity",
    "Ethereum", "Chainlink VRF", "Chainlink", "OAuth", "USDC", "ETH", "BTC",
    "KYC", "ERC-721C", "ERC-721", "ERC-1155", "ERC-20", "AES-256", "SHA-256",
    "Base Mainnet", "Base Sepolia", "Sepolia", "Holesky", "Foundry", "Anvil",
    "Hardhat", "ethers.js", "viem", "Datil", "Serrano", "Mint event",
    "Transfer event",
)

TASK = (
    "Classify every privacy-sensitive occurrence and every listed public requirement "
    "term in each supplied message. Do not rewrite the messages."
)

REPAIR_INSTRUCTION = (
    "The previous response failed local validation. Return exactly one entry for every "
    "supplied message, echoing message_id with its original JSON type. Every occurrence "
    "must quote an exact substring of that message's text with correct start/end offsets, "
    "use one of the allowed entity types, and carry the policy fixed for that type. "
    "Public companies, public services and public technologies are PUBLIC_THIRD_PARTY or "
    "PUBLIC_TECHNOLOGY with policy PRESERVE. Every <SECRET_CANDIDATE:...> token is "
    "SECRET_CANDIDATE with policy PROTECTED. Do not omit any email address, link, social "
    "handle or phone number that appears in the text. An ordinary lowercase word is not "
    "a PROJECT_NAME alias merely because it is one token inside a multiword project name. "
    "Every listed public tool or technology present in prose must be returned once with "
    "PRESERVE, and repeated exact private source text must use one normalized identity."
)


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


def build_sections(items: Sequence[SafeMessage]) -> dict[str, Any]:
    return {
        "POLICY": {
            "entity_types": list(ENTITY_TYPES),
            "type_policy": dict(TYPE_POLICY),
            "confidences": sorted(CONFIDENCES),
            "preserve_allowlist": list(PUBLIC_ALLOWLIST),
        },
        "SAFE_MESSAGES": [
            {
                "ordinal": item.ordinal,
                "message_id": item.message_id,
                "speaker": item.speaker,
                "text": item.safe_text,
            }
            for item in items
        ],
        "SECRET_TOKENS": sorted(
            {token for item in items for token in item.secret_tokens}
        ),
    }


def shard_sizer(item: SafeMessage) -> int:
    return len(item.safe_text) + 120


# --------------------------------------------------------------------------- #
# Coverage: which spans the model is not allowed to miss
# --------------------------------------------------------------------------- #


def _phone_digit_count(value: str) -> int:
    return sum(1 for character in value if character.isdigit())


def required_coverage_spans(safe_text: str) -> list[tuple[int, int, str]]:
    """Spans whose omission is a validation failure, not a judgement call.

    Regex-certain PII only.  A missed email address must fail the response
    rather than pass silently, but ``PHONE_RE`` is loose enough to match dates
    and long identifiers, so only clearly phone-shaped runs are required.
    """

    spans: list[tuple[int, int, str]] = []
    for pattern, label in (
        (EMAIL_RE, "EMAIL"),
        (ANGLE_URL_RE, "URL"),
        (URL_RE, "URL"),
        (HANDLE_RE, "HANDLE"),
        (WALLET_ADDRESS_RE, "WALLET_ADDRESS"),
    ):
        for match in pattern.finditer(safe_text):
            start, end = match.span()
            if label == "HANDLE":
                # ``HANDLE_RE`` allows '.' inside a handle, so it swallows a
                # sentence-final period.  Trim it, or the demanded value is
                # ``@Team.`` while the model correctly reports ``@Team``.
                while end > start and safe_text[end - 1] in ".,;:!?":
                    end -= 1
            spans.append((start, end, label))
    for match in PHONE_RE.finditer(safe_text):
        value = match.group(0)
        if _phone_digit_count(value) >= 9 and value.count("-") < 3:
            spans.append((*match.span(), "PHONE"))
    # Public tools and technical standards are not PII, but they are immutable
    # requirements.  Requiring one reported occurrence makes their PRESERVE
    # policy explicit instead of depending on optional model recall.
    for term in find_terms_outside_pii(safe_text, PUBLIC_ALLOWLIST):
        for match in re.finditer(literal_term_pattern(term), safe_text, flags=re.IGNORECASE):
            if overlaps_any(match.span(), [item[:2] for item in spans]):
                continue
            spans.append((*match.span(), "PUBLIC_REQUIREMENT"))
            break
    # Deduplicate nested spans, keeping the widest.
    spans.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: list[tuple[int, int, str]] = []
    for span in spans:
        if overlaps_any(span[:2], [item[:2] for item in selected]):
            continue
        selected.append(span)
    return selected


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def validate_discovery_response(
    payload: Mapping[str, Any], items: Sequence[SafeMessage]
) -> dict[int, tuple[PiiOccurrence, ...]]:
    """Validate one response and project it onto occurrence records."""

    failures: list[str] = []

    def fail(code: str, detail: str) -> None:
        failures.append(f"{code}: {detail}")

    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list):
        raise PiiValidationError(
            marked("DISCOVERY_SCHEMA_INVALID: response must contain a messages list"),
            failures=("DISCOVERY_SCHEMA_INVALID",),
        )

    expected = {item.ordinal: item for item in items}
    seen: set[int] = set()
    result: dict[int, tuple[PiiOccurrence, ...]] = {}

    for index, entry in enumerate(raw_messages):
        if not isinstance(entry, dict):
            fail("DISCOVERY_SCHEMA_INVALID", f"messages[{index}] must be an object")
            continue
        ordinal = entry.get("ordinal")
        if not isinstance(ordinal, int) or ordinal not in expected:
            fail("DISCOVERY_MISSING_MESSAGE", f"messages[{index}] has an unknown ordinal")
            continue
        if ordinal in seen:
            fail("DISCOVERY_SCHEMA_INVALID", f"ordinal {ordinal} appears twice")
            continue
        seen.add(ordinal)
        message = expected[ordinal]
        occurrences = entry.get("occurrences")
        if not isinstance(occurrences, list):
            fail("DISCOVERY_SCHEMA_INVALID", f"ordinal {ordinal} has no occurrences list")
            continue

        records: list[PiiOccurrence] = []
        taken: list[tuple[int, int]] = []
        for position, item in enumerate(occurrences):
            where = f"ordinal {ordinal} occurrence {position}"
            if not isinstance(item, dict):
                fail("DISCOVERY_SCHEMA_INVALID", f"{where} must be an object")
                continue
            source = item.get("source")
            entity_type = item.get("entity_type")
            policy = item.get("policy")
            confidence = item.get("confidence", "MEDIUM")
            start = item.get("start")
            end = item.get("end")
            if not isinstance(source, str) or not source:
                fail("DISCOVERY_SCHEMA_INVALID", f"{where} has no source string")
                continue
            if entity_type not in TYPE_POLICY:
                fail("DISCOVERY_CATEGORY_UNKNOWN", f"{where} type {entity_type!r}")
                continue
            if policy is not None and policy != TYPE_POLICY[entity_type]:
                fail(
                    "DISCOVERY_CATEGORY_UNKNOWN",
                    f"{where} policy {policy!r} contradicts the fixed policy for "
                    f"{entity_type}",
                )
                continue
            if confidence not in CONFIDENCES:
                fail("DISCOVERY_SCHEMA_INVALID", f"{where} confidence {confidence!r}")
                continue
            if not isinstance(start, int) or not isinstance(end, int):
                # Offsets are recoverable when the quote is unambiguous.
                found = message.safe_text.find(source)
                if found < 0:
                    fail("DISCOVERY_SPAN_NOT_FOUND", f"{where} source is not in the text")
                    continue
                start, end = found, found + len(source)
            if not (0 <= start < end <= len(message.safe_text)):
                fail("DISCOVERY_SPAN_NOT_FOUND", f"{where} offsets are out of range")
                continue
            if message.safe_text[start:end] != source:
                found = message.safe_text.find(source)
                if found < 0:
                    fail("DISCOVERY_SPAN_NOT_FOUND", f"{where} source does not match offsets")
                    continue
                start, end = found, found + len(source)
            if overlaps_any((start, end), taken):
                # A nested declaration -- the whole address plus its domain, say --
                # is a known model habit and is harmless: the maximal span already
                # covers the value, and `merge_entity_registry` groups by value, so
                # the inner record would only duplicate it.  Dropping the redundant
                # record is strictly better than rejecting an otherwise correct
                # response, which on a long message can be unsatisfiable in
                # practice.  Genuine partial overlaps resolve the same way:
                # keep-maximal, deterministically.
                if any(
                    taken_start <= start and end <= taken_end
                    for taken_start, taken_end in taken
                ):
                    continue
                replaced = [
                    index
                    for index, (taken_start, taken_end) in enumerate(taken)
                    if start <= taken_start and taken_end <= end
                ]
                if not replaced:
                    fail(
                        "DISCOVERY_SCHEMA_INVALID",
                        f"{where} partially overlaps another occurrence",
                    )
                    continue
                for index in reversed(replaced):
                    del taken[index]
                    del records[index]
            if INTERNAL_TOKEN_RE.fullmatch(source) and entity_type != "SECRET_CANDIDATE":
                fail(
                    "DISCOVERY_CATEGORY_UNKNOWN",
                    f"{where} is a shielded secret token but typed {entity_type}",
                )
                continue
            taken.append((start, end))
            normalized = item.get("normalized_value")
            link_hint = item.get("link_hint")
            records.append(
                PiiOccurrence(
                    ordinal=ordinal,
                    message_id=message.message_id,
                    source=source,
                    start=start,
                    end=end,
                    entity_type=entity_type,
                    policy=TYPE_POLICY[entity_type],
                    normalized_value=(
                        normalized.strip()
                        if isinstance(normalized, str) and normalized.strip()
                        else source.strip()
                    ),
                    link_hint=link_hint if isinstance(link_hint, str) and link_hint else None,
                    confidence=confidence,
                )
            )

        # Coverage: regex-certain PII may not be silently dropped.
        #
        # Checked per *value*, not per repetition.  What must hold is that the
        # value is discovered for this message -- that is what puts the entity in
        # this message's plan slice, and phase 3 then replaces every occurrence of
        # it in the text by value.  Demanding a separate record for each
        # repetition rejects a response that found the address once where it
        # appears twice, which is correct work.
        taken_spans = [(item.start, item.end) for item in records]
        covered_values = {item.source.casefold() for item in records}
        reported: set[str] = set()
        for start, end, label in required_coverage_spans(message.safe_text):
            value = message.safe_text[start:end]
            if value.casefold() in covered_values:
                continue
            if overlaps_any((start, end), taken_spans):
                continue
            if value.casefold() in reported:
                continue
            reported.add(value.casefold())
            fail(
                "DISCOVERY_COVERAGE_GAP",
                f"ordinal {ordinal} omitted a {label} present in the text",
            )

        # Every shielded secret token must be accounted for.
        for match in INTERNAL_TOKEN_RE.finditer(message.safe_text):
            if match.group(0).casefold() in covered_values:
                continue
            if not overlaps_any(match.span(), taken_spans):
                fail(
                    "DISCOVERY_COVERAGE_GAP",
                    f"ordinal {ordinal} omitted a shielded secret token",
                )

        # A name on the public allowlist must not be called private.
        for term in find_terms_outside_pii(message.safe_text, PUBLIC_ALLOWLIST):
            for record in records:
                if (
                    record.source.casefold() == term.casefold()
                    and record.entity_type not in ("PUBLIC_THIRD_PARTY", "PUBLIC_TECHNOLOGY", "NON_PII")
                ):
                    fail(
                        "DISCOVERY_CATEGORY_UNKNOWN",
                        f"ordinal {ordinal} classified a public name as "
                        f"{record.entity_type}",
                    )

        result[ordinal] = tuple(records)

    missing = sorted(set(expected).difference(seen))
    if missing:
        fail("DISCOVERY_MISSING_MESSAGE", f"omitted ordinals {missing[:20]}")

    if failures:
        raise PiiValidationError(
            marked("phase 0B validation failed: " + "; ".join(failures[:10])),
            failures=tuple(item.split(":", 1)[0] for item in failures),
        )
    return result


def validate_cached_occurrences(body: Any) -> None:
    """Re-validate a restored checkpoint body with the current rules."""

    if not isinstance(body, dict) or "occurrences" not in body:
        raise PiiValidationError(marked("cached 0B record has no occurrences"))
    for item in body["occurrences"]:
        occurrence = PiiOccurrence.from_json(item)
        if occurrence.entity_type not in TYPE_POLICY:
            raise PiiValidationError(
                marked(f"cached 0B record uses unknown type {occurrence.entity_type}")
            )
        if occurrence.policy != TYPE_POLICY[occurrence.entity_type]:
            raise PiiValidationError(
                marked(
                    f"cached 0B policy {occurrence.policy} no longer matches "
                    f"{occurrence.entity_type}"
                )
            )


# --------------------------------------------------------------------------- #
# Local identity resolution
# --------------------------------------------------------------------------- #


class _Union:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def add(self, key: str) -> None:
        self._parent.setdefault(key, key)

    def find(self, key: str) -> str:
        self.add(key)
        root = key
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[key] != root:
            self._parent[key], key = root, self._parent[key]
        return root

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            # Lower key wins so grouping is deterministic regardless of order.
            if right_root < left_root:
                left_root, right_root = right_root, left_root
            self._parent[right_root] = left_root


def _domain_of(value: str) -> str:
    host = value.split("://", 1)[-1]
    host = host.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    host = host.split("@", 1)[-1]
    return host.split(":", 1)[0].strip("<>").casefold()


BARE_NUMERAL_RE = re.compile(r"^[#no.\s]*\d{1,4}[.)\s]*$", re.IGNORECASE)


def _is_identifying(entity_type: str, value: str) -> bool:
    """Whether this value can identify anything at all.

    A bare numeral cannot.  ``1`` was extracted as an ACCOUNT_IDENTIFIER from
    ordinals and list markers ("option 1", "step 1"), and planning a
    replacement for it asks every later phase to turn every standalone ``1`` in
    the project into some other number -- corrupting counts and amounts where it
    lands, and unsatisfiable everywhere else.

    Such a value is *dropped* rather than marked PRESERVE: a PRESERVE entity
    becomes a must-appear-verbatim literal for the rewrite, which would then
    forbid the slot plan from re-valuing any amount that happens to contain it.
    It is neither an identity to disguise nor a term to protect.

    Length alone would be the wrong test -- a two-letter personal name is real
    PII.  Being *only* digits and list punctuation is the actual signal.
    """

    if TYPE_POLICY[entity_type] != POLICY_SYNTHESIZE:
        return True
    return not BARE_NUMERAL_RE.match(value.strip())


def _is_identifying_occurrence(occurrence: PiiOccurrence) -> bool:
    """Reject weak project-name expansions of ordinary lowercase words.

    A medium/low-confidence ``rebuild`` occurrence normalized to ``Project
    Rebuild`` does not make the verb an alias of the project.  Proper-cased or
    high-confidence short forms remain eligible, as do complete multiword
    names.  This keeps the rule general without maintaining a vocabulary of
    English verbs.
    """

    if not _is_identifying(occurrence.entity_type, occurrence.normalized_value):
        return False
    source = occurrence.source.strip()
    normalized_tokens = re.findall(r"[A-Za-z]+", occurrence.normalized_value)
    is_weak_project_fragment = (
        occurrence.entity_type == "PROJECT_NAME"
        and occurrence.confidence != "HIGH"
        and source.isalpha()
        and source == source.casefold()
        and len(normalized_tokens) > 1
        and source.casefold() in {item.casefold() for item in normalized_tokens}
    )
    return not is_weak_project_fragment


def merge_entity_registry(
    per_message: Mapping[int, Sequence[PiiOccurrence]]
) -> PiiEntityRegistry:
    """Derive project-wide entities and identity bundles, deterministically.

    Grouping key is ``(entity_type, casefolded normalized value)``; ids follow
    first-occurrence order.  Bundles come from the transitive closure of the
    model's ``link_hint`` plus a local rule that ties an address or link to the
    private domain it sits under.
    """

    grouped: dict[tuple[str, str], list[PiiOccurrence]] = {}
    order: list[tuple[str, str]] = []
    for ordinal in sorted(per_message):
        for occurrence in per_message[ordinal]:
            if not _is_identifying_occurrence(occurrence):
                continue
            key = (occurrence.entity_type, occurrence.normalized_value.casefold())
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(occurrence)

    entity_ids: dict[tuple[str, str], str] = {}
    entities: list[PiiEntity] = []
    for index, key in enumerate(order, start=1):
        entity_id = f"E{index:04d}"
        entity_ids[key] = entity_id
        occurrences = grouped[key]
        confidences = {item.confidence for item in occurrences}
        entities.append(
            PiiEntity(
                entity_id=entity_id,
                entity_type=key[0],
                policy=TYPE_POLICY[key[0]],
                canonical_value=occurrences[0].normalized_value,
                normalized_key=key[1],
                bundle_id=None,
                confidence=(
                    "HIGH"
                    if "HIGH" in confidences
                    else "MEDIUM"
                    if "MEDIUM" in confidences
                    else "LOW"
                ),
                occurrences=tuple(occurrences),
            )
        )

    # -- bundle grouping ---------------------------------------------------- #
    union = _Union()
    for entity in entities:
        union.add(entity.entity_id)

    by_hint: dict[str, list[str]] = {}
    for key, occurrences in grouped.items():
        entity_id = entity_ids[key]
        for occurrence in occurrences:
            if occurrence.link_hint:
                by_hint.setdefault(occurrence.link_hint, []).append(entity_id)
    for members in by_hint.values():
        for other in members[1:]:
            union.union(members[0], other)

    # Local rule: anything sharing a host must be re-hosted together, or the
    # synthetic address and the synthetic link would end up on different
    # domains.  Applied even when the model emitted no PRIVATE_DOMAIN entity of
    # its own, which is the common case.
    HOSTED_TYPES = frozenset(
        {"EMAIL", "PRIVATE_URL", "MEETING_URL", "PRIVATE_REPOSITORY", "PRIVATE_DOMAIN"}
    )
    by_host: dict[str, list[str]] = {}
    for entity in entities:
        if entity.entity_type not in HOSTED_TYPES:
            continue
        host = (
            entity.normalized_key
            if entity.entity_type == "PRIVATE_DOMAIN"
            else _domain_of(entity.canonical_value)
        )
        if host:
            by_host.setdefault(host, []).append(entity.entity_id)
    for members_of_host in by_host.values():
        for other in members_of_host[1:]:
            union.union(members_of_host[0], other)

    # A subdomain belongs with its parent domain when the parent is known.
    known_hosts = sorted(by_host)
    for host in known_hosts:
        for parent in known_hosts:
            if host != parent and host.endswith(f".{parent}"):
                union.union(by_host[parent][0], by_host[host][0])

    members: dict[str, list[str]] = {}
    for entity in entities:
        members.setdefault(union.find(entity.entity_id), []).append(entity.entity_id)

    type_by_id = {entity.entity_id: entity.entity_type for entity in entities}
    bundles: list[IdentityBundle] = []
    bundle_of: dict[str, str] = {}
    for index, root in enumerate(sorted(members), start=1):
        group = sorted(members[root])
        if len(group) < 2:
            continue
        types = {type_by_id[item] for item in group}
        if types & PERSON_BUNDLE_TYPES and not types <= ORG_BUNDLE_TYPES:
            kind = BUNDLE_KIND_PERSON
        elif types <= ORG_BUNDLE_TYPES:
            kind = BUNDLE_KIND_ORG
        else:
            kind = BUNDLE_KIND_PERSON
        bundle_id = f"B{index:04d}"
        bundles.append(
            IdentityBundle(bundle_id=bundle_id, kind=kind, entity_ids=tuple(group))
        )
        for item in group:
            bundle_of[item] = bundle_id

    resolved = tuple(
        PiiEntity(
            entity_id=entity.entity_id,
            entity_type=entity.entity_type,
            policy=entity.policy,
            canonical_value=entity.canonical_value,
            normalized_key=entity.normalized_key,
            bundle_id=bundle_of.get(entity.entity_id),
            confidence=entity.confidence,
            occurrences=entity.occurrences,
        )
        for entity in entities
    )
    return PiiEntityRegistry(entities=resolved, bundles=tuple(bundles))
