"""Failure bookkeeping: the unresolved ledger and the run status machine.

Two rules define this module.

1. :meth:`UnresolvedLedger.record` never raises and never re-raises.  A message
   that fails is isolated and the run keeps going, so one run enumerates every
   problem in the project instead of surfacing one failure per crash-restart
   cycle.
2. Nothing written here may contain a sensitive value.  Diagnostics carry
   ordinals, ids, failure codes, counts and 12-hex fingerprints -- never message
   text, never an original/replacement pair.  Values registered through
   :meth:`UnresolvedLedger.register_sensitive` are substituted out of every
   diagnostic string, so even a validator message that accidentally quotes one
   cannot leak it.

The transport/content split matters: an agent cannot repair a ``ConnectError``.
v6 conflated them, and the surviving artifact shows the cost -- 155 identical
``ConnectError`` rows in one project's deferred file.  Handing those to an agent
would invite it to invent text for a message no model ever read.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ._compat import append_jsonl, id_key, read_json, read_jsonl, write_json
from .config import (
    PHASE_0B,
    PHASE_1A,
    PHASE_1B,
    PHASE_2,
    PHASE_3,
    PHASE_4,
    PHASE_5,
)
from .errors import UnresolvedMessagesError
from .textutil import EMAIL_RE, URL_RE, fingerprint

LEDGER_DIR_NAME = "unresolved"
LEDGER_FILE_NAME = "ledger.jsonl"
SUMMARY_FILE_NAME = "summary.json"
RUN_METADATA_NAME = "run_metadata.json"

MAX_DIAGNOSTIC_CHARS = 1200

# --- failure classes ------------------------------------------------------- #

CLASS_TRANSPORT = "TRANSPORT"
CLASS_LOCAL_VALIDATOR = "LOCAL_VALIDATOR"
CLASS_VERIFIER_FAIL = "VERIFIER_FAIL"
CLASS_REPAIR_EXHAUSTED = "REPAIR_EXHAUSTED"
CLASS_PLAN_GAP = "PLAN_GAP"
CLASS_PLAN_CONFLICT = "PLAN_CONFLICT"
CLASS_FATAL = "FATAL"

FAILURE_CLASSES = frozenset(
    {
        CLASS_TRANSPORT,
        CLASS_LOCAL_VALIDATOR,
        CLASS_VERIFIER_FAIL,
        CLASS_REPAIR_EXHAUSTED,
        CLASS_PLAN_GAP,
        CLASS_PLAN_CONFLICT,
        CLASS_FATAL,
    }
)

# --- agent task kinds ------------------------------------------------------ #

TASK_KIND_TEXT = "TEXT"
TASK_KIND_EXTRACTION = "EXTRACTION"
TASK_KIND_NONE = "NONE"

# Which phases produce which kind of repairable task.  Extraction-level content
# failures need an *annotation* from the agent (consumed by the next `clean`
# run, which is already calling the API); rewrite/verify failures need final
# text (consumed by the offline `finalize`).
_EXTRACTION_PHASES = frozenset({PHASE_0B, PHASE_1A})
_TEXT_PHASES = frozenset({PHASE_3, PHASE_4, PHASE_5})
# Project-level phases: no hand-written text can fix a bad project-wide artifact.
_REPLAN_PHASES = frozenset({PHASE_1B, PHASE_2})

# --- run status ------------------------------------------------------------ #

STATUS_RUNNING = "RUNNING"
STATUS_PASSED = "PASSED"
STATUS_BLOCKED_RETRYABLE = "BLOCKED_RETRYABLE"
STATUS_AWAITING_AGENT_REPAIR = "AWAITING_AGENT_REPAIR"
STATUS_AGENT_REPAIR_REJECTED = "AGENT_REPAIR_REJECTED"
STATUS_REPLAN_REQUIRED = "REPLAN_REQUIRED"
STATUS_FATAL = "FATAL"

NEXT_COMMAND: Mapping[str, str] = {
    STATUS_BLOCKED_RETRYABLE: (
        "rerun: python .\\Code\\pii_clean.py --project-id {project_id} --insecure"
    ),
    STATUS_AWAITING_AGENT_REPAIR: (
        "agent repair: read {run_dir}\\agent_tasks\\index.json with "
        "prompt/PII/agent_repair_instructions.md, then run "
        "python .\\Code\\pii_finalize.py --project-id {project_id} --validate-only"
    ),
    STATUS_AGENT_REPAIR_REJECTED: (
        "revise the submission using {run_dir}\\agent_repairs\\repair_result.json, then rerun "
        "python .\\Code\\pii_finalize.py --project-id {project_id} --validate-only"
    ),
    STATUS_REPLAN_REQUIRED: (
        "replan: python .\\Code\\pii_clean.py --project-id {project_id} "
        "--force-phase PHASE_1B_PROJECT_CONSOLIDATION --insecure"
    ),
    STATUS_FATAL: "inspect the audit report; this needs a code or source-data fix",
    STATUS_PASSED: "nothing to do",
}


def agent_task_kind(phase: str, failure_class: str) -> str:
    if failure_class in (CLASS_TRANSPORT, CLASS_FATAL):
        return TASK_KIND_NONE
    if failure_class == CLASS_PLAN_CONFLICT:
        return TASK_KIND_NONE
    if phase in _REPLAN_PHASES:
        return TASK_KIND_NONE
    if phase in _EXTRACTION_PHASES:
        return TASK_KIND_EXTRACTION
    if phase in _TEXT_PHASES or failure_class == CLASS_PLAN_GAP:
        return TASK_KIND_TEXT
    return TASK_KIND_NONE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class UnresolvedEntry:
    recorded_at: str
    project_id: str
    phase: str
    code: str
    failure_class: str
    task_kind: str
    agent_actionable: bool
    ordinal: int | None
    message_id: Any
    attempts: int
    findings: tuple[dict[str, Any], ...]
    diagnostics: Mapping[str, Any]
    error: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "recorded_at": self.recorded_at,
            "project_id": self.project_id,
            "phase": self.phase,
            "code": self.code,
            "failure_class": self.failure_class,
            "task_kind": self.task_kind,
            "agent_actionable": self.agent_actionable,
            "ordinal": self.ordinal,
            "message_id": self.message_id,
            "attempts": self.attempts,
            "findings": [dict(item) for item in self.findings],
            "diagnostics": dict(self.diagnostics),
            "error": self.error,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "UnresolvedEntry":
        findings = value.get("findings") or []
        diagnostics = value.get("diagnostics") or {}
        return cls(
            recorded_at=str(value.get("recorded_at") or ""),
            project_id=str(value.get("project_id") or ""),
            phase=str(value.get("phase") or ""),
            code=str(value.get("code") or ""),
            failure_class=str(value.get("failure_class") or ""),
            task_kind=str(value.get("task_kind") or TASK_KIND_NONE),
            agent_actionable=bool(value.get("agent_actionable")),
            ordinal=value.get("ordinal") if isinstance(value.get("ordinal"), int) else None,
            message_id=value.get("message_id"),
            attempts=int(value.get("attempts") or 0),
            findings=tuple(item for item in findings if isinstance(item, dict)),
            diagnostics=diagnostics if isinstance(diagnostics, dict) else {},
            error=value.get("error") if isinstance(value.get("error"), str) else None,
        )


@dataclass
class UnresolvedLedger:
    """Append-only record of every message the pipeline could not finish."""

    run_dir: Path
    project_id: str
    _entries: dict[tuple[str, str], UnresolvedEntry] = field(default_factory=dict)
    _sensitive: dict[str, str] = field(default_factory=dict)
    _sensitive_pattern: re.Pattern[str] | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # -- paths ------------------------------------------------------------- #

    @property
    def ledger_path(self) -> Path:
        return self.run_dir / LEDGER_DIR_NAME / LEDGER_FILE_NAME

    @property
    def summary_path(self) -> Path:
        return self.run_dir / LEDGER_DIR_NAME / SUMMARY_FILE_NAME

    # -- redaction --------------------------------------------------------- #

    def register_sensitive(self, category: str, value: str) -> None:
        """Register a value that must never appear in a diagnostic string."""

        candidate = (value or "").strip()
        if len(candidate) < 3:
            return
        if candidate.casefold() in self._sensitive:
            return
        self._sensitive[candidate.casefold()] = (
            f"<{category}:{fingerprint(category, candidate)}>"
        )
        self._sensitive_pattern = None

    def register_all_sensitive(self, pairs: Iterable[tuple[str, str]]) -> None:
        for category, value in pairs:
            self.register_sensitive(category, value)

    def _pattern(self) -> re.Pattern[str] | None:
        """One case-insensitive alternation over every registered value.

        A single pass matters: replacing values one at a time can rescan its own
        output, and a fingerprint token may legitimately contain the substring
        that produced it.
        """

        if self._sensitive_pattern is not None:
            return self._sensitive_pattern
        if not self._sensitive:
            return None
        # Longest first so a domain nested in a URL is consumed whole.
        alternation = "|".join(
            re.escape(candidate)
            for candidate in sorted(self._sensitive, key=len, reverse=True)
        )
        self._sensitive_pattern = re.compile(alternation, re.IGNORECASE)
        return self._sensitive_pattern

    def redact(self, value: str) -> str:
        """Strip every known sensitive value, address and URL from a string."""

        text = value
        pattern = self._pattern()
        if pattern is not None:
            text = pattern.sub(
                lambda match: self._sensitive.get(
                    match.group(0).casefold(), "<redacted>"
                ),
                text,
            )
        text = EMAIL_RE.sub("<email:redacted>", text)
        text = URL_RE.sub("<url:redacted>", text)
        if len(text) > MAX_DIAGNOSTIC_CHARS:
            text = text[: MAX_DIAGNOSTIC_CHARS - 3] + "..."
        return text

    def redact_mapping(self, value: Mapping[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(item, str):
                cleaned[key] = self.redact(item)
            elif isinstance(item, dict):
                cleaned[key] = self.redact_mapping(item)
            elif isinstance(item, list):
                cleaned[key] = [
                    self.redact(element)
                    if isinstance(element, str)
                    else self.redact_mapping(element)
                    if isinstance(element, dict)
                    else element
                    for element in item
                ]
            else:
                cleaned[key] = item
        return cleaned

    # -- recording --------------------------------------------------------- #

    def record_sync(
        self,
        *,
        phase: str,
        code: str,
        failure_class: str,
        message_id: Any = None,
        ordinal: int | None = None,
        attempts: int = 0,
        findings: Sequence[Mapping[str, Any]] = (),
        diagnostics: Mapping[str, Any] | None = None,
        error: BaseException | None = None,
    ) -> UnresolvedEntry:
        """Record a failure.  Deliberately total: this must never raise."""

        try:
            resolved_class = (
                failure_class if failure_class in FAILURE_CLASSES else CLASS_LOCAL_VALIDATOR
            )
            kind = agent_task_kind(phase, resolved_class)
            entry = UnresolvedEntry(
                recorded_at=_now(),
                project_id=self.project_id,
                phase=phase,
                code=code,
                failure_class=resolved_class,
                task_kind=kind,
                agent_actionable=kind != TASK_KIND_NONE,
                ordinal=ordinal,
                message_id=message_id,
                attempts=attempts,
                findings=tuple(
                    self.redact_mapping(item) for item in findings if isinstance(item, Mapping)
                ),
                diagnostics=self.redact_mapping(diagnostics or {}),
                error=(
                    self.redact(f"{type(error).__name__}: {error}")
                    if error is not None
                    else None
                ),
            )
            self._entries[(phase, id_key(message_id))] = entry
            append_jsonl(self.ledger_path, entry.to_json())
            self._write_summary()
            print(
                f"[{self.project_id}] UNRESOLVED {phase} code={code} "
                f"message_id={message_id!r} class={resolved_class}; continuing",
                flush=True,
            )
            return entry
        except Exception as exc:  # pragma: no cover - bookkeeping must not break a run
            print(
                f"[{self.project_id}] ledger write failed ({type(exc).__name__}); continuing",
                flush=True,
            )
            return UnresolvedEntry(
                recorded_at=_now(),
                project_id=self.project_id,
                phase=phase,
                code=code,
                failure_class=CLASS_LOCAL_VALIDATOR,
                task_kind=TASK_KIND_NONE,
                agent_actionable=False,
                ordinal=ordinal,
                message_id=message_id,
                attempts=attempts,
                findings=(),
                diagnostics={},
                error=None,
            )

    async def record(self, **kwargs: Any) -> UnresolvedEntry:
        """Async wrapper; serializes concurrent appends like the API call log."""

        async with self._lock:
            return self.record_sync(**kwargs)

    def _write_summary(self) -> None:
        write_json(self.summary_path, self.summary())

    # -- queries ----------------------------------------------------------- #

    def entries(self) -> list[UnresolvedEntry]:
        return [self._entries[key] for key in sorted(self._entries)]

    def entries_for(self, message_id: Any) -> list[UnresolvedEntry]:
        key = id_key(message_id)
        return [entry for (phase, item), entry in sorted(self._entries.items()) if item == key]

    def is_blocked(self, message_id: Any) -> bool:
        key = id_key(message_id)
        return any(item == key for _phase, item in self._entries)

    def blocked_message_ids(self) -> list[Any]:
        seen: dict[str, Any] = {}
        for entry in self.entries():
            seen.setdefault(id_key(entry.message_id), entry.message_id)
        return [seen[key] for key in sorted(seen)]

    def agent_actionable(self) -> list[UnresolvedEntry]:
        return [entry for entry in self.entries() if entry.agent_actionable]

    def transport_only(self) -> bool:
        entries = self.entries()
        return bool(entries) and all(
            entry.failure_class == CLASS_TRANSPORT for entry in entries
        )

    def requires_replan(self) -> bool:
        return any(
            entry.failure_class == CLASS_PLAN_CONFLICT or entry.phase in _REPLAN_PHASES
            for entry in self.entries()
        )

    def has_fatal(self) -> bool:
        return any(entry.failure_class == CLASS_FATAL for entry in self.entries())

    def counts_by_code(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.entries():
            counts[entry.code] = counts.get(entry.code, 0) + 1
        return dict(sorted(counts.items()))

    def counts_by_phase(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.entries():
            counts[entry.phase] = counts.get(entry.phase, 0) + 1
        return dict(sorted(counts.items()))

    def summary(self) -> dict[str, Any]:
        entries = self.entries()
        return {
            "project_id": self.project_id,
            "updated_at": _now(),
            "unresolved": len(entries),
            "agent_actionable": len(self.agent_actionable()),
            "transport_only": self.transport_only(),
            "requires_replan": self.requires_replan(),
            "by_code": self.counts_by_code(),
            "by_phase": self.counts_by_phase(),
            "by_task_kind": self._counts_by_task_kind(),
            "message_ids": [entry.message_id for entry in entries],
        }

    def _counts_by_task_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.entries():
            counts[entry.task_kind] = counts.get(entry.task_kind, 0) + 1
        return dict(sorted(counts.items()))

    def status(self) -> str:
        """Derive the run status.  Order matters: fatal beats replan beats agent."""

        if self.has_fatal():
            return STATUS_FATAL
        if not self._entries:
            return STATUS_PASSED
        if self.requires_replan():
            return STATUS_REPLAN_REQUIRED
        if self.transport_only():
            return STATUS_BLOCKED_RETRYABLE
        return STATUS_AWAITING_AGENT_REPAIR

    def raise_if_unresolved(self) -> None:
        """Stop the project before anything could be committed.

        Called once, at the end of whichever phase group the run stopped in --
        not per phase.  A phase-3 failure on one message must not prevent phase
        3 from attempting the rest, nor phase 4 from verifying the successes.
        """

        if not self._entries:
            return
        message_ids = [str(item) for item in self.blocked_message_ids()]
        raise UnresolvedMessagesError(
            f"{len(message_ids)} message(s) unresolved after finishing all remaining work "
            f"in this phase group: {', '.join(message_ids[:40])}"
            + (" ..." if len(message_ids) > 40 else "")
            + f". Details: {self.summary_path}",
            message_ids=self.blocked_message_ids(),
        )

    # -- restore ----------------------------------------------------------- #

    def load_existing(self) -> None:
        """Rehydrate from ``ledger.jsonl`` so a rerun keeps prior diagnostics."""

        for row in read_jsonl(self.ledger_path):
            entry = UnresolvedEntry.from_json(row)
            if entry.phase:
                self._entries[(entry.phase, id_key(entry.message_id))] = entry

    def clear_for(self, phases: Sequence[str]) -> None:
        """Drop entries for phases that are about to be retried, then rewrite."""

        targets = set(phases)
        for key in [key for key in self._entries if key[0] in targets]:
            del self._entries[key]
        self._rewrite_ledger()

    def _rewrite_ledger(self) -> None:
        """Compact the append-only log down to the live entries."""

        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(entry.to_json(), ensure_ascii=False) for entry in self.entries()
        ]
        temporary = self.ledger_path.with_suffix(".jsonl.tmp")
        temporary.write_text(
            "".join(f"{line}\n" for line in lines), encoding="utf-8"
        )
        temporary.replace(self.ledger_path)
        self._write_summary()

    def reset(self) -> None:
        self._entries.clear()
        if self.ledger_path.is_file():
            self.ledger_path.unlink()
        self._write_summary()


def write_run_metadata(
    run_dir: Path,
    *,
    project_id: str,
    status: str,
    ledger: UnresolvedLedger | None = None,
    phase_timings: Mapping[str, float] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Path:
    """Write the fingerprint-only run report.

    Kept after a successful run (unlike the PII-bearing artifacts) so the
    project retains an audit trail without retaining a re-identification key.
    """

    body: dict[str, Any] = {
        "project_id": project_id,
        "status": status,
        "updated_at": _now(),
        "agent_instructions": "prompt/PII/agent_repair_instructions.md",
        "next_command": NEXT_COMMAND.get(status, "").format(
            project_id=project_id, run_dir=run_dir
        ),
        "phase_timings_seconds": dict(sorted((phase_timings or {}).items())),
    }
    if ledger is not None:
        body["unresolved"] = ledger.summary()
    if extra:
        body.update(extra)
    path = run_dir / RUN_METADATA_NAME
    write_json(path, body)
    return path


def read_run_metadata(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / RUN_METADATA_NAME
    if not path.is_file():
        return None
    try:
        value = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None
