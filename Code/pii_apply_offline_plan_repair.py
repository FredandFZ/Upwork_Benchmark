#!/usr/bin/env python3
"""Validate and install a project-level Phase 2 repair without an LLM call.

The normal agent handoff is message-scoped.  Phase 2 is project-scoped, so a
failed entity chunk has no message task to attach to and historically left no
offline recovery path.  This utility accepts an explicit, hash-bound plan in
``agent_repairs/phase2_plan.json``, validates it with the production Phase 2
validators, and writes ordinary checkpoints that the next ``pii_clean.py`` run
can resume from.

It also re-materializes Phase 0B from its already validated per-message
checkpoints.  This is necessary when a deterministic entity-merging bug is
fixed: no discovery API call should be repeated merely to rebuild the aggregate
registry under the corrected local rule.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Mapping, Sequence

try:  # ``python Code/pii_apply_offline_plan_repair.py``
    from PII import phase0b_entities as p0b
    from PII import phase2_plan as p2
    from PII._compat import read_json, write_json
    from PII.checkpoints import CheckpointStore
    from PII.config import PHASE_0A, PHASE_0B, PHASE_1B, PHASE_2, PiiConfig, UPSTREAM
    from PII.errors import PiiError, PiiValidationError, marked
    from PII.ledger import STATUS_RUNNING, UnresolvedLedger, write_run_metadata
    from PII.models import PiiEntityRegistry, PiiOccurrence, SafeMessage, SecretRegistry, SemanticRegistry
    from PII.prompts import load_prompt_set
    from PII.textutil import canonical_sha256
except ModuleNotFoundError:  # ``python -m Code.pii_apply_offline_plan_repair``
    from Code.PII import phase0b_entities as p0b
    from Code.PII import phase2_plan as p2
    from Code.PII._compat import read_json, write_json
    from Code.PII.checkpoints import CheckpointStore
    from Code.PII.config import PHASE_0A, PHASE_0B, PHASE_1B, PHASE_2, PiiConfig, UPSTREAM
    from Code.PII.errors import PiiError, PiiValidationError, marked
    from Code.PII.ledger import STATUS_RUNNING, UnresolvedLedger, write_run_metadata
    from Code.PII.models import PiiEntityRegistry, PiiOccurrence, SafeMessage, SecretRegistry, SemanticRegistry
    from Code.PII.prompts import load_prompt_set
    from Code.PII.textutil import canonical_sha256


REPAIR_SCHEMA = "pii-offline-phase2-repair-v1"
RESULT_SCHEMA = "pii-offline-phase2-result-v1"


def _checkpoint_body(path: Path) -> Mapping[str, Any]:
    envelope = read_json(path)
    if not isinstance(envelope, dict) or not isinstance(envelope.get("body"), dict):
        raise PiiError(f"checkpoint has no object body: {path}")
    return envelope["body"]


def _phase0b_results(
    store: CheckpointStore,
    safe_messages: Sequence[SafeMessage],
    fallback: PiiEntityRegistry,
) -> dict[int, tuple[PiiOccurrence, ...]]:
    """Read existing message checkpoints, falling back to the merged registry."""

    fallback_by_ordinal: dict[int, list[PiiOccurrence]] = {}
    for entity in fallback.entities:
        for occurrence in entity.occurrences:
            fallback_by_ordinal.setdefault(occurrence.ordinal, []).append(occurrence)

    results: dict[int, tuple[PiiOccurrence, ...]] = {}
    for safe in safe_messages:
        path = store.shard_path(PHASE_0B, f"messages/{safe.ordinal:05d}")
        if path.is_file():
            body = _checkpoint_body(path)
            p0b.validate_cached_occurrences(body)
            results[safe.ordinal] = tuple(
                PiiOccurrence.from_json(item) for item in body.get("occurrences", [])
            )
        else:
            results[safe.ordinal] = tuple(fallback_by_ordinal.get(safe.ordinal, ()))
    return results


def _migrate_phase0b(
    store: CheckpointStore,
    config: PiiConfig,
    prompts: Any,
    safe_messages: Sequence[SafeMessage],
    results: Mapping[int, tuple[PiiOccurrence, ...]],
) -> PiiEntityRegistry:
    """Commit current prompt hashes and rebuild the deterministic aggregate."""

    upstream = store.upstream_hashes(UPSTREAM[PHASE_0B])
    params = config.params_for(PHASE_0B)
    for safe in safe_messages:
        scope = {
            "ordinal": safe.ordinal,
            "safe_text_sha256": safe.safe_text_sha256,
            "candidates": canonical_sha256(p0b.required_coverage_spans(safe.safe_text)),
        }
        digest = store.input_hash(
            PHASE_0B,
            prompt_sha256=prompts.sha256(PHASE_0B),
            params=params,
            upstream=upstream,
            scope=scope,
            reasoning_effort=config.effort_for(PHASE_0B),
        )
        occurrences = results.get(safe.ordinal, ())
        store.commit(
            PHASE_0B,
            f"messages/{safe.ordinal:05d}",
            input_sha256=digest,
            prompt_sha256=prompts.sha256(PHASE_0B),
            body={"occurrences": [item.to_json() for item in occurrences]},
        )

    registry = p0b.merge_entity_registry(results)
    write_json(store.phase_dir(PHASE_0B) / "entities.json", registry.to_json())
    store.commit_output(
        PHASE_0B,
        body=registry.to_json(),
        input_sha256=canonical_sha256(sorted(results)),
    )
    return registry


def _entity_payload(
    chunk: p2.PlanChunk, repair_entities: Mapping[str, Any]
) -> dict[str, Any]:
    replacements: list[dict[str, Any]] = []
    for entity_id in chunk.entity_ids:
        body = repair_entities.get(entity_id)
        if not isinstance(body, dict):
            raise PiiValidationError(
                marked(f"offline repair has no entity decision for {entity_id}"),
                failures=("PLAN_INCOMPLETE",),
            )
        replacements.append(
            {
                "entity_id": entity_id,
                "replacement": body.get("replacement"),
                "aliases": body.get("aliases", []),
                "depends_on": body.get("depends_on", []),
            }
        )
    return {"replacements": replacements}


def _literal_value(slot: Any, values: Sequence[str], occurrence: Any) -> str:
    candidates = [
        index
        for index, entry in enumerate(slot.history)
        if entry.ordinal == occurrence.ordinal
        and entry.new_value.casefold() == occurrence.source_literal.casefold()
    ]
    if not candidates:
        candidates = [
            index
            for index, entry in enumerate(slot.history)
            if entry.new_value.casefold() == occurrence.source_literal.casefold()
        ]
    if not candidates:
        # Consolidation can fold spelling variants into one history value while
        # retaining every exact message occurrence (``Advance`` in an earlier
        # message, ``Advanced`` in the canonical history).  Bind such a variant
        # to the value effective at its ordinal instead of inventing a global
        # literal rule.  Before the first recorded transition, the first value
        # is the only project state available.
        prior = [
            index
            for index, entry in enumerate(slot.history)
            if entry.ordinal <= occurrence.ordinal
        ]
        candidates = [prior[-1] if prior else 0]
    planned = {values[index] for index in candidates}
    if len(planned) != 1:
        raise PiiValidationError(
            marked(
                f"offline repair cannot map literal occurrence for {slot.slot_id} "
                f"at ordinal {occurrence.ordinal}"
            ),
            failures=("PLAN_SCHEMA_INVALID",),
        )
    return next(iter(planned))


def _slot_payload(
    cluster: p2.SlotCluster,
    semantics: SemanticRegistry,
    repair_slots: Mapping[str, Any],
) -> dict[str, Any]:
    by_id = semantics.by_id()
    replacements: list[dict[str, Any]] = []
    for slot_id in cluster.slot_ids:
        slot = by_id[slot_id]
        values = repair_slots.get(slot_id)
        if (
            not isinstance(values, list)
            or len(values) != len(slot.history)
            or not all(isinstance(value, str) and value.strip() for value in values)
        ):
            raise PiiValidationError(
                marked(
                    f"offline repair for {slot_id} must contain exactly "
                    f"{len(slot.history)} non-empty history values"
                ),
                failures=("PLAN_SCHEMA_INVALID",),
            )
        replacements.append(
            {
                "slot_id": slot_id,
                "history": [{"new_value": value} for value in values],
                "literal_replacements": [
                    {
                        "ordinal": occurrence.ordinal,
                        "message_id": occurrence.message_id,
                        "start": occurrence.start,
                        "end": occurrence.end,
                        "original": occurrence.source_literal,
                        "replacement": _literal_value(slot, values, occurrence),
                    }
                    for occurrence in slot.literal_occurrences
                ],
            }
        )
    return {"slot_replacements": replacements}


def apply_repair(
    *,
    project_id: str,
    work_root: Path,
    output_root: Path,
    prompt_dir: Path,
) -> Path:
    run_dir = work_root / project_id
    repair_path = run_dir / "agent_repairs" / "phase2_plan.json"
    repair = read_json(repair_path)
    if not isinstance(repair, dict) or repair.get("schema_version") != REPAIR_SCHEMA:
        raise PiiError(f"unsupported or missing offline repair: {repair_path}")
    if repair.get("project_id") != project_id:
        raise PiiError("offline repair belongs to another project")

    phase0a_checkpoint = read_json(run_dir / "phase0a_secret_shield" / "registry.json")
    if not isinstance(phase0a_checkpoint, dict):
        raise PiiError("phase 0A registry checkpoint is malformed")
    model = str(phase0a_checkpoint.get("model") or "gpt-5.6-sol")
    effort = str(phase0a_checkpoint.get("reasoning_effort") or "high")
    store = CheckpointStore(
        run_dir, resume=True, model=model, reasoning_effort=effort
    )
    config = PiiConfig(
        output_root=output_root,
        work_root=work_root,
        model=model,
        reasoning_effort=effort,
    )
    prompts = load_prompt_set(prompt_dir)

    old_registry_json = read_json(store.phase_dir(PHASE_0B) / "entities.json")
    expected = repair.get("source_registry_sha256")
    already_repaired = repair.get("repaired_registry_sha256")
    actual = canonical_sha256(old_registry_json)
    if actual not in {expected, already_repaired}:
        # Repairs created before the first installation did not yet know the
        # deterministic re-materialized registry hash.  Recover it from this
        # tool's own signed result so repeating an already successful install
        # is idempotent, without accepting an unrelated registry mutation.
        prior_path = run_dir / "agent_repairs" / "phase2_repair_result.json"
        prior = read_json(prior_path) if prior_path.is_file() else {}
        if (
            isinstance(prior, dict)
            and prior.get("schema_version") == RESULT_SCHEMA
            and prior.get("project_id") == project_id
            and prior.get("source_registry_sha256") == expected
            and prior.get("repaired_registry_sha256") == actual
        ):
            already_repaired = actual
    if actual not in {expected, already_repaired}:
        raise PiiValidationError(
            marked("STALE_SUBMISSION: Phase 0B registry changed after the offline plan was written"),
            failures=("AGENT_REPAIR_REJECTED",),
        )
    old_registry = PiiEntityRegistry.from_json(old_registry_json)

    safe_messages = tuple(
        SafeMessage.from_json(item)
        for item in read_json(store.phase_dir(PHASE_0A) / "safe_messages.json")
    )
    discovery_results = _phase0b_results(store, safe_messages, old_registry)
    registry = _migrate_phase0b(
        store, config, prompts, safe_messages, discovery_results
    )
    repaired_registry_sha256 = canonical_sha256(registry.to_json())
    if repair.get("repaired_registry_sha256") != repaired_registry_sha256:
        repair = dict(repair)
        repair["repaired_registry_sha256"] = repaired_registry_sha256
        write_json(repair_path, repair)

    semantics = SemanticRegistry.from_json(
        read_json(store.phase_dir(PHASE_1B) / "registry.json")
    )
    secret_registry = SecretRegistry.from_json(phase0a_checkpoint["body"])
    repair_entities = repair.get("entities")
    repair_slots = repair.get("slots")
    if not isinstance(repair_entities, dict) or not isinstance(repair_slots, dict):
        raise PiiError("offline repair must contain object-valued entities and slots")

    upstream = store.upstream_hashes(UPSTREAM[PHASE_2])
    params = config.params_for(PHASE_2)
    entity_parts: dict[str, Any] = {}
    entity_chunks = p2.bundle_chunks(
        registry,
        max_bundles=config.plan_chunk_bundles,
        max_chars=config.plan_chunk_chars,
    )
    for chunk in entity_chunks:
        reserved = p2.reserved_values(entity_parts)
        payload = _entity_payload(chunk, repair_entities)
        part = p2.validate_entity_chunk(payload, chunk, registry, reserved)
        scope = {
            "index": chunk.index,
            "entities": list(chunk.entity_ids),
            "reserved": canonical_sha256(reserved),
        }
        digest = store.input_hash(
            PHASE_2,
            prompt_sha256=prompts.phase2_sha256(p2.MODE_ENTITY_CHUNK),
            params=params,
            upstream=upstream,
            scope=scope,
            reasoning_effort=config.effort_for(PHASE_2),
        )
        store.commit(
            PHASE_2,
            f"entities/{chunk.chunk_id}",
            input_sha256=digest,
            prompt_sha256=prompts.phase2_sha256(p2.MODE_ENTITY_CHUNK),
            prompt_variant="OFFLINE_AGENT_REPAIR",
            body={key: value.to_json() for key, value in part.items()},
        )
        entity_parts.update(part)

    slot_parts: dict[str, Any] = {}
    preserved = p2.preserved_surface_forms(registry)
    slot_clusters = p2.slot_clusters(semantics, max_chars=config.plan_chunk_chars)
    for cluster in slot_clusters:
        payload = _slot_payload(cluster, semantics, repair_slots)
        part = p2.validate_slot_cluster(payload, cluster, semantics, preserved)
        scope = {"index": cluster.index, "slots": list(cluster.slot_ids)}
        digest = store.input_hash(
            PHASE_2,
            prompt_sha256=prompts.phase2_sha256(p2.MODE_SLOT_CLUSTER),
            params=params,
            upstream=upstream,
            scope=scope,
            reasoning_effort=config.effort_for(PHASE_2),
        )
        store.commit(
            PHASE_2,
            f"slots/{cluster.cluster_id}",
            input_sha256=digest,
            prompt_sha256=prompts.phase2_sha256(p2.MODE_SLOT_CLUSTER),
            prompt_variant="OFFLINE_AGENT_REPAIR",
            body={key: value.to_json() for key, value in part.items()},
        )
        slot_parts.update(part)

    plan = p2.assemble_plan(entity_parts, slot_parts, secret_registry, semantics)
    p2.validate_plan(
        plan,
        entity_registry=registry,
        semantic_registry=semantics,
        secret_registry=secret_registry,
    )
    write_json(store.phase_dir(PHASE_2) / "plan.json", plan.to_json())
    plan_hash = store.commit_output(
        PHASE_2,
        body=plan.to_json(),
        input_sha256=canonical_sha256(
            {"entities": sorted(entity_parts), "slots": sorted(slot_parts)}
        ),
    )

    result_path = run_dir / "agent_repairs" / "phase2_repair_result.json"
    write_json(
        result_path,
        {
            "schema_version": RESULT_SCHEMA,
            "project_id": project_id,
            "source_registry_sha256": actual,
            "repaired_registry_sha256": repaired_registry_sha256,
            "plan_sha256": plan_hash,
            "entity_count": len(entity_parts),
            "slot_count": len(slot_parts),
            "entity_chunks": len(entity_chunks),
            "slot_clusters": len(slot_clusters),
            "validation": "PASS",
        },
    )
    # The repair replaces the failed project-level Phase 2 artifact, so its old
    # ledger row is no longer live.  Without retiring it, ``--status`` keeps
    # telling the operator to discard and rerun Phase 2 even though the normal
    # pipeline can restore the validated checkpoint and continue at Phase 3.
    ledger = UnresolvedLedger(run_dir=run_dir, project_id=project_id)
    ledger.load_existing()
    ledger.clear_for([PHASE_2])
    write_run_metadata(
        run_dir,
        project_id=project_id,
        status=STATUS_RUNNING,
        ledger=ledger,
        extra={
            "offline_phase2_repair": "PASS",
            "ready_from_phase": "PHASE_3_REWRITE",
        },
    )
    return result_path


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--work-root", type=Path, default=root / "outputs" / "pii_runs")
    parser.add_argument(
        "--output-root", type=Path, default=root / "Datasets" / "PII_clean_project"
    )
    parser.add_argument("--prompt-dir", type=Path, default=root / "prompt" / "PII")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = apply_repair(
        project_id=args.project_id,
        work_root=args.work_root,
        output_root=args.output_root,
        prompt_dir=args.prompt_dir,
    )
    print(f"offline Phase 2 repair validated and installed: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
