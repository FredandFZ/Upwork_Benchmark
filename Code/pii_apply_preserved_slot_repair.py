#!/usr/bin/env python3
"""Migrate phase-2 slot checkpoints onto the corrected preserved-term set.

Phase 1A is the only stage that reads a message closely enough to know a literal
*is* the requirement -- a file format, a compliance standard, a part number, a
tool version -- and it records those in ``must_preserve_terms``.  ``plan_slice``
folds them into the slice's ``preserve_literals``, so the rewrite gate enforces
them; the phase-2 slot channel never received them.  The slot validator therefore
re-valued exactly those literals, producing slices that demand both "keep this
verbatim" and "replace this".  No rewrite can satisfy that, so the messages
surfaced as agent tasks no text could fix.

The correction is forced, not chosen: for a value that *is* a preserved term,
:func:`validate_slot_cluster` already resolves it to the identity locally
("the correct answer is known without asking").  So the committed decisions are
replayed through the production validator under the corrected preserved set
rather than asked of the model again -- which also keeps every unrelated slot
value stable, and with it every phase-3 rewrite that does not depend on a
corrected slot.

This writes phase-2 slot checkpoints only.  Plan assembly, slice rebuilding and
every downstream phase stay with ``pii_clean.py``, which reuses what is still
valid and recomputes exactly what this changed.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

try:  # ``python Code/pii_apply_preserved_slot_repair.py``
    from PII import phase2_plan as p2
    from PII._compat import read_json
    from PII.checkpoints import CheckpointStore
    from PII.config import PHASE_0B, PHASE_1A, PHASE_1B, PHASE_2, UPSTREAM, PiiConfig
    from PII.errors import PiiError, PiiValidationError
    from PII.models import (
        EntityReplacement,
        MessageSemantics,
        PiiEntityRegistry,
        SemanticRegistry,
        SlotReplacement,
    )
    from PII.phase0b_entities import POLICY_SYNTHESIZE
    from PII.prompts import load_prompt_set
    from PII.textutil import canonical_sha256, literal_term_pattern
except ModuleNotFoundError:  # ``python -m Code.pii_apply_preserved_slot_repair``
    from Code.PII import phase2_plan as p2
    from Code.PII._compat import read_json
    from Code.PII.checkpoints import CheckpointStore
    from Code.PII.config import (
        PHASE_0B,
        PHASE_1A,
        PHASE_1B,
        PHASE_2,
        UPSTREAM,
        PiiConfig,
    )
    from Code.PII.errors import PiiError, PiiValidationError
    from Code.PII.models import (
        EntityReplacement,
        MessageSemantics,
        PiiEntityRegistry,
        SemanticRegistry,
        SlotReplacement,
    )
    from Code.PII.phase0b_entities import POLICY_SYNTHESIZE
    from Code.PII.prompts import load_prompt_set
    from Code.PII.textutil import canonical_sha256, literal_term_pattern


MIGRATION_VARIANT = "PRESERVED_TERM_MIGRATION"
OFFLINE_AGENT_VARIANT = "OFFLINE_AGENT_SLOT_REPAIR"
OFFLINE_ENTITY_REPLAY_VARIANT = "OFFLINE_AGENT_ENTITY_REPLAY"
OVERRIDE_SCHEMA = "pii-offline-slot-overrides-v1"
GENERATION_SCHEMA = "pii-offline-missing-slot-generation-v1"
_NUMBER_TOKEN_RE = re.compile(r"(?<!\d)-?\d+(?:,\d{3})*(?:\.\d+)?(?!\d)")


def entity_substitutions(
    registry: PiiEntityRegistry, decisions: Mapping[str, Any]
) -> list[tuple[str, str]]:
    """Real entity values that a slot value must not keep, and what replaces them.

    A slot's "synthetic" value is allowed to be a phrase, and phase 2 decides
    slots and identities in separate calls, so the slot channel can hand back a
    filename or a deadline still built around a real project name or place --
    publishing a true value while presenting it as synthetic.  ``validate_plan``
    catches it; the correction is forced rather than chosen, because the entity
    channel has already decided what that name becomes.

    Longest first, so a name that contains a shorter one is rewritten as a whole.
    """

    by_id = {entity.entity_id: entity for entity in registry.entities}
    pairs: dict[str, tuple[str, str]] = {}
    for entity_id, decision in decisions.items():
        entity = by_id.get(entity_id)
        replacement = getattr(decision, "replacement", None)
        if entity is None or entity.policy != POLICY_SYNTHESIZE or not replacement:
            continue
        # The canonical form is not enough.  A plan may carry distinct planned
        # spellings for a report code, compact project name, URL, etc.  If one
        # of those aliases is also a slot literal, the entity decision is the
        # authoritative one: asking the slot channel to invent a second value
        # creates a rewrite requirement no text can satisfy.
        for real, planned in decision.pairs():
            real = real.strip()
            planned = planned.strip()
            # Short aliases are retained for exact source-occurrence matches.
            # ``_without_real_values`` below still refuses to search for them
            # through free text, where e.g. a two-letter code is ambiguous.
            if real and planned:
                pairs.setdefault(real.casefold(), (real, planned))
    return sorted(pairs.values(), key=lambda item: len(item[0]), reverse=True)


def entity_occurrence_substitutions(
    registry: PiiEntityRegistry, decisions: Mapping[str, Any]
) -> dict[tuple[int, str], str]:
    """Entity mappings disambiguated by the source occurrence's ordinal."""

    candidates: dict[tuple[int, str], set[str]] = {}
    for entity in registry.entities:
        decision = decisions.get(entity.entity_id)
        if entity.policy != POLICY_SYNTHESIZE or decision is None:
            continue
        planned = {
            original.strip().casefold(): replacement.strip()
            for original, replacement in decision.pairs()
            if original.strip() and replacement.strip()
        }
        for occurrence in entity.occurrences:
            source = occurrence.source.strip()
            replacement = planned.get(source.casefold(), decision.replacement.strip())
            candidates.setdefault((occurrence.ordinal, source.casefold()), set()).add(
                replacement
            )
    return {
        key: next(iter(values))
        for key, values in candidates.items()
        if len(values) == 1
    }


