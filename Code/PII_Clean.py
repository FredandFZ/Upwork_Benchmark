"""Paraphrase and de-identify raw dataset ``chat_messages.json`` files.

Each project is copied from ``Datasets/project`` to
``Datasets/PII_clean_project``.  Only ``chat_messages.json`` content is changed;
all other project files are copied unchanged.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import re
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import httpx

try:  # ``python Code/PII_Clean.py``
    from stage1.api_client import ApiError, Stage1ApiClient
    from stage1.config import ANNOTATION_MODEL, REASONING_EFFORT
    from stage1.storage import id_key, read_json, sha256_text, write_json
    from stage1.validation import validate_stage1_annotation
except ModuleNotFoundError:  # ``python -m Code.PII_Clean`` and unit tests
    from Code.stage1.api_client import ApiError, Stage1ApiClient
    from Code.stage1.config import ANNOTATION_MODEL, REASONING_EFFORT
    from Code.stage1.storage import id_key, read_json, sha256_text, write_json
    from Code.stage1.validation import validate_stage1_annotation


CLEANING_VERSION = "6.0"
CONTEXT_CLASSIFY_RUN_MODE = "PII_CLEAN_CONTEXT_CLASSIFY"
REWRITE_RUN_MODE = "PII_CLEAN_REWRITE"
PII_RUN_MODE = "PII_CLEAN_REDACT"
CHECKPOINT_SCHEMA_VERSION = "pii-clean-checkpoint-v1"
REWRITE_CHECKPOINT_COMPATIBLE_VERSIONS = frozenset(
    {"5.7", "5.8", "5.9", "5.10", "5.11", "5.12"}
)
CONTEXT_CATEGORIES = (
    "LIST_INDEX",
    "NUMBER",
    "AMOUNT",
    "DATE",
    "VERSION",
    "FILENAME",
    "TECHNICAL_IDENTIFIER",
    "PII_COMPONENT",
)
PII_CATEGORIES = (
    "EMAIL",
    "URL",
    "ACCOUNT",
    "PASSWORD",
    "PHONE",
    "HANDLE",
    "SENDER_ID",
    "CLIENT_NAME",
    "FREELANCER_NAME",
    "PERSON_NAME",
    "PROJECT_NAME",
    "ORGANIZATION",
    "SERVICE",
)
PLACEHOLDER_RE = re.compile(
    r"\[(?:EMAIL|URL|ACCOUNT|PASSWORD|PHONE|HANDLE|SENDER_ID|CLIENT_NAME|FREELANCER_NAME|PERSON_NAME|PROJECT_NAME|ORGANIZATION|SERVICE)_\d{3,}\]"
)
FULL_PLACEHOLDER_RE = re.compile(
    r"\[(?P<category>EMAIL|URL|ACCOUNT|PASSWORD|PHONE|HANDLE|SENDER_ID|CLIENT_NAME|"
    r"FREELANCER_NAME|PERSON_NAME|PROJECT_NAME|ORGANIZATION|SERVICE)_(?P<index>\d{3,})\]"
)
EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Z0-9-]+\.)+[A-Z]{2,63}(?![\w.-])",
    re.IGNORECASE,
)
ANGLE_URL_RE = re.compile(r"<\s*(?:https?://|www\.)[^<>\s]+\s*>", re.IGNORECASE)
URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>]+", re.IGNORECASE)
HANDLE_RE = re.compile(r"(?<![\w@])@[A-Za-z0-9_][A-Za-z0-9_.-]{1,63}(?![\w@])")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{6,}\d)(?!\w)")
INLINE_CREDENTIAL_RE = re.compile(
    r"(?P<prefix>\b(?:user\s*name|username|login|account(?:\s+name)?|password|passcode|pwd)\b"
    r"(?:\s*[:=]\s*|\s+is\s+))(?P<value>[^\s,;]+)",
    re.IGNORECASE,
)
NUMBER_TOKEN_RE = re.compile(
    r"(?<!\w)(?:[$€£¥]\s*)?\d+(?:[.,:/-]\d+)*(?:%|[A-Za-z]{1,4})?(?!\w)"
)
DATE_RE = re.compile(
    r"(?<!\w)(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})(?!\w)"
)
LIST_MARKER_RE = re.compile(
    r"(?m)^[ \t]*(?:[*_]{1,3})?(?P<number>\d{1,4})(?:"
    r"(?:\\?[.)])+(?=(?:[*_]{1,3})?(?:\s|[^\W\d_]))|"
    r"[ \t]*[-\u2013\u2014][ \t]+(?=\S)|"
    r"[ \t]*:[ \t]+(?=[^\d\s])"
    r")"
)
WEAK_LIST_MARKER_RE = re.compile(
    r"(?m)^[ \t]*(?:[*_]{1,3})?(?P<number>\d{1,4})(?:"
    r"[ \t]+(?=\S)|-(?=[^\W\d_])"
    r")"
)
INLINE_LIST_MARKER_RE = re.compile(
    r"(?<!\w)(?P<number>\d{1,4})(?:\\?[.)])(?=\s)"
)
AMOUNT_TOKEN_RE = re.compile(
    r"(?<!\w)(?:"
    r"[$\u20ac\u00a3\u00a5]\s*\d+(?:[.,]\d+)*(?:[kKmMbB])?|"
    r"\d+(?:[.,]\d+)*\s*(?:USD|EUR|GBP|CNY|RMB|JPY|AUD|CAD|CHF|INR)"
    r")(?!\w)",
    re.IGNORECASE,
)
HTML_NUMERIC_ENTITY_RE = re.compile(r"&#(?:x[0-9A-F]+|\d+);", re.IGNORECASE)
VERSION_RE = re.compile(r"(?<!\w)v?\d+(?:\.\d+){1,}(?!\w)", re.IGNORECASE)
FILENAME_RE = re.compile(
    r"(?<![\w.])[A-Za-z0-9_.-]+\.(?:ai|csv|docx?|fig|gif|html?|jpeg|jpg|json|md|"
    r"pdf|png|psd|svg|txt|xlsx?|xml|zip)(?![\w.])",
    re.IGNORECASE,
)
# Uppercase technical identifiers are still protected. Versions and filenames
# deliberately are not: phase 1 must synthesize replacements for them.
PROTECTED_LITERAL_RE = re.compile(r"(?<!\w)[A-Z][A-Z0-9_-]{1,}(?!\w)")
WORD_RE = re.compile(r"[^\W_]+(?:['’.-][^\W_]+)*", re.UNICODE)
SINGLE_TOKEN_RE = re.compile(r"^[^\s]+$")
SENTENCE_BREAK_RE = re.compile(r"[.!?。！？]+")
CAMEL_PROJECT_TERM_RE = re.compile(
    r"(?<![\w.])(?P<name>(?:[A-Z][a-z]{1,}){3,})(?![\w.])"
)
PROJECT_NAME_CONTEXT_RE = re.compile(
    r"(?i:\b(?:"
    r"rename\s+(?:it|this|the\s+(?:project|product|app|platform|brand))\s+(?:to\s+)?|"
    r"(?:project|product|brand|app|application|platform|website|site|service)\s+"
    r"(?:name\s+)?(?:is|was|called|named)\s+"
    r"))"
    r"[\"'“”]?(?P<name>[A-Z][A-Za-z]*(?:[ -][A-Z][A-Za-z]*){0,3})"
)

# These are semantic or implementation terms, not project aliases. They remain
# exact during paraphrasing. Public companies and public service brands live in
# a separate list because phase 1 must replace them with synthetic alternatives.
DEFAULT_PRESERVED_TERMS = (
    "gamification mechanics",
    "gameification mechanics",
    "Visual Studio Code",
    "VisualStudioCode",
    "React Native",
    "ReactNative",
    "Ruby on Rails",
    "JavaScript",
    "TypeScript",
    "WordPress",
    "Docker",
    "Kubernetes",
    "FastAPI",
    "GraphQL",
    "PostgreSQL",
    "Solidity",
    "Ethereum",
    "Chainlink",
    "OAuth",
    "USDC",
    "ETH",
    "BTC",
    "KYC",
)
DEFAULT_PUBLIC_SERVICE_TERMS = (
    "AWS",
    "Amazon Web Services",
    "AmazonWebServices",
    "Microsoft Azure",
    "Azure",
    "Microsoft",
    "Google",
    "Google Cloud Platform",
    "GoogleTagManager",
    "GoDaddy",
    "Apple",
    "Meta",
    "Facebook",
    "Instagram",
    "WhatsApp",
    "GitHub",
    "GitLab",
    "OpenAI",
    "ChatGPT",
    "MongoDB",
    "Firebase",
    "Supabase",
    "Coinbase Commerce",
    "Coinbase Pay",
    "Coinbase",
    "Stripe",
    "MoonPay",
    "Ramp Network",
    "Wyre",
    "Transak",
    "Visa",
    "Mastercard",
    "PayPal",
    "Shopify",
    "Slack",
    "Twilio",
    "Cloudflare",
    "Vercel",
    "Netlify",
    "Heroku",
    "DigitalOcean",
    "Atlassian",
    "Jira",
    "Trello",
    "Notion",
    "Figma",
    "Canva",
    "Dropbox",
    "Google Drive",
    "OneDrive",
    "Gmail",
    "YouTube",
    "LinkedIn",
    "IBM",
    "SAP",
)
TECHNICAL_TERM_ALLOWLIST = {
    term.casefold()
    for term in (*DEFAULT_PRESERVED_TERMS, *DEFAULT_PUBLIC_SERVICE_TERMS)
}
PROJECT_TERM_STOPLIST = {
    "application",
    "brand",
    "company",
    "new",
    "platform",
    "product",
    "project",
    "service",
    "site",
    "system",
    "the",
    "this",
    "website",
}
STRUCTURAL_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "we",
    "with",
    "you",
}

NAME_WORD = r"[^\W\d_][\w'’.-]{1,49}"
GREETING_NAME_RE = re.compile(
    rf"(?i:(?<!\w)(?:hi|hello|hey|dear)\s*,?\s*)"
    rf"(?P<name>{NAME_WORD}(?:[ \t]+{NAME_WORD})?)",
)
THANKS_NAME_RE = re.compile(
    rf"(?i:(?<!\w)(?:thanks|thank\s+you)\s*,\s*)"
    rf"(?P<name>{NAME_WORD}(?:[ \t]+{NAME_WORD})?)",
)
SIGNATURE_NAME_RE = re.compile(
    rf"(?:^|\n)\s*(?:thanks|thank\s+you|regards|best(?:\s+regards)?|cheers|sincerely)"
    rf"\s*[,!]?\s*\n+\s*(?P<name>{NAME_WORD}(?:\s+{NAME_WORD})?)\s*[.!]?\s*$",
    re.IGNORECASE,
)

NON_NAME_WORDS = {
    "all",
    "again",
    "are",
    "can",
    "could",
    "did",
    "do",
    "everyone",
    "friend",
    "guys",
    "have",
    "how",
    "i'm",
    "i've",
    "is",
    "madam",
    "morning",
    "night",
    "please",
    "sir",
    "team",
    "there",
    "this",
    "what",
    "when",
    "where",
    "why",
    "would",
    "you",
}
NON_CREDENTIAL_VALUES = {
    "an",
    "above",
    "as",
    "at",
    "attached",
    "be",
    "below",
    "by",
    "credentials",
    "details",
    "disabled",
    "enabled",
    "if",
    "in",
    "it",
    "my",
    "needed",
    "no",
    "not",
    "of",
    "on",
    "or",
    "possible",
    "ready",
    "required",
    "same",
    "temporary",
    "the",
    "to",
    "unchanged",
    "up",
    "we",
    "working",
}
SHORT_ACKNOWLEDGEMENTS = re.compile(
    r"^(?:ok(?:ay)?|sure|thanks|thank\s+you|got\s+it|understood|i\s+know|"
    r"all\s+right|alright|sounds\s+good|no\s+problem|you(?:'|’)re\s+welcome|"
    r"yes|no|cool|great|perfect|hi|hello|hey)[\s.!?,;:…👍🙏😊🙂]*$",
    re.IGNORECASE,
)

CONTEXT_CLASSIFY_SYSTEM_PROMPT = """You are phase 0 of a workplace-chat de-identification pipeline.

Read each COMPLETE message and classify every supplied numeric/contextual occurrence by its
meaning at that exact position. Do not rewrite the message and do not discover extra occurrences.

Return JSON only, with exactly this shape:
{"classified_messages": [{"message_id": <same JSON value and type>, "occurrences": [{"occurrence_id": "C001", "category": "<category>"}]}]}

Allowed categories:
- LIST_INDEX: an ordinal used only to organize a list, checklist, heading, channel list, or steps.
- NUMBER: a requirement-bearing count, identifier, example value, range, percentage, duration, quantity, token ID, or other ordinary number that should be synthesized.
- AMOUNT: a price, payment, budget, balance, commission, prize, currency amount, or financial value.
- DATE: a calendar date, year, day-of-month, or project-specific time reference that could help identify the project.
- VERSION: an actual software, document, protocol, release, or artifact version; a decimal currency amount is never VERSION.
- FILENAME: a complete filename or artifact filename that should be synthesized.
- TECHNICAL_IDENTIFIER: a number embedded in a standard/protocol/hardware/technical identifier whose change would alter the requirement, such as ERC-721 or AES-256.
- PII_COMPONENT: a number contained inside an email, URL, phone, account, password, secret, address, or other PII value that phase 2 must replace as a whole.

Rules:
1. Return every message and every occurrence exactly once, in input order. Keep occurrence_id unchanged.
2. Use the full message, surrounding context, position, and neighboring occurrences. The local_hint is non-authoritative and may be wrong.
3. The same literal may receive different categories at different positions. For example, a heading 1 can be LIST_INDEX while a quoted referral code 1 is NUMBER.
4. LIST_INDEX is only structural numbering. A quantity at the beginning of a sentence is not automatically a list index.
5. Return no prose, confidence score, source text, replacement, or additional keys.
"""

REWRITE_SYSTEM_PROMPT = """You are phase 1 of a three-phase workplace-chat cleaning pipeline.

The input may contain personally identifiable information (PII). A second LLM
phase will identify and replace PII after your rewrite. Do not perform PII
redaction in this phase.

Return JSON only, with exactly this shape:
{"rewrites": [{"message_id": <same JSON value and type>, "text": "<rewritten text>"}]}

Rules:
1. Return exactly one rewrite for every input message_id. Never add, omit, merge, split, or reorder messages.
2. When require_structure_change is true, every rewrite MUST change sentence structure, not merely substitute words. Reorder clauses or information-bearing phrases, change grammatical construction/voice, or split/combine sentences. Lexical substitution with the same word order is invalid. Do not summarize. When it is false, changing all required contextual values is sufficient.
3. Preserve the meaning needed for downstream requirement/event annotation: speaker intent, request/acceptance/rejection, negation, uncertainty, modality, conditions, status, scope, chronology, and the functional role of each detail. The literal values listed for replacement are intentionally exempt and must change.
4. Replace every item in must_replace_context_values and must_replace_terms. Preserve every item in must_preserve_context_values; LIST_INDEX values must keep their value and order, and TECHNICAL_IDENTIFIER/PII_COMPONENT values must remain exact. Invent unrelated but plausible synthetic numbers, dates, amounts, versions, filenames, company names, and public-service names. Preserve the replacement's broad type and conversational role, but do not preserve, lightly mask, or derive an original value marked REPLACE. Use neutral fictional names such as "Payment Provider A" when appropriate; never substitute another real public brand.
5. Keep the original language and roughly the original level of formality. Do not add facts, promises, conclusions, or explanations.
6. Preserve technical identifiers, bracketed placeholders, every item in must_preserve_terms, private project aliases, person names, email addresses, URLs, accounts, passwords, phone numbers, and handles exactly as written. The LLM PII phase will replace those sensitive and project-specific values consistently after rewriting. Public companies and public services are the exception: replace those listed in must_replace_terms.
7. Each returned text must differ from its input text while remaining equivalent apart from the required synthetic contextual values. Before returning, verify that every required original literal is absent and, when required, that sentence construction actually changed.
"""

PII_SYSTEM_PROMPT = """You are phase 2 of a workplace-chat cleaning pipeline.

