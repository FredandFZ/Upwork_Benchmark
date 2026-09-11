"""Regexes and pure text predicates shared by every phase.

Most patterns are migrated verbatim from ``Code/PII_Clean.py`` (line references
in comments) because they were tuned against this dataset over several
revisions.  Three are new and carry the v7 semantics:

* :data:`INTERNAL_TOKEN_RE` matches the phase-0A secret placeholder.
* :data:`LEGACY_PLACEHOLDER_RE` matches v6's ``[EMAIL_001]`` form.  In v7 this is
  a *reject* pattern: the published output must read naturally, so any bracketed
  placeholder surviving into a rewrite is a validation failure.
* :data:`FAKE_CREDENTIAL_RE` matches the phase-6A rendering.  Only phase 6A may
  introduce it, so an earlier phase producing one is also a failure.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any, Sequence

from ._compat import id_key, safe_filename, sha256_text
from .config import (
    BUCKET_EMPTY,
    BUCKET_LONG,
    BUCKET_PRESERVE_SHORT,
    BUCKET_SHORT,
    RESERVED_DOMAIN_SUFFIX,
)

# --------------------------------------------------------------------------- #
# PII-shaped values (PII_Clean.py:79-101)
# --------------------------------------------------------------------------- #

EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Z0-9-]+\.)+[A-Z]{2,63}(?![\w.-])",
    re.IGNORECASE,
)
ANGLE_URL_RE = re.compile(r"<\s*(?:https?://|www\.)[^<>\s]+\s*>", re.IGNORECASE)
URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>]+", re.IGNORECASE)
HANDLE_RE = re.compile(r"(?<![\w@])@[A-Za-z0-9_][A-Za-z0-9_.-]{1,63}(?![\w@])")
PHONE_RE = re.compile(
    r"(?<!\d[.,])(?<![\w$€£¥])"
    r"(?:\+?\d[\d\s().-]{6,}\d)(?!\w)"
)
DATE_RE = re.compile(
    r"(?<!\w)(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})(?!\w)"
)
INLINE_CREDENTIAL_RE = re.compile(
    r"(?P<prefix>\b(?:user\s*name|username|login|account(?:\s+name)?|password|passcode|pwd)\b"
    r"(?:\s*[:=]\s*|\s+is\s+))(?P<value>[^\s,;]+)",
    re.IGNORECASE,
)
# Base58/bech32/hex chain addresses.  Deliberately narrow: only obvious shapes,
# because a false positive here silently mangles a requirement.
WALLET_ADDRESS_RE = re.compile(
    r"(?<!\w)(?:0x[a-fA-F0-9]{40}|bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})(?!\w)"
)

# --------------------------------------------------------------------------- #
# Contextual literals (PII_Clean.py:96-132)
# --------------------------------------------------------------------------- #

NUMBER_TOKEN_RE = re.compile(
    r"(?<!\w)(?:[$€£¥]\s*)?\d+(?:[.,:/-]\d+)*(?:%|[A-Za-z]{1,4})?(?!\w)"
)
AMOUNT_TOKEN_RE = re.compile(
    r"(?<!\w)(?:"
    r"[$€£¥]\s*\d+(?:[.,]\d+)*(?:[kKmMbB])?|"
    r"\d+(?:[.,]\d+)*\s*(?:USD|EUR|GBP|CNY|RMB|JPY|AUD|CAD|CHF|INR)"
    r")(?!\w)",
    re.IGNORECASE,
)
VERSION_RE = re.compile(r"(?<!\w)v?\d+(?:\.\d+){1,}(?!\w)", re.IGNORECASE)
FILENAME_RE = re.compile(
    r"(?<![\w.])[A-Za-z0-9_.-]+\.(?:ai|csv|docx?|fig|gif|html?|jpeg|jpg|json|md|"
    r"pdf|png|psd|svg|txt|xlsx?|xml|zip)(?![\w.])",
    re.IGNORECASE,
)
HTML_NUMERIC_ENTITY_RE = re.compile(r"&#(?:x[0-9A-F]+|\d+);", re.IGNORECASE)
LIST_MARKER_RE = re.compile(
    r"(?m)^[ \t]*(?:[*_]{1,3})?(?P<number>\d{1,4})(?:"
    r"(?:\\?[.)])+(?=(?:[*_]{1,3})?(?:\s|[^\W\d_]))|"
    r"[ \t]*[-–—][ \t]+(?=\S)|"
    r"[ \t]*:[ \t]+(?=[^\d\s])"
    r")"
)
# Upper-case technical identifiers such as ERC-721 or AES-256 must survive
# verbatim: changing the number changes the requirement.
PROTECTED_LITERAL_RE = re.compile(r"(?<!\w)[A-Z][A-Z0-9_-]{1,}(?!\w)")

# --------------------------------------------------------------------------- #
# Pipeline-internal tokens
# --------------------------------------------------------------------------- #

INTERNAL_TOKEN_RE = re.compile(r"<SECRET_CANDIDATE:S\d{3,}>")
INTERNAL_TOKEN_TEMPLATE = "<SECRET_CANDIDATE:{secret_id}>"
LEGACY_PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Z_]{2,}_\d{3,}\]")
FAKE_CREDENTIAL_RE = re.compile(
    r"FAKE_(?:API_KEY|API_SECRET|ACCESS_TOKEN|REFRESH_TOKEN|PASSWORD|SECRET|"
    r"PRIVATE_KEY|SEED_PHRASE|WEBHOOK_SECRET|SMTP_CREDENTIAL|CREDENTIAL)_[0-9A-F]{12}"
)
RESERVED_DOMAIN_RE = re.compile(
    r"(?i)(?:"
    + re.escape(RESERVED_DOMAIN_SUFFIX)
    + r"|\.invalid|\.test|\.localhost|(?<!\w)example\.(?:com|net|org))$"
)

# --------------------------------------------------------------------------- #
# Word / sentence primitives (PII_Clean.py:134-136, :253-279)
# --------------------------------------------------------------------------- #

WORD_RE = re.compile(r"[^\W_]+(?:['’.-][^\W_]+)*", re.UNICODE)
SINGLE_TOKEN_RE = re.compile(r"^[^\s]+$")
SENTENCE_BREAK_RE = re.compile(r"[.!?。！？]+")
NEGATION_MARKERS = frozenset(
    {
        "no",
        "not",
        "never",
        "none",
        "cannot",
        "cant",
        "dont",
        "doesnt",
        "didnt",
        "wont",
        "shouldnt",
        "wouldnt",
        "couldnt",
        "isnt",
        "arent",
        "wasnt",
        "werent",
        "without",
        "neither",
        "nor",
    }
)
STRUCTURAL_STOP_WORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
        "i", "in", "is", "it", "of", "on", "or", "that", "the", "this", "to",
        "we", "with", "you",
    }
)

# A single opaque stand-in so an internal token counts as one word instead of
# three (``SECRET``/``CANDIDATE``/``S001`` under WORD_RE), which would otherwise
# inflate word counts and misroute short messages into the long bucket.
_TOKEN_STANDIN = " secrettoken "


# --------------------------------------------------------------------------- #
# Span helpers (PII_Clean.py:640-651)
# --------------------------------------------------------------------------- #


def overlaps_any(span: tuple[int, int], excluded: Sequence[tuple[int, int]]) -> bool:
    start, end = span
    return any(
        start < excluded_end and excluded_start < end
        for excluded_start, excluded_end in excluded
    )


def mask_spans(text: str, spans: Sequence[tuple[int, int]]) -> str:
    """Hide complete spans while retaining offsets and token boundaries."""

    masked = list(text)
    for start, end in spans:
        masked[start:end] = " " * (end - start)
    return "".join(masked)


def pii_shaped_spans(text: str) -> list[tuple[int, int]]:
    """Spans that represent one complete value handled as a unit.

    Comparing contextual literals inside these spans is a category error: the
    digits in a synthetic URL are part of that URL, not a retained business
    number.  v6 documented this trap at ``PII_Clean.py:1822-1831``.
    """

    spans = [
        match.span()
        for pattern in (
            INTERNAL_TOKEN_RE,
            FAKE_CREDENTIAL_RE,
            LEGACY_PLACEHOLDER_RE,
            EMAIL_RE,
            ANGLE_URL_RE,
            URL_RE,
            HANDLE_RE,
            WALLET_ADDRESS_RE,
            HTML_NUMERIC_ENTITY_RE,
        )
        for match in pattern.finditer(text)
    ]
    date_spans = [match.span() for match in DATE_RE.finditer(text)]
    spans.extend(
        match.span()
        for match in PHONE_RE.finditer(text)
        if not overlaps_any(match.span(), date_spans)
    )
    spans.extend(match.span("value") for match in INLINE_CREDENTIAL_RE.finditer(text))
    return spans


def text_outside_pii(text: str) -> str:
    """``text`` with every complete PII-shaped value blanked out."""

    return mask_spans(text, pii_shaped_spans(text))


# --------------------------------------------------------------------------- #
# Configured-term helpers (PII_Clean.py:571-637)
# --------------------------------------------------------------------------- #


def literal_term_pattern(term: str) -> str:
    prefix = r"(?<!\w)" if term and term[0].isalnum() else ""
    suffix = r"(?!\w)" if term and term[-1].isalnum() else ""
    return prefix + re.escape(term) + suffix


def find_present_terms(text: str, terms: Sequence[str]) -> tuple[str, ...]:
    """The exact source spelling of each configured term present in ``text``."""

    found: list[str] = []
    seen: set[str] = set()
    for configured in terms:
        term = configured.strip()
        if not term or term.casefold() in seen:
            continue
        match = re.search(literal_term_pattern(term), text, flags=re.IGNORECASE)
        if match is not None:
            exact = match.group(0)
            found.append(exact)
            seen.add(exact.casefold())
    return tuple(found)


def find_terms_outside_pii(text: str, terms: Sequence[str]) -> tuple[str, ...]:
    """Find configured terms only outside complete PII-shaped values.

    A provider name inside a URL is part of that URL: the ``Google`` in
    ``docs.google.com`` must not make the whole message look like it mentions a
    public service in prose.
    """

    excluded = pii_shaped_spans(text)
    found: list[str] = []
    seen: set[str] = set()
    for configured in terms:
        term = configured.strip()
        if not term or term.casefold() in seen:
            continue
        for match in re.finditer(literal_term_pattern(term), text, flags=re.IGNORECASE):
            if overlaps_any(match.span(), excluded):
                continue
            exact = match.group(0)
            found.append(exact)
            seen.add(exact.casefold())
            break
    return tuple(found)


def preserved_term_counts(text: str, terms: Sequence[str]) -> Counter[str]:
    """Count protected terms case-sensitively so spelling is preserved too."""

    return Counter(
        {
            term: len(re.findall(literal_term_pattern(term), text))
            for term in terms
            if term
        }
    )


def occurrence_count(text: str, value: str, *, ignore_case: bool = True) -> int:
    """Word-boundary occurrences of a literal value."""

    if not value:
        return 0
    flags = re.IGNORECASE if ignore_case else 0
    return len(re.findall(literal_term_pattern(value), text, flags=flags))


def contains_value(text: str, value: str, *, ignore_case: bool = True) -> bool:
    return occurrence_count(text, value, ignore_case=ignore_case) > 0


# --------------------------------------------------------------------------- #
# Word counting and bucketing
# --------------------------------------------------------------------------- #


def _normalized_for_words(text: str) -> str:
    return INTERNAL_TOKEN_RE.sub(_TOKEN_STANDIN, text)


def word_count(text: str) -> int:
    return len(WORD_RE.findall(_normalized_for_words(text)))


def word_bucket(
    text: str, *, preserve_short_max_words: int, short_message_max_words: int
) -> str:
    """Provisional bucket from word count alone.

    ``PRESERVE_SHORT`` and ``EMPTY`` are *candidates* only.  They must be
    confirmed by :func:`resolve_bucket` once phases 0A/0B/1A have reported
    whether the message carries anything that must change -- ``WORD_RE`` counts
    ``will@example.org`` as two words, so an unconditional short-circuit would
    publish a bare email address verbatim.
    """

    count = word_count(text)
    if count == 0:
        return BUCKET_EMPTY
    if count <= preserve_short_max_words:
        return BUCKET_PRESERVE_SHORT
    if count <= short_message_max_words:
        return BUCKET_SHORT
    return BUCKET_LONG


def resolve_bucket(
    provisional: str,
    *,
    has_synthesized_entity: bool,
    has_secret_token: bool,
    has_semantic_slot: bool,
) -> str:
    """Promote a preserve-bucket message to ``SHORT`` when it carries content.

    This is the single guard behind the "1-2 word messages stay verbatim"
    decision.  All three inputs must be false for the original text to reach the
    published dataset unchanged.
    """

    if provisional not in (BUCKET_EMPTY, BUCKET_PRESERVE_SHORT):
        return provisional
    if has_synthesized_entity or has_secret_token or has_semantic_slot:
        return BUCKET_SHORT
    return provisional


def negation_markers(text: str) -> Counter[str]:
    """Negation tokens, used to assert that a short rewrite kept its polarity."""

    tokens = (
        token.casefold().replace("'", "").replace("’", "")
        for token in WORD_RE.findall(_normalized_for_words(text))
    )
    return Counter(token for token in tokens if token in NEGATION_MARKERS)


def is_interrogative(text: str) -> bool:
    return text.rstrip().endswith("?")


# --------------------------------------------------------------------------- #
# Structural change (PII_Clean.py:736-776, migrated as-is)
# --------------------------------------------------------------------------- #


def sentence_unit_count(text: str) -> int:
    return len([part for part in SENTENCE_BREAK_RE.split(text) if WORD_RE.search(part)])


def has_structural_change(source_text: str, rewritten_text: str) -> bool:
    """Reject shallow synonym swaps while allowing verifiable restructuring."""

    source_tokens = [
        token.casefold() for token in WORD_RE.findall(_normalized_for_words(source_text))
    ]
    rewritten_tokens = [
        token.casefold()
        for token in WORD_RE.findall(_normalized_for_words(rewritten_text))
    ]
    if not source_tokens or not rewritten_tokens:
        return False

    # Splitting or combining complete sentences is an observable structural edit.
    if sentence_unit_count(source_text) != sentence_unit_count(rewritten_text):
        return True

    source_counts = Counter(source_tokens)
    rewritten_counts = Counter(rewritten_tokens)
    rewritten_positions = {
        token: index
        for index, token in enumerate(rewritten_tokens)
        if rewritten_counts[token] == 1
    }
    mapped_positions = [
        rewritten_positions[token]
        for token in source_tokens
        if source_counts[token] == 1
        and token in rewritten_positions
        and len(token) >= 3
        and token not in STRUCTURAL_STOP_WORDS
    ]
    if any(left > right for left, right in zip(mapped_positions, mapped_positions[1:])):
        return True

    # A near-total grammatical recast may share too few anchors to prove an
    # inversion. Accept only when the token sequence differs substantially;
    # replacing one or two words leaves this ratio high and is rejected.
    return (
        SequenceMatcher(None, source_tokens, rewritten_tokens, autojunk=False).ratio()
        <= 0.55
    )


def similarity_ratio(left: str, right: str) -> float:
    """Token-sequence similarity, used to reject lightly-masked replacements."""

    return SequenceMatcher(
        None,
        [token.casefold() for token in WORD_RE.findall(left)],
        [token.casefold() for token in WORD_RE.findall(right)],
        autojunk=False,
    ).ratio()


# --------------------------------------------------------------------------- #
# Entropy and shape (generalizes PII_Clean.py:953-981)
# --------------------------------------------------------------------------- #


def shannon_entropy_bits_per_char(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum(
        (count / length) * math.log2(count / length) for count in counts.values()
    )


def charclass_signature(value: str) -> str:
    """A value's character-class fingerprint, safe to persist and log."""

    signature = ""
    if any(character.islower() for character in value):
        signature += "a"
    if any(character.isupper() for character in value):
        signature += "A"
    if any(character.isdigit() for character in value):
        signature += "9"
    if any(not character.isalnum() for character in value):
        signature += "-"
    return signature or "?"


def charclass_count(value: str) -> int:
    return len(charclass_signature(value).replace("?", ""))


# --------------------------------------------------------------------------- #
# Identity, naming and canonical hashing
# --------------------------------------------------------------------------- #


def message_file_stem(ordinal: int, message_id: Any) -> str:
    """A collision-free per-message filename stem.

    ``safe_filename(id_key(1))`` and ``safe_filename(id_key("1"))`` both yield
    ``"1"`` (``Code/stage1/storage.py:43-50``), so the hash of the canonical id
    is required to keep numeric and string identifiers distinct.
    """

    return f"{ordinal:05d}_{sha256_text(id_key(message_id))[:8]}"


def canonical_json(value: Any) -> str:
    """Deterministic JSON used for every content hash in the pipeline."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return sha256_text(canonical_json(value))


def fingerprint(category: str, value: str) -> str:
    """A short, non-reversible label for a sensitive value.

    Diagnostics, ledgers and logs may carry this; they may never carry the value
    itself.  Mirrors ``PII_Clean.py:1106-1110``.
    """

    return sha256_text(f"{category}:{value.strip()}")[:12]


def safe_stem(value: str) -> str:
    return safe_filename(value)
