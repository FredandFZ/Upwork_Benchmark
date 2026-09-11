"""The agent repair handoff: task package out, submission in.

Every task asks for the same thing regardless of which phase failed -- either
the final synthetic text for one message (``TEXT``) or the missing annotation
for it (``EXTRACTION``) -- so there is one submission format and one validation
path.  ``TEXT`` tasks are consumed by the offline ``finalize``; ``EXTRACTION``
tasks are consumed by the next ``clean`` run, which is calling the API anyway.
That split is what lets finalize stay completely offline.

Two hash guards, not one.  v6 guarded a hand-written rewrite with the SHA of its
source text (``Code/PII_Clean.py:469-476``, enforced ``:3219-3224``).  That is
necessary but insufficient here: a rewrite is only valid against the *plan* it
was written for, so a stale ``plan_slice_sha256`` must be rejected just as
loudly as a stale source.

A repaired message is re-checked by exactly the phase-3 gate.  The agent gets no
privileged path around the local validators.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ._compat import read_json, write_json
from .errors import PiiError, PiiValidationError, marked
from .ledger import TASK_KIND_EXTRACTION, TASK_KIND_TEXT, UnresolvedEntry
from .models import (
    MessagePlanSlice,
    RewriteRecord,
    SafeMessage,
    VerdictRecord,
)
from .phase3_rewrite import make_record, rewrite_violations
from .textutil import (
    EMAIL_RE,
    INTERNAL_TOKEN_RE,
    URL_RE,
    canonical_sha256,
    contains_value,
    fingerprint,
)

TASK_SCHEMA_VERSION = "pii-agent-tasks-v1"
SUBMISSION_SCHEMA_VERSION = "pii-agent-repairs-v1"
RESULT_SCHEMA_VERSION = "pii-agent-result-v1"

TASKS_DIR_NAME = "agent_tasks"
REPAIRS_DIR_NAME = "agent_repairs"
TASK_INDEX_NAME = "index.json"
SUBMISSION_NAME = "repairs.json"
RESULT_NAME = "repair_result.json"
INSTRUCTIONS_COPY_NAME = "repair_instructions.md"

STATUS_OPEN = "OPEN"
STATUS_SUBMITTED = "SUBMITTED"
STATUS_ACCEPTED = "ACCEPTED"
STATUS_REJECTED = "REJECTED"

CONTEXT_FULL_PLAN = "FULL_PLAN"
CONTEXT_PLAN_ONLY = "PLAN_ONLY"
CONTEXT_NONE = "NONE"

_SUBMISSION_KEYS = frozenset(
    {
        "task_id",
        "kind",
        "ordinal",
        "message_id",
        "text",
        "safe_source_sha256",
        "plan_slice_sha256",
        "applied_entity_ids",
        "applied_slot_ids",
        "plan_amendments",
        "author",
        "reason",
        "annotation",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def tasks_dir(run_dir: Path) -> Path:
    return run_dir / TASKS_DIR_NAME


def repairs_dir(run_dir: Path) -> Path:
    return run_dir / REPAIRS_DIR_NAME


def task_id_for(project_id: str, phase: str, ordinal: int) -> str:
    """Stable across runs, so a second run reuses the agent's work."""

    return f"{project_id}:{phase}:{ordinal:05d}"


# --------------------------------------------------------------------------- #
# Writing the task package
# --------------------------------------------------------------------------- #


@dataclass
class TaskContext:
    """Whatever the pipeline managed to produce for one failed message."""

    safe: SafeMessage
    slice_: MessagePlanSlice | None = None
    last_candidate: RewriteRecord | None = None
    verdict: VerdictRecord | None = None
    attempt_history: tuple[dict[str, Any], ...] = ()
    neighbors: tuple[dict[str, Any], ...] = ()
    local_validator_errors: tuple[str, ...] = ()
    plan_gap: Mapping[str, Any] | None = None