Inspect every supplied message and return its final PII-cleaned text. This phase
must identify and replace sensitive values itself; do not paraphrase or otherwise
edit the phase-1 text.

Return JSON only, with exactly this shape:
{"cleaned_messages": [{"message_id": <same JSON value and type>, "text": "<final text>", "sender_id": "<placeholder or null>", "entities": [{"field": "text or sender_id", "source": "<exact source substring>", "category": "<category>", "placeholder": "<placeholder>"}]}]}

Rules:
1. Return exactly one cleaned_messages item for every input message_id, in input order. Never add, omit, merge, split, or reorder messages.
2. Detect and replace actual email addresses, URLs, account/login names, passwords or secrets, phone numbers, social handles, sender IDs, person names, project/product/brand-specific names, and any real public company or public-service name that survived phase 1. Use only these categories: EMAIL, URL, ACCOUNT, PASSWORD, PHONE, HANDLE, SENDER_ID, CLIENT_NAME, FREELANCER_NAME, PERSON_NAME, PROJECT_NAME, ORGANIZATION, SERVICE.
3. Replace sensitive text with [CATEGORY_###]. Match each known_replacements.source_casefold case-insensitively and reuse its placeholder whenever that value occurs. For each new value, use the supplied next_indices and allocate consecutive category indices in first-occurrence order. The same value and category must always use the same placeholder.
4. Every non-empty sender_id is sensitive and must be replaced by a SENDER_ID placeholder. Null or empty sender_id values must remain unchanged. Do not copy a raw sender_id into text.
5. For each replacement, add one entities entry. source must be the exact, maximal, case-preserving substring from that field. Entity-list order is not significant. One entry covers every exact repetition of the same source in that field. Do not add nested parent/child declarations for the same span, and entity spans must not overlap.
6. Apart from replacing declared entities, text must remain byte-for-byte identical to the supplied phase-1 text. Do not rewrite, summarize, correct spelling, alter whitespace/punctuation, or change any number, date, amount, filename, version, identifier, tool, technology, feature, mechanic, protocol, or requirement-bearing concept.
7. Project/product/brand-specific aliases such as BooksOnChain use PROJECT_NAME. A remaining real public company uses ORGANIZATION and a remaining real public service uses SERVICE. Phase 1 should already have synthesized those names; never restore an original name. Do not classify neutral synthetic labels such as "Payment Provider A", protocols, libraries, generic domain concepts, or requirement-bearing feature names as project aliases. Never redact any must_preserve_terms item. In particular, gamification mechanics and gameification mechanics are requirement terms, not project names.
8. If text contains no PII, return it unchanged with an empty entities list for text. A sender_id entity is still required when sender_id is non-null.
9. Do not invent, normalize, partially mask, or infer values not literally present in the supplied field. Verify that no declared source remains in its field after replacement.
"""


class PiiCleanError(RuntimeError):
    """Raised when a project cannot be cleaned without violating invariants."""


class PiiLeakError(ValueError):
    """A model response contains a sensitive value from the same input message."""


@dataclass(frozen=True)
class ProjectFiles:
    project_id: str
    project_dir: Path
    chat_path: Path


@dataclass(frozen=True)
class ManualRewrite:
    """A reviewed rewrite guarded by the SHA-256 of its exact source text."""

    project_id: str
    message_id: Any
    source_sha256: str
    text: str


@dataclass(frozen=True)
class CleanConfig:
    output_root: Path
    model: str
    reasoning_effort: str
    short_message_max_words: int
    max_batch_messages: int
    max_batch_chars: int
    resume: bool
    partial_resume: bool
    overwrite: bool
    extra_names: tuple[str, ...]
    extra_project_terms: tuple[str, ...]
    preserve_terms: tuple[str, ...]
    manual_rewrites: tuple[ManualRewrite, ...]


@dataclass(frozen=True)
class PiiBatchResult:
    """Validated phase-2 output, ready to be committed atomically."""

    texts: dict[str, str]
    sender_ids: dict[str, str | None]
    entities: tuple[tuple[str, str, str], ...]
    payloads: tuple[dict[str, Any], ...] = ()


class LlmPiiReplacementState:
    """Keep LLM-assigned placeholders stable across sequential phase-2 batches."""

    def __init__(self) -> None:
        self._by_entity: dict[tuple[str, str], str] = {}
        self._by_placeholder: dict[str, tuple[str, str]] = {}

    @staticmethod
    def entity_key(category: str, source: str) -> tuple[str, str]:
        return category, source.strip().casefold()

    def placeholder_for(self, category: str, source: str) -> str | None:
        return self._by_entity.get(self.entity_key(category, source))

    def owner_for(self, placeholder: str) -> tuple[str, str] | None:
        return self._by_placeholder.get(placeholder)

    def next_indices(self) -> dict[str, int]:
        next_values = {category: 1 for category in PII_CATEGORIES}
        for placeholder in self._by_placeholder:
            match = FULL_PLACEHOLDER_RE.fullmatch(placeholder)
            if match is None:
                continue
            category = match.group("category")
            next_values[category] = max(next_values[category], int(match.group("index")) + 1)
        return next_values

    def reserved_placeholders(self) -> list[str]:
        return sorted(self._by_placeholder)

    def relevant_known_replacements(
        self, messages: Sequence[dict[str, Any]]
    ) -> list[dict[str, str]]:
        haystacks = [
            str(value)
            for message in messages
            for value in (message.get("text"), message.get("sender_id"))
            if value is not None
        ]
        relevant: list[dict[str, str]] = []
        for (category, normalized_source), placeholder in sorted(self._by_entity.items()):
            if any(normalized_source in value.casefold() for value in haystacks):
                relevant.append(
                    {
                        "category": category,
                        "source_casefold": normalized_source,
                        "placeholder": placeholder,
                    }
                )
        return relevant

    def commit(self, entities: Sequence[tuple[str, str, str]]) -> None:
        for category, source, placeholder in entities:
            key = self.entity_key(category, source)
            existing = self._by_entity.get(key)
            owner = self._by_placeholder.get(placeholder)
            if existing not in (None, placeholder) or owner not in (None, key):
                raise PiiCleanError("Validated PII placeholder state became inconsistent")
            self._by_entity[key] = placeholder
            self._by_placeholder[placeholder] = key

    def counts(self) -> dict[str, int]:
        counts = Counter(category for category, _ in self._by_entity)
        return {category: counts[category] for category in sorted(counts)}


def _literal_term_pattern(term: str) -> str:
    prefix = r"(?<!\w)" if term and term[0].isalnum() else ""
    suffix = r"(?!\w)" if term and term[-1].isalnum() else ""
    return prefix + re.escape(term) + suffix


def find_present_terms(text: str, terms: Sequence[str]) -> tuple[str, ...]:
    """Return the exact source spelling of configured terms present in text."""

    found: list[str] = []
    seen: set[str] = set()
    for configured in terms:
        term = configured.strip()
        if not term or term.casefold() in seen:
            continue
        match = re.search(_literal_term_pattern(term), text, flags=re.IGNORECASE)
        if match is not None:
            exact = match.group(0)
            found.append(exact)
            seen.add(exact.casefold())
    return tuple(found)


def find_terms_outside_pii(
    text: str, terms: Sequence[str]
) -> tuple[str, ...]:
    """Find configured terms only outside fields replaced as complete PII.

    A provider name inside an email address or URL is part of that complete PII
    value. Sending a standalone ``docs.google.com`` URL to the structural
    rewrite phase would create an impossible task: it has no sentence structure
    to change and must instead be replaced as one URL during phase 2.
    """

    excluded = _context_rewrite_excluded_spans(text)
    found: list[str] = []
    seen: set[str] = set()
    for configured in terms:
        term = configured.strip()
        if not term or term.casefold() in seen:
            continue
        for match in re.finditer(
            _literal_term_pattern(term), text, flags=re.IGNORECASE
        ):
            if _overlaps_any(match.span(), excluded):
                continue
            exact = match.group(0)
            found.append(exact)
            seen.add(exact.casefold())
            break
    return tuple(found)


def find_public_service_terms(text: str) -> tuple[str, ...]:
    return find_terms_outside_pii(text, DEFAULT_PUBLIC_SERVICE_TERMS)


def preserved_term_counts(text: str, terms: Sequence[str]) -> Counter[str]:
    """Count protected terms case-sensitively so spelling is also preserved."""

    return Counter(
        {
            term: len(re.findall(_literal_term_pattern(term), text))
            for term in terms
            if term
        }
    )


def _overlaps_any(span: tuple[int, int], excluded: Sequence[tuple[int, int]]) -> bool:
    start, end = span
    return any(start < excluded_end and excluded_start < end for excluded_start, excluded_end in excluded)


def _is_technical_identifier_context(text: str, span: tuple[int, int]) -> bool:
    """Recognize code-symbol contexts that must not be treated as project names."""

    start, end = span
    before = text[max(0, start - 80) : start]
    after = text[end : min(len(text), end + 20)]
    technical_prefix = re.search(
        r"(?i)\b(?:emit|emits|emitted|event|function|method|class|contract|interface|"
        r"struct|enum|variable|constant|type|hook|component|endpoint|use|using|via|"
        r"built\s+(?:with|on)|powered\s+by|integrate(?:d)?\s+with|integration\s+with|"
        r"hosted\s+on|deployed\s+on)\s*$",
        before,
    )
    return technical_prefix is not None or re.match(r"\s*\(", after) is not None


def discover_project_terms(
    messages: Sequence[dict[str, Any]], extra_terms: Sequence[str] = ()
) -> tuple[str, ...]:
    """Find high-confidence project/brand aliases without touching tool terms.

    Automatic discovery is deliberately conservative: it accepts three-part
    CamelCase names and proper names in explicit naming contexts. Ambiguous
    names can be supplied with ``--extra-project-term``.
    """

    discovered: list[str] = []
    seen: set[str] = set()
    blocked: set[str] = set()
    explicit_names = {
        term.strip(" \t\r\n,.!?:;\"'“”()[]{}").casefold()
        for term in extra_terms
        if term.strip(" \t\r\n,.!?:;\"'“”()[]{}")
    }

    def add(raw_value: str, *, explicit: bool = False) -> None:
        value = raw_value.strip(" \t\r\n,.!?:;\"'“”()[]{}")
        if not value or len(value) < 3 or len(value) > 80:
            return
        normalized = value.casefold()
        if normalized in seen or (normalized in blocked and not explicit):
            return
        if not explicit:
            if normalized in TECHNICAL_TERM_ALLOWLIST:
                return
            words = value.replace("-", " ").split()
            if not words or words[0].casefold() in PROJECT_TERM_STOPLIST:
                return
            if any(char.isdigit() for char in value):
                return
        seen.add(normalized)
        discovered.append(value)

    for term in extra_terms:
        add(term, explicit=True)

    for message in messages:
        text = str(message.get("text") or "")
        excluded_spans = [
            match.span()
            for pattern in (EMAIL_RE, ANGLE_URL_RE, URL_RE, HANDLE_RE, PROTECTED_LITERAL_RE)
            for match in pattern.finditer(text)
        ]
        for pattern in (CAMEL_PROJECT_TERM_RE, PROJECT_NAME_CONTEXT_RE):
            for match in pattern.finditer(text):
                name_span = match.span("name")
                if _overlaps_any(name_span, excluded_spans):
                    continue
                candidate = match.group("name")
                normalized = candidate.casefold()
                if _is_technical_identifier_context(text, name_span):
                    if normalized not in explicit_names:
                        blocked.add(normalized)
                        seen.discard(normalized)
                        discovered[:] = [
                            term for term in discovered if term.casefold() != normalized
                        ]
                    continue
                add(candidate)
    return tuple(discovered)


def _sentence_unit_count(text: str) -> int:
    return len([part for part in SENTENCE_BREAK_RE.split(text) if WORD_RE.search(part)])


def has_structural_change(source_text: str, rewritten_text: str) -> bool:
    """Reject shallow synonym swaps while allowing verifiable restructuring."""

    source_tokens = [token.casefold() for token in WORD_RE.findall(PLACEHOLDER_RE.sub(" placeholder ", source_text))]
    rewritten_tokens = [
        token.casefold() for token in WORD_RE.findall(PLACEHOLDER_RE.sub(" placeholder ", rewritten_text))
    ]
    if not source_tokens or not rewritten_tokens:
        return False

    # Splitting or combining complete sentences is an observable structural edit.
    if _sentence_unit_count(source_text) != _sentence_unit_count(rewritten_text):
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
    return SequenceMatcher(None, source_tokens, rewritten_tokens, autojunk=False).ratio() <= 0.55


class PlaceholderRegistry:
    """Assign stable per-project placeholders without persisting raw PII."""

    def __init__(self) -> None:
        self._by_category: dict[str, dict[str, str]] = {}
        self._raw_values: dict[str, set[str]] = {}

    def token(self, category: str, raw_value: str) -> str:
        category = category.upper()
        raw_value = raw_value.strip()
        normalized = raw_value.casefold()
        mapping = self._by_category.setdefault(category, {})
        if normalized not in mapping:
            mapping[normalized] = f"[{category}_{len(mapping) + 1:03d}]"
            self._raw_values.setdefault(category, set()).add(raw_value)
        return mapping[normalized]

    def existing_token(self, category: str, raw_value: str) -> str | None:
        return self._by_category.get(category.upper(), {}).get(raw_value.strip().casefold())

    def counts(self) -> dict[str, int]:
        return {category: len(values) for category, values in sorted(self._by_category.items())}

    def sensitive_values(self) -> Iterable[str]:
        for values in self._raw_values.values():
            yield from values

    def sensitive_entries(self) -> Iterable[tuple[str, str]]:
        for category, values in self._raw_values.items():
            for value in values:
                yield category, value


class DeterministicPiiCleaner:
    """Detect and replace PII consistently within one project."""

    def __init__(
        self,
        messages: Sequence[dict[str, Any]],
        extra_names: Sequence[str] = (),
        project_terms: Sequence[str] = (),
    ) -> None:
        self.registry = PlaceholderRegistry()
        self._name_categories: dict[str, tuple[str, str]] = {}
        self._project_names: dict[str, str] = {}
        self._standalone_credentials: dict[str, list[tuple[str, str]]] = {}
        self._sender_ids: list[str] = []
        for name in extra_names:
            self._add_name(name, "PERSON_NAME")
        for term in project_terms:
            self._add_project_name(term)
        for message in messages:
            sender_id = message.get("sender_id")
            if sender_id is not None and str(sender_id).strip():
                value = str(sender_id).strip()
                if value.casefold() not in {item.casefold() for item in self._sender_ids}:
                    self._sender_ids.append(value)
                    self.registry.token("SENDER_ID", value)
        self._discover_names(messages)
        self._discover_standalone_credentials(messages)
        self._discover_inline_credentials(messages)

    def _add_project_name(self, raw_name: str) -> None:
        cleaned = raw_name.strip(" \t\r\n,.!?:;\"'“”()[]{}")
        if not cleaned or len(cleaned) > 80:
            return
        key = cleaned.casefold()
        if key not in self._project_names:
            self._project_names[key] = cleaned
            self.registry.token("PROJECT_NAME", cleaned)

    def _add_name(self, raw_name: str, category: str, *, require_title_case: bool = False) -> None:
        cleaned = raw_name.strip(" \t\r\n,.!?:;\"'()[]{}")
        if not cleaned:
            return
        name_parts = cleaned.split()
        if require_title_case:
            title_parts: list[str] = []
            for part in name_parts:
                if not part or not part[0].isupper():
                    break
                title_parts.append(part)
            cleaned = " ".join(title_parts)
            name_parts = title_parts
        if not cleaned or cleaned.casefold() in NON_NAME_WORDS | STRUCTURAL_STOP_WORDS:
            return
        if any(
            part.casefold() in NON_NAME_WORDS | STRUCTURAL_STOP_WORDS
            for part in name_parts
        ):
            return
        if any(char.isdigit() for char in cleaned) or len(cleaned) > 80:
            return
        key = cleaned.casefold()
        if key not in self._name_categories:
            self._name_categories[key] = (cleaned, category)
            self.registry.token(category, cleaned)

    @staticmethod
    def _speaker_name_category(speaker: Any) -> str:
        value = str(speaker or "").casefold()
        if value == "client":
            return "CLIENT_NAME"
        if value == "freelancer":
            return "FREELANCER_NAME"
        return "PERSON_NAME"

    @staticmethod
    def _addressed_name_category(speaker: Any) -> str:
        value = str(speaker or "").casefold()
        if value == "client":
            return "FREELANCER_NAME"
        if value == "freelancer":
            return "CLIENT_NAME"
        return "PERSON_NAME"

    def _discover_names(self, messages: Sequence[dict[str, Any]]) -> None:
        for message in messages:
            text = str(message.get("text") or "")
            addressed_category = self._addressed_name_category(message.get("speaker"))
            for pattern in (GREETING_NAME_RE, THANKS_NAME_RE):
                for match in pattern.finditer(text):
                    self._add_name(match.group("name"), addressed_category, require_title_case=True)
            for match in SIGNATURE_NAME_RE.finditer(text):
                self._add_name(
                    match.group("name"),
                    self._speaker_name_category(message.get("speaker")),
                    require_title_case=True,
                )

    def _discover_standalone_credentials(self, messages: Sequence[dict[str, Any]]) -> None:
        login_context_remaining = 0
        account_seen = False
        for message in messages:
            key = id_key(message.get("message_id"))
            text = str(message.get("text") or "").strip()
            if self._looks_like_login_context(text):
                login_context_remaining = 3
                account_seen = False
                continue

            if self._is_high_entropy_secret(text):
                self._register_standalone(key, "PASSWORD", text)
                if login_context_remaining:
                    login_context_remaining -= 1
                continue

            if login_context_remaining and self._looks_like_account_token(text) and not account_seen:
                self._register_standalone(key, "ACCOUNT", text)
                account_seen = True
                login_context_remaining -= 1
                continue

            if login_context_remaining:
                if text and not SHORT_ACKNOWLEDGEMENTS.fullmatch(text):
                    login_context_remaining = 0
                    account_seen = False
                else:
                    login_context_remaining -= 1

    def _register_standalone(self, message_key: str, category: str, value: str) -> None:
        self.registry.token(category, value)
        self._standalone_credentials.setdefault(message_key, []).append((category, value))

    def _discover_inline_credentials(self, messages: Sequence[dict[str, Any]]) -> None:
        """Register explicit credentials before any message is sanitized.

        Pre-registration lets the same credential be replaced when it is reused
        later in a sentence without another ``password:``/``login:`` prefix.
        """
        for message in messages:
            text = str(message.get("text") or "")
            for match in INLINE_CREDENTIAL_RE.finditer(text):
                self._replace_inline_credential(match)

    @staticmethod
    def _looks_like_login_context(text: str) -> bool:
        lowered = text.casefold()
        has_url = bool(ANGLE_URL_RE.search(text) or URL_RE.search(text))
        return has_url and any(word in lowered for word in ("login", "admin", "sign-in", "signin", "wp-admin"))

    @staticmethod
    def _is_high_entropy_secret(text: str) -> bool:
        if not (8 <= len(text) <= 200) or not SINGLE_TOKEN_RE.fullmatch(text):
            return False
        if EMAIL_RE.fullmatch(text) or ANGLE_URL_RE.fullmatch(text) or URL_RE.fullmatch(text):
            return False
        classes = sum(
            (
                any(char.islower() for char in text),
                any(char.isupper() for char in text),
                any(char.isdigit() for char in text),
                any(not char.isalnum() for char in text),
            )
        )
        return classes >= 3 and any(char.isdigit() for char in text)

    @staticmethod
    def _looks_like_account_token(text: str) -> bool:
        if not (2 <= len(text) <= 80) or not SINGLE_TOKEN_RE.fullmatch(text):
            return False
        if text.casefold() in NON_CREDENTIAL_VALUES or SHORT_ACKNOWLEDGEMENTS.fullmatch(text):
            return False
        return bool(re.search(r"[A-Za-z]", text)) and not text.startswith("[")

    def sanitize_message(self, message: dict[str, Any]) -> str:
        message_key = id_key(message.get("message_id"))
        text = str(message.get("text") or "")

        for category, raw_value in self._standalone_credentials.get(message_key, []):
            if text.strip() == raw_value:
                return self.registry.token(category, raw_value)

        text = EMAIL_RE.sub(lambda match: self.registry.token("EMAIL", match.group(0)), text)
        text = ANGLE_URL_RE.sub(lambda match: self.registry.token("URL", match.group(0)), text)
        text = URL_RE.sub(self._replace_url, text)
        text = PHONE_RE.sub(self._replace_phone, text)
        text = HANDLE_RE.sub(lambda match: self.registry.token("HANDLE", match.group(0)), text)
        text = self._replace_known_credentials(text)
        text = INLINE_CREDENTIAL_RE.sub(self._replace_inline_credential, text)

        for sender_id in self._sender_ids:
            token = self.registry.existing_token("SENDER_ID", sender_id)
            if token is not None:
                text = re.sub(
                    rf"(?<!\w){re.escape(sender_id)}(?!\w)",
                    lambda _match, replacement=token: replacement,
                    text,
                    flags=re.IGNORECASE,
                )

        for _, raw_name in sorted(
            self._project_names.items(), key=lambda item: len(item[1]), reverse=True
        ):
            token = self.registry.existing_token("PROJECT_NAME", raw_name)
            if token is None:
                continue
            text = re.sub(
                rf"(?<!\w){re.escape(raw_name)}(?!\w)",
                lambda _match, replacement=token: replacement,
                text,
                flags=re.IGNORECASE,
            )

        for _, (raw_name, category) in sorted(
            self._name_categories.items(), key=lambda item: len(item[1][0]), reverse=True
        ):
            token = self.registry.existing_token(category, raw_name)
            if token is None:
                continue
            text = re.sub(
                rf"(?<!\w){re.escape(raw_name)}(?!\w)",
                lambda _match, replacement=token: replacement,
                text,
                flags=re.IGNORECASE,
            )
        return text

    def _replace_known_credentials(self, text: str) -> str:
        for category, raw_value in sorted(
            (
                (category, raw_value)
                for category, raw_value in self.registry.sensitive_entries()
                if category in {"ACCOUNT", "PASSWORD"}
            ),
            key=lambda item: len(item[1]),
            reverse=True,
        ):
            token = self.registry.existing_token(category, raw_value)
            if token is None:
                continue
            if category == "PASSWORD":
                pattern = re.escape(raw_value)
            else:
                pattern = rf"(?<!\w){re.escape(raw_value)}(?!\w)"
            text = re.sub(
                pattern,
                lambda _match, replacement=token: replacement,
                text,
                flags=re.IGNORECASE,
            )
        return text

    def _replace_url(self, match: re.Match[str]) -> str:
        raw = match.group(0)
        core = raw.rstrip(".,;:!?)]")
        trailing = raw[len(core) :]
        return self.registry.token("URL", core) + trailing

    def _replace_phone(self, match: re.Match[str]) -> str:
        raw = match.group(0)
        if DATE_RE.search(raw):
            return raw
        digits = sum(char.isdigit() for char in raw)
        looks_specific = raw.startswith("+") or "(" in raw or digits >= 10
        if 7 <= digits <= 15 and looks_specific:
            return self.registry.token("PHONE", raw)
        return raw

    def _replace_inline_credential(self, match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        value = match.group("value").strip("\"'")
        if not value or value.startswith("[") or value.casefold() in NON_CREDENTIAL_VALUES:
            return match.group(0)
        lowered_prefix = prefix.casefold()
        category = "PASSWORD" if any(word in lowered_prefix for word in ("password", "passcode", "pwd")) else "ACCOUNT"
        explicit_separator = ":" in prefix or "=" in prefix
        if category == "ACCOUNT" and not explicit_separator and value.isalpha() and len(value) <= 2:
            # Natural-language phrases such as "login is to ..." are not credentials.
            # Explicit forms such as "login: ab" remain protected.
            return match.group(0)
        return prefix + self.registry.token(category, value)

    def assert_no_known_pii(self, text: str, *, source_text: str | None = None, message_id: Any = None) -> None:
        """Reject a reintroduced PII value without exposing that value in logs.

        ``source_text`` scopes the check to one message. This avoids treating a
        normal word in message B as a leak merely because the same word happened
        to be an account/name in a different message A.
        """
        for category, raw_value in self.registry.sensitive_entries():
            candidate = raw_value.strip()
            if len(candidate) < 2:
                continue
            pattern = rf"(?<!\w){re.escape(candidate)}(?!\w)"
            if source_text is not None and not re.search(pattern, source_text, flags=re.IGNORECASE):
                continue
            if re.search(pattern, text, flags=re.IGNORECASE):
                fingerprint = sha256_text(f"{category}:{candidate}")[:12]
                location = f" for message_id {message_id!r}" if message_id is not None else ""
                raise PiiLeakError(
                    f"PII reintroduced{location}: category={category}, fingerprint={fingerprint}"
                )
        if EMAIL_RE.search(text) or ANGLE_URL_RE.search(text) or URL_RE.search(text):
            location = f" for message_id {message_id!r}" if message_id is not None else ""
            raise PiiLeakError(f"PII reintroduced{location}: category=EMAIL_OR_URL")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(
        description="Classify context, paraphrase, and de-identify project chats with three LLM phases."
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=root / "Datasets" / "project",
        help="Directory containing <project_id>/chat_messages.json.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=root / "Datasets" / "PII_clean_project",
        help="Destination root for copied projects with cleaned chat_messages.json files.",
    )
    parser.add_argument("--project-id", action="append", help="Repeat to select multiple project IDs.")
    parser.add_argument("--model", default=ANNOTATION_MODEL)
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high", "xhigh", "max"),
        default=REASONING_EFFORT,
    )
    parser.add_argument("--short-message-max-words", type=int, default=5)
    parser.add_argument("--max-batch-messages", type=int, default=40)
    parser.add_argument("--max-batch-chars", type=int, default=30_000)
    parser.add_argument("--project-concurrency", type=int, default=2)
    parser.add_argument("--max-concurrent-requests", type=int, default=4)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--partial-resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Reuse validated per-batch checkpoints after a failed run. This is independent "
            "of --resume/--no-resume; use --no-partial-resume for a completely fresh run."
        ),
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification for trusted staging only.")
    parser.add_argument(
        "--extra-name",
        action="append",
        default=[],
        help="Person name the local post-LLM audit must require the PII LLM to replace.",
    )
    parser.add_argument(
        "--extra-project-term",
        action="append",
        default=[],
        help=(
            "Project, brand, or product name the local post-LLM audit must require "
            "the PII LLM to replace; repeat for multiple terms."
        ),
    )
    parser.add_argument(
        "--preserve-term",
        action="append",
        default=[],
        help=(
            "Tool, technology, feature, or requirement-bearing term that the rewrite "
            "and PII phases must preserve exactly; repeat for multiple terms."
        ),
    )
    parser.add_argument(
        "--manual-rewrites",
        type=Path,
        default=root / "Code" / "PII_Clean_manual_rewrites.json",
        help=(
            "Optional reviewed-rewrite JSON file. Each entry must include project_id, "
            "message_id, source_sha256, and text. Defaults to the repository's reviewed "
            "rewrite file; source hashes prevent stale rewrites."
        ),
    )
    args = parser.parse_args()
    if args.short_message_max_words < 0:
        parser.error("--short-message-max-words must be >= 0")
    if args.max_batch_messages < 1 or args.max_batch_chars < 1:
        parser.error("batch limits must be >= 1")
    if args.project_concurrency < 1 or args.max_concurrent_requests < 1:
        parser.error("concurrency values must be >= 1")
    if args.retries < 0 or args.timeout <= 0:
        parser.error("--retries must be >= 0 and --timeout must be > 0")
    if args.source_root.resolve() == args.output_root.resolve():
        parser.error("--output-root must differ from --source-root; in-place cleaning is intentionally disabled")
    return args


def load_manual_rewrites(path: Path | None) -> tuple[ManualRewrite, ...]:
    if path is None:
        return ()
    payload = read_json(path)
    entries = payload.get("rewrites") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise PiiCleanError(f"{path}: expected an object containing a rewrites list")

    rewrites: list[ManualRewrite] = []
    seen: set[tuple[str, str]] = set()
    required = {"project_id", "message_id", "source_sha256", "text"}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != required:
            raise PiiCleanError(
                f"{path}: rewrites[{index}] must contain exactly {', '.join(sorted(required))}"
            )
        project_id = entry["project_id"]
        source_hash = entry["source_sha256"]
        text = entry["text"]
        if not isinstance(project_id, str) or not project_id.strip():
            raise PiiCleanError(f"{path}: rewrites[{index}].project_id must be a non-empty string")
        if not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash):
            raise PiiCleanError(f"{path}: rewrites[{index}].source_sha256 must be lowercase SHA-256")
        if not isinstance(text, str) or not text.strip():
            raise PiiCleanError(f"{path}: rewrites[{index}].text must be non-empty")
        key = (project_id, id_key(entry["message_id"]))
        if key in seen:
            raise PiiCleanError(
                f"{path}: duplicate manual rewrite for project {project_id}, "
                f"message_id {entry['message_id']!r}"
            )
        seen.add(key)
        rewrites.append(
            ManualRewrite(
                project_id=project_id,
                message_id=entry["message_id"],
                source_sha256=source_hash,
                text=text,
            )
        )
    return tuple(rewrites)


def discover_projects(source_root: Path, wanted_ids: set[str] | None = None) -> list[ProjectFiles]:
    if not source_root.is_dir():
        raise PiiCleanError(f"Dataset project root does not exist: {source_root}")
    projects: list[ProjectFiles] = []
    for project_dir in sorted((path for path in source_root.iterdir() if path.is_dir()), key=lambda path: path.name):
        project_id = project_dir.name
        if wanted_ids is not None and project_id not in wanted_ids:
            continue
        chat_path = project_dir / "chat_messages.json"
        if not chat_path.is_file():
            continue
        projects.append(ProjectFiles(project_id, project_dir, chat_path))
    if wanted_ids is not None:
        missing = wanted_ids.difference(project.project_id for project in projects)
        if missing:
            raise PiiCleanError(f"Unknown project ID(s) or missing chat_messages.json: {', '.join(sorted(missing))}")
    return projects


def validate_and_adapt_chat_messages(chat: Any, project_id: str) -> list[dict[str, Any]]:
    """Validate raw chat rows and adapt them to the internal message schema."""
    if not isinstance(chat, list):
        raise PiiCleanError(f"{project_id}: chat_messages.json must contain a JSON list")
    adapted: list[dict[str, Any]] = []
    for index, row in enumerate(chat):
        if not isinstance(row, dict):
            raise PiiCleanError(f"{project_id}: chat row {index} must be an object")
        if not isinstance(row.get("message"), str):
            raise PiiCleanError(f"{project_id}: chat row {index} needs a string message field")
        adapted.append(
            {
                "message_id": index + 1,
                "speaker": row.get("message_user_type"),
                "text": row["message"],
                "sender_id": row.get("sender_id"),
            }
        )
    return adapted


def validate_normalized_messages(normalized: dict[str, Any], project_id: str) -> list[dict[str, Any]]:
    messages = normalized.get("messages")
    if not isinstance(messages, list):
        raise PiiCleanError(f"{project_id}: normalized_project.messages must be a list")
    seen: set[str] = set()
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise PiiCleanError(f"{project_id}: message {index} must be an object")
        if "message_id" not in message or not isinstance(message.get("text"), str):
            raise PiiCleanError(f"{project_id}: message {index} needs message_id and string text")
        key = id_key(message["message_id"])
        if key in seen:
            raise PiiCleanError(f"{project_id}: duplicate message_id {message['message_id']!r}")
        seen.add(key)
    return messages


def word_count(text: str) -> int:
    return len(WORD_RE.findall(PLACEHOLDER_RE.sub(" placeholder ", text)))


def _rewrite_exempt(text: str) -> bool:
    stripped = text.strip()
    if not stripped or SHORT_ACKNOWLEDGEMENTS.fullmatch(stripped):
        return True
    if any(
        pattern.fullmatch(stripped)
        for pattern in (EMAIL_RE, ANGLE_URL_RE, URL_RE, HANDLE_RE)
    ):
        return True
    if PHONE_RE.fullmatch(stripped) and DATE_RE.search(stripped) is None:
        return True
    without_placeholders = PLACEHOLDER_RE.sub(" ", text)
    if not without_placeholders.strip(" \t\r\n.,!?;:()[]{}<>-'\"…"):
        return True
    return False


def requires_structural_rewrite(text: str, short_message_max_words: int) -> bool:
    """Whether a message has enough natural language to require restructuring."""

    return not _rewrite_exempt(text) and word_count(text) > short_message_max_words


def should_rewrite(text: str, short_message_max_words: int) -> bool:
    if _rewrite_exempt(text):
        return False
    # Even a short message must enter phase 1 when it contains contextual
    # values that the user explicitly wants synthesized.
    return bool(contextual_values(text) or find_public_service_terms(text)) or (
        word_count(text) > short_message_max_words
    )


def build_batches(
    messages: Sequence[dict[str, Any]], max_messages: int, max_chars: int
) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for message in messages:
        size = len(str(message.get("text") or ""))
        if current and (len(current) >= max_messages or current_chars + size > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(message)
        current_chars += size
    if current:
        batches.append(current)
    return batches


def protected_numbers(text: str) -> Counter[str]:
    # Numeric HTML entities such as ``&#39;`` encode punctuation rather than
    # business numbers. Models may safely render them as literal characters.
    without_entities = HTML_NUMERIC_ENTITY_RE.sub(
        lambda match: " " * len(match.group(0)), text
    )
    return Counter(match.group(0) for match in NUMBER_TOKEN_RE.finditer(without_entities))


def protected_literals(
    text: str, excluded_terms: Sequence[str] = ()
) -> Counter[str]:
    masked = text
    for term in sorted(
        (value for value in excluded_terms if value), key=len, reverse=True
    ):
        masked = re.sub(
            _literal_term_pattern(term),
            lambda match: " " * len(match.group(0)),
            masked,
            flags=re.IGNORECASE,
        )
    return Counter(match.group(0) for match in PROTECTED_LITERAL_RE.finditer(masked))


def _structural_list_marker_matches(text: str) -> tuple[re.Match[str], ...]:
    """Classify structural list indices without treating all line-leading numbers alike.

    Explicit punctuation (``1.``, ``2)``, ``3 -`` and ``4:``) is strong evidence.
    Ambiguous forms such as ``1-grid`` or ``1 #rules`` are accepted only when
    entries in the same message form a consecutive sequence beginning at 0 or 1
    (or continue an explicit sequence). Two-item weak sequences must also be on
    nearby lines. This keeps standalone quantities, times, ranges, addresses and
    decimals in the contextual-value path.
    """

    explicit = list(LIST_MARKER_RE.finditer(text))
    selected: dict[tuple[int, int], re.Match[str]] = {
        match.span("number"): match for match in explicit
    }
    explicit_spans = set(selected)

    weak = [
        match
        for match in WEAK_LIST_MARKER_RE.finditer(text)
        if match.span("number") not in explicit_spans
    ]
    candidates = sorted((*explicit, *weak), key=lambda match: match.start("number"))

    runs: list[list[re.Match[str]]] = []
    current_run: list[re.Match[str]] = []
    previous_number: int | None = None
    for match in candidates:
        number = int(match.group("number"))
        if current_run and number == (previous_number or 0) + 1:
            current_run.append(match)
        else:
            if current_run:
                runs.append(current_run)
            current_run = [match]
        previous_number = number
    if current_run:
        runs.append(current_run)

    for run in runs:
        starts_like_list = int(run[0].group("number")) in {0, 1}
        continues_explicit_list = any(
            match.span("number") in explicit_spans for match in run
        )
        line_numbers = [text.count("\n", 0, match.start("number")) for match in run]
        closely_spaced = all(
            right - left <= 2
            for left, right in zip(line_numbers, line_numbers[1:])
        )
        credible_weak_sequence = starts_like_list and (
            len(run) >= 3 or closely_spaced
        )
        if len(run) >= 2 and (credible_weak_sequence or continues_explicit_list):
            for match in run:
                selected[match.span("number")] = match

    # Handle compact lists that continue on the same physical line, for example
    # ``1. First item 2. Second item``. Only an explicit line-start marker can
    # seed this inference, which avoids treating ordinary prose about phases as
    # a list merely because it contains ``1.`` and ``2.``.
    for first in explicit:
        line_end = text.find("\n", first.end())
        if line_end < 0:
            line_end = len(text)
        expected_number = int(first.group("number")) + 1
        for match in INLINE_LIST_MARKER_RE.finditer(text, first.end(), line_end):
            if match.span("number") in selected:
                continue
            if int(match.group("number")) != expected_number:
                continue
            selected[match.span("number")] = match
            expected_number += 1

    return tuple(selected[span] for span in sorted(selected))


def _pii_context_excluded_spans(text: str) -> list[tuple[int, int]]:
    """Return complete values that phase 2 handles as PII."""

    spans = [
        match.span()
        for pattern in (
            PLACEHOLDER_RE,
            EMAIL_RE,
            ANGLE_URL_RE,
            URL_RE,
            HANDLE_RE,
            HTML_NUMERIC_ENTITY_RE,
        )
        for match in pattern.finditer(text)
    ]
    date_spans = [match.span() for match in DATE_RE.finditer(text)]
    spans.extend(
        match.span()
        for match in PHONE_RE.finditer(text)
        if not _overlaps_any(match.span(), date_spans)
    )
    spans.extend(match.span("value") for match in INLINE_CREDENTIAL_RE.finditer(text))
    return spans


def _context_rewrite_excluded_spans(text: str) -> list[tuple[int, int]]:
    """Return PII and structural-list spans excluded from local synthesis."""

    spans = _pii_context_excluded_spans(text)
    spans.extend(
        match.span("number") for match in _structural_list_marker_matches(text)
    )
    return spans


def context_occurrence_candidates(text: str) -> tuple[dict[str, Any], ...]:
    """Extract maximal candidates for semantic classification by the LLM.

    Regexes only nominate occurrences and provide a non-authoritative hint. The
    phase-0 model assigns the actual role after reading the complete message.
    """

    pii_spans = _pii_context_excluded_spans(text)
    technical_spans = [match.span() for match in PROTECTED_LITERAL_RE.finditer(text)]
    proposals: list[tuple[int, int, int, str]] = []

    for match in _structural_list_marker_matches(text):
        start, end = match.span("number")
        proposals.append((start, end, 0, "LIST_INDEX"))
    for priority, (hint, pattern) in enumerate(
        (
            ("FILENAME", FILENAME_RE),
            ("AMOUNT", AMOUNT_TOKEN_RE),
            ("DATE", DATE_RE),
            ("VERSION", VERSION_RE),
            ("NUMBER", NUMBER_TOKEN_RE),
        ),
        start=1,
    ):
        for match in pattern.finditer(text):
            start, end = match.span()
            if _overlaps_any((start, end), pii_spans):
                continue
            proposals.append((start, end, priority, hint))

    selected: list[tuple[int, int, int, str]] = []
    for proposal in sorted(
        proposals,
        key=lambda item: (item[0], -(item[1] - item[0]), item[2]),
    ):
        span = proposal[:2]
        if _overlaps_any(span, [item[:2] for item in selected]):
            continue
        selected.append(proposal)
    selected.sort(key=lambda item: item[0])

    occurrences: list[dict[str, Any]] = []
    for index, (start, end, _priority, hint) in enumerate(selected, start=1):
        if hint == "NUMBER" and _overlaps_any((start, end), technical_spans):
            hint = "TECHNICAL_IDENTIFIER"
        context_start = max(0, start - 80)
        context_end = min(len(text), end + 80)
        occurrences.append(
            {
                "occurrence_id": f"C{index:03d}",
                "source": text[start:end],
                "local_hint": hint,
                "context": text[context_start:context_end],
            }
        )
    return tuple(occurrences)


def contextual_values(text: str) -> tuple[tuple[str, str], ...]:
    """Extract contextual literals that phase 1 must replace with synthetic values.

    Filenames, amounts, versions and dates are selected before general numeric
    values so a digit inside one of those values is represented by the maximal
    literal. Amounts precede versions so ``$15.00`` cannot be misclassified as
    version ``15.00``.
    PII-shaped spans are excluded because phase 2 will remove them entirely.
    Complete protected technical identifiers are also excluded so embedded
    numbers in values such as ``ERC-721`` and ``AES-256`` are not synthesized.
    """

    excluded = _context_rewrite_excluded_spans(text)
    protected_identifier_spans = [
        match.span() for match in PROTECTED_LITERAL_RE.finditer(text)
    ]
    selected_spans: list[tuple[int, int]] = []
    values: list[tuple[int, str, str]] = []
    for category, pattern in (
        ("FILENAME", FILENAME_RE),
        ("AMOUNT", AMOUNT_TOKEN_RE),
        ("VERSION", VERSION_RE),
        ("DATE", DATE_RE),
    ):
        for match in pattern.finditer(text):
            span = match.span()
            if _overlaps_any(span, excluded) or _overlaps_any(span, selected_spans):
                continue
            selected_spans.append(span)
            values.append((span[0], category, match.group(0)))
    for match in NUMBER_TOKEN_RE.finditer(text):
        span = match.span()
        if (
            _overlaps_any(span, excluded)
            or _overlaps_any(span, protected_identifier_spans)
            or _overlaps_any(span, selected_spans)
        ):
            continue
        selected_spans.append(span)
        values.append((span[0], "NUMBER", match.group(0)))
    values.sort(key=lambda item: item[0])
    return tuple((category, source) for _, category, source in values)


def _context_category_counts(values: Sequence[tuple[str, str]]) -> Counter[str]:
    return Counter(category for category, _ in values)


def structural_list_markers(text: str) -> tuple[str, ...]:
    """Return ordered-list indices, which are layout rather than project data."""

    return tuple(
        match.group("number") for match in _structural_list_marker_matches(text)
    )


def _context_action(category: str) -> str:
    if category in {"LIST_INDEX", "TECHNICAL_IDENTIFIER", "PII_COMPONENT"}:
        return "PRESERVE"
    return "REPLACE"


def validate_context_classification_response(
    payload: dict[str, Any],
    inputs: Sequence[dict[str, Any]],
) -> dict[str, tuple[dict[str, str], ...]]:
    classified = payload.get("classified_messages")
    if not isinstance(classified, list):
        raise ValueError("LLM context response must contain a classified_messages list")
    expected = {id_key(message["message_id"]): message for message in inputs}
    actual: dict[str, tuple[dict[str, str], ...]] = {}
    for index, item in enumerate(classified):
        if not isinstance(item, dict) or set(item) != {"message_id", "occurrences"}:
            raise ValueError(
                f"classified_messages[{index}] must contain exactly message_id and occurrences"
            )
        key = id_key(item.get("message_id"))
        if key not in expected or key in actual:
            raise ValueError(f"Unexpected or duplicate classified message_id: {item.get('message_id')!r}")
        supplied = item.get("occurrences")
        if not isinstance(supplied, list):
            raise ValueError(f"Context classification for {item.get('message_id')!r} must be a list")
        candidates = expected[key].get("context_candidates", ())
        expected_by_id = {
            candidate["occurrence_id"]: candidate for candidate in candidates
        }
        if len(supplied) != len(expected_by_id):
            raise ValueError(
                f"Context classification for {item.get('message_id')!r} changed occurrence count"
            )
        resolved: list[dict[str, str]] = []
        seen: set[str] = set()
        for occurrence in supplied:
            if not isinstance(occurrence, dict) or set(occurrence) != {
                "occurrence_id",
                "category",
            }:
                raise ValueError("Each context classification must contain occurrence_id and category")
            occurrence_id = occurrence.get("occurrence_id")
            category = occurrence.get("category")
            if (
                not isinstance(occurrence_id, str)
                or occurrence_id not in expected_by_id
                or occurrence_id in seen
            ):
                raise ValueError("Context classification returned an unknown or duplicate occurrence_id")
            if category not in CONTEXT_CATEGORIES:
                raise ValueError(f"Context classification returned invalid category {category!r}")
            seen.add(occurrence_id)
            candidate = expected_by_id[occurrence_id]
            resolved.append(
                {
                    "occurrence_id": occurrence_id,
                    "source": str(candidate["source"]),
                    "local_hint": str(candidate["local_hint"]),
                    "category": str(category),
                    "action": _context_action(str(category)),
                }
            )
        resolved.sort(key=lambda value: value["occurrence_id"])
        actual[key] = tuple(resolved)
    if set(actual) != set(expected):
        raise ValueError("LLM context response omitted one or more messages")
    return actual


def context_classification_request_messages(
    batch: Sequence[dict[str, Any]],
    repair_instruction: str | None = None,
) -> list[dict[str, str]]:
    body: dict[str, Any] = {
        "task": "Classify each supplied occurrence after reading its complete message.",
        "messages": [
            {
                "message_id": message["message_id"],
                "speaker": message.get("speaker"),
                "text": message["text"],
                "occurrences": list(message.get("context_candidates", ())),
            }
            for message in batch
        ],
    }
    if repair_instruction:
        body["validation_repair"] = repair_instruction
    return [
        {"role": "system", "content": CONTEXT_CLASSIFY_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
    ]


async def classify_context_batch(
    api: Stage1ApiClient,
    project_id: str,
    batch_number: int,
    batch: Sequence[dict[str, Any]],
    progress_callback: Callable[[dict[str, tuple[dict[str, str], ...]]], None]
    | None = None,
) -> dict[str, tuple[dict[str, str], ...]]:
    async def call_one(
        target: str,
        inputs: Sequence[dict[str, Any]],
        repair_instruction: str | None = None,
    ) -> dict[str, tuple[dict[str, str], ...]]:
        def validator(payload: dict[str, Any]) -> None:
            validate_context_classification_response(payload, inputs)

        payload = await api.call(
            project_id=project_id,
            run_mode=CONTEXT_CLASSIFY_RUN_MODE,
            target_requirement=target,
            messages=context_classification_request_messages(inputs, repair_instruction),
            validator=validator,
            failed_response_redactor=lambda _raw: "[REDACTED: raw context response omitted]",
        )
        return validate_context_classification_response(payload, inputs)

    target = f"batch_{batch_number:04d}"
    try:
        return await call_one(target, batch)
    except ApiError as exc:
        if len(batch) <= 1 or "ValueError" not in str(exc):
            raise

    combined: dict[str, tuple[dict[str, str], ...]] = {}
    for message in batch:
        result = await call_one(
            f"{target}_message_{id_key(message['message_id'])}",
            [message],
            (
                "The previous batched classification failed validation. Return this message and "
                "every supplied occurrence_id exactly once, using only an allowed category. Read "
                "the complete message before deciding; do not rewrite or add keys."
            ),
        )
        combined.update(result)
        if progress_callback is not None:
            progress_callback(result)
    return combined


def validate_rewrite_response(
    payload: dict[str, Any],
    inputs: Sequence[dict[str, Any]],
) -> dict[str, str]:
    rewrites = payload.get("rewrites")
    if not isinstance(rewrites, list):
        raise ValueError("LLM response must contain a rewrites list")
    expected = {id_key(message["message_id"]): message for message in inputs}
    actual: dict[str, str] = {}
    for index, item in enumerate(rewrites):
        if not isinstance(item, dict) or set(item) != {"message_id", "text"}:
            raise ValueError(f"rewrites[{index}] must contain exactly message_id and text")
        key = id_key(item.get("message_id"))
        if key not in expected:
            raise ValueError(f"Unexpected message_id in LLM response: {item.get('message_id')!r}")
        if key in actual:
            raise ValueError(f"Duplicate message_id in LLM response: {item.get('message_id')!r}")
        output_text = item.get("text")
        if not isinstance(output_text, str) or not output_text.strip():
            raise ValueError(f"Rewrite for {item.get('message_id')!r} must be non-empty text")
        input_text = str(expected[key]["text"])
        if output_text.strip() == input_text.strip():
            raise ValueError(f"Rewrite for {item.get('message_id')!r} is unchanged")
        classified_occurrences = expected[key].get("context_occurrences")
        # The local parser only extracts syntactic ordered-list markers such as
        # line-leading ``1.``/``2.``.  The context LLM can additionally classify
        # headings such as ``Option 1`` as LIST_INDEX.  Do not compare those
        # semantic headings with the narrower local extractor: every
        # LLM-classified preserved occurrence is checked separately below.
        expected_list_markers = structural_list_markers(input_text)
        if structural_list_markers(output_text) != expected_list_markers:
            raise ValueError(
                f"Rewrite for {item.get('message_id')!r} changed structural list numbering"
            )
        output_context_values = contextual_values(output_text)
        if isinstance(classified_occurrences, (list, tuple)):
            replace_occurrences = [
                occurrence
                for occurrence in classified_occurrences
                if occurrence.get("action") == "REPLACE"
            ]
            replace_sources = Counter(
                occurrence["source"] for occurrence in replace_occurrences
            )
            preserved_sources = Counter(
                occurrence["source"]
                for occurrence in classified_occurrences
                if occurrence.get("action") == "PRESERVE"
            )
            output_source_counts = preserved_term_counts(
                output_text, tuple(set(replace_sources) | set(preserved_sources))
            )
            missing_preserved = {
                source: preserved_sources[source] - output_source_counts[source]
                for source in preserved_sources
                if output_source_counts[source] < preserved_sources[source]
            }
            if missing_preserved:
                raise ValueError(
                    f"Rewrite for {item.get('message_id')!r} changed "
                    f"{sum(missing_preserved.values())} LLM-classified contextual "
                    "occurrence(s) marked for preservation"
                )
            retained_replacements = {
                source: output_source_counts[source] - preserved_sources[source]
                for source in replace_sources
                if output_source_counts[source] > preserved_sources[source]
            }
            if retained_replacements:
                raise ValueError(
                    f"Rewrite for {item.get('message_id')!r} retained "
                    f"{sum(retained_replacements.values())} LLM-classified contextual "
                    "occurrence(s) marked for replacement"
                )
            output_context_source_counts = Counter(
                source for _category, source in output_context_values
            )
            preserved_values_seen_by_local_extractor = sum(
                min(count, output_context_source_counts[source])
                for source, count in preserved_sources.items()
            )
            effective_output_context_count = (
                len(output_context_values) - preserved_values_seen_by_local_extractor
            )
            if effective_output_context_count != len(replace_occurrences):
                raise ValueError(
                    f"Rewrite for {item.get('message_id')!r} changed the total number of "
                    "LLM-classified replaceable contextual occurrences: "
                    f"expected={len(replace_occurrences)}, "
                    f"output={effective_output_context_count}"
                )
        else:
            input_context_values = contextual_values(input_text)
            input_category_counts = _context_category_counts(input_context_values)
            output_category_counts = _context_category_counts(output_context_values)
            if output_category_counts != input_category_counts:
                raise ValueError(
                    f"Rewrite for {item.get('message_id')!r} changed the count or type of "
                    "numbers, dates, amounts, versions, or filenames: "
                    f"input_counts={dict(sorted(input_category_counts.items()))}, "
                    f"output_counts={dict(sorted(output_category_counts.items()))}"
                )
            unchanged_context_values = Counter(input_context_values) & Counter(
                output_context_values
            )
            if unchanged_context_values:
                raise ValueError(
                    f"Rewrite for {item.get('message_id')!r} retained an original number, "
                    "date, amount, version, or filename"
                )
        must_replace_terms = expected[key].get(
            "must_replace_terms",
            find_public_service_terms(input_text),
        )
        if not isinstance(must_replace_terms, (list, tuple)):
            raise ValueError(
                f"Rewrite input for {item.get('message_id')!r} has invalid must_replace_terms"
            )
        required_identifiers = protected_literals(input_text, must_replace_terms)
        output_identifiers = protected_literals(output_text)
        if any(
            output_identifiers[literal] != count
            for literal, count in required_identifiers.items()
        ):
            raise ValueError(
                f"Rewrite for {item.get('message_id')!r} changed a protected technical identifier"
            )
        must_preserve_terms = expected[key].get("must_preserve_terms", ())
        if not isinstance(must_preserve_terms, (list, tuple)):
            raise ValueError(f"Rewrite input for {item.get('message_id')!r} has invalid must_preserve_terms")
        if preserved_term_counts(output_text, must_preserve_terms) != preserved_term_counts(
            input_text, must_preserve_terms
        ):
            raise ValueError(
                f"Rewrite for {item.get('message_id')!r} changed a protected tool, feature, or project term"
            )
        retained_public_terms = find_terms_outside_pii(
            output_text,
            (*DEFAULT_PUBLIC_SERVICE_TERMS, *must_replace_terms),
        )
        if retained_public_terms:
            raise ValueError(
                f"Rewrite for {item.get('message_id')!r} retained a public company or service name"
            )
        require_structure_change = expected[key].get("require_structure_change", True)
        if not isinstance(require_structure_change, bool):
            raise ValueError(
                f"Rewrite input for {item.get('message_id')!r} has invalid require_structure_change"
            )
        if require_structure_change and not has_structural_change(input_text, output_text):
            raise ValueError(
                f"Rewrite for {item.get('message_id')!r} did not change sentence structure"
            )
        actual[key] = output_text
    if set(actual) != set(expected):
        missing = set(expected).difference(actual)
        raise ValueError(f"LLM response omitted {len(missing)} message(s)")
    return actual


def rewrite_request_messages(
    batch: Sequence[dict[str, Any]], repair_instruction: str | None = None
) -> list[dict[str, str]]:
    body = {
        "task": "Semantically paraphrase every message while preserving all annotation-relevant facts.",
        "messages": [
            {
                "message_id": message["message_id"],
                "speaker": message.get("speaker"),
                "text": message["text"],
                "protected_literals": sorted(
                    set(PLACEHOLDER_RE.findall(message["text"]))
                    | set(
                        protected_literals(
                            message["text"], message.get("must_replace_terms", ())
                        )
                    )
                ),
                "must_preserve_terms": list(message.get("must_preserve_terms", ())),
                "must_replace_context_values": [
                    {
                        "occurrence_id": occurrence["occurrence_id"],
                        "category": occurrence["category"],
                        "source": occurrence["source"],
                    }
                    for occurrence in message.get("context_occurrences", ())
                    if occurrence.get("action") == "REPLACE"
                ],
                "must_preserve_context_values": [
                    {
                        "occurrence_id": occurrence["occurrence_id"],
                        "category": occurrence["category"],
                        "source": occurrence["source"],
                    }
                    for occurrence in message.get("context_occurrences", ())
                    if occurrence.get("action") == "PRESERVE"
                ],
                "must_replace_terms": list(message.get("must_replace_terms", ())),
                "structural_list_markers_to_preserve": list(
                    structural_list_markers(message["text"])
                ),
                "other_llm_list_indexes_to_preserve": list(
                    occurrence["source"]
                    for occurrence in message.get("context_occurrences", ())
                    if occurrence.get("category") == "LIST_INDEX"
                    and occurrence.get("local_hint") != "LIST_INDEX"
                ),
                "require_structure_change": message.get("require_structure_change", True),
                "required_structure_change": (
                    "Reorder clauses/information-bearing phrases, change grammatical construction/voice, "
                    "or split/combine sentences; synonym replacement in the same order is invalid."
                    if message.get("require_structure_change", True)
                    else "Not required for this short contextual-value-only rewrite."
                ),
            }
            for message in batch
        ],
    }
    if repair_instruction:
        body["validation_repair"] = repair_instruction
    return [
        {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
    ]


async def rewrite_batch(
    api: Stage1ApiClient,
    project_id: str,
    batch_number: int,
    batch: Sequence[dict[str, Any]],
    failed_response_redactor: Callable[[str], str],
    progress_callback: Callable[[dict[str, str]], None] | None = None,
) -> dict[str, str]:
    async def call_one(
        target: str,
        inputs: Sequence[dict[str, Any]],
        repair_instruction: str | None = None,
    ) -> dict[str, str]:
        def validator(payload: dict[str, Any]) -> None:
            validate_rewrite_response(payload, inputs)

        payload = await api.call(
            project_id=project_id,
            run_mode=REWRITE_RUN_MODE,
            target_requirement=target,
            messages=rewrite_request_messages(inputs, repair_instruction),
            validator=validator,
            failed_response_redactor=failed_response_redactor,
        )
        return validate_rewrite_response(payload, inputs)

    target = f"batch_{batch_number:04d}"
    try:
        return await call_one(target, batch)
    except ApiError as exc:
        if "ValueError" not in str(exc):
            raise

    # A single shallow/invalid rewrite should not force every otherwise valid
    # message in the batch through the same retries. Isolate each message and
    # explicitly tell the model how to repair the locally detected violation.
    repaired: dict[str, str] = {}
    for message in batch:
        message_target = f"{target}_message_{id_key(message['message_id'])}"
        if message.get("require_structure_change", True):
            repair_instruction = (
                "The previous batched response failed local validation. For this single message, "
                "make an unmistakable structural rewrite by moving an information-bearing phrase "
                "or clause, changing voice/construction, or splitting/combining sentences. Preserve "
                "all protected values, replace every required contextual value, and do not merely "
                "replace synonyms in the original order. Do not begin with the same first two lexical "
                "tokens as the source. If the source is a yes/no question, recast it as a wh-/choice-first "
                "question or move the final alternative to the front without changing meaning. For a "
                "statement, front a different clause, object, or time phrase, or use a clearly different "
                "voice. Keep every structural_list_markers_to_preserve value and every "
                "other_llm_list_indexes_to_preserve value exact, in the original order, and in its "
                "original structural role."
            )
        else:
            repair_instruction = (
                "The previous response failed contextual de-identification. Preserve the short message's "
                "role while replacing every supplied number, date, amount, version, filename, public "
                "company, and public-service name with an unrelated plausible synthetic alternative. "
                "Keep protected technical identifiers and PII exact for phase 2. Keep every "
                "structural_list_markers_to_preserve value and every "
                "other_llm_list_indexes_to_preserve value exact and in the original order."
            )
        validated_rewrite = await call_one(
            message_target,
            [message],
            repair_instruction,
        )
        repaired.update(validated_rewrite)
        if progress_callback is not None:
            progress_callback(validated_rewrite)
    return repaired


def _used_entities_for_rendered_value(
    source_value: str,
    rendered_value: str,
    entities: Sequence[dict[str, str]],
    *,
    message_id: Any,
    field: str,
) -> list[dict[str, str]]:
    """Resolve only declarations actually used to render the returned field.

    LLMs sometimes emit redundant nested declarations (for example both a full
    product name and one word inside it).  The returned text is authoritative:
    this matcher proves that every changed span is backed by one declaration,
    selects the declaration that produced it, and ignores unused metadata.
    Non-PII edits still cannot pass.
    """

    cache: dict[tuple[int, int], tuple[int, ...] | None] = {}

    def resolve(source_index: int, rendered_index: int) -> tuple[int, ...] | None:
        original_key = (source_index, rendered_index)
        if original_key in cache:
            return cache[original_key]

        while (
            source_index < len(source_value)
            and rendered_index < len(rendered_value)
            and source_value[source_index] == rendered_value[rendered_index]
        ):
            source_index += 1
            rendered_index += 1
        if source_index == len(source_value) and rendered_index == len(rendered_value):
            cache[original_key] = ()
            return ()
        if source_index == len(source_value) or rendered_index == len(rendered_value):
            cache[original_key] = None
            return None

        candidates = [
            (index, entity)
            for index, entity in enumerate(entities)
            if source_value.startswith(entity["source"], source_index)
            and rendered_value.startswith(entity["placeholder"], rendered_index)
        ]
        candidates.sort(key=lambda item: len(item[1]["source"]), reverse=True)
        for index, entity in candidates:
            tail = resolve(
                source_index + len(entity["source"]),
                rendered_index + len(entity["placeholder"]),
            )
            if tail is not None:
                result = (index, *tail)
                cache[original_key] = result
                return result
        cache[original_key] = None
        return None

    used_indices = resolve(0, 0)
    if used_indices is None:
        raise ValueError(
            f"PII phase changed non-PII content for message_id {message_id!r}, field={field}"
        )
    used: list[dict[str, str]] = []
    seen: set[int] = set()
    for index in used_indices:
        if index not in seen:
            used.append(entities[index])
            seen.add(index)
    return used


def pii_request_messages(
    batch: Sequence[dict[str, Any]],
    state: LlmPiiReplacementState,
    repair_instruction: str | None = None,
) -> list[dict[str, str]]:
    body: dict[str, Any] = {
        "task": "Identify and replace PII in every phase-1 message.",
        "known_replacements": state.relevant_known_replacements(batch),
        "reserved_placeholders": state.reserved_placeholders(),
        "next_indices": state.next_indices(),
        "messages": [
            {
                "message_id": message["message_id"],
                "speaker": message.get("speaker"),
                "text": message["text"],
                "sender_id": (
                    None if message.get("sender_id") is None else str(message.get("sender_id"))
                ),
                "must_preserve_terms": list(message.get("must_preserve_terms", ())),
            }
            for message in batch
        ],
    }
    if repair_instruction:
        body["validation_repair"] = repair_instruction
    return [
        {"role": "system", "content": PII_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
    ]


def validate_pii_response(
    payload: dict[str, Any],
    inputs: Sequence[dict[str, Any]],
    state: LlmPiiReplacementState,
    local_auditor: DeterministicPiiCleaner,
) -> PiiBatchResult:
    """Validate LLM PII decisions without locally creating the final text."""

    cleaned_messages = payload.get("cleaned_messages")
    if not isinstance(cleaned_messages, list):
        raise ValueError("LLM PII response must contain a cleaned_messages list")
    expected = {id_key(message["message_id"]): message for message in inputs}
    if len(cleaned_messages) != len(inputs):
        raise ValueError("LLM PII response returned the wrong message count")

    next_indices = state.next_indices()
    pending_by_entity: dict[tuple[str, str], str] = {}
    pending_by_placeholder: dict[str, tuple[str, str]] = {}
    texts: dict[str, str] = {}
    sender_ids: dict[str, str | None] = {}
    committed_entities: list[tuple[str, str, str]] = []

    for expected_input, item in zip(inputs, cleaned_messages):
        if not isinstance(item, dict) or set(item) != {
            "message_id",
            "text",
            "sender_id",
            "entities",
        }:
            raise ValueError(
                "Each cleaned_messages item must contain exactly message_id, text, "
                "sender_id, and entities"
            )
        key = id_key(item.get("message_id"))
        expected_key = id_key(expected_input["message_id"])
        if key != expected_key or key not in expected or key in texts:
            raise ValueError("LLM PII response changed, reordered, or duplicated a message_id")
        if not isinstance(item.get("text"), str):
            raise ValueError(f"PII-cleaned text must be a string for message_id {item.get('message_id')!r}")
        raw_entities = item.get("entities")
        if not isinstance(raw_entities, list):
            raise ValueError(f"PII entities must be a list for message_id {item.get('message_id')!r}")

        normalized_entities: list[dict[str, str]] = []
        seen_message_entities: set[tuple[str, str]] = set()
        source_text = str(expected_input["text"])
        raw_sender = (
            None
            if expected_input.get("sender_id") is None
            else str(expected_input.get("sender_id"))
        )

        for entity in raw_entities:
            if not isinstance(entity, dict) or set(entity) != {
                "field",
                "source",
                "category",
                "placeholder",
            }:
                raise ValueError("Each PII entity must contain exactly field, source, category, placeholder")
            field = entity.get("field")
            source = entity.get("source")
            category = entity.get("category")
            placeholder = entity.get("placeholder")
            if field not in {"text", "sender_id"}:
                raise ValueError("PII entity field must be text or sender_id")
            if category not in PII_CATEGORIES:
                raise ValueError("PII entity category is invalid")
            if not isinstance(source, str) or not source or source != source.strip():
                raise ValueError("PII entity source must be a non-empty exact substring without edge whitespace")
            if not isinstance(placeholder, str):
                raise ValueError("PII entity placeholder must be a string")
            placeholder_match = FULL_PLACEHOLDER_RE.fullmatch(placeholder)
            if placeholder_match is None or placeholder_match.group("category") != category:
                raise ValueError("PII placeholder category does not match the declared category")
            if PLACEHOLDER_RE.fullmatch(source):
                raise ValueError("An existing placeholder cannot be declared as new PII")
            if field == "sender_id" and category != "SENDER_ID":
                raise ValueError("sender_id may only use the SENDER_ID category")
            if field == "text" and category == "SENDER_ID":
                raise ValueError("SENDER_ID entities must belong to the sender_id field")

            field_value = source_text if field == "text" else raw_sender
            if field_value is None or source not in field_value:
                raise ValueError(
                    f"PII entity source is absent for message_id {item.get('message_id')!r}, "
                    f"field={field}"
                )
            entity_identity = (field, source)
            if entity_identity in seen_message_entities:
                raise ValueError("Duplicate PII entity declaration in one message")
            seen_message_entities.add(entity_identity)
            normalized_entities.append(
                {
                    "field": field,
                    "source": source,
                    "category": category,
                    "placeholder": placeholder,
                }
            )

        text_entities = [entity for entity in normalized_entities if entity["field"] == "text"]
        sender_entities = [
            entity for entity in normalized_entities if entity["field"] == "sender_id"
        ]
        used_text_entities = _used_entities_for_rendered_value(
            source_text,
            item["text"],
            text_entities,
            message_id=item.get("message_id"),
            field="text",
        )
        must_preserve_terms = expected_input.get("must_preserve_terms", ())
        if preserved_term_counts(item["text"], must_preserve_terms) != preserved_term_counts(
            source_text, must_preserve_terms
        ):
            raise ValueError(
                f"PII phase redacted a protected requirement term for message_id "
                f"{item.get('message_id')!r}"
            )

        if raw_sender is None or raw_sender == "":
            if item["sender_id"] != raw_sender or sender_entities:
                raise ValueError("Null or empty sender_id must remain unchanged and have no sender entity")
            expected_sender: str | None = raw_sender
            used_sender_entities: list[dict[str, str]] = []
        else:
            used_sender_entities = [
                entity
                for entity in sender_entities
                if entity["source"] == raw_sender
                and entity["placeholder"] == item["sender_id"]
            ]
            if len(used_sender_entities) != 1:
                raise ValueError(
                    f"Non-null sender_id requires one exact SENDER_ID replacement for message_id "
                    f"{item.get('message_id')!r}"
                )
            sender_entity = used_sender_entities[0]
            expected_sender = sender_entity["placeholder"]

        # Only declarations that can reproduce the returned final fields are
        # allowed to affect placeholder allocation and cross-batch state. An
        # LLM may redundantly list a nested substring, but unused metadata is
        # harmless and is deliberately ignored. Every actual character change
        # has already been proven to be a declared source -> placeholder edit.
        for entity in (*used_text_entities, *used_sender_entities):
            category = entity["category"]
            source = entity["source"]
            placeholder = entity["placeholder"]
            entity_key = state.entity_key(category, source)
            known_placeholder = state.placeholder_for(category, source)
            pending_placeholder = pending_by_entity.get(entity_key)
            required_placeholder = known_placeholder or pending_placeholder
            if required_placeholder is not None:
                if placeholder != required_placeholder:
                    raise ValueError("A known PII value was assigned an inconsistent placeholder")
            else:
                expected_placeholder = f"[{category}_{next_indices[category]:03d}]"
                if placeholder != expected_placeholder:
                    raise ValueError(
                        f"New {category} placeholder is not the next available category index"
                    )
                owner = state.owner_for(placeholder) or pending_by_placeholder.get(placeholder)
                if owner not in (None, entity_key):
                    raise ValueError("A PII placeholder was reused for a different value")
                pending_by_entity[entity_key] = placeholder
                pending_by_placeholder[placeholder] = entity_key
                next_indices[category] += 1
            committed_entities.append((category, source, placeholder))

        local_auditor.assert_no_known_pii(
            item["text"], source_text=source_text, message_id=item.get("message_id")
        )
        if raw_sender is not None and expected_sender is not None:
            local_auditor.assert_no_known_pii(
                expected_sender,
                source_text=raw_sender,
                message_id=item.get("message_id"),
            )
        texts[key] = item["text"]
        sender_ids[key] = expected_sender

    if set(texts) != set(expected):
        raise ValueError("LLM PII response omitted one or more messages")
    return PiiBatchResult(texts, sender_ids, tuple(committed_entities))


async def redact_pii_batch(
    api: Stage1ApiClient,
    project_id: str,
    batch_number: int,
    batch: Sequence[dict[str, Any]],
    state: LlmPiiReplacementState,
    local_auditor: DeterministicPiiCleaner,
) -> PiiBatchResult:
    """Ask the LLM to redact one batch, falling back to single messages."""

    async def call_one(
        target: str,
        inputs: Sequence[dict[str, Any]],
        repair_instruction: str | None = None,
    ) -> PiiBatchResult:
        def validator(payload: dict[str, Any]) -> None:
            validate_pii_response(payload, inputs, state, local_auditor)

        payload = await api.call(
            project_id=project_id,
            run_mode=PII_RUN_MODE,
            target_requirement=target,
            messages=pii_request_messages(inputs, state, repair_instruction),
            validator=validator,
            failed_response_redactor=lambda _raw: "[REDACTED: raw phase-two response omitted]",
        )
        validated = validate_pii_response(payload, inputs, state, local_auditor)
        return PiiBatchResult(
            validated.texts,
            validated.sender_ids,
            validated.entities,
            (payload,),
        )

    target = f"batch_{batch_number:04d}"
    try:
        result = await call_one(target, batch)
    except ApiError as exc:
        if len(batch) <= 1 or "ValueError" not in str(exc):
            raise
    else:
        state.commit(result.entities)
        return result

    combined_texts: dict[str, str] = {}
    combined_sender_ids: dict[str, str | None] = {}
    combined_entities: list[tuple[str, str, str]] = []
    combined_payloads: list[dict[str, Any]] = []
    for message in batch:
        result = await call_one(
            f"{target}_message_{id_key(message['message_id'])}",
            [message],
            (
                "The previous batched PII response failed strict validation. Reinspect this one "
                "message, replace every actual PII value and every non-empty full sender_id, preserve every "
                "other character exactly, use known mappings and the next available indices, and "
                "ensure entities are exact, maximal, non-overlapping source substrings. If a real "
                "public company or public service survived phase 1, use ORGANIZATION or SERVICE; "
                "PROJECT_NAME is only for a private alias specific to this user's project. Do not "
                "redact neutral synthetic provider labels, protocols, libraries, tools, or "
                "must_preserve_terms. Do not declare both a complete entity and a nested substring "
                "of it."
            ),
        )
        state.commit(result.entities)
        combined_texts.update(result.texts)
        combined_sender_ids.update(result.sender_ids)
        combined_entities.extend(result.entities)
        combined_payloads.extend(result.payloads)
    return PiiBatchResult(
        combined_texts,
        combined_sender_ids,
        tuple(combined_entities),
        tuple(combined_payloads),
    )


def source_signature(value: Any) -> str:
    return sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def run_signature(source_sha256: str, project_id: str, config: CleanConfig) -> dict[str, Any]:
    signature = {
        "cleaning_version": CLEANING_VERSION,
        "source_sha256": source_sha256,
        "model": config.model,
        "reasoning_effort": config.reasoning_effort,
        "short_message_max_words": config.short_message_max_words,
        "max_batch_messages": config.max_batch_messages,
        "max_batch_chars": config.max_batch_chars,
        "extra_names_sha256": sha256_text(
            "\n".join(sorted(name.strip().casefold() for name in config.extra_names if name.strip()))
        ),
        "extra_project_terms_sha256": sha256_text(
            "\n".join(
                sorted(term.strip().casefold() for term in config.extra_project_terms if term.strip())
            )
        ),
        "preserve_terms_sha256": sha256_text(
            "\n".join(sorted(term.strip().casefold() for term in config.preserve_terms if term.strip()))
        ),
        "context_classify_prompt_sha256": sha256_text(
            CONTEXT_CLASSIFY_SYSTEM_PROMPT
        ),
        "rewrite_prompt_sha256": sha256_text(REWRITE_SYSTEM_PROMPT),
        "pii_prompt_sha256": sha256_text(PII_SYSTEM_PROMPT),
        "pii_engine": "three_stage_llm_with_local_validation",
    }
    project_manual_rewrites = [
        rewrite for rewrite in config.manual_rewrites if rewrite.project_id == project_id
    ]
    if project_manual_rewrites:
        signature["manual_rewrites_sha256"] = sha256_text(
            json.dumps(
                [
                    {
                        "project_id": rewrite.project_id,
                        "message_id": rewrite.message_id,
                        "source_sha256": rewrite.source_sha256,
                        "text": rewrite.text,
                    }
                    for rewrite in project_manual_rewrites
                ],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return signature


def _checkpoint_payload(body: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(body)
    payload["content_sha256"] = source_signature(body)
    return payload


def _read_matching_checkpoint(
    path: Path,
    *,
    phase: str,
    signature: dict[str, Any],
    dependency_sha256: str | None = None,
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = read_json(path)
    if not isinstance(payload, dict):
        return None
    content_sha256 = payload.get("content_sha256")
    body = {key: value for key, value in payload.items() if key != "content_sha256"}
    if not isinstance(content_sha256, str) or content_sha256 != source_signature(body):
        return None
    stored_signature = body.get("signature")
    signature_matches = stored_signature == signature
    if (
        not signature_matches
        and phase == "rewrite"
        and isinstance(stored_signature, dict)
        and stored_signature.get("cleaning_version")
        in REWRITE_CHECKPOINT_COMPATIBLE_VERSIONS
        and signature.get("cleaning_version") == CLEANING_VERSION
    ):
        compatible_ignored_keys = {
            "cleaning_version",
            "context_classify_prompt_sha256",
            "rewrite_prompt_sha256",
            "pii_engine",
        }
        stored_without_version = {
            key: value
            for key, value in stored_signature.items()
            if key not in compatible_ignored_keys
        }
        current_without_version = {
            key: value
            for key, value in signature.items()
            if key not in compatible_ignored_keys
        }
        signature_matches = stored_without_version == current_without_version
    if (
        body.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
        or body.get("phase") != phase
        or not signature_matches
    ):
        return None
    if dependency_sha256 is not None and body.get("dependency_sha256") != dependency_sha256:
        return None
    return body


def save_context_classification_checkpoint(
    path: Path,
    signature: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    classified_by_key: dict[str, tuple[dict[str, str], ...]],
) -> None:
    entries = []
    for message in candidates:
        key = id_key(message["message_id"])
        if key not in classified_by_key:
            continue
        entries.append(
            {
                "message_id": message["message_id"],
                "occurrences": [
                    {
                        "occurrence_id": occurrence["occurrence_id"],
                        "category": occurrence["category"],
                    }
                    for occurrence in classified_by_key[key]
                ],
            }
        )
    write_json(
        path,
        _checkpoint_payload(
            {
                "schema_version": CHECKPOINT_SCHEMA_VERSION,
                "phase": "context_classification",
                "signature": signature,
                "classified_messages": entries,
            }
        ),
    )


def restore_context_classification_checkpoint(
    path: Path,
    signature: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> dict[str, tuple[dict[str, str], ...]]:
    try:
        body = _read_matching_checkpoint(
            path,
            phase="context_classification",
            signature=signature,
        )
        if body is None:
            return {}
        payload = {"classified_messages": body.get("classified_messages")}
        saved_ids = {
            id_key(item.get("message_id"))
            for item in payload["classified_messages"]
            if isinstance(item, dict)
        } if isinstance(payload["classified_messages"], list) else set()
        selected_candidates = [
            message
            for message in candidates
            if id_key(message["message_id"]) in saved_ids
        ]
        if not selected_candidates and candidates:
            return {}
        return validate_context_classification_response(payload, selected_candidates)
    except (OSError, ValueError, PiiCleanError):
        print(
            f"[{path.parent.name}] ignored invalid context-classification checkpoint",
            file=sys.stderr,
            flush=True,
        )
        return {}


def save_phase_one_checkpoint(
    path: Path,
    signature: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    rewritten_by_key: dict[str, str],
) -> None:
    entries = [
        {
            "message_id": message["message_id"],
            "text": rewritten_by_key[id_key(message["message_id"])],
        }
        for message in candidates
        if (
            id_key(message["message_id"]) in rewritten_by_key
            and rewritten_by_key[id_key(message["message_id"])] != message["text"]
        )
    ]
    write_json(
        path,
        _checkpoint_payload(
            {
                "schema_version": CHECKPOINT_SCHEMA_VERSION,
                "phase": "rewrite",
                "signature": signature,
                "completed_rewrites": entries,
            }
        ),
    )


def restore_phase_one_checkpoint(
    path: Path,
    signature: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> dict[str, str]:
    try:
        body = _read_matching_checkpoint(
            path, phase="rewrite", signature=signature
        )
        if body is None:
            return {}
        entries = body.get("completed_rewrites")
        if not isinstance(entries, list):
            return {}
        candidates_by_key = {
            id_key(message["message_id"]): message for message in candidates
        }
        restored: dict[str, str] = {}
        skipped_entries = 0
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"message_id", "text"}:
                skipped_entries += 1
                continue
            key = id_key(entry.get("message_id"))
            candidate = candidates_by_key.get(key)
            if candidate is None or key in restored:
                skipped_entries += 1
                continue
            try:
                restored.update(
                    validate_rewrite_response(
                        {"rewrites": [entry]},
                        [candidate],
                    )
                )
            except (ValueError, PiiCleanError):
                skipped_entries += 1
        if skipped_entries:
            print(
                f"[{path.parent.name}] skipped {skipped_entries} invalid phase-1 "
                "checkpoint rewrite(s); they will be regenerated",
                file=sys.stderr,
                flush=True,
            )
        return restored
    except (OSError, ValueError, PiiCleanError):
        print(
            f"[{path.parent.name}] ignored invalid phase-one checkpoint",
            file=sys.stderr,
            flush=True,
        )
        return {}


def save_phase_two_checkpoint(
    path: Path,
    signature: dict[str, Any],
    dependency_sha256: str,
    completed_batches: Sequence[dict[str, Any]],
) -> None:
    write_json(
        path,
        _checkpoint_payload(
            {
                "schema_version": CHECKPOINT_SCHEMA_VERSION,
                "phase": "pii",
                "signature": signature,
                "dependency_sha256": dependency_sha256,
                "completed_batches": list(completed_batches),
            }
        ),
    )


def restore_phase_two_checkpoint(
    path: Path,
    signature: dict[str, Any],
    dependency_sha256: str,
    batches: Sequence[Sequence[dict[str, Any]]],
    local_auditor: DeterministicPiiCleaner,
) -> tuple[
    LlmPiiReplacementState,
    dict[str, str],
    dict[str, str | None],
    list[dict[str, Any]],
]:
    fresh = (LlmPiiReplacementState(), {}, {}, [])
    try:
        body = _read_matching_checkpoint(
            path,
            phase="pii",
            signature=signature,
            dependency_sha256=dependency_sha256,
        )
        if body is None:
            return fresh
        records = body.get("completed_batches")
        if not isinstance(records, list) or len(records) > len(batches):
            return fresh

        state = LlmPiiReplacementState()
        texts: dict[str, str] = {}
        sender_ids: dict[str, str | None] = {}
        restored_records: list[dict[str, Any]] = []
        for expected_number, record in enumerate(records, start=1):
            if not isinstance(record, dict) or set(record) != {
                "batch_number",
                "payloads",
            }:
                raise ValueError("invalid phase-two checkpoint batch")
            if record.get("batch_number") != expected_number:
                raise ValueError("non-contiguous phase-two checkpoint batches")
            payloads = record.get("payloads")
            if not isinstance(payloads, list) or not payloads:
                raise ValueError("phase-two checkpoint batch has no payloads")

            expected_batch = list(batches[expected_number - 1])
            inputs_by_key = {
                id_key(message["message_id"]): message for message in expected_batch
            }
            covered: set[str] = set()
            for payload in payloads:
                if not isinstance(payload, dict):
                    raise ValueError("invalid phase-two checkpoint payload")
                cleaned_messages = payload.get("cleaned_messages")
                if not isinstance(cleaned_messages, list) or not cleaned_messages:
                    raise ValueError("phase-two checkpoint payload has no messages")
                payload_keys = [
                    id_key(item.get("message_id"))
                    for item in cleaned_messages
                    if isinstance(item, dict)
                ]
                if len(payload_keys) != len(cleaned_messages):
                    raise ValueError("invalid phase-two checkpoint message")
                if any(key not in inputs_by_key or key in covered for key in payload_keys):
                    raise ValueError("phase-two checkpoint message mismatch")
                payload_inputs = [inputs_by_key[key] for key in payload_keys]
                result = validate_pii_response(
                    payload, payload_inputs, state, local_auditor
                )
                state.commit(result.entities)
                texts.update(result.texts)
                sender_ids.update(result.sender_ids)
                covered.update(payload_keys)
            if covered != set(inputs_by_key):
                raise ValueError("incomplete phase-two checkpoint batch")
            restored_records.append(record)
        return state, texts, sender_ids, restored_records
    except (OSError, ValueError, PiiCleanError):
        print(
            f"[{path.parent.name}] ignored invalid phase-two checkpoint",
            file=sys.stderr,
            flush=True,
        )
        return fresh


def remove_completed_checkpoints(paths: Sequence[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    if paths:
        try:
            paths[0].parent.rmdir()
        except OSError:
            pass


def apply_message_texts(
    normalized: dict[str, Any],
    texts: dict[str, str],
    pii_cleaner: DeterministicPiiCleaner | None = None,
) -> dict[str, Any]:
    cleaned = copy.deepcopy(normalized)
    for message in cleaned["messages"]:
        key = id_key(message["message_id"])
        if key not in texts:
            raise PiiCleanError(f"No cleaned text for message_id {message['message_id']!r}")
        message["text"] = texts[key]
        if pii_cleaner is not None and message.get("sender_id") is not None:
            message["sender_id"] = pii_cleaner.registry.token("SENDER_ID", str(message["sender_id"]))
    return cleaned


def sync_annotation_texts(
    annotation: dict[str, Any], cleaned_normalized: dict[str, Any]
) -> tuple[dict[str, Any], int]:
    cleaned = copy.deepcopy(annotation)
    message_by_key = {id_key(message["message_id"]): message for message in cleaned_normalized["messages"]}
    updated = 0
    for requirement in cleaned.get("requirements", []):
        for event in requirement.get("events", []):
            source = event.get("source_message")
            if not isinstance(source, dict):
                raise PiiCleanError("Annotation Event has no source_message object")
            key = id_key(source.get("message_id"))
            message = message_by_key.get(key)
            if message is None:
                raise PiiCleanError(f"Annotation references unknown message_id {source.get('message_id')!r}")
            if source.get("speaker") != message.get("speaker"):
                raise PiiCleanError(f"Speaker mismatch for message_id {source.get('message_id')!r}")
            source["text"] = message["text"]
            updated += 1
    return cleaned, updated


def align_whitespace_only_annotation_texts(
    annotation: dict[str, Any], normalized: dict[str, Any]
) -> tuple[dict[str, Any], int]:
    """Repair source text only when it differs from the raw message by whitespace.

    Stage 1 validation is intentionally strict.  PII cleaning can safely accept
    whitespace-only drift because the annotation is synchronized from the
    canonical message text later in this pipeline.  Any substantive mismatch is
    left untouched so the normal Stage 1 validator still rejects it.
    """
    aligned = copy.deepcopy(annotation)
    message_by_key = {
        id_key(message["message_id"]): message for message in normalized.get("messages", [])
    }
    repaired = 0
    for requirement in aligned.get("requirements", []):
        for event in requirement.get("events", []):
            source = event.get("source_message")
            if not isinstance(source, dict):
                continue
            message = message_by_key.get(id_key(source.get("message_id")))
            if message is None:
                continue
            source_text = source.get("text")
            raw_text = message.get("text")
            if not isinstance(source_text, str) or not isinstance(raw_text, str) or source_text == raw_text:
                continue
            source_normalized = " ".join(source_text.split())
            raw_normalized = " ".join(raw_text.split())
            if source_normalized == raw_normalized:
                source["text"] = raw_text
                repaired += 1
    return aligned, repaired


def _normalized_without_text(normalized: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(normalized)
    for message in value.get("messages", []):
        message["text"] = "<MESSAGE_TEXT>"
        if "sender_id" in message:
            message["sender_id"] = "<SENDER_ID>"
    return value


def _annotation_without_source_text(annotation: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(annotation)
    for requirement in value.get("requirements", []):
        for event in requirement.get("events", []):
            source = event.get("source_message")
            if isinstance(source, dict):
                source["text"] = "<SOURCE_TEXT>"
    return value


def assert_only_allowed_fields_changed(
    original_normalized: dict[str, Any],
    cleaned_normalized: dict[str, Any],
    original_annotation: dict[str, Any],
    cleaned_annotation: dict[str, Any],
) -> None:
    if _normalized_without_text(original_normalized) != _normalized_without_text(cleaned_normalized):
        raise PiiCleanError("normalized_project changed outside messages[].text or messages[].sender_id")
    if _annotation_without_source_text(original_annotation) != _annotation_without_source_text(cleaned_annotation):
        raise PiiCleanError("Stage 1 annotation changed outside source_message.text")


def output_is_current(
    manifest_path: Path,
    chat_output: Path,
    signature: dict[str, Any],
) -> bool:
    if not (manifest_path.is_file() and chat_output.is_file()):
        return False
    manifest = read_json(manifest_path)
    return isinstance(manifest, dict) and manifest.get("status") == "DONE" and manifest.get("signature") == signature


def build_cleaned_chat(
    original_chat: list[dict[str, Any]],
    final_texts: dict[str, str],
    final_sender_ids: dict[str, str | None],
) -> list[dict[str, Any]]:
    """Apply cleaned text, then remove sender_id and created_ts from output."""
    cleaned = copy.deepcopy(original_chat)
    for index, row in enumerate(cleaned, start=1):
        key = id_key(index)
        if key not in final_texts:
            raise PiiCleanError(f"No cleaned text for chat row {index}")
        row["message"] = final_texts[key]
        if row.get("sender_id") is not None:
            if key not in final_sender_ids or final_sender_ids[key] is None:
                raise PiiCleanError(f"No cleaned sender_id for chat row {index}")
        row.pop("sender_id", None)
        row.pop("created_ts", None)
    return cleaned


def _chat_without_cleaned_fields(chat: list[dict[str, Any]]) -> list[dict[str, Any]]:
    value = copy.deepcopy(chat)
    for row in value:
        row.pop("message", None)
        row.pop("sender_id", None)
        row.pop("created_ts", None)
    return value


def assert_only_chat_fields_changed(
    original_chat: list[dict[str, Any]], cleaned_chat: list[dict[str, Any]]
) -> None:
    if len(original_chat) != len(cleaned_chat):
        raise PiiCleanError("chat_messages.json changed the number of rows")
    for index, row in enumerate(cleaned_chat, start=1):
        if not isinstance(row.get("message"), str):
            raise PiiCleanError(f"Cleaned chat row {index} has no string message")
        if "sender_id" in row or "created_ts" in row:
            raise PiiCleanError(
                f"Cleaned chat row {index} retained sender_id or created_ts"
            )
    if _chat_without_cleaned_fields(original_chat) != _chat_without_cleaned_fields(cleaned_chat):
        raise PiiCleanError(
            "chat_messages.json changed outside message removal/cleaning fields"
        )


def copy_project_except_chat(project: ProjectFiles, project_output: Path) -> None:
    """Copy all project content except the raw chat file itself."""
    project_output.mkdir(parents=True, exist_ok=True)
    for source in project.project_dir.iterdir():
        if source.name == "chat_messages.json":
            continue
        destination = project_output / source.name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True, copy_function=shutil.copy2)
        else:
            shutil.copy2(source, destination)


async def clean_project(
    project: ProjectFiles,
    api: Stage1ApiClient,
    config: CleanConfig,
) -> dict[str, Any]:
    original_chat = read_json(project.chat_path)
    messages = validate_and_adapt_chat_messages(original_chat, project.project_id)
    source_sha256 = source_signature(original_chat)
    signature = run_signature(source_sha256, project.project_id, config)

    project_output = config.output_root / project.project_id
    chat_output = project_output / "chat_messages.json"
    manifest_path = config.output_root / "_manifests" / f"{project.project_id}.json"
    checkpoint_dir = config.output_root / "_checkpoints" / project.project_id
    phase_zero_checkpoint = checkpoint_dir / "phase0_context.json"
    phase_one_checkpoint = checkpoint_dir / "phase1_rewrite.json"
    phase_two_checkpoint = checkpoint_dir / "phase2_pii.json"

    if not config.partial_resume:
        remove_completed_checkpoints(
            (phase_zero_checkpoint, phase_one_checkpoint, phase_two_checkpoint)
        )

    if config.resume and not config.overwrite and output_is_current(
        manifest_path, chat_output, signature
    ):
        print(f"[{project.project_id}] already clean; skipped", flush=True)
        return {"project_id": project.project_id, "status": "SKIPPED"}

    # Phase 1 works from the original message text. Only validated outputs are
    # checkpointed; failed/raw model responses remain redacted in diagnostics.
    project_terms = discover_project_terms(messages, config.extra_project_terms)
    protected_semantic_terms = (
        *DEFAULT_PRESERVED_TERMS,
        *config.preserve_terms,
        *project_terms,
    )
    rewritten_by_key: dict[str, str] = {}
    rewrite_candidates: list[dict[str, Any]] = []
    project_manual_rewrites = {
        id_key(rewrite.message_id): rewrite
        for rewrite in config.manual_rewrites
        if rewrite.project_id == project.project_id
    }
    source_message_keys = {id_key(message["message_id"]) for message in messages}
    unknown_manual_keys = set(project_manual_rewrites).difference(source_message_keys)
    if unknown_manual_keys:
        raise PiiCleanError(
            f"{project.project_id}: manual rewrite references unknown message_id(s): "
            f"{', '.join(sorted(unknown_manual_keys))}"
        )
    manual_rewrite_count = 0
    short_preserved = 0
    contextual_value_count = sum(
        len(contextual_values(message["text"])) for message in messages
    )
    public_service_term_count = sum(
        len(find_public_service_terms(message["text"]))
        for message in messages
    )
    context_synthesis_message_count = sum(
        bool(contextual_values(message["text"]))
        or bool(find_public_service_terms(message["text"]))
        for message in messages
    )
    for message in messages:
        key = id_key(message["message_id"])
        rewritten_by_key[key] = message["text"]
        rewrite_input = {
            "message_id": message["message_id"],
            "speaker": message.get("speaker"),
            "text": message["text"],
            "must_preserve_terms": find_present_terms(
                message["text"], protected_semantic_terms
            ),
            "must_replace_terms": find_public_service_terms(message["text"]),
            "require_structure_change": (
                requires_structural_rewrite(
                    message["text"], config.short_message_max_words
                )
            ),
            "context_candidates": context_occurrence_candidates(message["text"]),
        }
        manual_rewrite = project_manual_rewrites.get(key)
        if manual_rewrite is not None:
            if not should_rewrite(message["text"], config.short_message_max_words):
                raise PiiCleanError(
                    f"{project.project_id}: manual rewrite targets non-rewrite message_id "
                    f"{message['message_id']!r}"
                )
            actual_source_hash = sha256_text(message["text"])
            if actual_source_hash != manual_rewrite.source_sha256:
                raise PiiCleanError(
                    f"{project.project_id}: stale manual rewrite source hash for message_id "
                    f"{message['message_id']!r}"
                )
            rewritten_by_key.update(
                validate_rewrite_response(
                    {
                        "rewrites": [
                            {
                                "message_id": message["message_id"],
                                "text": manual_rewrite.text,
                            }
                        ]
                    },
                    [rewrite_input],
                )
            )
            manual_rewrite_count += 1
            continue
        if should_rewrite(message["text"], config.short_message_max_words):
            rewrite_candidates.append(rewrite_input)
        else:
            short_preserved += 1

    context_candidates = [
        message for message in rewrite_candidates if message["context_candidates"]
    ]
    classified_by_key = (
        restore_context_classification_checkpoint(
            phase_zero_checkpoint,
            signature,
            context_candidates,
        )
        if config.partial_resume
        else {}
    )
    if classified_by_key:
        print(
            f"[{project.project_id}] resumed {len(classified_by_key)}/"
            f"{len(context_candidates)} validated context classifications",
            flush=True,
        )
    context_batches = build_batches(
        context_candidates,
        config.max_batch_messages,
        config.max_batch_chars,
    )
    for batch_number, batch in enumerate(context_batches, start=1):
        pending_batch = [
            message
            for message in batch
            if id_key(message["message_id"]) not in classified_by_key
        ]
        if not pending_batch:
            print(
                f"[{project.project_id}] context batch {batch_number}/"
                f"{len(context_batches)} restored from checkpoint",
                flush=True,
            )
            continue
        print(
            f"[{project.project_id}] context batch {batch_number}/{len(context_batches)} "
            f"({len(pending_batch)} messages)",
            flush=True,
        )

        def checkpoint_context_progress(
            progress: dict[str, tuple[dict[str, str], ...]],
        ) -> None:
            classified_by_key.update(progress)
            save_context_classification_checkpoint(
                phase_zero_checkpoint,
                signature,
                context_candidates,
                classified_by_key,
            )

        classified_by_key.update(
            await classify_context_batch(
                api,
                project.project_id,
                batch_number,
                pending_batch,
                checkpoint_context_progress,
            )
        )
        save_context_classification_checkpoint(
            phase_zero_checkpoint,
            signature,
            context_candidates,
            classified_by_key,
        )

    for message in rewrite_candidates:
        key = id_key(message["message_id"])
        if message["context_candidates"]:
            if key not in classified_by_key:
                raise PiiCleanError(
                    f"Missing context classification for message_id {message['message_id']!r}"
                )
            message["context_occurrences"] = classified_by_key[key]
        else:
            message["context_occurrences"] = ()

    contextual_value_count = sum(
        occurrence["action"] == "REPLACE"
        for message in rewrite_candidates
        for occurrence in message["context_occurrences"]
    )
    context_synthesis_message_count = sum(
        any(
            occurrence["action"] == "REPLACE"
            for occurrence in message["context_occurrences"]
        )
        or bool(message["must_replace_terms"])
        for message in rewrite_candidates
    )

    batches = build_batches(rewrite_candidates, config.max_batch_messages, config.max_batch_chars)
    restored_rewrites = (
        restore_phase_one_checkpoint(
            phase_one_checkpoint, signature, rewrite_candidates
        )
        if config.partial_resume
        else {}
    )
    rewritten_by_key.update(restored_rewrites)
    if restored_rewrites:
        print(
            f"[{project.project_id}] resumed {len(restored_rewrites)}/"
            f"{len(rewrite_candidates)} validated phase-1 rewrites",
            flush=True,
        )
    for batch_number, batch in enumerate(batches, start=1):
        pending_batch = [
            message
            for message in batch
            if id_key(message["message_id"]) not in restored_rewrites
        ]
        if not pending_batch:
            print(
                f"[{project.project_id}] rewrite batch {batch_number}/{len(batches)} "
                f"restored from checkpoint",
                flush=True,
            )
            continue
        print(
            f"[{project.project_id}] rewrite batch {batch_number}/{len(batches)} "
            f"({len(pending_batch)} messages)",
            flush=True,
        )

        def checkpoint_rewrite_progress(progress: dict[str, str]) -> None:
            rewritten_by_key.update(progress)
            save_phase_one_checkpoint(
                phase_one_checkpoint,
                signature,
                rewrite_candidates,
                rewritten_by_key,
            )

        rewritten_by_key.update(
            await rewrite_batch(
                api,
                project.project_id,
                batch_number,
                pending_batch,
                lambda _raw: "[REDACTED: raw phase-one response omitted]",
                checkpoint_rewrite_progress,
            )
        )
        save_phase_one_checkpoint(
            phase_one_checkpoint,
            signature,
            rewrite_candidates,
            rewritten_by_key,
        )

    # Phase 2 sends every rewritten (or deliberately preserved short) message
    # to the LLM. Local detection is used only as an independent rejection
    # guard; it never creates the final text or sender placeholders.
    rewritten_messages = copy.deepcopy(messages)
    phase_two_preserved_terms = (*DEFAULT_PRESERVED_TERMS, *config.preserve_terms)
    for message in rewritten_messages:
        message["text"] = rewritten_by_key[id_key(message["message_id"])]
        message["must_preserve_terms"] = find_present_terms(
            message["text"], phase_two_preserved_terms
        )
    local_auditor = DeterministicPiiCleaner(
        rewritten_messages,
        config.extra_names,
        project_terms,
    )
    # Prime regex/context candidates for later leak assertions. The returned
    # locally sanitized strings are deliberately discarded.
    for message in rewritten_messages:
        local_auditor.sanitize_message(message)

    pii_batches = build_batches(
        rewritten_messages, config.max_batch_messages, config.max_batch_chars
    )
    phase_one_output_sha256 = source_signature(
        [
            {
                "message_id": message["message_id"],
                "text": message["text"],
            }
            for message in rewritten_messages
        ]
    )
    if config.partial_resume:
        (
            pii_state,
            final_texts,
            final_sender_ids,
            completed_pii_batches,
        ) = restore_phase_two_checkpoint(
            phase_two_checkpoint,
            signature,
            phase_one_output_sha256,
            pii_batches,
            local_auditor,
        )
    else:
        pii_state = LlmPiiReplacementState()
        final_texts = {}
        final_sender_ids = {}
        completed_pii_batches = []
    if completed_pii_batches:
        print(
            f"[{project.project_id}] resumed {len(completed_pii_batches)}/"
            f"{len(pii_batches)} validated phase-2 batches",
            flush=True,
        )
    for batch_number, batch in enumerate(pii_batches, start=1):
        if batch_number <= len(completed_pii_batches):
            print(
                f"[{project.project_id}] PII LLM batch {batch_number}/{len(pii_batches)} "
                "restored from checkpoint",
                flush=True,
            )
            continue
        print(
            f"[{project.project_id}] PII LLM batch {batch_number}/{len(pii_batches)} "
            f"({len(batch)} messages)",
            flush=True,
        )
        result = await redact_pii_batch(
            api,
            project.project_id,
            batch_number,
            batch,
            pii_state,
            local_auditor,
        )
        final_texts.update(result.texts)
        final_sender_ids.update(result.sender_ids)
        completed_pii_batches.append(
            {
                "batch_number": batch_number,
                "payloads": list(result.payloads),
            }
        )
        save_phase_two_checkpoint(
            phase_two_checkpoint,
            signature,
            phase_one_output_sha256,
            completed_pii_batches,
        )

    pii_changed = sum(
        final_texts[id_key(message["message_id"])] != message["text"]
        for message in rewritten_messages
    )

    cleaned_chat = build_cleaned_chat(original_chat, final_texts, final_sender_ids)
    assert_only_chat_fields_changed(original_chat, cleaned_chat)

    copy_project_except_chat(project, project_output)
    write_json(chat_output, cleaned_chat)
    manifest = {
        "status": "DONE",
        "project_id": project.project_id,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "signature": signature,
        "source": {"chat_messages": str(project.chat_path)},
        "outputs": {"project_dir": str(project_output), "chat_messages": str(chat_output)},
        "counts": {
            "messages": len(messages),
            "messages_with_pii_replaced_by_llm": pii_changed,
            "sender_ids_replaced_by_llm": pii_state.counts().get("SENDER_ID", 0),
            "short_messages_preserved_before_pii_replacement": short_preserved,
            "messages_paraphrased": len(rewrite_candidates) + manual_rewrite_count,
            "messages_manually_rewritten": manual_rewrite_count,
            "messages_with_synthetic_context": context_synthesis_message_count,
            "contextual_values_synthesized": contextual_value_count,
            "public_service_terms_synthesized": public_service_term_count,
            "context_occurrences_classified_by_llm": sum(
                len(message["context_occurrences"])
                for message in rewrite_candidates
            ),
            "context_classification_llm_batches": len(context_batches),
            "rewrite_llm_batches": len(batches),
            "pii_llm_batches": len(pii_batches),
            "project_names_replaced_by_llm": pii_state.counts().get("PROJECT_NAME", 0),
            "unique_llm_placeholders": pii_state.counts(),
        },
        "output_sha256": {"chat_messages": source_signature(cleaned_chat)},
    }
    write_json(manifest_path, manifest)
    remove_completed_checkpoints(
        (phase_zero_checkpoint, phase_one_checkpoint, phase_two_checkpoint)
    )
    print(
        f"[{project.project_id}] DONE: {len(messages)} messages, "
        f"{pii_changed} PII-cleaned by LLM after rewrite, "
        f"{len(rewrite_candidates) + manual_rewrite_count} paraphrased "
        f"({manual_rewrite_count} manual)",
        flush=True,
    )
    return manifest


def dry_run_project(project: ProjectFiles, config: CleanConfig) -> dict[str, Any]:
    original_chat = read_json(project.chat_path)
    messages = validate_and_adapt_chat_messages(original_chat, project.project_id)
    project_terms = discover_project_terms(messages, config.extra_project_terms)
    pii_cleaner = DeterministicPiiCleaner(messages, config.extra_names, project_terms)
    pii_changed = 0
    rewrite_count = 0
    contextual_value_count = 0
    context_candidate_count = 0
    public_service_term_count = 0
    context_synthesis_message_count = 0
    for message in messages:
        sanitized = pii_cleaner.sanitize_message(message)
        if sanitized != message["text"]:
            pii_changed += 1
        if should_rewrite(message["text"], config.short_message_max_words):
            rewrite_count += 1
        message_context_values = contextual_values(message["text"])
        context_candidate_count += len(context_occurrence_candidates(message["text"]))
        message_public_terms = find_public_service_terms(message["text"])
        contextual_value_count += len(message_context_values)
        public_service_term_count += len(message_public_terms)
        context_synthesis_message_count += bool(message_context_values) or bool(
            message_public_terms
        )
    return {
        "project_id": project.project_id,
        "messages": len(messages),
        "local_audit_messages_with_pii_candidates": pii_changed,
        "local_audit_sender_ids": pii_cleaner.registry.counts().get("SENDER_ID", 0),
        "would_paraphrase": rewrite_count,
        "would_synthesize_context_messages": context_synthesis_message_count,
        "contextual_values_to_synthesize": contextual_value_count,
        "context_occurrences_to_classify_by_llm": context_candidate_count,
        "public_service_terms_to_synthesize": public_service_term_count,
        "would_send_to_pii_llm": len(messages),
        "local_project_name_hints": len(project_terms),
        "local_audit_placeholder_candidates": pii_cleaner.registry.counts(),
    }


async def main_async(args: argparse.Namespace) -> int:
    print(
        f"PII Clean v{CLEANING_VERSION} | source={Path(__file__).resolve()}",
        flush=True,
    )
    wanted_ids = set(args.project_id) if args.project_id else None
    try:
        projects = discover_projects(args.source_root, wanted_ids)
    except (OSError, ValueError, PiiCleanError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not projects:
        print("No projects containing chat_messages.json found.", file=sys.stderr)
        return 2

    try:
        manual_rewrites = load_manual_rewrites(args.manual_rewrites)
    except (OSError, ValueError, PiiCleanError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    config = CleanConfig(
        output_root=args.output_root,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        short_message_max_words=args.short_message_max_words,
        max_batch_messages=args.max_batch_messages,
        max_batch_chars=args.max_batch_chars,
        resume=args.resume,
        partial_resume=args.partial_resume,
        overwrite=args.overwrite,
        extra_names=tuple(args.extra_name),
        extra_project_terms=tuple(args.extra_project_term),
        preserve_terms=tuple(args.preserve_term),
        manual_rewrites=manual_rewrites,
    )

    if args.dry_run:
        summaries = [dry_run_project(project, config) for project in projects]
        print(json.dumps({"projects": summaries}, ensure_ascii=False, indent=2))
        return 0

    api_key = os.environ.get("UPWORK_API_KEY", "").strip()
    budget_id = os.environ.get("UPWORK_BUDGET_ID", "").strip()
    missing = [
        name
        for name, value in (("UPWORK_API_KEY", api_key), ("UPWORK_BUDGET_ID", budget_id))
        if not value
    ]
    if missing:
        print(f"Missing required environment variable(s): {', '.join(missing)}", file=sys.stderr)
        return 2

    log_dir = config.output_root / "_logs"
    log_path = log_dir / "api_calls.jsonl"
    failures: list[dict[str, str]] = []
    project_semaphore = asyncio.Semaphore(args.project_concurrency)
    timeout = httpx.Timeout(args.timeout)
    async with httpx.AsyncClient(verify=not args.insecure, trust_env=False, timeout=timeout) as http_client:
        api = Stage1ApiClient(
            http_client=http_client,
            api_key=api_key,
            budget_id=budget_id,
            model=config.model,
            reasoning_effort=config.reasoning_effort,
            retries=args.retries,
            max_concurrent_requests=args.max_concurrent_requests,
            log_path=log_path,
            failed_response_dir=log_dir / "failed_responses",
        )

        async def run_one(project: ProjectFiles) -> None:
            async with project_semaphore:
                try:
                    await clean_project(project, api, config)
                except Exception as exc:  # Keep the remaining projects resumable.
                    failures.append({"project_id": project.project_id, "error": f"{type(exc).__name__}: {exc}"})
                    print(f"[{project.project_id}] FAILED: {exc}", file=sys.stderr, flush=True)

        await asyncio.gather(*(run_one(project) for project in projects))

    if failures:
        write_json(log_dir / "batch_failures.json", failures)
        print(f"Completed with {len(failures)} failed project(s).", file=sys.stderr)
        return 1
    print(f"All {len(projects)} project(s) cleaned successfully.")
    return 0


def main() -> int:
    return asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