def _without_real_values(value: str, substitutions: Sequence[tuple[str, str]]) -> str:
    for real, replacement in substitutions:
        if len(real.strip()) < 5:
            continue
        value = re.sub(
            literal_term_pattern(real), replacement, value, flags=re.IGNORECASE
        )
    return value


def _entity_authoritative_value(
    source: str,
    planned: str,
    substitutions: Sequence[tuple[str, str]],
    *,
    ordinal: int | None = None,
    occurrence_substitutions: Mapping[tuple[int, str], str] = {},
) -> str:
    """Apply an entity decision to a colliding slot source and value.

    Rewriting only ``planned`` is insufficient when the slot model invented a
    wholly unrelated value.  If the *source occurrence* is an entity surface,
    use that entity surface's planned value directly.  Otherwise merely scrub
    any real entity value embedded in the planned phrase.
    """

    source_key = source.strip().casefold()
    if ordinal is not None:
        contextual = occurrence_substitutions.get((ordinal, source_key))
        if contextual:
            return contextual
    for real, replacement in substitutions:
        if source_key == real.strip().casefold():
            return replacement
    return _without_real_values(planned, substitutions)


def _restore_missing_preserved_terms(
    source: str, planned: str, preserved: frozenset[str]
) -> str:
    missing = p2._preserved_terms_in(source, preserved) - p2._preserved_terms_in(
        planned, preserved
    )
    if not missing:
        return planned
    ordered = sorted(missing, key=lambda item: (len(item), item.casefold()))
    suffix = Path(planned).suffix
    if suffix:
        return f"{' '.join(ordered)} {planned}"
    return f"{planned} {' '.join(ordered)}"