def build_task(
    project_id: str,
    entry: UnresolvedEntry,
    context: TaskContext,
    *,
    preserve_terms: Sequence[str] = (),
) -> dict[str, Any]:
    """One agent task, carrying everything needed to fix it without guessing."""

    safe = context.safe
    slice_ = context.slice_
    if slice_ is not None:
        available = CONTEXT_FULL_PLAN
    elif entry.task_kind == TASK_KIND_TEXT:
        available = CONTEXT_PLAN_ONLY
    else:
        available = CONTEXT_NONE

    entities = [
        {
            "entity_id": item.entity_id,
            "entity_type": item.entity_type,
            "policy": item.policy,
            "original_surface_forms": list(item.originals()),
            "replacement": item.replacement,
            "alias_replacements": [alias.to_json() for alias in item.aliases],
        }
        for item in (slice_.entity_replacements if slice_ else ())
        if item.policy == "SYNTHESIZE"
    ]
    slots = [
        {
            "slot_id": item.slot_id,
            "value_type": item.value_type,
            "literal_map": dict(item.literal_map),
            "target_values": [entry_.new_value for entry_ in item.history],
        }
        for item in (slice_.slot_replacements if slice_ else ())
    ]

    return {
        "task_id": task_id_for(project_id, entry.phase, safe.ordinal),
        "kind": entry.task_kind,
        "ordinal": safe.ordinal,
        "message_id": safe.message_id,
        "speaker": safe.speaker,
        "bucket": safe.bucket,
        "failed_phase": entry.phase,
        "failure_code": entry.code,
        "failure_class": entry.failure_class,
        "agent_actionable": entry.agent_actionable,
        "requires_replan": entry.failure_class == "PLAN_CONFLICT",
        "context_available": available,
        "attempt_history": [dict(item) for item in context.attempt_history],
        "safe_original_text": safe.safe_text,
        "safe_source_sha256": safe.safe_text_sha256,
        "source_text_sha256": safe.source_text_sha256,
        "last_candidate_text": (
            context.last_candidate.text if context.last_candidate else None
        ),
        "last_candidate_sha256": (
            context.last_candidate.text_sha256 if context.last_candidate else None
        ),
        "plan_slice_sha256": (canonical_sha256(slice_.to_json()) if slice_ else None),
        "rewrite_directive": {
            "bucket": safe.bucket,
            "source_word_count": safe.word_count,
            "require_structural_change": safe.bucket == "LONG",
        },
        "must_apply_entities": entities,
        "must_apply_slots": slots,
        "relation_constraints": list(slice_.relation_constraints if slice_ else ()),
        "must_preserve_verbatim": sorted(
            {*(slice_.preserve_literals if slice_ else ()), *preserve_terms}
        ),
        "protected_tokens_present": [
            {"token": token, "count": safe.secret_tokens.count(token)}
            for token in sorted(set(safe.secret_tokens))
        ],
        "verifier_failures": [
            item.to_json() for item in (context.verdict.findings if context.verdict else ())
        ],
        "local_validator_errors": list(context.local_validator_errors),
        "plan_gap": dict(context.plan_gap) if context.plan_gap else None,
        "context_window": [dict(item) for item in context.neighbors],
        "semantic_expectations": dict(slice_.semantic_expectations) if slice_ else {},
        "status": STATUS_OPEN,
        "submission_slot": (
            f"{REPAIRS_DIR_NAME}/{SUBMISSION_NAME} -> repairs[] entry with this task_id"
        ),
    }


def write_task_package(
    run_dir: Path,
    *,
    project_id: str,
    engine_version: str,
    source_sha256: str,
    plan_sha256: str | None,
    blocked_phase: str,
    tasks: Sequence[Mapping[str, Any]],
    protected_tokens: Sequence[str],
    preserve_terms: Sequence[str],
    instructions_path: Path,
    instructions_sha256: str,
    instructions_text: str | None = None,
) -> Path:
    """Write ``agent_tasks/index.json`` plus a readable page per task.

    Derived, never authoritative: regenerated from the phase checkpoints on
    every run, and bound to the current signature so stale agent work is
    rejected rather than misapplied.
    """

    counts: dict[str, int] = {}
    for task in tasks:
        code = str(task.get("failure_code"))
        counts[code] = counts.get(code, 0) + 1

    index = {
        "schema_version": TASK_SCHEMA_VERSION,
        "project_id": project_id,
        "engine_version": engine_version,
        "generated_at": _now(),
        "source_sha256": source_sha256,
        "plan_sha256": plan_sha256,
        "blocked_phase": blocked_phase,
        "instructions_path": str(instructions_path),
        "instructions_sha256": instructions_sha256,
        # A closed list, which is what makes "no token outside this list" decidable.
        "protected_tokens": sorted(set(protected_tokens)),
        "preserve_terms_global": sorted(set(preserve_terms)),
        "counts": {
            "tasks": len(tasks),
            "agent_actionable": sum(1 for task in tasks if task.get("agent_actionable")),
            "by_failure_code": dict(sorted(counts.items())),
            "by_kind": {
                kind: sum(1 for task in tasks if task.get("kind") == kind)
                for kind in (TASK_KIND_TEXT, TASK_KIND_EXTRACTION)
            },
        },
        "tasks": [dict(task) for task in tasks],
    }
    directory = tasks_dir(run_dir)
    path = directory / TASK_INDEX_NAME
    write_json(path, index)

    for task in tasks:
        write_json(directory / f"task_{task['ordinal']:05d}.json", dict(task))

    if instructions_text is not None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / INSTRUCTIONS_COPY_NAME).write_text(
            instructions_text, encoding="utf-8"
        )
    return path


