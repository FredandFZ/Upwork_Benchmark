"""Offline finalize: fold agent repairs in, render, audit, commit.

Calls no API.  The agent's text is checked by exactly the phase-3 gate plus the
two staleness guards, then phase 6A renders credentials and phase 6B audits the
*whole* project -- not only the repaired rows, because one repaired message can
break a project-wide invariant (reusing a replacement assigned to someone else,
for instance).

The commit precondition is set-based, so a partially repaired project cannot
ship:

    no open agent-actionable task
      AND every submitted repair accepted by local validation
      AND zero phase-6B violations

A submission covering some tasks still validates those (useful, persisted
feedback) and then refuses, naming the uncovered ones.  Re-finalizing after the
gap is filled reuses the accepted records, so nothing is redone.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

from ._compat import read_json, write_json
from .agent_handoff import (
    RESULT_NAME,
    SUBMISSION_NAME,
    assert_submission_usable,
    load_submission,
    read_task_package,
    repairs_dir,
    review_submission,
    submission_template,
    write_review,
)
from .checkpoints import CheckpointStore, PHASE_DIR
from .config import (
    ENGINE_VERSION,
    PHASE_0A,
    PHASE_2,
    PHASE_3,
    PHASE_5,
    PHASE_6,
    PRESERVED_BUCKETS,
    PiiConfig,
    ProjectFiles,
)
from .discovery import (
    adapt_messages,
    build_cleaned_chat,
    copy_project_except_chat,
    load_chat,
    sender_id_values,
    source_signature_hash,
    write_chat,
)
from .errors import PiiError
from .ledger import (
    STATUS_AGENT_REPAIR_REJECTED,
    STATUS_PASSED,
    UnresolvedLedger,
    write_run_metadata,
)
from .models import (
    PROVENANCE_AGENT_REPAIR,
    PROVENANCE_LLM_REPAIR,
    PROVENANCE_LLM_REWRITE,
    PROVENANCE_PRESERVED,
    MessagePlanSlice,
    MessageState,
    PiiEntityRegistry,
    RewriteRecord,
    SafeMessage,
    SecretRegistry,
    SemanticRegistry,
    TransformationPlan,
)
from .phase6_render import AuditInputs, audit_final_texts, render_final_texts
from .textutil import canonical_sha256


class FinalizeState:
    """Everything reloaded from the run directory, with no API available."""

    def __init__(self, project: ProjectFiles, run_dir: Path, config: PiiConfig) -> None:
        self.project = project
        self.run_dir = run_dir
        self.config = config
        self.store = CheckpointStore(run_dir, resume=True)
        self.original_chat = load_chat(project.chat_path)
        self.messages = adapt_messages(self.original_chat, project.project_id)
        self.source_sha256 = source_signature_hash(self.original_chat)
        self.safe_messages = self._load_safe_messages()
        self.secret_registry = self._load_secret_registry()
        self.entity_registry = self._load_entity_registry()
        self.semantic_registry = self._load_semantic_registry()
        self.plan = self._load_plan()
        self.slices = self._load_slices()
        self.rewrites = self._load_rewrites()
        self.ledger = UnresolvedLedger(run_dir=run_dir, project_id=project.project_id)
        self.ledger.load_existing()

    # -- loading ------------------------------------------------------------ #

    def _read(self, phase: str, name: str) -> Any:
        path = self.store.phase_dir(phase) / name
        if not path.is_file():
            raise PiiError(
                f"{self.project.project_id}: {path} is missing; run pii_clean.py first "
                "(or the run directory was pruned after a successful run)"
            )
        return read_json(path)

    def _load_safe_messages(self) -> list[SafeMessage]:
        """Phase 0A's messages with the pipeline's resolved buckets applied.

        Phase 0A can only assign a *provisional* bucket, because whether a
        1-2 word message may stay verbatim depends on phases 0A/0B/1A together.
        The pipeline persists the resolution; applying it here is what keeps the
        offline path's bucket policy identical to the online one.
        """

        messages = [
            SafeMessage.from_json(item)
            for item in self._read(PHASE_0A, "safe_messages.json")
        ]
        path = self.run_dir / "resolved_buckets.json"
        if not path.is_file():
            return messages
        resolved = read_json(path)
        if not isinstance(resolved, dict):
            return messages
        return [
            item.with_bucket(resolved[str(item.ordinal)])
            if str(item.ordinal) in resolved
            else item
            for item in messages
        ]

    def _load_secret_registry(self) -> SecretRegistry:
        envelope = self._read(PHASE_0A, "registry.json")
        body = envelope.get("body", envelope)
        return SecretRegistry.from_json(body)

    def _load_entity_registry(self) -> PiiEntityRegistry:
        from .config import PHASE_0B

        path = self.store.phase_dir(PHASE_0B) / "entities.json"
        if not path.is_file():
            return PiiEntityRegistry(entities=(), bundles=())
        return PiiEntityRegistry.from_json(read_json(path))

    def _load_semantic_registry(self) -> SemanticRegistry:
        from .config import PHASE_1B

        path = self.store.phase_dir(PHASE_1B) / "registry.json"
        if not path.is_file():
            return SemanticRegistry(slots=(), relations=(), decisions=())
        return SemanticRegistry.from_json(read_json(path))

    def _load_plan(self) -> TransformationPlan:
        return TransformationPlan.from_json(self._read(PHASE_2, "plan.json"))

    def _load_slices(self) -> dict[int, MessagePlanSlice]:
        directory = self.store.phase_dir(PHASE_2) / "slices"
        slices: dict[int, MessagePlanSlice] = {}
        if not directory.is_dir():
            return slices
        for path in sorted(directory.glob("*.json")):
            slice_ = MessagePlanSlice.from_json(read_json(path))
            slices[slice_.ordinal] = slice_
        return slices

    def _load_rewrites(self) -> dict[int, tuple[RewriteRecord, str]]:
        """Accepted texts from phases 3 and 5, with their provenance.

        A phase-5 record supersedes the phase-3 record for the same message.
        """

        records: dict[int, tuple[RewriteRecord, str]] = {}
        for phase, provenance in (
            (PHASE_3, PROVENANCE_LLM_REWRITE),
            (PHASE_5, PROVENANCE_LLM_REPAIR),
        ):
            directory = self.store.phase_dir(phase) / "messages"
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.json")):
                envelope = read_json(path)
                body = envelope.get("body", envelope)
                record = RewriteRecord.from_json(body)
                records[record.ordinal] = (record, provenance)
        return records

    # -- state assembly ----------------------------------------------------- #

    def build_states(
        self, agent_texts: Mapping[int, RewriteRecord]
    ) -> dict[int, MessageState]:
        states: dict[int, MessageState] = {}
        for safe in self.safe_messages:
            state = MessageState(
                ordinal=safe.ordinal,
                message_id=safe.message_id,
                bucket=safe.bucket,
                requires_change=safe.bucket not in PRESERVED_BUCKETS,
            )
            if safe.ordinal in agent_texts:
                record = agent_texts[safe.ordinal]
                state.mark_done(
                    record.text,
                    provenance=PROVENANCE_AGENT_REPAIR,
                    text_sha256=record.text_sha256,
                    # Offline finalize does no LLM re-verification; the local
                    # gate plus the phase-6B audit are the guarantee.
                    verified=True,
                )
            elif safe.ordinal in self.rewrites:
                record, provenance = self.rewrites[safe.ordinal]
                state.mark_done(
                    record.text,
                    provenance=provenance,
                    text_sha256=record.text_sha256,
                    verified=True,
                )
            elif safe.bucket in PRESERVED_BUCKETS:
                state.mark_done(
                    safe.safe_text,
                    provenance=PROVENANCE_PRESERVED,
                    text_sha256=safe.safe_text_sha256,
                    verified=True,
                )
            states[safe.ordinal] = state
        return states

    def plan_originals(self) -> list[str]:
        values: list[str] = []
        for item in self.plan.synthesized():
            values.extend(item.originals())
        return values


def write_submission_template(project: ProjectFiles, run_dir: Path) -> Path:
    """Emit a prefilled skeleton so the agent cannot get the shape wrong."""

    package = read_task_package(run_dir)
    if package is None:
        raise PiiError(f"{project.project_id}: no agent task package in {run_dir}")
    path = repairs_dir(run_dir) / "repairs.template.json"
    write_json(path, submission_template(package))
    return path


def finalize_project(
    project: ProjectFiles,
    config: PiiConfig,
    *,
    run_root: Path,
    submission_path: Path | None = None,
    validate_only: bool = False,
) -> dict[str, Any]:
    """Validate the agent submission and, if everything passes, commit."""

    run_dir = run_root / project.project_id
    state = FinalizeState(project, run_dir, config)
    package = read_task_package(run_dir)

    agent_records: dict[int, RewriteRecord] = {}
    review = None
    if package is not None:
        path = submission_path or (repairs_dir(run_dir) / SUBMISSION_NAME)
        submission, repairs, blocked = load_submission(path)
        review = review_submission(
            package=package,
            submission=submission,
            repairs=repairs,
            blocked=blocked,
            safe_by_ordinal={item.ordinal: item for item in state.safe_messages},
            slices=state.slices,
            plan_originals=state.plan_originals(),
            current_source_sha256=state.source_sha256,
        )
        write_review(run_dir, review)
        if not review.ok:
            write_run_metadata(
                run_dir,
                project_id=project.project_id,
                status=STATUS_AGENT_REPAIR_REJECTED,
                ledger=state.ledger,
                extra={
                    "rejected": len(review.rejected),
                    "uncovered": list(review.uncovered),
                    "blocked": list(review.blocked),
                },
            )
            _print_review(project.project_id, review, run_dir)
            assert_submission_usable(review)
        agent_records = dict(review.accepted)
        print(
            f"[{project.project_id}] accepted {len(agent_records)} agent repair(s)",
            flush=True,
        )

    states = state.build_states(agent_records)
    missing = [
        ordinal for ordinal, item in sorted(states.items()) if item.final_text is None
    ]
    if missing:
        raise PiiError(
            f"{project.project_id}: {len(missing)} message(s) still have no accepted text "
            f"({missing[:20]}); run pii_clean.py again or supply an agent repair"
        )

    final_texts = render_final_texts(states, state.secret_registry)
    cleaned_chat = build_cleaned_chat(state.original_chat, final_texts)
    inputs = AuditInputs(
        project_id=project.project_id,
        original_chat=state.original_chat,
        messages=state.messages,
        safe_messages=state.safe_messages,
        states=states,
        secret_registry=state.secret_registry,
        entity_registry=state.entity_registry,
        semantic_registry=state.semantic_registry,
        plan=state.plan,
        preserve_terms=config.preserve_terms,
        extra_private_terms=config.extra_private_terms,
        sender_ids=sender_id_values(state.messages),
        verified_text_hashes=frozenset(
            (ordinal, item.text_sha256 or "") for ordinal, item in states.items()
        ),
        unresolved_message_ids=(),
    )
    report = audit_final_texts(inputs, final_texts, cleaned_chat)
    write_json(state.store.phase_dir(PHASE_6) / "audit_report.json", report.to_json())

    if validate_only:
        print(
            f"[{project.project_id}] validate-only: audit "
            f"{'clean' if report.ok else 'FAILED'} "
            f"({len(report.violations)} violation(s)); nothing written",
            flush=True,
        )
        report.raise_if_failed()
        return {
            "project_id": project.project_id,
            "status": "VALIDATED",
            "audit": report.counts_by_check(),
            "agent_repairs": len(agent_records),
        }

    report.raise_if_failed()

    project_output = config.output_root / project.project_id
    copy_project_except_chat(project, project_output)
    write_chat(project_output / "chat_messages.json", cleaned_chat)

    manifest = {
        "status": "DONE",
        "project_id": project.project_id,
        "engine_version": ENGINE_VERSION,
        "source_sha256": state.source_sha256,
        "model": config.model,
        "reasoning_effort": config.reasoning_effort,
        "finalized_offline": True,
        "counts": {
            "messages": len(state.messages),
            "agent_repairs": len(agent_records),
            "provenance": _provenance_counts(states),
        },
        "plan_sha256": canonical_sha256(state.plan.to_json()),
        "plan_amendments": [dict(item) for item in state.plan.amendments],
        "audit": report.counts_by_check(),
        "repaired_by_agent": sorted(agent_records),
        "output_sha256": {"chat_messages": canonical_sha256(final_texts)},
    }
    write_json(config.output_root / "_manifests" / f"{project.project_id}.json", manifest)
    write_run_metadata(
        run_dir,
        project_id=project.project_id,
        status=STATUS_PASSED,
        ledger=state.ledger,
        extra={"agent_repairs": len(agent_records), "audit": report.counts_by_check()},
    )
    if not config.keep_run_artifacts:
        _prune(state)
    print(
        f"[{project.project_id}] DONE: committed {len(final_texts)} message(s) "
        f"({len(agent_records)} agent-repaired)",
        flush=True,
    )
    return manifest


def _provenance_counts(states: Mapping[int, MessageState]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for state in states.values():
        key = state.provenance or "NONE"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _print_review(project_id: str, review: Any, run_dir: Path) -> None:
    for error in review.errors:
        print(f"[{project_id}] {error}", file=sys.stderr, flush=True)
    for task_id, problems in sorted(review.rejected.items()):
        print(f"[{project_id}] REJECTED {task_id}", flush=True)
        for problem in problems[:6]:
            print(f"    - {problem}", flush=True)
    if review.uncovered:
        print(
            f"[{project_id}] {len(review.uncovered)} task(s) have no submission: "
            f"{', '.join(review.uncovered[:10])}",
            flush=True,
        )
    if review.blocked:
        print(
            f"[{project_id}] {len(review.blocked)} task(s) marked blocked by the agent; "
            "these need a re-plan, not text",
            flush=True,
        )
    print(f"[{project_id}] details: {repairs_dir(run_dir) / RESULT_NAME}", flush=True)


def _prune(state: FinalizeState) -> None:
    from .agent_handoff import repairs_dir as _repairs, tasks_dir as _tasks

    removed = state.store.discard_phases(set(PHASE_DIR) - {PHASE_6})
    for directory in (_tasks(state.run_dir), _repairs(state.run_dir)):
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
                removed.append(path)
        try:
            directory.rmdir()
        except OSError:
            pass
    print(
        f"[{state.project.project_id}] pruned {len(removed)} PII-bearing run artifact(s)",
        flush=True,
    )


def status_report(project: ProjectFiles, run_root: Path) -> dict[str, Any]:
    """Read-only: what happened and what to run next.  No network, no writes."""

    from .ledger import NEXT_COMMAND, read_run_metadata

    run_dir = run_root / project.project_id
    metadata = read_run_metadata(run_dir) or {}
    package = read_task_package(run_dir)
    status = str(metadata.get("status") or "UNKNOWN")
    return {
        "project_id": project.project_id,
        "status": status,
        "blocked_phase": metadata.get("blocked_phase"),
        "unresolved": (metadata.get("unresolved") or {}).get("unresolved", 0),
        "by_failure_code": (package or {}).get("counts", {}).get("by_failure_code", {}),
        "agent_tasks": (package or {}).get("counts", {}).get("tasks", 0),
        "task_index": str(run_dir / "agent_tasks" / "index.json") if package else None,
        "submission_path": str(repairs_dir(run_dir) / SUBMISSION_NAME) if package else None,
        "next_command": metadata.get("next_command")
        or NEXT_COMMAND.get(status, "").format(project_id=project.project_id, run_dir=run_dir),
    }
