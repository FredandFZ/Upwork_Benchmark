#!/usr/bin/env python3
"""Rebind existing TEXT agent tasks to the project's current Phase 2 plan.

Use this only after an offline plan repair invalidates an older task package.
The task texts are derived artifacts; this utility rebuilds their plan slices
from validated checkpoints and preserves only the failure identity/ordinal.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

try:
    from PII._compat import read_json
    from PII.agent_handoff import TaskContext, build_task, write_task_package
    from PII.config import ENGINE_VERSION, PHASE_3, PHASE_6
    from PII.errors import PiiError
    from PII.ledger import TASK_KIND_TEXT, UnresolvedEntry
    from PII.models import (
        MessageSemantics,
        PiiEntityRegistry,
        SafeMessage,
        SecretRegistry,
        SemanticRegistry,
        TransformationPlan,
    )
    from PII.phase2_plan import plan_slice
    from PII.prompts import load_prompt_set
    from PII.textutil import canonical_sha256
except ModuleNotFoundError:
    from Code.PII._compat import read_json
    from Code.PII.agent_handoff import TaskContext, build_task, write_task_package
    from Code.PII.config import ENGINE_VERSION, PHASE_3, PHASE_6
    from Code.PII.errors import PiiError
    from Code.PII.ledger import TASK_KIND_TEXT, UnresolvedEntry
    from Code.PII.models import (
        MessageSemantics,
        PiiEntityRegistry,
        SafeMessage,
        SecretRegistry,
        SemanticRegistry,
        TransformationPlan,
    )
    from Code.PII.phase2_plan import plan_slice
    from Code.PII.prompts import load_prompt_set
    from Code.PII.textutil import canonical_sha256


def refresh(
    project_id: str,
    work_root: Path,
    *,
    add_ordinals: tuple[int, ...] = (),
    failure_code: str = "REWRITE_PII_REINTRODUCED",
    local_validator_error: str = "UNEXPECTED_CREDENTIAL_LIKE_VALUE",
    prompt_dir: Path | None = None,
) -> Path:
    run_dir = work_root / project_id
    package_path = run_dir / "agent_tasks" / "index.json"
    if package_path.is_file():
        package = read_json(package_path)
        if not isinstance(package, dict) or package.get("project_id") != project_id:
            raise PiiError(f"mismatched task package for {project_id}")
        old_tasks = package.get("tasks")
        if not isinstance(old_tasks, list):
            raise PiiError(f"{project_id} has a malformed task package")
    else:
        if not add_ordinals:
            raise PiiError(
                f"{project_id} has no task package; supply --add-ordinal to "
                "bootstrap a Phase 6 audit task"
            )
        prompt_dir = prompt_dir or Path(__file__).resolve().parents[1] / "prompt" / "PII"
        prompts = load_prompt_set(prompt_dir)
        signature = read_json(run_dir / "source_signature.json")
        secret_envelope = read_json(
            run_dir / "phase0a_secret_shield" / "registry.json"
        )
        if not isinstance(signature, dict) or not isinstance(secret_envelope, dict):
            raise PiiError(f"{project_id} lacks source/secret checkpoint metadata")
        secret_registry = SecretRegistry.from_json(secret_envelope.get("body"))
        package = {
            "project_id": project_id,
            "engine_version": ENGINE_VERSION,
            "source_sha256": str(signature.get("source_sha256") or ""),
            "blocked_phase": "REWRITE_VERIFY",
            "protected_tokens": list(secret_registry.tokens()),
            "preserve_terms_global": [],
            "instructions_path": str(prompts.agent_instructions_path),
            "instructions_sha256": prompts.agent_instructions_sha256,
        }
        old_tasks = []
    if not old_tasks and not add_ordinals:
        raise PiiError(f"{project_id} has no tasks to refresh")
    if any(task.get("kind") != TASK_KIND_TEXT for task in old_tasks):
        raise PiiError(f"{project_id} contains a non-TEXT task")

    plan = TransformationPlan.from_json(
        read_json(run_dir / "phase2_transformation_plan" / "plan.json")
    )
    entities = PiiEntityRegistry.from_json(
        read_json(run_dir / "phase0b_pii_discovery" / "entities.json")
    )
    registry = SemanticRegistry.from_json(
        read_json(run_dir / "phase1b_project_consolidation" / "registry.json")
    )
    semantics = {
        item.ordinal: item
        for item in (
            MessageSemantics.from_json(raw)
            for raw in read_json(
                run_dir / "phase1a_message_semantics" / "semantics.json"
            )
        )
    }
    safe_messages = {
        item.ordinal: item
        for item in (
            SafeMessage.from_json(raw)
            for raw in read_json(run_dir / "phase0a_secret_shield" / "safe_messages.json")
        )
    }
    # Phase 0A stores provisional word-count buckets.  The pipeline promotes a
    # 1-2 word message when discovery finds PII/a secret/a semantic slot and
    # persists that decision for the offline finalizer.  Rebinding a task to
    # the provisional bucket produces a different slice hash and an impossible
    # PRESERVE_SHORT instruction for exactly the messages that need rewriting.
    resolved_path = run_dir / "resolved_buckets.json"
    if resolved_path.is_file():
        resolved = read_json(resolved_path)
        if isinstance(resolved, dict):
            safe_messages = {
                ordinal: safe.with_bucket(str(resolved.get(str(ordinal), safe.bucket)))
                for ordinal, safe in safe_messages.items()
            }
    known_ordinals = {task.get("ordinal") for task in old_tasks}
    for ordinal in add_ordinals:
        if ordinal in known_ordinals:
            continue
        if ordinal not in safe_messages:
            raise PiiError(f"{project_id} has no safe message at ordinal {ordinal}")
        old_tasks.append(
            {
                "ordinal": ordinal,
                "failed_phase": PHASE_6,
                "failure_code": failure_code,
                "failure_class": "LOCAL_VALIDATOR",
                "kind": TASK_KIND_TEXT,
                "agent_actionable": True,
                "local_validator_errors": [local_validator_error],
            }
        )
        known_ordinals.add(ordinal)
    preserve_terms = tuple(package.get("preserve_terms_global") or ())

    refreshed: list[dict] = []
    for old in old_tasks:
        ordinal = old.get("ordinal")
        safe = safe_messages.get(ordinal)
        if safe is None:
            raise PiiError(f"{project_id} task ordinal {ordinal} has no safe message")
        slice_ = plan_slice(
            plan,
            safe,
            entity_registry=entities,
            semantic_registry=registry,
            semantics=semantics.get(ordinal),
            preserve_terms=preserve_terms,
        )
        entry = UnresolvedEntry(
            recorded_at=datetime.now(timezone.utc).isoformat(),
            project_id=project_id,
            phase=str(old.get("failed_phase") or PHASE_3),
            code=str(old.get("failure_code") or "REWRITE_PLAN_MAPPING_VIOLATED"),
            failure_class=str(old.get("failure_class") or "LOCAL_VALIDATOR"),
            task_kind=TASK_KIND_TEXT,
            agent_actionable=True,
            ordinal=safe.ordinal,
            message_id=safe.message_id,
            attempts=0,
            findings=(),
            diagnostics={},
            error=None,
        )
        refreshed.append(
            build_task(
                project_id,
                entry,
                TaskContext(
                    safe=safe,
                    slice_=slice_,
                    local_validator_errors=tuple(old.get("local_validator_errors") or ()),
                ),
                preserve_terms=preserve_terms,
            )
        )

    return write_task_package(
        run_dir,
        project_id=project_id,
        engine_version=str(package.get("engine_version") or ENGINE_VERSION),
        source_sha256=str(package.get("source_sha256") or ""),
        plan_sha256=canonical_sha256(plan.to_json()),
        blocked_phase=str(package.get("blocked_phase") or "REWRITE_VERIFY"),
        tasks=refreshed,
        protected_tokens=tuple(package.get("protected_tokens") or ()),
        preserve_terms=preserve_terms,
        instructions_path=Path(str(package.get("instructions_path") or "prompt/PII/agent_repair_instructions.md")),
        instructions_sha256=str(package.get("instructions_sha256") or ""),
    )


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--work-root", type=Path, default=root / "outputs" / "pii_runs")
    parser.add_argument(
        "--add-ordinal",
        action="append",
        type=int,
        default=[],
        help="Add a Phase-6 audit ordinal as a TEXT task before refreshing.",
    )
    parser.add_argument(
        "--failure-code",
        default="REWRITE_PII_REINTRODUCED",
        help="Failure code attached to newly added Phase-6 audit tasks.",
    )
    parser.add_argument(
        "--local-validator-error",
        default="UNEXPECTED_CREDENTIAL_LIKE_VALUE",
        help="Audit finding attached to newly added Phase-6 audit tasks.",
    )
    parser.add_argument(
        "--prompt-dir",
        type=Path,
        default=root / "prompt" / "PII",
    )
    args = parser.parse_args()
    path = refresh(
        args.project_id,
        args.work_root,
        add_ordinals=tuple(args.add_ordinal),
        failure_code=args.failure_code,
        local_validator_error=args.local_validator_error,
        prompt_dir=args.prompt_dir,
    )
    print(f"[{args.project_id}] refreshed current-plan TEXT tasks: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
