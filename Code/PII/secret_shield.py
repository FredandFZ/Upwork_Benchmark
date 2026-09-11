"""Phase 0A (shield) and Phase 6A (render): the whole secret lifecycle.

Both halves live together because they are inverses and must agree exactly, and
because the phase 6B audit re-runs the *same* detector over the finished output
-- a secret the shield missed, or one a model invented, must be caught by the
identical code path rather than a second implementation that can drift.

Scope is narrow on purpose.  Phase 0A removes only values that grant access:
keys, secrets, tokens, passwords, private keys, seed phrases.  Usernames, login
names and account identifiers are personal data but not credentials, so they are
left in place for phase 0B to discover and phase 2 to replace with a natural
synthetic identity -- ``marcus.f`` reads like a conversation, ``FAKE_ACCOUNT_…``
does not.

Nothing here ever persists a raw secret.  :class:`SecretRegistry` stores offsets,
a length, a character-class signature and a SHA-256.  Masking is re-derived from
the source text on resume, which makes it structurally impossible for a run
artifact to carry a live credential.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ._compat import sha256_text
from .errors import PiiValidationError, marked
from .models import SafeMessage, SecretEntry, SecretOccurrence, SecretRegistry
from .textutil import (
    ANGLE_URL_RE,
    EMAIL_RE,
    FAKE_CREDENTIAL_RE,
    FILENAME_RE,
    HANDLE_RE,
    INTERNAL_TOKEN_RE,
    INTERNAL_TOKEN_TEMPLATE,
    LEGACY_PLACEHOLDER_RE,
    PROTECTED_LITERAL_RE,
    SINGLE_TOKEN_RE,
    URL_RE,
    VERSION_RE,
    WALLET_ADDRESS_RE,
    charclass_count,
    charclass_signature,
    overlaps_any,
    shannon_entropy_bits_per_char,
    word_bucket,
    word_count,
)

# ``ordinal -> [(span, secret_id), ...]`` -- detection results carried straight
# through to masking so the two can never disagree.
ResolvedSpans = dict[int, list[tuple["SecretCandidateSpan", str]]]

# --------------------------------------------------------------------------- #
# Kinds
# --------------------------------------------------------------------------- #

KIND_API_KEY = "API_KEY"
KIND_API_SECRET = "API_SECRET"
KIND_ACCESS_TOKEN = "ACCESS_TOKEN"
KIND_REFRESH_TOKEN = "REFRESH_TOKEN"
KIND_PASSWORD = "PASSWORD"
KIND_SECRET = "SECRET"
KIND_PRIVATE_KEY = "PRIVATE_KEY"
KIND_SEED_PHRASE = "SEED_PHRASE"
KIND_WEBHOOK_SECRET = "WEBHOOK_SECRET"
KIND_SMTP_CREDENTIAL = "SMTP_CREDENTIAL"
KIND_CREDENTIAL = "CREDENTIAL"

SECRET_KINDS: tuple[str, ...] = (
    KIND_API_KEY,
    KIND_API_SECRET,
    KIND_ACCESS_TOKEN,
    KIND_REFRESH_TOKEN,
    KIND_PASSWORD,
    KIND_SECRET,
    KIND_PRIVATE_KEY,
    KIND_SEED_PHRASE,
    KIND_WEBHOOK_SECRET,
    KIND_SMTP_CREDENTIAL,
    KIND_CREDENTIAL,
)

# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #

# Credential-bearing assignments only.  Deliberately excludes username/login/
# account: those are PII for phase 0B, not secrets for phase 0A.
CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(?P<keyword>\b(?:"
    r"api[\s_-]*key|apikey|api[\s_-]*secret|client[\s_-]*secret|app[\s_-]*secret|"
    r"secret[\s_-]*key|secret|password|passcode|passwd|pwd|"
    r"access[\s_-]*token|refresh[\s_-]*token|auth[\s_-]*token|bearer[\s_-]*token|token|"
    r"webhook[\s_-]*secret|signing[\s_-]*secret|"
    r"smtp[\s_-]*(?:password|key|credential)|"
    r"private[\s_-]*key|seed[\s_-]*phrase|mnemonic|recovery[\s_-]*phrase"
    r")\b)"
    r"(?P<sep>\s*(?:[:=]|\bis\b|->)\s*)"
    r"(?P<value>[^\s,;\"'`)\]]+)",
    re.IGNORECASE,
)

BEARER_RE = re.compile(
    r"(?i)\b(?:authorization\s*:\s*)?bearer\s+(?P<value>[A-Za-z0-9._~+/=-]{12,})"
)

PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)

JWT_RE = re.compile(r"(?<![\w.])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?![\w.])")

# Provider-independent token *shapes*.  Not an attempt to enumerate vendors:
# each entry is a structural prefix that only ever precedes a credential.
PREFIX_KINDS: tuple[tuple[str, str], ...] = (
    ("sk_live_", KIND_API_KEY),
    ("sk_test_", KIND_API_KEY),
    ("pk_live_", KIND_API_KEY),
    ("rk_live_", KIND_API_KEY),
    ("whsec_", KIND_WEBHOOK_SECRET),
    ("xkeysib-", KIND_API_KEY),
    ("xsmtpsib-", KIND_SMTP_CREDENTIAL),
    ("github_pat_", KIND_ACCESS_TOKEN),
    ("ghp_", KIND_ACCESS_TOKEN),
    ("gho_", KIND_ACCESS_TOKEN),
    ("ghu_", KIND_ACCESS_TOKEN),
    ("ghs_", KIND_ACCESS_TOKEN),
    ("ghr_", KIND_ACCESS_TOKEN),
    ("glpat-", KIND_ACCESS_TOKEN),
    ("npm_", KIND_ACCESS_TOKEN),
    ("shpat_", KIND_ACCESS_TOKEN),
    ("shpss_", KIND_ACCESS_TOKEN),
    ("dop_v1_", KIND_ACCESS_TOKEN),
    ("AKIA", KIND_API_KEY),
    ("ASIA", KIND_API_KEY),
    ("AIza", KIND_API_KEY),
    ("SG.", KIND_API_KEY),
    ("sk-", KIND_API_KEY),
    ("xoxb-", KIND_ACCESS_TOKEN),
    ("xoxp-", KIND_ACCESS_TOKEN),
    ("xoxa-", KIND_ACCESS_TOKEN),
    ("xoxr-", KIND_ACCESS_TOKEN),
    ("xoxs-", KIND_ACCESS_TOKEN),
)

KEYWORD_KINDS: tuple[tuple[str, str], ...] = (
    ("seed phrase", KIND_SEED_PHRASE),
    ("recovery phrase", KIND_SEED_PHRASE),
    ("mnemonic", KIND_SEED_PHRASE),
    ("private key", KIND_PRIVATE_KEY),
    ("smtp", KIND_SMTP_CREDENTIAL),
    ("webhook secret", KIND_WEBHOOK_SECRET),
    ("signing secret", KIND_WEBHOOK_SECRET),
    ("refresh token", KIND_REFRESH_TOKEN),
    ("access token", KIND_ACCESS_TOKEN),
    ("auth token", KIND_ACCESS_TOKEN),
    ("bearer token", KIND_ACCESS_TOKEN),
    ("api secret", KIND_API_SECRET),
    ("client secret", KIND_API_SECRET),
    ("app secret", KIND_API_SECRET),
    ("secret key", KIND_API_SECRET),
    ("api key", KIND_API_KEY),
    ("apikey", KIND_API_KEY),
    ("password", KIND_PASSWORD),
    ("passcode", KIND_PASSWORD),
    ("passwd", KIND_PASSWORD),
    ("pwd", KIND_PASSWORD),
    ("token", KIND_ACCESS_TOKEN),
    ("secret", KIND_SECRET),
)

# Words that show up after a credential keyword but are prose, not values
# (migrated from ``PII_Clean.py:330-364``).
NON_CREDENTIAL_VALUES = frozenset(
    {
        "an", "above", "as", "at", "attached", "be", "below", "by", "changed",
        "credentials", "details", "disabled", "done", "enabled", "expired",
        "here", "if", "in", "invalid", "it", "me", "my", "needed", "new", "no",
        "not", "of", "ok", "on", "or", "possible", "ready", "required", "reset",
        "same", "sent", "set", "temporary", "the", "there", "this", "to",
        "unchanged", "up", "updated", "valid", "we", "working", "yes",
    }
)

# Generic opaque-token gate.  Deliberately *conditional*: it fires only when the
# message also carries a credential context word.  An unconditional entropy gate
# was measured against all 55 projects and produced 63 hits of which nearly all
# were URL query parameters (``gclid=``, ``rlkey=``, ``lcsc_vid=``), CAD
# filenames (``USB4215-03-A.stp``) and hardware part numbers
# (``s_z=n_ESP32-S3-WROOM-1-N16R8``).  Shielding any of those destroys a
# requirement, and a shielded value is never restored -- so precision matters
# more here than recall, and the spec's own formulation is a conjunction:
# keyword *and* shape *and* entropy *and* length.
GENERIC_MIN_LENGTH = 20
GENERIC_MAX_LENGTH = 512
GENERIC_MIN_ENTROPY = 3.2
GENERIC_MIN_CLASSES = 3

# Words that make a high-entropy token in the same message worth shielding.
# ``Alchemy API - ErB5sYhQdYbeOFsVJJqas`` is a real key with no ``key:`` prefix,
# which is why bare ``api`` and ``key`` belong here.
CREDENTIAL_CONTEXT_RE = re.compile(
    r"(?i)(?<!\w)(?:api|apis|key|keys|token|tokens|secret|secrets|password|passwords|"
    r"passcode|pwd|credential|credentials|auth|oauth|bearer|login|signin|sign-in|"
    r"webhook|smtp|mnemonic|seed\s+phrase|private\s+key)(?!\w)"
)

# Paths and filenames: ``libs/easyeda/easyeda.3dshapes/`` and ``TS-1088-AR02016.step``
# both clear the entropy bar and are both requirement-bearing.
PATHLIKE_RE = re.compile(r"[\\/]")
DOTTED_EXTENSION_RE = re.compile(r"\.[A-Za-z][A-Za-z0-9]{1,5}$")

KEYWORD_MIN_LENGTH = 4
KEYWORD_MAX_LENGTH = 512

BIP39_RUN_RE = re.compile(r"(?<!\w)(?:[a-z]{3,8}\s+){11,23}[a-z]{3,8}(?!\w)")

DETECTOR_ASSIGNMENT = "KEYWORD_ASSIGNMENT"
DETECTOR_PREFIX = "STRUCTURAL_PREFIX"
DETECTOR_BEARER = "BEARER_HEADER"
DETECTOR_PEM = "PEM_BLOCK"
DETECTOR_JWT = "JWT_SHAPE"
DETECTOR_ENTROPY = "ENTROPY_SHAPE"
DETECTOR_SEED = "SEED_PHRASE_RUN"

OPAQUE_TOKEN_RE = re.compile(r"(?<![\w./-])[A-Za-z0-9][A-Za-z0-9._~+/=-]{8,511}(?![\w./-])")


@dataclass(frozen=True)
class SecretCandidateSpan:
    start: int
    end: int
    value: str
    kind: str
    detectors: tuple[str, ...]
    confidence: str


def _kind_from_keyword(keyword: str) -> str:
    lowered = re.sub(r"[\s_-]+", " ", keyword.casefold()).strip()
    for needle, kind in KEYWORD_KINDS:
        if needle in lowered:
            return kind
    return KIND_CREDENTIAL


def _kind_from_prefix(value: str) -> str | None:
    for prefix, kind in PREFIX_KINDS:
        if value.startswith(prefix) and len(value) > len(prefix) + 6:
            return kind
    return None


def _is_plausible_secret_value(value: str) -> bool:
    """Reject prose and structured non-secrets that follow a credential keyword."""

    if not value or not SINGLE_TOKEN_RE.fullmatch(value):
        return False
    stripped = value.strip("\"'`<>()[],;:.")
    if not stripped or len(stripped) < KEYWORD_MIN_LENGTH:
        return False
    if stripped.casefold() in NON_CREDENTIAL_VALUES:
        return False
    if EMAIL_RE.fullmatch(stripped) or URL_RE.fullmatch(stripped):
        return False
    if FILENAME_RE.fullmatch(stripped) or VERSION_RE.fullmatch(stripped):
        return False
    if INTERNAL_TOKEN_RE.fullmatch(stripped) or LEGACY_PLACEHOLDER_RE.fullmatch(stripped):
        return False
    if FAKE_CREDENTIAL_RE.fullmatch(stripped):
        return False
    return True


def _looks_like_opaque_secret(value: str) -> bool:
    """The shape half of the generic gate; the caller supplies the keyword half."""

    if not (GENERIC_MIN_LENGTH <= len(value) <= GENERIC_MAX_LENGTH):
        return False
    if not SINGLE_TOKEN_RE.fullmatch(value):
        return False
    if not any(character.isdigit() for character in value):
        return False
    if charclass_count(value) < GENERIC_MIN_CLASSES:
        return False
    if shannon_entropy_bits_per_char(value) < GENERIC_MIN_ENTROPY:
        return False
    # Structured values that merely look random.
    if EMAIL_RE.fullmatch(value) or URL_RE.fullmatch(value):
        return False
    if FILENAME_RE.fullmatch(value) or VERSION_RE.fullmatch(value):
        return False
    if PATHLIKE_RE.search(value) or DOTTED_EXTENSION_RE.search(value):
        return False  # a path or filename; requirement-bearing, not a credential
    if WALLET_ADDRESS_RE.fullmatch(value):
        return False  # a wallet address is PII for phase 0B, not a credential
    if PROTECTED_LITERAL_RE.fullmatch(value):
        return False  # an all-caps technical identifier
    if INTERNAL_TOKEN_RE.fullmatch(value) or FAKE_CREDENTIAL_RE.fullmatch(value):
        return False
    return True


def _wholesale_pii_spans(text: str) -> list[tuple[int, int]]:
    """Complete values that phase 0B/2 replace as a single unit.

    Deliberately narrower than the shared span helper in ``textutil``, which also
    marks v6's ``INLINE_CREDENTIAL_RE`` value group -- i.e. exactly the
    ``Password: <value>`` spans this module exists to shield.  Reusing that
    wider set made the detector exclude its own target.
    """

    return [
        match.span()
        for pattern in (EMAIL_RE, ANGLE_URL_RE, URL_RE, HANDLE_RE, WALLET_ADDRESS_RE)
        for match in pattern.finditer(text)
    ]


def _trim_token(value: str) -> tuple[str, int]:
    """Strip trailing punctuation.  Returns the value and how much was removed.

    Without this, ``0x3b55…B5.`` fails the wallet-address guard because of the
    sentence-final period and then trips the entropy gate instead.
    """

    trimmed = value.rstrip("\"'`<>()[]{},;:.!?")
    return trimmed, len(value) - len(trimmed)


def nominate_secret_spans(text: str) -> list[SecretCandidateSpan]:
    """Every span in ``text`` that may be a live credential.

    Signals are unioned and the longest span wins on overlap.  Returned spans
    never overlap.
    """

    if not text:
        return []

    # Regions that are already protected output, not input to protect.  Without
    # this, re-running the detector over shielded text re-nominates the token it
    # just wrote (``password: <SECRET_CANDIDATE:S002>`` matches the assignment
    # pattern), which would make the fail-closed shield check unsatisfiable.
    protected_spans = [
        match.span()
        for pattern in (INTERNAL_TOKEN_RE, FAKE_CREDENTIAL_RE, LEGACY_PLACEHOLDER_RE)
        for match in pattern.finditer(text)
    ]

    # Complete PII-shaped values (URLs, addresses, handles, wallets) are owned by
    # phase 0B and replaced wholesale by phase 2.  Shielding a fragment *inside*
    # one is both unnecessary and harmful: the Zoom link
    # ``…/j/899…?pwd=TSOrv…`` must be replaced as one meeting URL, not have its
    # query parameter swapped while the real link survives.  Unambiguous
    # credential shapes (PEM/JWT/provider prefixes) still fire inside them,
    # because those values must never reach a model at all.
    pii_spans = _wholesale_pii_spans(text)
    has_credential_context = bool(CREDENTIAL_CONTEXT_RE.search(text))

    proposals: list[SecretCandidateSpan] = []

    # 1. PEM private key blocks -- highest confidence, longest span.
    for match in PEM_BLOCK_RE.finditer(text):
        proposals.append(
            SecretCandidateSpan(
                *match.span(),
                value=match.group(0),
                kind=KIND_PRIVATE_KEY,
                detectors=(DETECTOR_PEM,),
                confidence="HIGH",
            )
        )

    # 2. Explicit credential assignments, outside complete PII values.
    for match in CREDENTIAL_ASSIGNMENT_RE.finditer(text):
        value = match.group("value")
        if not _is_plausible_secret_value(value):
            continue
        start, end = match.span("value")
        if overlaps_any((start, end), pii_spans):
            continue
        trimmed, removed = _trim_token(value)
        end -= removed
        kind = _kind_from_prefix(trimmed) or _kind_from_keyword(match.group("keyword"))
        proposals.append(
            SecretCandidateSpan(
                start=start,
                end=end,
                value=trimmed,
                kind=kind,
                detectors=(DETECTOR_ASSIGNMENT,),
                confidence="HIGH",
            )
        )

    # 3. Authorization: Bearer <token>
    for match in BEARER_RE.finditer(text):
        value = match.group("value")
        if not _is_plausible_secret_value(value):
            continue
        proposals.append(
            SecretCandidateSpan(
                *match.span("value"),
                value=value,
                kind=KIND_ACCESS_TOKEN,
                detectors=(DETECTOR_BEARER,),
                confidence="HIGH",
            )
        )

    # 4. JWTs.
    for match in JWT_RE.finditer(text):
        proposals.append(
            SecretCandidateSpan(
                *match.span(),
                value=match.group(0),
                kind=KIND_ACCESS_TOKEN,
                detectors=(DETECTOR_JWT,),
                confidence="HIGH",
            )
        )

    # 5. Structural provider prefixes (always) and the conditional entropy gate.
    for match in OPAQUE_TOKEN_RE.finditer(text):
        raw = match.group(0)
        start, end = match.span()
        value, removed = _trim_token(raw)
        end -= removed
        if not value:
            continue
        prefix_kind = _kind_from_prefix(value)
        if prefix_kind is not None:
            proposals.append(
                SecretCandidateSpan(
                    start=start,
                    end=end,
                    value=value,
                    kind=prefix_kind,
                    detectors=(DETECTOR_PREFIX,),
                    confidence="HIGH",
                )
            )
            continue
        if not has_credential_context:
            continue
        if overlaps_any((start, end), pii_spans):
            continue
        if _looks_like_opaque_secret(value):
            proposals.append(
                SecretCandidateSpan(
                    start=start,
                    end=end,
                    value=value,
                    kind=KIND_CREDENTIAL,
                    detectors=(
                        DETECTOR_ENTROPY,
                        f"ENTROPY_{shannon_entropy_bits_per_char(value):.1f}",
                    ),
                    confidence="MEDIUM",
                )
            )

    # 6. Seed phrases: a long run of lowercase words near a wallet keyword.
    lowered = text.casefold()
    if any(word in lowered for word in ("seed phrase", "mnemonic", "recovery phrase")):
        for match in BIP39_RUN_RE.finditer(text):
            proposals.append(
                SecretCandidateSpan(
                    *match.span(),
                    value=match.group(0),
                    kind=KIND_SEED_PHRASE,
                    detectors=(DETECTOR_SEED,),
                    confidence="MEDIUM",
                )
            )

    # Longest span wins; ties resolved by earlier start then higher confidence.
    ordered = sorted(
        proposals,
        key=lambda item: (item.start, -(item.end - item.start), item.confidence != "HIGH"),
    )
    selected: list[SecretCandidateSpan] = []
    for candidate in ordered:
        span = (candidate.start, candidate.end)
        if overlaps_any(span, protected_spans):
            continue
        if overlaps_any(span, [(item.start, item.end) for item in selected]):
            continue
        selected.append(candidate)
    selected.sort(key=lambda item: item.start)
    return selected


# --------------------------------------------------------------------------- #
# Registry and masking
# --------------------------------------------------------------------------- #


DETECTOR_STANDALONE = "STANDALONE_AFTER_CREDENTIAL_CONTEXT"

STANDALONE_MIN_LENGTH = 8
STANDALONE_MAX_LENGTH = 200
STANDALONE_WINDOW = 3

_ACKNOWLEDGEMENT_RE = re.compile(
    r"(?i)^(?:ok(?:ay)?|sure|thanks|thank\s+you|got\s+it|yes|no|cool|great|perfect|"
    r"hi|hello|hey|done)[\s.!?,;:…]*$"
)


def _looks_like_standalone_credential(text: str) -> bool:
    if not (STANDALONE_MIN_LENGTH <= len(text) <= STANDALONE_MAX_LENGTH):
        return False
    if not SINGLE_TOKEN_RE.fullmatch(text):
        return False
    if EMAIL_RE.fullmatch(text) or URL_RE.fullmatch(text) or ANGLE_URL_RE.fullmatch(text):
        return False
    if HANDLE_RE.fullmatch(text) or WALLET_ADDRESS_RE.fullmatch(text):
        return False
    if FILENAME_RE.fullmatch(text) or VERSION_RE.fullmatch(text):
        return False
    if PATHLIKE_RE.search(text) or DOTTED_EXTENSION_RE.search(text):
        return False
    if INTERNAL_TOKEN_RE.fullmatch(text) or FAKE_CREDENTIAL_RE.fullmatch(text):
        return False
    if text.casefold() in NON_CREDENTIAL_VALUES:
        return False
    return charclass_count(text) >= 3 and any(character.isdigit() for character in text)


def nominate_standalone_credentials(
    messages: Sequence[Mapping[str, Any]]
) -> dict[int, SecretCandidateSpan]:
    """Catch a credential sent as a message of its own.

    A password is frequently posted on a line by itself right after a message
    that set up the context ("the login is my email / Password: ..."), so the
    value carries no keyword of its own.  Migrated from v6's
    ``_discover_standalone_credentials`` (``PII_Clean.py:908-936``); the window
    keeps it from firing on unrelated tokens later in the conversation.

    Shielding wins over leaving these to phase 0B: a synthetic name would read
    better, but a missed password is the highest-severity leak in the corpus.
    """

    found: dict[int, SecretCandidateSpan] = {}
    window = 0
    for message in messages:
        raw = str(message.get("text") or "")
        text = raw.strip()
        if CREDENTIAL_CONTEXT_RE.search(text):
            window = STANDALONE_WINDOW
            continue
        if window <= 0:
            continue
        if _looks_like_standalone_credential(text):
            start = raw.index(text)
            found[int(message["ordinal"])] = SecretCandidateSpan(
                start=start,
                end=start + len(text),
                value=text,
                kind=KIND_PASSWORD,
                detectors=(DETECTOR_STANDALONE,),
                confidence="MEDIUM",
            )
            window -= 1
            continue
        if text and not _ACKNOWLEDGEMENT_RE.fullmatch(text):
            window = 0
        else:
            window -= 1
    return found


def build_secret_registry(
    project_id: str, messages: Sequence[Mapping[str, Any]]
) -> tuple[SecretRegistry, ResolvedSpans]:
    """Group identical secret values under one stable id.

    Returns the registry plus the per-ordinal spans, so masking never has to
    re-run detection and the two can never disagree.
    """

    spans_by_ordinal: dict[int, list[SecretCandidateSpan]] = {}
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    standalone = nominate_standalone_credentials(messages)

    for message in messages:
        ordinal = int(message["ordinal"])
        text = str(message.get("text") or "")
        spans = nominate_secret_spans(text)
        extra = standalone.get(ordinal)
        if extra is not None and not overlaps_any(
            (extra.start, extra.end), [(item.start, item.end) for item in spans]
        ):
            spans = sorted([*spans, extra], key=lambda item: item.start)
        if spans:
            spans_by_ordinal[ordinal] = spans
        for span in spans:
            key = span.value
            if key not in grouped:
                grouped[key] = {
                    "kind": span.kind,
                    "detectors": set(span.detectors),
                    "confidence": span.confidence,
                    "length": len(span.value),
                    "value_sha256": sha256_text(span.value),
                    "charclass_signature": charclass_signature(span.value),
                    "occurrences": [],
                }
                order.append(key)
            entry = grouped[key]
            entry["detectors"].update(span.detectors)
            if span.confidence == "HIGH":
                entry["confidence"] = "HIGH"
                entry["kind"] = span.kind if entry["kind"] == KIND_CREDENTIAL else entry["kind"]
            entry["occurrences"].append(
                SecretOccurrence(
                    ordinal=ordinal,
                    message_id=message.get("message_id"),
                    start=span.start,
                    end=span.end,
                )
            )

    secrets: list[SecretEntry] = []
    for index, key in enumerate(order, start=1):
        entry = grouped[key]
        secrets.append(
            SecretEntry(
                secret_id=f"S{index:03d}",
                kind=entry["kind"],
                occurrences=tuple(entry["occurrences"]),
                length=entry["length"],
                value_sha256=entry["value_sha256"],
                charclass_signature=entry["charclass_signature"],
                detectors=tuple(sorted(entry["detectors"])),
                confidence=entry["confidence"],
            )
        )

    # Assign the id back onto the spans so masking can use it directly.
    id_by_value = {key: secrets[index].secret_id for index, key in enumerate(order)}
    resolved: ResolvedSpans = {
        ordinal: [(span, id_by_value[span.value]) for span in spans]
        for ordinal, spans in spans_by_ordinal.items()
    }
    return SecretRegistry(project_id=project_id, secrets=tuple(secrets)), resolved


def mask_text(text: str, spans: Sequence[tuple[SecretCandidateSpan, str]]) -> str:
    """Replace each span with its internal token, right to left."""

    masked = text
    for span, secret_id in sorted(spans, key=lambda item: item[0].start, reverse=True):
        token = INTERNAL_TOKEN_TEMPLATE.format(secret_id=secret_id)
        masked = masked[: span.start] + token + masked[span.end :]
    return masked


def mask_messages(
    messages: Sequence[Mapping[str, Any]],
    spans_by_ordinal: Mapping[int, Sequence[tuple[SecretCandidateSpan, str]]],
    *,
    preserve_short_max_words: int,
    short_message_max_words: int,
) -> list[SafeMessage]:
    """Build the shielded view of every message."""

    safe: list[SafeMessage] = []
    for message in messages:
        ordinal = int(message["ordinal"])
        text = str(message.get("text") or "")
        spans = list(spans_by_ordinal.get(ordinal, ()))
        safe_text = mask_text(text, spans) if spans else text
        tokens = tuple(
            INTERNAL_TOKEN_TEMPLATE.format(secret_id=secret_id)
            for _span, secret_id in sorted(spans, key=lambda item: item[0].start)
        )
        sender_id = message.get("sender_id")
        safe.append(
            SafeMessage(
                ordinal=ordinal,
                message_id=message.get("message_id"),
                speaker=message.get("speaker"),
                safe_text=safe_text,
                safe_text_sha256=sha256_text(safe_text),
                source_text_sha256=sha256_text(text),
                word_count=word_count(safe_text),
                bucket=word_bucket(
                    safe_text,
                    preserve_short_max_words=preserve_short_max_words,
                    short_message_max_words=short_message_max_words,
                ),
                secret_tokens=tokens,
                sender_id_present=bool(sender_id is not None and str(sender_id).strip()),
            )
        )
    return safe


def shield_project(
    project_id: str,
    messages: Sequence[Mapping[str, Any]],
    *,
    preserve_short_max_words: int,
    short_message_max_words: int,
) -> tuple[SecretRegistry, list[SafeMessage]]:
    """Run phase 0A end to end and validate the result."""

    registry, spans = build_secret_registry(project_id, messages)
    safe_messages = mask_messages(
        messages,
        spans,
        preserve_short_max_words=preserve_short_max_words,
        short_message_max_words=short_message_max_words,
    )
    validate_shield(registry, safe_messages, messages, spans)
    return registry, safe_messages


# --------------------------------------------------------------------------- #
# Fail-closed validation of the shield
# --------------------------------------------------------------------------- #


def validate_shield(
    registry: SecretRegistry,
    safe_messages: Sequence[SafeMessage],
    messages: Sequence[Mapping[str, Any]],
    spans_by_ordinal: Mapping[int, Sequence[tuple[SecretCandidateSpan, str]]],
) -> None:
    """Assert the shield is complete, reversible and collision-free.

    The core clause is (1): re-running the detector over the shielded text must
    find nothing.  The detector is not allowed to leave behind a secret it is
    itself capable of recognizing.
    """

    failures: list[str] = []
    by_ordinal = {message.ordinal: message for message in safe_messages}
    source_by_ordinal = {int(message["ordinal"]): message for message in messages}

    if len(by_ordinal) != len(messages):
        failures.append("SHIELD_COVERAGE_INCOMPLETE: one safe message per source row required")

    # (1) nothing detectable survives
    for safe in safe_messages:
        residual = [
            span
            for span in nominate_secret_spans(safe.safe_text)
            if not INTERNAL_TOKEN_RE.fullmatch(span.value)
        ]
        if residual:
            failures.append(
                "SHIELD_UNMASKED_SECRET_REMAINS: "
                f"ordinal={safe.ordinal} count={len(residual)} "
                f"fingerprints={[sha256_text(span.value)[:12] for span in residual]}"
            )

    # (2) ids unique and contiguous; (3) token shape
    ids = [entry.secret_id for entry in registry.secrets]
    if len(set(ids)) != len(ids):
        failures.append("SHIELD_TOKEN_COLLISION: duplicate secret_id")
    expected_ids = [f"S{index:03d}" for index in range(1, len(ids) + 1)]
    if ids != expected_ids:
        failures.append("SHIELD_TOKEN_COLLISION: secret ids are not contiguous")
    hashes = [entry.value_sha256 for entry in registry.secrets]
    if len(set(hashes)) != len(hashes):
        failures.append("SHIELD_TOKEN_COLLISION: two ids share one value hash")

    # (4) spans round-trip against the source and the mask is offset-exact
    for ordinal, spans in spans_by_ordinal.items():
        source = str(source_by_ordinal.get(ordinal, {}).get("text") or "")
        for span, secret_id in spans:
            actual = source[span.start : span.end]
            if actual != span.value:
                failures.append(
                    f"SHIELD_NONREVERSIBLE: ordinal={ordinal} secret_id={secret_id} "
                    "span does not round-trip against the source"
                )
        rebuilt = mask_text(source, spans)
        safe = by_ordinal.get(ordinal)
        if safe is not None and rebuilt != safe.safe_text:
            failures.append(
                f"SHIELD_NONREVERSIBLE: ordinal={ordinal} masking is not reproducible"
            )

    # (5) token multiplicity matches the recorded occurrences
    recorded: dict[int, int] = {}
    for entry in registry.secrets:
        for occurrence in entry.occurrences:
            recorded[occurrence.ordinal] = recorded.get(occurrence.ordinal, 0) + 1
    for safe in safe_messages:
        found = len(INTERNAL_TOKEN_RE.findall(safe.safe_text))
        if found != recorded.get(safe.ordinal, 0):
            failures.append(
                f"SHIELD_NONREVERSIBLE: ordinal={safe.ordinal} token count {found} "
                f"!= recorded {recorded.get(safe.ordinal, 0)}"
            )

    if failures:
        raise PiiValidationError(
            marked("phase 0A shield validation failed: " + "; ".join(failures[:10])),
            failures=tuple(item.split(":", 1)[0] for item in failures),
        )


# --------------------------------------------------------------------------- #
# Phase 6A -- deterministic fake credential rendering
# --------------------------------------------------------------------------- #

RENDER_SALT = "pii-v7-fake-credential"

_LABEL_BY_KIND: Mapping[str, str] = {
    KIND_API_KEY: "API_KEY",
    KIND_API_SECRET: "API_SECRET",
    KIND_ACCESS_TOKEN: "ACCESS_TOKEN",
    KIND_REFRESH_TOKEN: "REFRESH_TOKEN",
    KIND_PASSWORD: "PASSWORD",
    KIND_SECRET: "SECRET",
    KIND_PRIVATE_KEY: "PRIVATE_KEY",
    KIND_SEED_PHRASE: "SEED_PHRASE",
    KIND_WEBHOOK_SECRET: "WEBHOOK_SECRET",
    KIND_SMTP_CREDENTIAL: "SMTP_CREDENTIAL",
    KIND_CREDENTIAL: "CREDENTIAL",
}


def credential_label(kind: str) -> str:
    return _LABEL_BY_KIND.get(kind, "CREDENTIAL")


def render_credential(project_id: str, secret_id: str, kind: str) -> str:
    """A stable, obviously-invalid stand-in for one secret.

    Deterministic in ``(project_id, secret_id, salt)`` so a resumed run, a
    finalize pass and a rerun all produce byte-identical output -- which is what
    lets the commit step be redone safely after a crash.
    """

    digest = sha256_text(f"{project_id}|{secret_id}|{RENDER_SALT}")[:12].upper()
    return f"FAKE_{credential_label(kind)}_{digest}"


def credential_map(registry: SecretRegistry) -> dict[str, str]:
    """``internal token -> rendered fake credential`` for one project."""

    rendered: dict[str, str] = {}
    seen: dict[str, str] = {}
    for entry in registry.secrets:
        value = render_credential(registry.project_id, entry.secret_id, entry.kind)
        if value in seen:
            raise PiiValidationError(
                marked(
                    "RENDER_COLLISION: two secret ids render to the same credential "
                    f"({seen[value]} and {entry.secret_id})"
                ),
                failures=("RENDER_COLLISION",),
            )
        seen[value] = entry.secret_id
        rendered[entry.internal_token] = value
    return rendered


def render_text(text: str, rendered: Mapping[str, str]) -> str:
    """Substitute every internal token with its fake credential."""

    if not rendered:
        return text

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        value = rendered.get(token)
        if value is None:
            raise PiiValidationError(
                marked(f"RENDER_UNKNOWN_TOKEN: {token} has no rendering"),
                failures=("RENDER_UNKNOWN_TOKEN",),
            )
        return value

    return INTERNAL_TOKEN_RE.sub(_replace, text)


def unexpected_credential_spans(text: str) -> list[SecretCandidateSpan]:
    """Credential-shaped values in finished output that are not fake renderings.

    Catches both a secret the shield missed and a realistic-looking credential a
    model invented.
    """

    fake_spans = [match.span() for match in FAKE_CREDENTIAL_RE.finditer(text)]
    return [
        span
        for span in nominate_secret_spans(text)
        if not overlaps_any((span.start, span.end), fake_spans)
        and not INTERNAL_TOKEN_RE.fullmatch(span.value)
    ]


def sensitive_pairs(registry: SecretRegistry) -> list[tuple[str, str]]:
    """Category/fingerprint pairs for the ledger's redaction table.

    The registry holds no raw values, so nothing sensitive is exposed here; the
    pipeline registers raw secret values separately and only in memory.
    """

    return [(entry.kind, entry.value_sha256) for entry in registry.secrets]