def read_task_package(run_dir: Path) -> dict[str, Any] | None:
    path = tasks_dir(run_dir) / TASK_INDEX_NAME
    if not path.is_file():
        return None
    value = read_json(path)
    return value if isinstance(value, dict) else None


def queue_sha256(package: Mapping[str, Any]) -> str:
    """Content hash of the queue, excluding its own timestamp."""

    body = {key: value for key, value in package.items() if key != "generated_at"}
    return canonical_sha256(body)


# --------------------------------------------------------------------------- #
# Reading the submission
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AgentRepair:
    task_id: str
    kind: str
    ordinal: int
    text: str | None
    safe_source_sha256: str
    plan_slice_sha256: str | None
    author: str
    reason: str
    annotation: Mapping[str, Any] | None = None
    plan_amendments: tuple[Mapping[str, Any], ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "kind": self.kind,
            "ordinal": self.ordinal,
            "text": self.text,
            "safe_source_sha256": self.safe_source_sha256,
            "plan_slice_sha256": self.plan_slice_sha256,
            "author": self.author,
            "reason": self.reason,
            "annotation": dict(self.annotation) if self.annotation else None,
            "plan_amendments": [dict(item) for item in self.plan_amendments],
        }


@dataclass
class SubmissionReview:
    """The outcome of validating one submission, per task."""

    accepted: dict[int, RewriteRecord] = field(default_factory=dict)
    rejected: dict[str, list[str]] = field(default_factory=dict)
    blocked: dict[str, str] = field(default_factory=dict)
    uncovered: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.rejected and not self.uncovered and not self.errors

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "reviewed_at": _now(),
            "ok": self.ok,
            "accepted": {
                str(ordinal): record.to_json() for ordinal, record in sorted(self.accepted.items())
            },
            "rejected": {key: list(value) for key, value in sorted(self.rejected.items())},
            "blocked": dict(sorted(self.blocked.items())),
            "uncovered_task_ids": list(self.uncovered),
            "errors": list(self.errors),
        }


