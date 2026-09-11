"""Phase sequencing, checkpoint wiring, and the phase-group barriers.

No regex, no prompt text and no response parsing live here -- those belong to
the phase modules.  This file decides *order*, *resume* and *when to stop*.

The barrier rule is the one non-obvious part:

    Within a phase, never stop: quarantine the message and keep going, so one
    run enumerates every problem.  At an aggregation boundary, stop advancing if
    any input to the aggregate is missing.

Phases 1B and 2 build one project-wide artifact, and global consistency cannot
be derived from a partial inventory.  If message 231 failed extraction, its
entities never enter the plan; continuing would either leak the real value in
the *other* messages that mention it, or invent an ad-hoc mapping that
contradicts the plan once 231 is repaired.  So extraction-level failures cap the
run at the extraction stage -- while still running 0B *and* 1A to completion, so
one run reports every extraction failure.  Phases 3/4/5 are per-message against
a frozen plan, so they always run to completion; that is where failures actually
cluster.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import phase0b_entities as p0b
from . import phase1a_semantics as p1a
from . import phase1b_consolidate as p1b
from . import phase2_plan as p2
from . import phase3_rewrite as p3
from . import phase4_verify as p4
from . import phase5_repair as p5
from ._compat import ApiError, write_json
from .checkpoints import CheckpointStore, check_source_signature, source_signature
from .config import (
    BUCKET_LONG,
    ENGINE_VERSION,
    PHASE_0A,
    PHASE_0B,
    PHASE_1A,
    PHASE_1B,
    PHASE_2,
    PHASE_3,
    PHASE_4,
    PHASE_5,
    PHASE_6,
    PRESERVED_BUCKETS,
    PiiConfig,
    ProjectFiles,
    UPSTREAM,
    phases_up_to,
)
from .discovery import (
    adapt_messages,
    build_cleaned_chat,
    copy_project_except_chat,
    load_chat,
    output_is_current,
    sender_id_values,
    source_signature_hash,
    write_chat,
)
from .errors import (
    PiiError,
    PiiValidationError,
    ResumeSignatureError,
    api_error_is_validation_failure,
)
from .agent_handoff import TaskContext, build_task, write_task_package
from .ledger import (
    CLASS_LOCAL_VALIDATOR,
    CLASS_PLAN_CONFLICT,
    CLASS_REPAIR_EXHAUSTED,
    CLASS_TRANSPORT,
    CLASS_VERIFIER_FAIL,
    STATUS_PASSED,
    STATUS_RUNNING,
    UnresolvedLedger,
    write_run_metadata,
)
from .llm import build_shards, run_sharded_phase, run_single_call
from .models import (
    PROVENANCE_LLM_REPAIR,
    PROVENANCE_LLM_REWRITE,
    PROVENANCE_PRESERVED,
    MessagePlanSlice,
    MessageSemantics,
    MessageState,
    PiiEntityRegistry,
    RewriteRecord,
    SafeMessage,
    SecretRegistry,
    SemanticRegistry,
    TransformationPlan,
    VerdictRecord,
)
from .phase6_render import (
    AuditInputs,
    audit_final_texts,
    render_final_texts,
    secret_values,
)
from .prompts import PromptSet, rewrite_prompt_key
from .secret_shield import shield_project
from .textutil import canonical_sha256, resolve_bucket


@dataclass
class ProjectRun:
    """Mutable state for one project's pass through the pipeline."""

    project: ProjectFiles
    run_dir: Path
    store: CheckpointStore
    ledger: UnresolvedLedger
    original_chat: list[Any] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    safe_messages: list[SafeMessage] = field(default_factory=list)
    secret_registry: SecretRegistry | None = None
    entity_registry: PiiEntityRegistry | None = None
    semantics: dict[int, MessageSemantics] = field(default_factory=dict)
    semantic_registry: SemanticRegistry | None = None
    plan: TransformationPlan | None = None
    slices: dict[int, MessagePlanSlice] = field(default_factory=dict)
    rewrites: dict[int, RewriteRecord] = field(default_factory=dict)
    verdicts: dict[int, VerdictRecord] = field(default_factory=dict)
    states: dict[int, MessageState] = field(default_factory=dict)
    attempts: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    source_sha256: str = ""

    def safe_by_ordinal(self) -> dict[int, SafeMessage]:
        return {item.ordinal: item for item in self.safe_messages}

    def record_attempt(self, ordinal: int, entry: Mapping[str, Any]) -> None:
        self.attempts.setdefault(ordinal, []).append(dict(entry))