def _load_slot_overrides(run_dir: Path, project_id: str, semantics: SemanticRegistry) -> dict[str, list[str]]:
    """Load a hash-bound, human/Agent-authored slot repair when one exists."""

    path = run_dir / "agent_repairs" / "phase2_slot_overrides.json"
    if not path.is_file():
        return {}
    body = read_json(path)
    if not isinstance(body, dict) or body.get("schema_version") != OVERRIDE_SCHEMA:
        raise PiiError(f"{project_id}: unsupported offline slot override")
    if body.get("project_id") != project_id:
        raise PiiError(f"{project_id}: offline slot override belongs to another project")
    if body.get("source_semantic_registry_sha256") != canonical_sha256(semantics.to_json()):
        raise PiiError(f"{project_id}: offline slot override is stale")
    raw_slots = body.get("slots")
    if not isinstance(raw_slots, dict):
        raise PiiError(f"{project_id}: offline slot override has no slots object")
    known = semantics.by_id()
    result: dict[str, list[str]] = {}
    for slot_id, values in raw_slots.items():
        source = known.get(slot_id)
        if source is None:
            raise PiiError(f"{project_id}: offline override names unknown slot {slot_id}")
        if (
            not isinstance(values, list)
            or len(values) != len(source.history)
            or not all(isinstance(value, str) and value.strip() for value in values)
        ):
            raise PiiError(
                f"{project_id}: offline override for {slot_id} must contain "
                f"{len(source.history)} non-empty history values"
            )
        result[slot_id] = [value.strip() for value in values]
    return result


def _missing_slot_generation_authorized(
    run_dir: Path, project_id: str, semantics: SemanticRegistry
) -> bool:
    """Require an explicit, hash-bound Agent artifact before inventing values."""

    path = run_dir / "agent_repairs" / "phase2_missing_slot_generation.json"
    if not path.is_file():
        return False
    body = read_json(path)
    if not isinstance(body, dict) or body.get("schema_version") != GENERATION_SCHEMA:
        raise PiiError(f"{project_id}: unsupported missing-slot generation artifact")
    if body.get("project_id") != project_id:
        raise PiiError(f"{project_id}: generation artifact belongs to another project")
    if body.get("source_semantic_registry_sha256") != canonical_sha256(semantics.to_json()):
        raise PiiError(f"{project_id}: missing-slot generation artifact is stale")
    return body.get("generate_missing_slots") is True


def _scaled_numbers(value: str) -> str:
    """Deterministically re-value numeric tokens while keeping units and syntax."""

    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        compact = raw.replace(",", "")
        try:
            number = float(compact)
        except ValueError:
            return raw
        if number == 0:
            return "0.0"
        scaled = number * 2
        if "." not in compact and scaled.is_integer():
            return str(int(scaled))
        rendered = f"{scaled:.6f}".rstrip("0").rstrip(".")
        return rendered

    return _NUMBER_TOKEN_RE.sub(replace, value)


def _synthetic_slot_value(
    slot_id: str,
    source_value: str,
    value_type: str,
    preserved: frozenset[str],
) -> str:
    """Create a conservative offline value for a slot with no valid decision.

    This is deliberately mechanical: the Phase 3 model owns natural prose;
    Phase 2 only needs a stable, non-identical semantic target.  Numeric values
    keep their surrounding unit/syntax and use one global scale, while opaque
    identifiers and filenames use reserved synthetic forms.
    """

    tag = canonical_sha256({"slot_id": slot_id, "source": source_value})[:8]
    suffix = Path(source_value.strip()).suffix if value_type == "FILENAME" else ""
    if value_type == "FILENAME":
        candidate = f"northstar-asset-{tag}{suffix or '.dat'}"
    elif value_type == "DATE":
        candidate = "2031-06-15"
    elif value_type == "VERSION":
        candidate = f"v{2 + int(tag[:2], 16) % 7}.0"
    elif value_type == "IDENTIFIER":
        candidate = f"NX-{tag[:4].upper()}-{tag[4:].upper()}"
    elif _NUMBER_TOKEN_RE.search(source_value):
        candidate = _scaled_numbers(source_value)
    else:
        candidate = f"alternate-setting-{tag}"

    # Public technical terms are requirements, not identities.  If the generic
    # value did not naturally retain them, carry them explicitly so the same
    # production preservation gate used for API plans remains authoritative.
    kept = p2._preserved_terms_in(source_value, preserved)
    present = p2._preserved_terms_in(candidate, preserved)
    missing = sorted(kept - present, key=lambda item: (len(item), item.casefold()))
    if missing:
        candidate = f"{candidate} {' '.join(missing)}"
    if candidate.strip().casefold() == source_value.strip().casefold():
        candidate = f"alternate-{candidate}"
    return candidate.strip()