def load_submission(path: Path) -> tuple[dict[str, Any], list[AgentRepair], dict[str, str]]:
    """Parse the agent's file with a closed key set.

    Rejecting unknown keys matters: a typo on a key that carries a hash guard
    would otherwise silently disable that guard.  Same discipline as v6's
    ``load_manual_rewrites`` (``Code/PII_Clean.py:1233``).
    """

    if not path.is_file():
        raise PiiError(f"no agent submission found at {path}")
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise PiiError(f"{path}: submission must be a JSON object")
    if payload.get("schema_version") != SUBMISSION_SCHEMA_VERSION:
        raise PiiError(
            f"{path}: unsupported schema_version {payload.get('schema_version')!r}; "
            f"expected {SUBMISSION_SCHEMA_VERSION}"
        )
    raw_repairs = payload.get("repairs")
    if not isinstance(raw_repairs, list):
        raise PiiError(f"{path}: submission needs a repairs list")

    repairs: list[AgentRepair] = []
    for index, entry in enumerate(raw_repairs):
        if not isinstance(entry, dict):
            raise PiiError(f"{path}: repairs[{index}] must be an object")
        unknown = sorted(set(entry).difference(_SUBMISSION_KEYS))
        if unknown:
            raise PiiError(f"{path}: repairs[{index}] has unknown key(s) {unknown}")
        task_id = entry.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise PiiError(f"{path}: repairs[{index}] has no task_id")
        ordinal = entry.get("ordinal")
        if not isinstance(ordinal, int):
            raise PiiError(f"{path}: repairs[{index}] has no integer ordinal")
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise PiiError(
                f"{path}: repairs[{index}] needs a non-empty reason explaining the fix"
            )
        kind = entry.get("kind") or TASK_KIND_TEXT
        text = entry.get("text")
        if kind == TASK_KIND_TEXT and (not isinstance(text, str) or not text.strip()):
            raise PiiError(f"{path}: repairs[{index}] is a TEXT repair with no text")
        safe_hash = entry.get("safe_source_sha256")
        if not isinstance(safe_hash, str) or not safe_hash:
            raise PiiError(f"{path}: repairs[{index}] has no safe_source_sha256")
        repairs.append(
            AgentRepair(
                task_id=task_id,
                kind=kind,
                ordinal=ordinal,
                text=text if isinstance(text, str) else None,
                safe_source_sha256=safe_hash,
                plan_slice_sha256=(
                    entry.get("plan_slice_sha256")
                    if isinstance(entry.get("plan_slice_sha256"), str)
                    else None
                ),
                author=str(entry.get("author") or "unknown"),
                reason=reason.strip(),
                annotation=(
                    entry.get("annotation")
                    if isinstance(entry.get("annotation"), dict)
                    else None
                ),
                plan_amendments=tuple(
                    item
                    for item in (entry.get("plan_amendments") or [])
                    if isinstance(item, dict)
                ),
            )
        )

    blocked: dict[str, str] = {}
    for entry in payload.get("blocked") or []:
        if isinstance(entry, dict) and isinstance(entry.get("task_id"), str):
            blocked[entry["task_id"]] = str(entry.get("reason") or "")
    return payload, repairs, blocked


def reason_violations(reason: str, plan_originals: Sequence[str]) -> list[str]:
    """Keep re-identifying values out of the one field an agent writes freely.

    ``reason`` is where an agent naturally writes "changed William to Marcus" --
    which is precisely a re-identification key, in the field most likely to be
    pasted into a chat or a commit message.  Instruction plus enforcement.
    """

    problems: list[str] = []
    if EMAIL_RE.search(reason):
        problems.append("reason contains an email address")
    if URL_RE.search(reason):
        problems.append("reason contains a link")
    for original in plan_originals:
        if len(original) >= 4 and contains_value(reason, original):
            problems.append(
                f"reason quotes an original value ({fingerprint('ORIGINAL', original)})"
            )
    return problems