class PiiPipeline:
    def __init__(
        self,
        api: Any,
        config: PiiConfig,
        prompts: PromptSet,
        *,
        run_root: Path,
    ) -> None:
        config.validate()
        self.api = api
        self.config = config
        self.prompts = prompts
        self.run_root = run_root

    # -- entry point -------------------------------------------------------- #

    async def run(self, project: ProjectFiles) -> dict[str, Any]:
        run_dir = self.run_root / project.project_id
        original_chat = load_chat(project.chat_path)
        messages = adapt_messages(original_chat, project.project_id)
        digest = source_signature_hash(original_chat)
        expected = source_signature(digest, project.chat_path, len(messages))

        usable, reason = check_source_signature(run_dir, expected)
        if not usable:
            raise ResumeSignatureError(
                f"{project.project_id}: {reason}. Use --no-resume to start a clean run, "
                "or point --work-root at a fresh directory."
            )
        write_json(run_dir / "source_signature.json", expected)

        manifest_path = self.config.output_root / "_manifests" / f"{project.project_id}.json"
        chat_output = self.config.output_root / project.project_id / "chat_messages.json"
        if (
            self.config.resume
            and not self.config.overwrite
            and output_is_current(manifest_path, chat_output, digest, ENGINE_VERSION)
        ):
            print(f"[{project.project_id}] already clean; skipped", flush=True)
            return {"project_id": project.project_id, "status": "SKIPPED"}

        forced = self.config.expanded_force_phases()
        store = CheckpointStore(
            run_dir,
            resume=self.config.resume,
            forced=forced,
            model=self.config.model,
            reasoning_effort=self.config.reasoning_effort,
        )
        if not self.config.resume:
            store.discard_phases(set(UPSTREAM))
        elif forced:
            store.discard_phases(forced)

        ledger = UnresolvedLedger(run_dir=run_dir, project_id=project.project_id)
        if self.config.resume:
            ledger.load_existing()
            ledger.clear_for(sorted(forced))

        run = ProjectRun(
            project=project,
            run_dir=run_dir,
            store=store,
            ledger=ledger,
            original_chat=list(original_chat),
            messages=messages,
            source_sha256=digest,
        )
        write_run_metadata(
            run_dir, project_id=project.project_id, status=STATUS_RUNNING, ledger=ledger
        )

        wanted = phases_up_to(self.config.stop_after_phase)
        return await self._sequence(run, wanted)

    # -- sequencing --------------------------------------------------------- #

    async def _sequence(self, run: ProjectRun, wanted: Sequence[str]) -> dict[str, Any]:
        await self._timed(run, PHASE_0A, self._phase_0a)

        if PHASE_0B in wanted:
            await self._timed(run, PHASE_0B, self._phase_0b)
        if PHASE_1A in wanted:
            await self._timed(run, PHASE_1A, self._phase_1a)

        # Barrier: the plan cannot be built from a partial inventory.
        if run.ledger.entries():
            return self._halt(run, blocked_phase="EXTRACTION")
        self._resolve_buckets(run)

        if PHASE_1B in wanted:
            try:
                await self._timed(run, PHASE_1B, self._phase_1b)
            except (PiiValidationError, ApiError) as exc:
                return await self._project_level_failure(run, PHASE_1B, exc)
        if PHASE_2 in wanted:
            try:
                await self._timed(run, PHASE_2, self._phase_2)
            except (PiiValidationError, ApiError) as exc:
                return await self._project_level_failure(run, PHASE_2, exc)

        if run.plan is None:
            return self._halt(run, blocked_phase="PLAN")

        if PHASE_3 in wanted:
            await self._timed(run, PHASE_3, self._phase_3)
        if PHASE_4 in wanted:
            await self._timed(run, PHASE_4, self._phase_4)
        if PHASE_5 in wanted:
            await self._timed(run, PHASE_5, self._phase_5)

        if run.ledger.entries():
            return self._halt(run, blocked_phase="REWRITE_VERIFY")

        if PHASE_6 not in wanted:
            return self._halt(run, blocked_phase="STOPPED_EARLY")
        return self._phase_6(run)

    async def _timed(self, run: ProjectRun, phase: str, handler: Any) -> None:
        started = time.monotonic()
        await handler(run)
        run.timings[phase] = round(time.monotonic() - started, 3)

    # -- phase 0A: local shield --------------------------------------------- #

    async def _phase_0a(self, run: ProjectRun) -> None:
        store = run.store
        input_hash = store.input_hash(
            PHASE_0A,
            params=self.config.params_for(PHASE_0A),
            scope={"source_sha256": run.source_sha256},
        )
        registry, safe_messages = shield_project(
            run.project.project_id,
            run.messages,
            preserve_short_max_words=self.config.preserve_short_max_words,
            short_message_max_words=self.config.short_message_max_words,
        )
        run.secret_registry = registry
        run.safe_messages = safe_messages
        store.commit(
            PHASE_0A,
            "registry",
            input_sha256=input_hash,
            body=registry.to_json(),
        )
        write_json(
            store.phase_dir(PHASE_0A) / "safe_messages.json",
            [item.to_json() for item in safe_messages],
        )
        store.commit_output(
            PHASE_0A,
            body={
                "registry": registry.to_json(),
                "safe": [item.to_json() for item in safe_messages],
            },
            input_sha256=input_hash,
        )
        # Diagnostics may never echo a raw secret or a sender id.
        for value in secret_values(registry, run.messages).values():
            run.ledger.register_sensitive("SECRET", value)
        for value in sender_id_values(run.messages):
            run.ledger.register_sensitive("SENDER_ID", value)
        # Provisional states now, so a failure in 0B/1A can quarantine rather
        # than leave a message with no record at all.  `_resolve_buckets`
        # rewrites them once the preserve-bucket inputs are known.
        for safe in safe_messages:
            run.states[safe.ordinal] = MessageState(
                ordinal=safe.ordinal,
                message_id=safe.message_id,
                bucket=safe.bucket,
                requires_change=safe.bucket not in PRESERVED_BUCKETS,
            )
        print(
            f"[{run.project.project_id}] phase 0A: {len(registry.secrets)} secret(s) "
            f"shielded across {len(safe_messages)} message(s)",
            flush=True,
        )

    # -- phase 0B: PII discovery -------------------------------------------- #

    async def _phase_0b(self, run: ProjectRun) -> None:
        store = run.store
        prompt = self.prompts.text(PHASE_0B)
        upstream = store.upstream_hashes(UPSTREAM[PHASE_0B])
        params = self.config.params_for(PHASE_0B)
        pending: list[SafeMessage] = []
        results: dict[int, tuple[Any, ...]] = {}

        for safe in run.safe_messages:
            scope = {
                "ordinal": safe.ordinal,
                "safe_text_sha256": safe.safe_text_sha256,
                "candidates": canonical_sha256(
                    p0b.required_coverage_spans(safe.safe_text)
                ),
            }
            digest = store.input_hash(
                PHASE_0B,
                prompt_sha256=self.prompts.sha256(PHASE_0B),
                params=params,
                upstream=upstream,
                scope=scope,
                reasoning_effort=self.config.effort_for(PHASE_0B),
            )
            cached = store.load(
                PHASE_0B, f"messages/{safe.ordinal:05d}", digest, p0b.validate_cached_occurrences
            )
            if cached is not None:
                from .models import PiiOccurrence

                results[safe.ordinal] = tuple(
                    PiiOccurrence.from_json(item) for item in cached["body"]["occurrences"]
                )
                continue
            pending.append(safe)

        if pending:
            await self._run_message_phase(
                run,
                phase=PHASE_0B,
                prompt=prompt,
                task=p0b.TASK,
                items=pending,
                sizer=p0b.shard_sizer,
                build_sections=lambda items: p0b.build_sections(items),
                validator_for=lambda items: (
                    lambda payload: p0b.validate_discovery_response(payload, items)
                ),
                parse=p0b.validate_discovery_response,
                repair_instruction=p0b.REPAIR_INSTRUCTION,
                on_result=lambda safe, value: self._commit_0b(
                    run, safe, value, upstream, params, results
                ),
            )

        registry = p0b.merge_entity_registry(results)
        run.entity_registry = registry
        write_json(store.phase_dir(PHASE_0B) / "entities.json", registry.to_json())
        store.commit_output(
            PHASE_0B, body=registry.to_json(), input_sha256=canonical_sha256(sorted(results))
        )
        for entity in registry.entities:
            if entity.policy == "SYNTHESIZE":
                for surface in entity.surface_forms():
                    run.ledger.register_sensitive(entity.entity_type, surface)
        print(
            f"[{run.project.project_id}] phase 0B: {len(registry.entities)} entity/entities, "
            f"{len(registry.bundles)} bundle(s)",
            flush=True,
        )

    def _commit_0b(
        self,
        run: ProjectRun,
        safe: SafeMessage,
        occurrences: Any,
        upstream: Mapping[str, str],
        params: Mapping[str, Any],
        results: dict[int, tuple[Any, ...]],
    ) -> None:
        scope = {
            "ordinal": safe.ordinal,
            "safe_text_sha256": safe.safe_text_sha256,
            "candidates": canonical_sha256(p0b.required_coverage_spans(safe.safe_text)),
        }
        digest = run.store.input_hash(
            PHASE_0B,
            prompt_sha256=self.prompts.sha256(PHASE_0B),
            params=params,
            upstream=upstream,
            scope=scope,
            reasoning_effort=self.config.effort_for(PHASE_0B),
        )
        results[safe.ordinal] = tuple(occurrences)
        run.store.commit(
            PHASE_0B,
            f"messages/{safe.ordinal:05d}",
            input_sha256=digest,
            prompt_sha256=self.prompts.sha256(PHASE_0B),
            body={"occurrences": [item.to_json() for item in occurrences]},
        )

    # -- phase 1A: semantics ------------------------------------------------ #

    async def _phase_1a(self, run: ProjectRun) -> None:
        store = run.store
        prompt = self.prompts.text(PHASE_1A)
        upstream = store.upstream_hashes(UPSTREAM[PHASE_1A])
        params = self.config.params_for(PHASE_1A)
        neighbors = p1a.neighbor_context(
            run.safe_messages, window=self.config.neighbor_window
        )

        def digest_for(safe: SafeMessage) -> str:
            return store.input_hash(
                PHASE_1A,
                prompt_sha256=self.prompts.sha256(PHASE_1A),
                params=params,
                upstream=upstream,
                scope={
                    "ordinal": safe.ordinal,
                    "safe_text_sha256": safe.safe_text_sha256,
                    "neighbors": canonical_sha256(neighbors.get(safe.ordinal, [])),
                },
                reasoning_effort=self.config.effort_for(PHASE_1A),
            )

        pending: list[SafeMessage] = []
        for safe in run.safe_messages:
            cached = store.load(
                PHASE_1A,
                f"messages/{safe.ordinal:05d}",
                digest_for(safe),
                p1a.validate_cached_semantics,
            )
            if cached is not None:
                run.semantics[safe.ordinal] = MessageSemantics.from_json(cached["body"])
                continue
            pending.append(safe)

        if pending:

            def commit(safe: SafeMessage, record: MessageSemantics) -> None:
                run.semantics[safe.ordinal] = record
                store.commit(
                    PHASE_1A,
                    f"messages/{safe.ordinal:05d}",
                    input_sha256=digest_for(safe),
                    prompt_sha256=self.prompts.sha256(PHASE_1A),
                    body=record.to_json(),
                )

            await self._run_message_phase(
                run,
                phase=PHASE_1A,
                prompt=prompt,
                task=p1a.TASK,
                items=pending,
                sizer=p1a.shard_sizer,
                build_sections=lambda items: p1a.build_sections(items, neighbors=neighbors),
                validator_for=lambda items: (
                    lambda payload: p1a.validate_semantics_response(payload, items)
                ),
                parse=p1a.validate_semantics_response,
                repair_instruction=p1a.REPAIR_INSTRUCTION,
                on_result=commit,
            )

        write_json(
            store.phase_dir(PHASE_1A) / "semantics.json",
            [run.semantics[key].to_json() for key in sorted(run.semantics)],
        )
        store.commit_output(
            PHASE_1A,
            body=[run.semantics[key].to_json() for key in sorted(run.semantics)],
            input_sha256=canonical_sha256(sorted(run.semantics)),
        )
        slot_total = sum(len(record.slots) for record in run.semantics.values())
        print(
            f"[{run.project.project_id}] phase 1A: {slot_total} slot occurrence(s) across "
            f"{len(run.semantics)} message(s)",
            flush=True,
        )

    # -- bucket resolution -------------------------------------------------- #

    def _resolve_buckets(self, run: ProjectRun) -> None:
        """Confirm or promote the provisional preserve buckets.

        ``WORD_RE`` counts ``will@example.org`` as two words, so a 1-2 word
        message can be pure PII.  A preserve bucket survives only when phase 0B
        found no synthesized entity, phase 0A left no secret token, and phase 1A
        bound no slot.
        """

        registry = run.entity_registry
        promoted = 0
        resolved: list[SafeMessage] = []
        for safe in run.safe_messages:
            has_entity = bool(
                registry
                and any(
                    entity.policy == "SYNTHESIZE"
                    for entity in registry.for_ordinal(safe.ordinal)
                )
            )
            semantics = run.semantics.get(safe.ordinal)
            bucket = resolve_bucket(
                safe.bucket,
                has_synthesized_entity=has_entity,
                has_secret_token=bool(safe.secret_tokens),
                has_semantic_slot=bool(semantics and semantics.slots),
            )
            if bucket != safe.bucket:
                promoted += 1
                safe = safe.with_bucket(bucket)
            resolved.append(safe)
        run.safe_messages = resolved
        # Persisted because `finalize` reloads phase 0A's *provisional* buckets;
        # without this the offline path would apply the wrong bucket policy to a
        # message that was promoted out of the verbatim bucket.
        write_json(
            run.run_dir / "resolved_buckets.json",
            {str(item.ordinal): item.bucket for item in resolved},
        )
        for safe in resolved:
            run.states[safe.ordinal] = MessageState(
                ordinal=safe.ordinal,
                message_id=safe.message_id,
                bucket=safe.bucket,
                requires_change=safe.bucket not in PRESERVED_BUCKETS,
            )
        if promoted:
            print(
                f"[{run.project.project_id}] promoted {promoted} short message(s) out of "
                "the verbatim bucket because they carry PII, a secret or a slot",
                flush=True,
            )

    # -- phase 1B: consolidation -------------------------------------------- #

    async def _phase_1b(self, run: ProjectRun) -> None:
        store = run.store
        prompt = self.prompts.text(PHASE_1B)
        upstream = store.upstream_hashes(UPSTREAM[PHASE_1B])
        params = self.config.params_for(PHASE_1B)
        records = [run.semantics[key] for key in sorted(run.semantics)]
        folds = p1b.build_folds(
            records,
            max_chars=self.config.semantic_fold_chars,
            max_records=self.config.semantic_fold_records,
        )
        accumulator: SemanticRegistry | None = None
        previous_hash = ""

        for fold in folds:
            scope = {
                "index": fold.index,
                "previous": previous_hash,
                "records": canonical_sha256([item.to_json() for item in fold.records]),
            }
            digest = store.input_hash(
                PHASE_1B,
                prompt_sha256=self.prompts.sha256(PHASE_1B),
                params=params,
                upstream=upstream,
                scope=scope,
                reasoning_effort=self.config.effort_for(PHASE_1B),
            )
            cached = store.load(PHASE_1B, f"folds/{fold.fold_id}", digest)
            if cached is not None:
                accumulator = SemanticRegistry.from_json(cached["body"])
                previous_hash = canonical_sha256(accumulator.to_json())
                continue

            sections = p1b.build_sections(fold, accumulator)
            captured = accumulator

            def validator(payload: dict[str, Any], _fold=fold, _acc=captured) -> None:
                p1b.validate_fold_response(
                    payload,
                    _fold,
                    _acc,
                    max_accumulator_chars=self.config.max_accumulator_chars,
                )

            accumulator = await run_single_call(
                self.api,
                phase=PHASE_1B,
                project_id=run.project.project_id,
                target=fold.fold_id,
                prompt=prompt,
                sections=sections,
                task=p1b.TASK,
                validator=validator,
                parse=lambda payload, _fold=fold, _acc=captured: p1b.validate_fold_response(
                    payload,
                    _fold,
                    _acc,
                    max_accumulator_chars=self.config.max_accumulator_chars,
                ),
                repair_instruction=p1b.REPAIR_INSTRUCTION,
            )
            previous_hash = canonical_sha256(accumulator.to_json())
            store.commit(
                PHASE_1B,
                f"folds/{fold.fold_id}",
                input_sha256=digest,
                prompt_sha256=self.prompts.sha256(PHASE_1B),
                body=accumulator.to_json(),
            )

        registry = accumulator or SemanticRegistry(slots=(), relations=(), decisions=())
        p1b.validate_semantic_registry(registry, records)
        run.semantic_registry = registry
        write_json(store.phase_dir(PHASE_1B) / "registry.json", registry.to_json())
        store.commit_output(
            PHASE_1B, body=registry.to_json(), input_sha256=previous_hash or "seed"
        )
        print(
            f"[{run.project.project_id}] phase 1B: {len(registry.slots)} slot(s), "
            f"{len(registry.relations)} relation(s) over {len(folds)} fold(s)",
            flush=True,
        )

    # -- phase 2: plan ------------------------------------------------------ #

    async def _phase_2(self, run: ProjectRun) -> None:
        store = run.store
        prompt = self.prompts.text(PHASE_2)
        upstream = store.upstream_hashes(UPSTREAM[PHASE_2])
        params = self.config.params_for(PHASE_2)
        entities = run.entity_registry
        semantics = run.semantic_registry
        if entities is None or semantics is None or run.secret_registry is None:
            raise PiiError("phase 2 requires phases 0A, 0B and 1B to have completed")

        entity_parts: dict[str, Any] = {}
        for chunk in p2.bundle_chunks(
            entities,
            max_bundles=self.config.plan_chunk_bundles,
            max_chars=self.config.plan_chunk_chars,
        ):
            reserved = p2.reserved_values(entity_parts)
            scope = {
                "index": chunk.index,
                "entities": list(chunk.entity_ids),
                "reserved": canonical_sha256(reserved),
            }
            digest = store.input_hash(
                PHASE_2,
                prompt_sha256=self.prompts.sha256(PHASE_2),
                params=params,
                upstream=upstream,
                scope=scope,
                reasoning_effort=self.config.effort_for(PHASE_2),
            )
            cached = store.load(PHASE_2, f"entities/{chunk.chunk_id}", digest)
            if cached is not None:
                from .models import EntityReplacement

                entity_parts.update(
                    {
                        key: EntityReplacement.from_json(value)
                        for key, value in cached["body"].items()
                    }
                )
                continue
            part = await run_single_call(
                self.api,
                phase=PHASE_2,
                project_id=run.project.project_id,
                target=f"entities_{chunk.chunk_id}",
                prompt=prompt,
                sections=p2.build_entity_sections(chunk, entities, reserved),
                task=p2.TASK_ENTITIES,
                validator=lambda payload, _c=chunk, _r=reserved: p2.validate_entity_chunk(
                    payload, _c, entities, _r
                ),
                parse=lambda payload, _c=chunk, _r=reserved: p2.validate_entity_chunk(
                    payload, _c, entities, _r
                ),
                repair_instruction=p2.REPAIR_INSTRUCTION_ENTITIES,
            )
            entity_parts.update(part)
            store.commit(
                PHASE_2,
                f"entities/{chunk.chunk_id}",
                input_sha256=digest,
                prompt_sha256=self.prompts.sha256(PHASE_2),
                body={key: value.to_json() for key, value in part.items()},
            )

        slot_parts: dict[str, Any] = {}
        for cluster in p2.slot_clusters(semantics, max_chars=self.config.plan_chunk_chars):
            scope = {"index": cluster.index, "slots": list(cluster.slot_ids)}
            digest = store.input_hash(
                PHASE_2,
                prompt_sha256=self.prompts.sha256(PHASE_2),
                params=params,
                upstream=upstream,
                scope=scope,
                reasoning_effort=self.config.effort_for(PHASE_2),
            )
            cached = store.load(PHASE_2, f"slots/{cluster.cluster_id}", digest)
            if cached is not None:
                from .models import SlotReplacement

                slot_parts.update(
                    {
                        key: SlotReplacement.from_json(value)
                        for key, value in cached["body"].items()
                    }
                )
                continue
            part = await run_single_call(
                self.api,
                phase=PHASE_2,
                project_id=run.project.project_id,
                target=f"slots_{cluster.cluster_id}",
                prompt=prompt,
                sections=p2.build_slot_sections(cluster, semantics),
                task=p2.TASK_SLOTS,
                validator=lambda payload, _c=cluster: p2.validate_slot_cluster(
                    payload, _c, semantics
                ),
                parse=lambda payload, _c=cluster: p2.validate_slot_cluster(
                    payload, _c, semantics
                ),
                repair_instruction=p2.REPAIR_INSTRUCTION_SLOTS,
            )
            slot_parts.update(part)
            store.commit(
                PHASE_2,
                f"slots/{cluster.cluster_id}",
                input_sha256=digest,
                prompt_sha256=self.prompts.sha256(PHASE_2),
                body={key: value.to_json() for key, value in part.items()},
            )

        plan = p2.assemble_plan(entity_parts, slot_parts, run.secret_registry, semantics)
        p2.validate_plan(
            plan,
            entity_registry=entities,
            semantic_registry=semantics,
            secret_registry=run.secret_registry,
        )
        run.plan = plan
        write_json(store.phase_dir(PHASE_2) / "plan.json", plan.to_json())

        for safe in run.safe_messages:
            slice_ = p2.plan_slice(
                plan,
                safe,
                entity_registry=entities,
                semantic_registry=semantics,
                semantics=run.semantics.get(safe.ordinal),
                preserve_terms=self.config.preserve_terms,
            )
            run.slices[safe.ordinal] = slice_
            write_json(
                store.phase_dir(PHASE_2) / f"slices/{safe.ordinal:05d}.json", slice_.to_json()
            )
        store.commit_output(
            PHASE_2,
            body=plan.to_json(),
            input_sha256=canonical_sha256(
                {"entities": sorted(entity_parts), "slots": sorted(slot_parts)}
            ),
        )
        print(
            f"[{run.project.project_id}] phase 2: {len(plan.entity_replacements)} entity "
            f"decision(s), {len(plan.slot_replacements)} slot decision(s)",
            flush=True,
        )

    # -- phase 3: rewrite --------------------------------------------------- #

    async def _phase_3(self, run: ProjectRun) -> None:
        store = run.store
        upstream = store.upstream_hashes(UPSTREAM[PHASE_3])
        params = self.config.params_for(PHASE_3)

        def digest_for(safe: SafeMessage) -> str:
            slice_ = run.slices[safe.ordinal]
            return store.input_hash(
                PHASE_3,
                prompt_sha256=self.prompts.sha256(rewrite_prompt_key(safe.bucket)),
                params=params,
                upstream=upstream,
                scope={
                    "ordinal": safe.ordinal,
                    "bucket": safe.bucket,
                    "safe_text_sha256": safe.safe_text_sha256,
                    "plan_slice_sha256": canonical_sha256(slice_.to_json()),
                },
                reasoning_effort=self.config.effort_for(PHASE_3),
            )

        by_bucket = p3.partition_by_bucket(run.safe_messages)
        for bucket, items in sorted(by_bucket.items()):
            if bucket in PRESERVED_BUCKETS:
                for safe in items:
                    record = p3.preserved_record(safe)
                    run.rewrites[safe.ordinal] = record
                    run.states[safe.ordinal].mark_done(
                        record.text,
                        provenance=PROVENANCE_PRESERVED,
                        text_sha256=record.text_sha256,
                        verified=True,
                    )
                continue

            pending: list[SafeMessage] = []
            for safe in items:
                if run.ledger.is_blocked(safe.message_id):
                    continue
                cached = store.load(
                    PHASE_3,
                    f"messages/{safe.ordinal:05d}",
                    digest_for(safe),
                    lambda body, _s=safe: p3.validate_cached_rewrite(
                        body, _s, run.slices[_s.ordinal]
                    ),
                )
                if cached is not None:
                    record = RewriteRecord.from_json(cached["body"])
                    run.rewrites[safe.ordinal] = record
                    run.states[safe.ordinal].mark_done(
                        record.text,
                        provenance=PROVENANCE_LLM_REWRITE,
                        text_sha256=record.text_sha256,
                        verified=False,
                    )
                    continue
                pending.append(safe)

            if not pending:
                continue

            def commit(safe: SafeMessage, record: RewriteRecord) -> None:
                run.rewrites[safe.ordinal] = record
                run.states[safe.ordinal].mark_done(
                    record.text,
                    provenance=PROVENANCE_LLM_REWRITE,
                    text_sha256=record.text_sha256,
                    verified=False,
                )
                store.commit(
                    PHASE_3,
                    f"messages/{safe.ordinal:05d}",
                    input_sha256=digest_for(safe),
                    prompt_sha256=self.prompts.sha256(rewrite_prompt_key(safe.bucket)),
                    prompt_variant=rewrite_prompt_key(safe.bucket),
                    body=record.to_json(),
                )

            await self._run_message_phase(
                run,
                phase=PHASE_3,
                prompt=self.prompts.text(rewrite_prompt_key(bucket)),
                task=p3.task_for(bucket),
                items=pending,
                sizer=p3.shard_sizer,
                build_sections=lambda items, _b=bucket: p3.build_sections(
                    items, run.slices, bucket=_b
                ),
                validator_for=lambda items: (
                    lambda payload: p3.validate_rewrite_response(payload, items, run.slices)
                ),
                parse=lambda payload, items: p3.validate_rewrite_response(
                    payload, items, run.slices
                ),
                repair_instruction=p3.repair_instruction_for(bucket),
                on_result=commit,
                max_concurrent_shards=2 if bucket != BUCKET_LONG else 1,
            )

        store.commit_output(
            PHASE_3,
            body=[run.rewrites[key].to_json() for key in sorted(run.rewrites)],
            input_sha256=canonical_sha256(sorted(run.rewrites)),
        )

    # -- phase 4: verification ---------------------------------------------- #

    async def _phase_4(self, run: ProjectRun) -> None:
        store = run.store
        upstream = store.upstream_hashes(UPSTREAM[PHASE_4])
        params = self.config.params_for(PHASE_4)
        prompt = self.prompts.text(PHASE_4)

        def digest_for(safe: SafeMessage) -> str:
            slice_ = run.slices[safe.ordinal]
            return store.input_hash(
                PHASE_4,
                prompt_sha256=self.prompts.sha256(PHASE_4),
                params=params,
                upstream=upstream,
                scope={
                    "ordinal": safe.ordinal,
                    "safe_text_sha256": safe.safe_text_sha256,
                    "plan_slice_sha256": canonical_sha256(slice_.to_json()),
                    "rewrite_text_sha256": run.rewrites[safe.ordinal].text_sha256,
                },
                reasoning_effort=self.config.effort_for(PHASE_4),
            )

        candidates = [
            safe
            for safe in run.safe_messages
            if safe.bucket not in PRESERVED_BUCKETS
            and safe.ordinal in run.rewrites
            and not run.ledger.is_blocked(safe.message_id)
        ]
        pending: list[SafeMessage] = []
        for safe in candidates:
            cached = store.load(
                PHASE_4,
                f"messages/{safe.ordinal:05d}",
                digest_for(safe),
                lambda body, _s=safe: p4.validate_cached_verdict(
                    body, _s, run.rewrites[_s.ordinal], run.slices[_s.ordinal]
                ),
            )
            if cached is not None:
                run.verdicts[safe.ordinal] = VerdictRecord.from_json(cached["body"])
                continue
            pending.append(safe)

        if pending:

            def commit(safe: SafeMessage, verdict: VerdictRecord) -> None:
                checked = p4.cross_check_verdict(
                    verdict, safe, run.rewrites[safe.ordinal], run.slices[safe.ordinal]
                )
                run.verdicts[safe.ordinal] = checked
                store.commit(
                    PHASE_4,
                    f"messages/{safe.ordinal:05d}",
                    input_sha256=digest_for(safe),
                    prompt_sha256=self.prompts.sha256(PHASE_4),
                    body=checked.to_json(),
                )

            await self._run_message_phase(
                run,
                phase=PHASE_4,
                prompt=prompt,
                task=p4.TASK,
                items=pending,
                sizer=p4.shard_sizer,
                build_sections=lambda items: p4.build_sections(
                    items, run.slices, run.rewrites
                ),
                validator_for=lambda items: (
                    lambda payload: p4.validate_verdict_response(payload, items)
                ),
                parse=p4.validate_verdict_response,
                repair_instruction=p4.REPAIR_INSTRUCTION,
                on_result=commit,
                max_concurrent_shards=2,
            )

        for ordinal, verdict in run.verdicts.items():
            state = run.states.get(ordinal)
            if state is not None and verdict.status == p4.STATUS_PASS:
                state.verified = True

        failed = [
            ordinal
            for ordinal, verdict in sorted(run.verdicts.items())
            if verdict.status == p4.STATUS_FAIL
        ]
        store.commit_output(
            PHASE_4,
            body=[run.verdicts[key].to_json() for key in sorted(run.verdicts)],
            input_sha256=canonical_sha256(sorted(run.verdicts)),
        )
        print(
            f"[{run.project.project_id}] phase 4: {len(run.verdicts) - len(failed)} pass, "
            f"{len(failed)} fail",
            flush=True,
        )

    # -- phase 5: repair ---------------------------------------------------- #

    async def _phase_5(self, run: ProjectRun) -> None:
        store = run.store
        upstream = store.upstream_hashes(UPSTREAM[PHASE_5])
        params = self.config.params_for(PHASE_5)
        prompt = self.prompts.text(PHASE_5)
        safe_by_ordinal = run.safe_by_ordinal()

        targets = [
            ordinal
            for ordinal, verdict in sorted(run.verdicts.items())
            if verdict.status == p4.STATUS_FAIL
        ]
        for ordinal in targets:
            safe = safe_by_ordinal[ordinal]
            slice_ = run.slices[ordinal]
            verdict = run.verdicts[ordinal]
            rewrite = run.rewrites[ordinal]
            repaired = False

            for attempt in range(1, self.config.max_repair_attempts + 1):
                digest = store.input_hash(
                    PHASE_5,
                    prompt_sha256=self.prompts.sha256(PHASE_5),
                    params=params,
                    upstream=upstream,
                    scope={
                        "ordinal": ordinal,
                        "attempt": attempt,
                        "verdict": canonical_sha256(verdict.to_json()),
                        "rewrite_text_sha256": rewrite.text_sha256,
                    },
                    reasoning_effort=self.config.effort_for(PHASE_5),
                )
                shard = f"messages/{ordinal:05d}.attempt{attempt:02d}"
                cached = store.load(PHASE_5, shard, digest)
                if cached is not None:
                    candidate = RewriteRecord.from_json(cached["body"])
                else:
                    try:
                        candidate = await run_single_call(
                            self.api,
                            phase=PHASE_5,
                            project_id=run.project.project_id,
                            target=f"repair_{ordinal:05d}_a{attempt}",
                            prompt=prompt,
                            sections=p5.build_sections(
                                safe, slice_, rewrite, verdict, attempt=attempt
                            ),
                            task=p5.TASK,
                            validator=lambda payload, _a=attempt: p5.validate_repair_response(
                                payload, safe, slice_, verdict, rewrite, attempt=_a
                            ),
                            parse=lambda payload, _a=attempt: p5.validate_repair_response(
                                payload, safe, slice_, verdict, rewrite, attempt=_a
                            ),
                            repair_instruction=p5.repair_prompt_instruction(
                                safe.bucket, verdict, attempt
                            ),
                            attempts=1,
                        )
                    except ApiError as exc:
                        transport = not api_error_is_validation_failure(exc)
                        run.record_attempt(
                            ordinal,
                            p5.attempt_summary(
                                attempt, PHASE_5, "TRANSPORT" if transport else "REJECTED",
                                error=exc,
                            ),
                        )
                        if transport:
                            await run.ledger.record(
                                phase=PHASE_5,
                                code="TRANSPORT_EXHAUSTED",
                                failure_class=CLASS_TRANSPORT,
                                message_id=safe.message_id,
                                ordinal=ordinal,
                                attempts=attempt,
                                error=exc,
                            )
                            repaired = True  # not repaired, but do not double-record
                            break
                        continue
                    store.commit(
                        PHASE_5,
                        shard,
                        input_sha256=digest,
                        prompt_sha256=self.prompts.sha256(PHASE_5),
                        body=candidate.to_json(),
                        attempt=attempt,
                    )

                # Re-verify: a repair is not accepted on its own word.
                recheck = p4.cross_check_verdict(
                    VerdictRecord(
                        ordinal=ordinal,
                        message_id=safe.message_id,
                        status=p4.STATUS_PASS,
                        checks={key: p4.STATUS_PASS for key in p4.CHECK_DIMENSIONS},
                        findings=(),
                        verified_against={},
                    ),
                    safe,
                    candidate,
                    slice_,
                )
                run.record_attempt(
                    ordinal,
                    p5.attempt_summary(
                        attempt,
                        PHASE_5,
                        "ACCEPTED" if recheck.status == p4.STATUS_PASS else "REJECTED",
                        findings=[item.to_json() for item in recheck.findings],
                        candidate_sha256=candidate.text_sha256,
                    ),
                )
                if recheck.status == p4.STATUS_PASS:
                    run.rewrites[ordinal] = candidate
                    run.verdicts[ordinal] = recheck
                    run.states[ordinal].mark_done(
                        candidate.text,
                        provenance=PROVENANCE_LLM_REPAIR,
                        text_sha256=candidate.text_sha256,
                        verified=True,
                    )
                    repaired = True
                    break
                rewrite = candidate
                verdict = recheck

            if not repaired:
                run.states[ordinal].quarantine()
                await run.ledger.record(
                    phase=PHASE_5,
                    code="REPAIR_EXHAUSTED",
                    failure_class=CLASS_REPAIR_EXHAUSTED,
                    message_id=safe.message_id,
                    ordinal=ordinal,
                    attempts=self.config.max_repair_attempts,
                    findings=[item.to_json() for item in verdict.findings],
                    diagnostics={
                        "bucket": safe.bucket,
                        "word_count": safe.word_count,
                        "plan_slice_sha256": canonical_sha256(slice_.to_json()),
                    },
                )

        # Messages that failed verification but were never repaired (no attempts
        # configured) must still be quarantined rather than shipped.
        for ordinal, verdict in sorted(run.verdicts.items()):
            if verdict.status != p4.STATUS_FAIL:
                continue
            state = run.states.get(ordinal)
            if state is None or run.ledger.is_blocked(state.message_id):
                continue
            state.quarantine()
            await run.ledger.record(
                phase=PHASE_4,
                code="VERIFY_FAILED",
                failure_class=CLASS_VERIFIER_FAIL,
                message_id=state.message_id,
                ordinal=ordinal,
                attempts=0,
                findings=[item.to_json() for item in verdict.findings],
            )

        store.commit_output(
            PHASE_5,
            body=[run.rewrites[key].to_json() for key in sorted(run.rewrites)],
            input_sha256=canonical_sha256(sorted(run.rewrites)),
        )

    # -- phase 6: render, audit, commit ------------------------------------- #

    def _phase_6(self, run: ProjectRun) -> dict[str, Any]:
        if run.secret_registry is None or run.plan is None:
            raise PiiError("phase 6 requires phases 0A and 2 to have completed")
        entities = run.entity_registry or PiiEntityRegistry(entities=(), bundles=())
        semantics = run.semantic_registry or SemanticRegistry(
            slots=(), relations=(), decisions=()
        )

        final_texts = render_final_texts(run.states, run.secret_registry)
        cleaned_chat = build_cleaned_chat(run.original_chat, final_texts)
        inputs = AuditInputs(
            project_id=run.project.project_id,
            original_chat=run.original_chat,
            messages=run.messages,
            safe_messages=run.safe_messages,
            states=run.states,
            secret_registry=run.secret_registry,
            entity_registry=entities,
            semantic_registry=semantics,
            plan=run.plan,
            preserve_terms=self.config.preserve_terms,
            extra_private_terms=self.config.extra_private_terms,
            sender_ids=sender_id_values(run.messages),
            verified_text_hashes=frozenset(
                (ordinal, state.text_sha256 or "")
                for ordinal, state in run.states.items()
                if state.verified
            ),
            unresolved_message_ids=tuple(run.ledger.blocked_message_ids()),
        )
        report = audit_final_texts(inputs, final_texts, cleaned_chat)
        write_json(
            run.store.phase_dir(PHASE_6) / "audit_report.json", report.to_json()
        )
        write_json(run.store.phase_dir(PHASE_6) / "final_texts.json", final_texts)
        report.raise_if_failed()

        project_output = self.config.output_root / run.project.project_id
        copy_project_except_chat(run.project, project_output)
        write_chat(project_output / "chat_messages.json", cleaned_chat)
        manifest = self._manifest(run, report, final_texts)
        write_json(
            self.config.output_root / "_manifests" / f"{run.project.project_id}.json",
            manifest,
        )
        write_run_metadata(
            run.run_dir,
            project_id=run.project.project_id,
            status=STATUS_PASSED,
            ledger=run.ledger,
            phase_timings=run.timings,
            extra={"audit": report.counts_by_check()},
        )
        if not self.config.keep_run_artifacts:
            self._prune_run_dir(run)
        print(
            f"[{run.project.project_id}] DONE: {len(final_texts)} message(s) committed",
            flush=True,
        )
        return manifest

    def _manifest(
        self, run: ProjectRun, report: Any, final_texts: Mapping[int, str]
    ) -> dict[str, Any]:
        assert run.plan is not None and run.secret_registry is not None
        buckets: dict[str, int] = {}
        for state in run.states.values():
            buckets[state.bucket] = buckets.get(state.bucket, 0) + 1
        provenance: dict[str, int] = {}
        for state in run.states.values():
            key = state.provenance or "NONE"
            provenance[key] = provenance.get(key, 0) + 1
        return {
            "status": "DONE",
            "project_id": run.project.project_id,
            "engine_version": ENGINE_VERSION,
            "source_sha256": run.source_sha256,
            "model": self.config.model,
            "reasoning_effort": self.config.reasoning_effort,
            "phase_reasoning_effort": {
                phase: self.config.effort_for(phase) for phase in UPSTREAM
            },
            "prompts": self.prompts.manifest_entries(),
            "counts": {
                "messages": len(run.messages),
                "secrets_shielded": len(run.secret_registry.secrets),
                "entities_discovered": len(
                    run.entity_registry.entities if run.entity_registry else ()
                ),
                "identity_bundles": len(
                    run.entity_registry.bundles if run.entity_registry else ()
                ),
                "semantic_slots": len(
                    run.semantic_registry.slots if run.semantic_registry else ()
                ),
                "entity_replacements": len(run.plan.entity_replacements),
                "slot_replacements": len(run.plan.slot_replacements),
                "buckets": dict(sorted(buckets.items())),
                "provenance": dict(sorted(provenance.items())),
            },
            "plan_sha256": canonical_sha256(run.plan.to_json()),
            "plan_amendments": [dict(item) for item in run.plan.amendments],
            "audit": report.counts_by_check(),
            "phase_timings_seconds": dict(sorted(run.timings.items())),
            "output_sha256": {"chat_messages": canonical_sha256(final_texts)},
        }

    def _prune_run_dir(self, run: ProjectRun) -> None:
        """Delete the PII-bearing artifacts, keep the fingerprint-only trail.

        The phase-2 plan and the agent tasks juxtapose original values with their
        synthetic replacements -- a complete re-identification key for the
        released dataset, and the most sensitive artifact the pipeline produces.
        """

        from .agent_handoff import repairs_dir, tasks_dir

        removed = run.store.discard_phases(
            {PHASE_0A, PHASE_0B, PHASE_1A, PHASE_1B, PHASE_2, PHASE_3, PHASE_5}
        )
        for directory in (tasks_dir(run.run_dir), repairs_dir(run.run_dir)):
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
        final_texts = run.store.phase_dir(PHASE_6) / "final_texts.json"
        if final_texts.is_file():
            final_texts.unlink()
            removed.append(final_texts)
        print(
            f"[{run.project.project_id}] pruned {len(removed)} PII-bearing run artifact(s); "
            "run_metadata, unresolved summary and audit report retained",
            flush=True,
        )

    # -- shared message-phase driver ---------------------------------------- #

    async def _run_message_phase(
        self,
        run: ProjectRun,
        *,
        phase: str,
        prompt: str,
        task: str,
        items: Sequence[SafeMessage],
        sizer: Any,
        build_sections: Any,
        validator_for: Any,
        parse: Any,
        repair_instruction: str,
        on_result: Any,
        max_concurrent_shards: int = 1,
    ) -> None:
        shards = build_shards(
            items,
            max_items=self.config.max_batch_messages,
            max_chars=self.config.max_batch_chars,
            sizer=sizer,
        )

        async def success(item: SafeMessage, value: Any) -> None:
            on_result(item, value)

        async def failure(item: SafeMessage, error: BaseException, transport: bool) -> None:
            state = run.states.get(item.ordinal)
            if state is not None:
                state.quarantine()
            codes = tuple(getattr(error, "failures", ()) or ())
            await run.ledger.record(
                phase=phase,
                code="TRANSPORT_EXHAUSTED" if transport else (codes[0] if codes else "REJECTED"),
                failure_class=CLASS_TRANSPORT if transport else CLASS_LOCAL_VALIDATOR,
                message_id=item.message_id,
                ordinal=item.ordinal,
                attempts=1,
                error=error,
                diagnostics={"bucket": item.bucket, "word_count": item.word_count},
            )
            run.record_attempt(
                item.ordinal,
                p5.attempt_summary(
                    1, phase, "TRANSPORT" if transport else "REJECTED", error=error
                ),
            )

        await run_sharded_phase(
            self.api,
            phase=phase,
            project_id=run.project.project_id,
            prompt=prompt,
            task=task,
            shards=shards,
            build_sections=build_sections,
            validator_for=validator_for,
            parse=parse,
            repair_instruction=repair_instruction,
            on_success=success,
            on_failure=failure,
            max_concurrent_shards=max_concurrent_shards,
            progress=lambda message: print(f"[{run.project.project_id}] {message}", flush=True),
        )

    # -- halting ------------------------------------------------------------ #

    async def _project_level_failure(
        self, run: ProjectRun, phase: str, error: BaseException
    ) -> dict[str, Any]:
        """1B/2 build one artifact; no hand-written text can fix a bad one."""

        transport = isinstance(error, ApiError) and not api_error_is_validation_failure(error)
        await run.ledger.record(
            phase=phase,
            code="TRANSPORT_EXHAUSTED" if transport else "PROJECT_ARTIFACT_INVALID",
            failure_class=CLASS_TRANSPORT if transport else CLASS_PLAN_CONFLICT,
            message_id=None,
            ordinal=None,
            attempts=1,
            error=error,
        )
        return self._halt(run, blocked_phase="PLAN")

    def _halt(self, run: ProjectRun, *, blocked_phase: str) -> dict[str, Any]:
        """Stop without committing, and leave the agent everything it needs."""

        status = run.ledger.status()
        tasks: list[dict[str, Any]] = []
        safe_by_ordinal = run.safe_by_ordinal()
        for entry in run.ledger.agent_actionable():
            safe = safe_by_ordinal.get(entry.ordinal or -1)
            if safe is None:
                continue
            tasks.append(
                build_task(
                    run.project.project_id,
                    entry,
                    TaskContext(
                        safe=safe,
                        slice_=run.slices.get(safe.ordinal),
                        last_candidate=run.rewrites.get(safe.ordinal),
                        verdict=run.verdicts.get(safe.ordinal),
                        attempt_history=tuple(run.attempts.get(safe.ordinal, ())),
                        neighbors=tuple(
                            p1a.neighbor_context(
                                run.safe_messages, window=self.config.neighbor_window
                            ).get(safe.ordinal, ())
                        ),
                        local_validator_errors=tuple(
                            str(item.get("violation") or item.get("code") or "")
                            for item in entry.findings
                        ),
                    ),
                    preserve_terms=self.config.preserve_terms,
                )
            )
        if tasks:
            write_task_package(
                run.run_dir,
                project_id=run.project.project_id,
                engine_version=ENGINE_VERSION,
                source_sha256=run.source_sha256,
                plan_sha256=(
                    canonical_sha256(run.plan.to_json()) if run.plan is not None else None
                ),
                blocked_phase=blocked_phase,
                tasks=tasks,
                protected_tokens=(
                    run.secret_registry.tokens() if run.secret_registry else ()
                ),
                preserve_terms=self.config.preserve_terms,
                instructions_path=self.prompts.agent_instructions_path,
                instructions_sha256=self.prompts.agent_instructions_sha256,
                instructions_text=self.prompts.agent_instructions,
            )
        write_run_metadata(
            run.run_dir,
            project_id=run.project.project_id,
            status=status,
            ledger=run.ledger,
            phase_timings=run.timings,
            extra={"blocked_phase": blocked_phase, "agent_tasks": len(tasks)},
        )
        summary = run.ledger.summary()
        print(
            f"[{run.project.project_id}] {status} at {blocked_phase}: "
            f"{summary['unresolved']} unresolved, {len(tasks)} agent task(s) written",
            flush=True,
        )
        return {
            "project_id": run.project.project_id,
            "status": status,
            "blocked_phase": blocked_phase,
            "unresolved": summary,
            "agent_tasks": len(tasks),
        }