def _generated_slot_body(
    slot: Any,
    preserved: frozenset[str],
    substitutions: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    history_values = [
        _entity_authoritative_value(
            item.new_value,
            _synthetic_slot_value(
                slot.slot_id, item.new_value, slot.value_type, preserved
            ),
            substitutions,
        )
        for item in slot.history
    ]
    literal_replacements: list[dict[str, Any]] = []
    for occurrence in slot.literal_occurrences:
        matching = {
            history_values[index]
            for index, item in enumerate(slot.history)
            if item.new_value.casefold() == occurrence.source_literal.casefold()
        }
        value = (
            next(iter(matching))
            if len(matching) == 1
            else _entity_authoritative_value(
                occurrence.source_literal,
                _synthetic_slot_value(
                    slot.slot_id,
                    occurrence.source_literal,
                    slot.value_type,
                    preserved,
                ),
                substitutions,
            )
        )
        literal_replacements.append(
            {
                "ordinal": occurrence.ordinal,
                "message_id": occurrence.message_id,
                "start": occurrence.start,
                "end": occurrence.end,
                "original": occurrence.source_literal,
                "replacement": value,
                "match_mode": (
                    "SEMANTIC_ONLY"
                    if p2.is_bare_numeric_literal(occurrence.source_literal)
                    else "EXACT"
                ),
            }
        )
    return {
        "slot_id": slot.slot_id,
        "value_type": slot.value_type,
        "history": [
            {
                "ordinal": source.ordinal,
                "op": source.op,
                "old_value": history_values[index - 1] if index else None,
                "new_value": value,
            }
            for index, (source, value) in enumerate(zip(slot.history, history_values))
        ],
        "literal_replacements": literal_replacements,
    }


def _coerced_payload(
    body: Mapping[str, Any],
    semantics: SemanticRegistry,
    preserved: frozenset[str],
    substitutions: Sequence[tuple[str, str]] = (),
    overrides: Mapping[str, Sequence[str]] = {},
    restore_preserved_terms: bool = False,
    occurrence_substitutions: Mapping[tuple[int, str], str] = {},
) -> tuple[dict[str, Any], set[str]]:
    """The committed decisions, with two forced corrections applied.

    Values that are *wholly* a preserved term go back to themselves; values
    carrying an entity's real value get the entity's planned replacement.  A
    value that merely contains a preserved term keeps the model's replacement
    and is judged by the validator's ``PLAN_PRESERVED_TERM_DROPPED`` rule.
    """

    by_id = semantics.by_id()
    replacements: list[dict[str, Any]] = []
    corrected: set[str] = set()
    for slot_id, raw in sorted(body.items()):
        committed = SlotReplacement.from_json(raw)
        source = by_id.get(slot_id)
        if source is None:
            raise PiiError(f"{slot_id} is not in the consolidated semantic registry")
        if len(committed.history) != len(source.history):
            raise PiiError(f"{slot_id} history length drifted from phase 1B")
        forced_values = overrides.get(slot_id)
        history: list[dict[str, Any]] = []
        for position, (original, planned) in enumerate(zip(source.history, committed.history)):
            value = forced_values[position] if forced_values is not None else planned.new_value
            if forced_values is not None and value != planned.new_value:
                corrected.add(slot_id)
            if p2._is_only_preserved(original.new_value, preserved):
                if value != original.new_value:
                    corrected.add(slot_id)
                value = original.new_value
            elif restore_preserved_terms:
                restored = _restore_missing_preserved_terms(
                    original.new_value, value, preserved
                )
                if restored != value:
                    corrected.add(slot_id)
                    value = restored
            # Identity removal outranks term preservation, so this runs last:
            # a value restored to itself may be the very one carrying a real
            # name, and that name still has to go.
            scrubbed = _entity_authoritative_value(
                original.new_value,
                value,
                substitutions,
                ordinal=original.ordinal,
                occurrence_substitutions=occurrence_substitutions,
            )
            if restore_preserved_terms:
                scrubbed = _restore_missing_preserved_terms(
                    original.new_value, scrubbed, preserved
                )
            if scrubbed != value:
                corrected.add(slot_id)
                value = scrubbed
            history.append({"new_value": value})
        literals: list[dict[str, Any]] = []
        for occurrence in committed.literal_replacements:
            value = occurrence.replacement
            if forced_values is not None:
                matching = {
                    forced_values[index]
                    for index, item in enumerate(source.history)
                    if item.new_value.casefold() == occurrence.original.casefold()
                }
                if len(matching) != 1:
                    raise PiiError(
                        f"{slot_id} offline override cannot map occurrence at "
                        f"ordinal {occurrence.ordinal}"
                    )
                value = next(iter(matching))
                if value != occurrence.replacement:
                    corrected.add(slot_id)
            if p2._is_only_preserved(occurrence.original, preserved):
                if value != occurrence.original:
                    corrected.add(slot_id)
                value = occurrence.original
            elif restore_preserved_terms:
                restored = _restore_missing_preserved_terms(
                    occurrence.original, value, preserved
                )
                if restored != value:
                    corrected.add(slot_id)
                    value = restored
            scrubbed = _entity_authoritative_value(
                occurrence.original,
                value,
                substitutions,
                ordinal=occurrence.ordinal,
                occurrence_substitutions=occurrence_substitutions,
            )
            if restore_preserved_terms:
                scrubbed = _restore_missing_preserved_terms(
                    occurrence.original, scrubbed, preserved
                )
            if scrubbed != value:
                corrected.add(slot_id)
                value = scrubbed
            literals.append(
                {
                    "ordinal": occurrence.ordinal,
                    "message_id": occurrence.message_id,
                    "start": occurrence.start,
                    "end": occurrence.end,
                    "original": occurrence.original,
                    "replacement": value,
                }
            )
        replacements.append(
            {
                "slot_id": slot_id,
                "history": history,
                "literal_replacements": literals,
            }
        )
    return {"slot_replacements": replacements}, corrected


def migrate_project(
    project_id: str,
    *,
    work_root: Path,
    output_root: Path,
    prompt_dir: Path,
    dry_run: bool,
) -> dict[str, Any]:
    run_dir = work_root / project_id
    if not (run_dir / "phase2_transformation_plan").is_dir():
        raise PiiError(f"{project_id}: no phase 2 checkpoints to migrate")

    entities = PiiEntityRegistry.from_json(
        read_json(run_dir / "phase0b_pii_discovery" / "entities.json")
    )
    semantics = SemanticRegistry.from_json(
        read_json(run_dir / "phase1b_project_consolidation" / "registry.json")
    )
    records = [
        MessageSemantics.from_json(item)
        for item in read_json(run_dir / "phase1a_message_semantics" / "semantics.json")
    ]

    before = p2.preserved_surface_forms(entities)
    after = before | p2.semantic_preserve_terms(records, entities)

    entity_dir = run_dir / "phase2_transformation_plan" / "entities"
    decisions: dict[str, EntityReplacement] = {}
    entity_envelopes: list[dict[str, Any]] = []
    for path in sorted(entity_dir.glob("*.json")) if entity_dir.is_dir() else []:
        envelope = read_json(path)
        if not isinstance(envelope, dict):
            continue
        entity_envelopes.append(envelope)
        body = envelope.get("body") or {}
        decisions.update(
            {key: EntityReplacement.from_json(value) for key, value in body.items()}
        )
    substitutions = entity_substitutions(entities, decisions)
    occurrence_substitutions = entity_occurrence_substitutions(entities, decisions)
    overrides = _load_slot_overrides(run_dir, project_id, semantics)
    generate_missing = _missing_slot_generation_authorized(
        run_dir, project_id, semantics
    )
    if after == before and not substitutions and not overrides and not generate_missing:
        return {"project_id": project_id, "status": "UNCHANGED", "clusters": 0}

    prompts = load_prompt_set(prompt_dir)
    # Re-validate and re-sign entity chunks too.  A local Phase 0B policy fix
    # can change which entities need synthesis without changing the already
    # accepted decisions for those that remain.  Replaying those decisions is
    # deterministic and avoids an unnecessary external call.
    entity_chunks = p2.bundle_chunks(
        entities,
        max_bundles=PiiConfig(
            output_root=output_root, work_root=work_root, model="", reasoning_effort=""
        ).plan_chunk_bundles,
        max_chars=PiiConfig(
            output_root=output_root, work_root=work_root, model="", reasoning_effort=""
        ).plan_chunk_chars,
    )
    migrated_entities: list[str] = []
    entity_parts: dict[str, EntityReplacement] = {}
    for chunk in entity_chunks:
        if not entity_envelopes:
            raise PiiError(f"{project_id}: no phase 2 entity checkpoints to replay")
        envelope = entity_envelopes[min(chunk.index - 1, len(entity_envelopes) - 1)]
        store = CheckpointStore(
            run_dir,
            resume=True,
            model=str(envelope.get("model") or ""),
            reasoning_effort=str(envelope.get("reasoning_effort") or ""),
        )
        run_config = PiiConfig(
            output_root=output_root,
            work_root=work_root,
            model=store.model,
            reasoning_effort=store.reasoning_effort,
        )
        payload = {
            "replacements": [
                {
                    "entity_id": entity_id,
                    "replacement": decisions[entity_id].replacement,
                    "aliases": [item.to_json() for item in decisions[entity_id].aliases],
                    "depends_on": list(decisions[entity_id].depends_on),
                }
                for entity_id in chunk.entity_ids
                if entity_id in decisions
            ]
        }
        reserved = p2.reserved_values(entity_parts)
        part = p2.validate_entity_chunk(payload, chunk, entities, reserved)
        params = run_config.params_for(PHASE_2)
        digest = store.input_hash(
            PHASE_2,
            prompt_sha256=prompts.phase2_sha256(p2.MODE_ENTITY_CHUNK),
            params=params,
            upstream=store.upstream_hashes(UPSTREAM[PHASE_2]),
            scope={
                "index": chunk.index,
                "entities": list(chunk.entity_ids),
                "reserved": canonical_sha256(reserved),
            },
            reasoning_effort=run_config.effort_for(PHASE_2),
        )
        migrated_entities.append(chunk.chunk_id)
        entity_parts.update(part)
        if not dry_run:
            store.commit(
                PHASE_2,
                f"entities/{chunk.chunk_id}",
                input_sha256=digest,
                prompt_sha256=prompts.phase2_sha256(p2.MODE_ENTITY_CHUNK),
                prompt_variant=OFFLINE_ENTITY_REPLAY_VARIANT,
                body={key: value.to_json() for key, value in part.items()},
            )

    prompt_sha = prompts.phase2_sha256(p2.MODE_SLOT_CLUSTER)

    migrated: list[str] = []
    unverified: list[str] = []
    needs_replan: list[tuple[str, str]] = []
    corrected_slots: set[str] = set()
    # Only ``plan_chunk_chars`` is read here, and it does not depend on the
    # model or effort; a per-cluster config carrying the checkpoint's own values
    # is built below for anything that does.  A wrong chunk size would change
    # cluster composition, which the input-hash replay check would catch.
    config = PiiConfig(
        output_root=output_root, work_root=work_root, model="", reasoning_effort=""
    )
    slot_dir = run_dir / "phase2_transformation_plan" / "slots"
    slot_envelopes: list[dict[str, Any]] = []
    slot_bodies: dict[str, Any] = {}
    for path in sorted(slot_dir.glob("*.json")) if slot_dir.is_dir() else []:
        envelope = read_json(path)
        if not isinstance(envelope, dict) or not isinstance(envelope.get("body"), dict):
            continue
        slot_envelopes.append(envelope)
        slot_bodies.update(envelope["body"])
    if semantics.slots and not slot_envelopes:
        raise PiiError(f"{project_id}: no phase 2 slot checkpoints to migrate")
    generated_slots: set[str] = set()
    semantic_by_id = semantics.by_id()
    for cluster in p2.slot_clusters(semantics, max_chars=config.plan_chunk_chars):
        store_path = (
            run_dir / "phase2_transformation_plan" / "slots" / f"{cluster.cluster_id}.json"
        )
        envelope = (
            read_json(store_path)
            if store_path.is_file()
            else slot_envelopes[min(cluster.index - 1, len(slot_envelopes) - 1)]
        )
        body = {slot_id: slot_bodies[slot_id] for slot_id in cluster.slot_ids if slot_id in slot_bodies}
        missing_decisions = sorted(set(cluster.slot_ids) - set(body))
        if missing_decisions and generate_missing:
            for slot_id in missing_decisions:
                body[slot_id] = _generated_slot_body(
                    semantic_by_id[slot_id], after, substitutions
                )
                generated_slots.add(slot_id)
            missing_decisions = []
        if missing_decisions:
            raise PiiError(
                f"{project_id}: no offline slot decision for {missing_decisions[:10]}"
            )

        # Model and effort come from the checkpoint that is being migrated, not
        # from a reconstructed config: they are what the original call used, and
        # guessing them would silently produce a digest the pipeline never looks
        # for -- turning a free migration into a full re-plan.  Note the two are
        # not the same value: an envelope records the *global* effort, while the
        # digest carries the phase-resolved one.
        store = CheckpointStore(
            run_dir,
            resume=True,
            model=str(envelope.get("model") or ""),
            reasoning_effort=str(envelope.get("reasoning_effort") or ""),
        )
        run_config = PiiConfig(
            output_root=output_root,
            work_root=work_root,
            model=store.model,
            reasoning_effort=store.reasoning_effort,
        )
        params = run_config.params_for(PHASE_2)
        effort = run_config.effort_for(PHASE_2)
        upstream = store.upstream_hashes(UPSTREAM[PHASE_2])

        sections = p2.build_slot_sections(cluster, semantics, after)
        scopes = {
            # The scope the pipeline used before the preserved terms entered the
            # input hash, and the one it uses now.  Either may be what is on
            # disk, because a cluster this tool already migrated carries the
            # second -- and running it again must be a no-op, not an error.
            "before": {"index": cluster.index, "slots": list(cluster.slot_ids)},
            "after": {
                "index": cluster.index,
                "slots": list(cluster.slot_ids),
                "preserved_terms": list(sections.get("PRESERVED_TERMS") or ()),
            },
        }
        # Proof that this reconstruction is exact: one of those scopes must
        # reproduce the digest the pipeline stored.  Without the check a silent
        # mismatch would look like a successful migration and then cost a full
        # re-plan on the next run.
        replayed = {
            name: store.input_hash(
                PHASE_2,
                prompt_sha256=prompt_sha,
                params=params,
                upstream=upstream,
                scope=scope,
                reasoning_effort=effort,
            )
            for name, scope in scopes.items()
        }
        # Reproducing the stored digest proves the reconstruction of everything
        # that is *not* the scope -- prompt, params, upstream, model, effort.
        # It cannot always be had: a cluster carrying a scope built from an
        # earlier preserved set matches neither candidate, and that set is not
        # recoverable from the checkpoint.
        #
        # Failing closed there would be the wrong trade.  A digest the pipeline
        # does not look for costs a model re-plan of that cluster -- exactly
        # what happens without this tool -- and cannot produce wrong data,
        # because the pipeline validates whatever it plans.  So an unprovable
        # cluster is still migrated, and counted, so the operator can see which
        # ones may be re-planned anyway.
        if envelope.get("input_sha256") not in replayed.values():
            unverified.append(cluster.cluster_id)

        # Every cluster is re-committed, not only the corrected ones.  Adding the
        # preserved terms to the scope changes every cluster's digest, so a
        # cluster left behind would read as stale and be re-planned by the model
        # for no reason -- discarding values that are already correct and
        # churning the phase-3 rewrites that depend on them.
        payload, corrected = _coerced_payload(
            body,
            semantics,
            after,
            substitutions,
            overrides,
            restore_preserved_terms=generate_missing,
            occurrence_substitutions=occurrence_substitutions,
        )
        try:
            part = p2.validate_slot_cluster(payload, cluster, semantics, after)
        except PiiValidationError as exc:
            # Some values are not resolvable without a decision: "3D model" has
            # a preserved term *and* a re-valuable noun, so neither the identity
            # nor the committed replacement is right.  Leave the checkpoint at
            # its old digest; the new scope makes the next ``pii_clean.py`` run
            # miss it and ask the model, which is the correct authority for a
            # choice.  Deterministic here, model-decided there.
            needs_replan.append((cluster.cluster_id, str(exc)))
            continue
        digest = replayed["after"]
        corrected_slots |= corrected
        migrated.append(cluster.cluster_id)
        if dry_run:
            continue
        store.commit(
            PHASE_2,
            f"slots/{cluster.cluster_id}",
            input_sha256=digest,
            prompt_sha256=prompt_sha,
            prompt_variant=(
                OFFLINE_AGENT_VARIANT
                if set(cluster.slot_ids) & (set(overrides) | generated_slots)
                else MIGRATION_VARIANT
            ),
            body={key: value.to_json() for key, value in part.items()},
        )

    return {
        "project_id": project_id,
        "status": "DRY_RUN" if dry_run else ("MIGRATED" if migrated else "UNCHANGED"),
        "clusters": len(migrated),
        "entity_chunks": len(migrated_entities),
        "cluster_ids": migrated,
        "unverified": unverified,
        "needs_replan": [item for item, _reason in needs_replan],
        "replan_reasons": {item: reason for item, reason in needs_replan},
        "slots_corrected": len(corrected_slots),
        "slots_overridden": len(set(overrides) & corrected_slots),
        "slots_generated": len(generated_slots),
        "preserved_terms_added": len(after) - len(before),
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", action="append", required=True)
    parser.add_argument("--work-root", type=Path, default=root / "outputs" / "pii_runs")
    parser.add_argument(
        "--output-root", type=Path, default=root / "Datasets" / "PII_clean_project"
    )
    parser.add_argument("--prompt-dir", type=Path, default=root / "prompt" / "PII")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing any checkpoint.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    failures = 0
    for project_id in args.project_id:
        try:
            report = migrate_project(
                project_id,
                work_root=args.work_root,
                output_root=args.output_root,
                prompt_dir=args.prompt_dir,
                dry_run=args.dry_run,
            )
        except PiiError as exc:
            failures += 1
            print(f"[{project_id}] FAILED: {exc}")
            continue
        print(
            f"[{project_id}] {report['status']} migrated={report['clusters']} "
            f"unverified={len(report.get('unverified') or ())} "
            f"needs_replan={len(report['needs_replan'])} "
            f"slots_corrected={report['slots_corrected']} "
            f"preserved_terms_added={report['preserved_terms_added']}"
        )
        for cluster_id in report["needs_replan"]:
            print(f"    re-plan {cluster_id}: {report['replan_reasons'][cluster_id][:160]}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