def review_submission(
    *,
    package: Mapping[str, Any],
    submission: Mapping[str, Any],
    repairs: Sequence[AgentRepair],
    blocked: Mapping[str, str],
    safe_by_ordinal: Mapping[int, SafeMessage],
    slices: Mapping[int, MessagePlanSlice],
    plan_originals: Sequence[str],
    current_source_sha256: str,
) -> SubmissionReview:
    """Validate every repair locally.  Continues across repairs to report all."""

    review = SubmissionReview()
    errors: list[str] = []

    expected_queue_hash = queue_sha256(package)
    submitted_hash = submission.get("queue_sha256")
    if submitted_hash != expected_queue_hash:
        errors.append(
            "STALE_QUEUE: the task package was regenerated after this submission was "
            "written; re-read agent_tasks/index.json"
        )
    if package.get("source_sha256") != current_source_sha256:
        errors.append(
            "STALE_QUEUE: the raw chat changed after the task package was generated"
        )

    tasks_by_id = {
        str(task.get("task_id")): task for task in package.get("tasks") or []
    }
    actionable = {
        task_id
        for task_id, task in tasks_by_id.items()
        if task.get("agent_actionable")
    }
    closed_tokens = set(package.get("protected_tokens") or [])

    seen: set[str] = set()
    for repair in repairs:
        problems: list[str] = []
        task = tasks_by_id.get(repair.task_id)
        if task is None:
            problems.append(f"unknown task_id {repair.task_id}")
            review.rejected[repair.task_id] = problems
            continue
        if repair.task_id in seen:
            problems.append("duplicate submission for this task")
        seen.add(repair.task_id)
        if repair.task_id not in actionable:
            problems.append("this task is not agent-actionable")
        if task.get("requires_replan"):
            problems.append("this task requires a re-plan; text cannot fix it")

        safe = safe_by_ordinal.get(repair.ordinal)
        if safe is None:
            problems.append(f"no message at ordinal {repair.ordinal}")
            review.rejected[repair.task_id] = problems
            continue
        if repair.ordinal != task.get("ordinal"):
            problems.append("ordinal does not match the task")

        # Two-sided staleness guard.
        if repair.safe_source_sha256 != safe.safe_text_sha256:
            problems.append(
                "STALE_SUBMISSION: safe_source_sha256 does not match the current message"
            )
        if task.get("source_text_sha256") != safe.source_text_sha256:
            problems.append("STALE_SUBMISSION: the raw source row changed")

        if repair.kind == TASK_KIND_EXTRACTION:
            # Consumed by the next `clean` run, not by finalize.
            if repair.annotation is None:
                problems.append("an EXTRACTION repair needs an annotation object")
            if problems:
                review.rejected[repair.task_id] = problems
            continue

        slice_ = slices.get(repair.ordinal)
        if slice_ is None:
            problems.append("no plan slice is available for this message")
            review.rejected[repair.task_id] = problems
            continue
        expected_slice_hash = canonical_sha256(slice_.to_json())
        if repair.plan_slice_sha256 != expected_slice_hash:
            problems.append(
                "STALE_SUBMISSION: plan_slice_sha256 does not match the current plan; "
                "this repair was written against a different transformation"
            )

        text = repair.text or ""
        # The same gate a phase-3 rewrite passes -- not a weaker copy.
        problems.extend(rewrite_violations(safe, text, slice_))

        stray = sorted(
            token
            for token in set(INTERNAL_TOKEN_RE.findall(text))
            if token not in closed_tokens
        )
        if stray:
            problems.append(
                f"REWRITE_PROTECTED_TOKEN_DAMAGED: unknown protected token(s) {stray}"
            )

        problems.extend(
            f"REASON_LEAK: {item}" for item in reason_violations(repair.reason, plan_originals)
        )

        if problems:
            review.rejected[repair.task_id] = problems
            continue
        review.accepted[repair.ordinal] = make_record(
            safe, text, slice_, source="AGENT_REPAIR", attempt=1
        )

    for task_id, reason in blocked.items():
        if task_id in tasks_by_id:
            review.blocked[task_id] = reason

    covered = seen | set(review.blocked)
    review.uncovered = tuple(sorted(actionable.difference(covered)))
    review.errors = tuple(errors)
    return review


def write_review(run_dir: Path, review: SubmissionReview) -> Path:
    path = repairs_dir(run_dir) / RESULT_NAME
    write_json(path, review.to_json())
    return path


def submission_template(package: Mapping[str, Any]) -> dict[str, Any]:
    """A prefilled skeleton so the agent cannot get the shape wrong."""

    return {
        "schema_version": SUBMISSION_SCHEMA_VERSION,
        "project_id": package.get("project_id"),
        "queue_sha256": queue_sha256(package),
        "repairs": [
            {
                "task_id": task.get("task_id"),
                "kind": task.get("kind"),
                "ordinal": task.get("ordinal"),
                "message_id": task.get("message_id"),
                "text": "<final synthetic text for this message>",
                "safe_source_sha256": task.get("safe_source_sha256"),
                "plan_slice_sha256": task.get("plan_slice_sha256"),
                "author": "claude-code",
                "reason": "<what you changed and why; never quote an original value>",
            }
            for task in package.get("tasks") or []
            if task.get("agent_actionable")
        ],
        "blocked": [],
    }


def assert_submission_usable(review: SubmissionReview) -> None:
    if review.ok:
        return
    parts: list[str] = []
    if review.errors:
        parts.append("; ".join(review.errors))
    if review.uncovered:
        parts.append(f"{len(review.uncovered)} task(s) not covered: {review.uncovered[:10]}")
    if review.rejected:
        parts.append(f"{len(review.rejected)} repair(s) rejected")
    raise PiiValidationError(
        marked("agent submission cannot be committed: " + " | ".join(parts)),
        failures=("AGENT_REPAIR_REJECTED",),
    )
