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
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import httpx

try:  # ``python Code/PII_Clean.py``
    from stage1.api_client import Stage1ApiClient
    from stage1.config import ANNOTATION_MODEL, REASONING_EFFORT
    from stage1.storage import id_key, read_json, sha256_text, write_json
    from stage1.validation import validate_stage1_annotation
except ModuleNotFoundError:  # ``python -m Code.PII_Clean`` and unit tests
    from Code.stage1.api_client import Stage1ApiClient
    from Code.stage1.config import ANNOTATION_MODEL, REASONING_EFFORT
    from Code.stage1.storage import id_key, read_json, sha256_text, write_json
    from Code.stage1.validation import validate_stage1_annotation


CLEANING_VERSION = "3.1"
RUN_MODE = "PII_CLEAN_REWRITE"
PLACEHOLDER_RE = re.compile(
    r"\[(?:EMAIL|URL|ACCOUNT|PASSWORD|PHONE|HANDLE|SENDER_ID|CLIENT_NAME|FREELANCER_NAME|PERSON_NAME)_\d{3,}\]"
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
HTML_NUMERIC_ENTITY_RE = re.compile(r"&#(?:x[0-9A-F]+|\d+);", re.IGNORECASE)
PROTECTED_LITERAL_RE = re.compile(
    r"(?<!\w)(?:"
    r"v?\d+(?:\.\d+){1,}|"
    r"[A-Za-z0-9_.-]+\.(?:ai|csv|docx?|fig|gif|html?|jpeg|jpg|json|md|pdf|png|psd|svg|txt|xlsx?|xml|zip)|"
    r"[A-Z][A-Z0-9_-]{1,}"
    r")(?!\w)"
)
WORD_RE = re.compile(r"[^\W_]+(?:['’.-][^\W_]+)*", re.UNICODE)
SINGLE_TOKEN_RE = re.compile(r"^[^\s]+$")

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

SYSTEM_PROMPT = """You are phase 1 of a two-phase workplace-chat cleaning pipeline.

The input may contain personally identifiable information (PII). A local phase 2
will deterministically replace PII after your rewrite. Do not perform PII
redaction in this phase.

Return JSON only, with exactly this shape:
{"rewrites": [{"message_id": <same JSON value and type>, "text": "<rewritten text>"}]}

Rules:
1. Return exactly one rewrite for every input message_id. Never add, omit, merge, split, or reorder messages.
2. Paraphrase wording and sentence structure substantially. Do not summarize.
3. Preserve the complete meaning needed for downstream requirement/event annotation: speaker intent, request/acceptance/rejection, negation, uncertainty, modality, conditions, status, scope, chronology, and every factual detail.
4. Preserve every number, amount, date, version, filename, technical identifier, and bracketed placeholder exactly. Do not translate placeholders or change their count.
5. Keep the original language and roughly the original level of formality. Do not add facts, promises, conclusions, or explanations.
6. Preserve every existing proper name, email address, URL, account, password, phone number, and handle exactly as written. Do not redact, normalize, omit, move to another message, reconstruct, guess, or invent any PII.
7. Each returned text must differ from its input text while remaining semantically equivalent.
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
class CleanConfig:
    output_root: Path
    model: str
    reasoning_effort: str
    short_message_max_words: int
    max_batch_messages: int
    max_batch_chars: int
    resume: bool
    overwrite: bool
    extra_names: tuple[str, ...]


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

    def __init__(self, messages: Sequence[dict[str, Any]], extra_names: Sequence[str] = ()) -> None:
        self.registry = PlaceholderRegistry()
        self._name_categories: dict[str, tuple[str, str]] = {}
        self._standalone_credentials: dict[str, list[tuple[str, str]]] = {}
        self._sender_ids: list[str] = []
        for name in extra_names:
            self._add_name(name, "PERSON_NAME")
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
        if not cleaned or cleaned.casefold() in NON_NAME_WORDS:
            return
        if any(part.casefold() in NON_NAME_WORDS for part in name_parts):
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
        description="Paraphrase and de-identify raw dataset project chat messages."
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
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification for trusted staging only.")
    parser.add_argument(
        "--extra-name",
        action="append",
        default=[],
        help="Additional person name to replace; repeat for multiple names.",
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


def should_rewrite(text: str, short_message_max_words: int) -> bool:
    if not text.strip() or SHORT_ACKNOWLEDGEMENTS.fullmatch(text.strip()):
        return False
    without_placeholders = PLACEHOLDER_RE.sub(" ", text)
    if not without_placeholders.strip(" \t\r\n.,!?;:()[]{}<>-'\"…"):
        return False
    return word_count(text) > short_message_max_words


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


def protected_literals(text: str) -> Counter[str]:
    return Counter(match.group(0) for match in PROTECTED_LITERAL_RE.finditer(text))


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
        if protected_numbers(output_text) != protected_numbers(input_text):
            raise ValueError(f"Rewrite for {item.get('message_id')!r} changed numbers, dates, or amounts")
        if protected_literals(output_text) != protected_literals(input_text):
            raise ValueError(f"Rewrite for {item.get('message_id')!r} changed versions, filenames, or identifiers")
        actual[key] = output_text
    if set(actual) != set(expected):
        missing = set(expected).difference(actual)
        raise ValueError(f"LLM response omitted {len(missing)} message(s)")
    return actual


def rewrite_request_messages(batch: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    body = {
        "task": "Semantically paraphrase every message while preserving all annotation-relevant facts.",
        "messages": [
            {
                "message_id": message["message_id"],
                "speaker": message.get("speaker"),
                "text": message["text"],
                "protected_literals": sorted(
                    set(PLACEHOLDER_RE.findall(message["text"]))
                    | set(protected_numbers(message["text"]))
                    | set(protected_literals(message["text"]))
                ),
            }
            for message in batch
        ],
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
    ]


async def rewrite_batch(
    api: Stage1ApiClient,
    project_id: str,
    batch_number: int,
    batch: Sequence[dict[str, Any]],
    failed_response_redactor: Callable[[str], str],
) -> dict[str, str]:
    def validator(payload: dict[str, Any]) -> None:
        validate_rewrite_response(payload, batch)

    payload = await api.call(
        project_id=project_id,
        run_mode=RUN_MODE,
        target_requirement=f"batch_{batch_number:04d}",
        messages=rewrite_request_messages(batch),
        validator=validator,
        failed_response_redactor=failed_response_redactor,
    )
    return validate_rewrite_response(payload, batch)


def source_signature(value: Any) -> str:
    return sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def run_signature(source_sha256: str, config: CleanConfig) -> dict[str, Any]:
    return {
        "cleaning_version": CLEANING_VERSION,
        "source_sha256": source_sha256,
        "model": config.model,
        "reasoning_effort": config.reasoning_effort,
        "short_message_max_words": config.short_message_max_words,
        "extra_names_sha256": sha256_text(
            "\n".join(sorted(name.strip().casefold() for name in config.extra_names if name.strip()))
        ),
        "prompt_sha256": sha256_text(SYSTEM_PROMPT),
    }


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
    pii_cleaner: DeterministicPiiCleaner,
) -> list[dict[str, Any]]:
    """Apply cleaned text and sender IDs without changing any other chat field."""
    cleaned = copy.deepcopy(original_chat)
    for index, row in enumerate(cleaned, start=1):
        key = id_key(index)
        if key not in final_texts:
            raise PiiCleanError(f"No cleaned text for chat row {index}")
        row["message"] = final_texts[key]
        if row.get("sender_id") is not None:
            row["sender_id"] = pii_cleaner.registry.token("SENDER_ID", str(row["sender_id"]))
    return cleaned


def _chat_without_cleaned_fields(chat: list[dict[str, Any]]) -> list[dict[str, Any]]:
    value = copy.deepcopy(chat)
    for row in value:
        if "message" in row:
            row["message"] = "<MESSAGE>"
        if "sender_id" in row:
            row["sender_id"] = "<SENDER_ID>"
    return value


def assert_only_chat_fields_changed(
    original_chat: list[dict[str, Any]], cleaned_chat: list[dict[str, Any]]
) -> None:
    if _chat_without_cleaned_fields(original_chat) != _chat_without_cleaned_fields(cleaned_chat):
        raise PiiCleanError("chat_messages.json changed outside message or sender_id fields")


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
    signature = run_signature(source_sha256, config)

    project_output = config.output_root / project.project_id
    chat_output = project_output / "chat_messages.json"
    manifest_path = config.output_root / "_manifests" / f"{project.project_id}.json"

    if config.resume and not config.overwrite and output_is_current(
        manifest_path, chat_output, signature
    ):
        print(f"[{project.project_id}] already clean; skipped", flush=True)
        return {"project_id": project.project_id, "status": "SKIPPED"}

    # Phase 1 intentionally works from the original message text.  Its raw
    # responses are never persisted: a failed batch starts over on rerun.
    rewritten_by_key: dict[str, str] = {}
    rewrite_candidates: list[dict[str, Any]] = []
    short_preserved = 0
    for message in messages:
        key = id_key(message["message_id"])
        rewritten_by_key[key] = message["text"]
        if should_rewrite(message["text"], config.short_message_max_words):
            rewrite_candidates.append(
                {
                    "message_id": message["message_id"],
                    "speaker": message.get("speaker"),
                    "text": message["text"],
                }
            )
        else:
            short_preserved += 1

    batches = build_batches(rewrite_candidates, config.max_batch_messages, config.max_batch_chars)
    for batch_number, batch in enumerate(batches, start=1):
        print(
            f"[{project.project_id}] rewrite batch {batch_number}/{len(batches)} "
            f"({len(batch)} messages)",
            flush=True,
        )
        rewritten_by_key.update(
            await rewrite_batch(
                api,
                project.project_id,
                batch_number,
                batch,
                lambda _raw: "[REDACTED: raw phase-one response omitted]",
            )
        )

    # Phase 2 scans every rewritten (or deliberately preserved short) message.
    # The mapping is created from the post-rewrite transcript so replacements
    # remain stable even if wording or sentence order changed in phase 1.
    rewritten_messages = copy.deepcopy(messages)
    for message in rewritten_messages:
        message["text"] = rewritten_by_key[id_key(message["message_id"])]
    pii_cleaner = DeterministicPiiCleaner(rewritten_messages, config.extra_names)
    final_texts: dict[str, str] = {}
    pii_changed = 0
    for message in rewritten_messages:
        key = id_key(message["message_id"])
        sanitized = pii_cleaner.sanitize_message(message)
        pii_cleaner.assert_no_known_pii(
            sanitized,
            source_text=message["text"],
            message_id=message["message_id"],
        )
        final_texts[key] = sanitized
        if sanitized != message["text"]:
            pii_changed += 1

    cleaned_chat = build_cleaned_chat(original_chat, final_texts, pii_cleaner)
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
            "messages_with_pii_replaced_after_rewrite": pii_changed,
            "sender_ids_replaced": pii_cleaner.registry.counts().get("SENDER_ID", 0),
            "short_messages_preserved_before_pii_replacement": short_preserved,
            "messages_paraphrased": len(rewrite_candidates),
            "unique_placeholders": pii_cleaner.registry.counts(),
        },
        "output_sha256": {"chat_messages": source_signature(cleaned_chat)},
    }
    write_json(manifest_path, manifest)
    print(
        f"[{project.project_id}] DONE: {len(messages)} messages, "
        f"{pii_changed} PII-cleaned after rewrite, {len(rewrite_candidates)} paraphrased",
        flush=True,
    )
    return manifest


def dry_run_project(project: ProjectFiles, config: CleanConfig) -> dict[str, Any]:
    original_chat = read_json(project.chat_path)
    messages = validate_and_adapt_chat_messages(original_chat, project.project_id)
    pii_cleaner = DeterministicPiiCleaner(messages, config.extra_names)
    pii_changed = 0
    rewrite_count = 0
    for message in messages:
        sanitized = pii_cleaner.sanitize_message(message)
        if sanitized != message["text"]:
            pii_changed += 1
        if should_rewrite(message["text"], config.short_message_max_words):
            rewrite_count += 1
    return {
        "project_id": project.project_id,
        "messages": len(messages),
        "input_messages_with_pii_candidates": pii_changed,
        "input_sender_ids": pii_cleaner.registry.counts().get("SENDER_ID", 0),
        "would_paraphrase": rewrite_count,
        "input_placeholder_candidates": pii_cleaner.registry.counts(),
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

    config = CleanConfig(
        output_root=args.output_root,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        short_message_max_words=args.short_message_max_words,
        max_batch_messages=args.max_batch_messages,
        max_batch_chars=args.max_batch_chars,
        resume=args.resume,
        overwrite=args.overwrite,
        extra_names=tuple(args.extra_name),
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
