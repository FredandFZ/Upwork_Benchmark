"""Phase 2 tests: chunking, fail-closed plan validation, and slice closure.

The closure property test is the important one.  Per-message rewrite
checkpointing is only sound if a message's plan slice covers *every* decision
that could change its correct rewrite.  If the closure is too narrow, a stale
rewrite restores as valid and the contradiction surfaces only in the final
project-wide audit with no trail back to its cause -- so the property is
asserted in both directions.
"""

from __future__ import annotations

import unittest

from Code.PII.phase0b_entities import _is_identifying, _is_identifying_occurrence
from Code.PII.textutil import EMAIL_RE, normalized_surface
from Code.pii_prepare_offline_text_repairs import _apply_slots, _entity_slot_conflicts
from Code.pii_apply_preserved_slot_repair import (
    _entity_authoritative_value,
    _restore_missing_preserved_terms,
    _synthetic_slot_value,
    _without_real_values,
    entity_occurrence_substitutions,
    entity_substitutions,
)
from Code.PII.phase3_rewrite import rewrite_violations, split_violations
from Code.PII.prompts import mode_hashes, phase2_prompt_key
from dataclasses import replace

from Code.PII.config import BUCKET_LONG
from Code.PII.errors import PlanConsistencyError
from Code.PII.models import (
    EntityAlias,
    MessagePlanSlice,
    EntityReplacement,
    IdentityBundle,
    MessageSemantics,
    PiiEntity,
    PiiEntityRegistry,
    PiiOccurrence,
    SafeMessage,
    SecretRegistry,
    SemanticRegistry,
    SemanticSlot,
    SlotHistoryEntry,
    SlotLiteralOccurrence,
    SlotLiteralReplacement,
    SlotRelation,
    SlotReplacement,
    TransformationPlan,
)
from Code.PII.phase2_plan import (
    PlanChunk,
    SlotCluster,
    _is_only_preserved,
    assemble_plan,
    preserved_surface_forms,
    bundle_chunks,
    semantic_preserve_terms,
    plan_slice,
    reserved_values,
    slot_clusters,
    validate_entity_chunk,
    _masking_failure,
    _pads_original,
    _preserved_terms_in,
    validate_plan,
    validate_slot_cluster,
)
from Code.PII.textutil import canonical_sha256
from Code.PII.textutil import private_resource_identifiers, semantic_anchor_differences

# A fabricated credential-shaped value, assembled from two adjacent literals
# so the contiguous ``sk_live_`` form never appears in the source.  Vendor
# secret scanners (GitHub push protection among them) match the shape alone
# and block a push on this fixture even though the value is invented.  The
# shield keys off the prefix, so the split is behaviourally inert.
CREDENTIAL_SHAPED_VALUE = "sk_" "live_51H8xYzAbCdEfGhIjKlMnOpQr"


def occurrence(ordinal: int, source: str, entity_type: str) -> PiiOccurrence:
    return PiiOccurrence(
        ordinal=ordinal,
        message_id=ordinal,
        source=source,
        start=0,
        end=len(source),
        entity_type=entity_type,
        policy="SYNTHESIZE",
        normalized_value=source,
        link_hint=None,
        confidence="HIGH",
    )


def entity(
    entity_id: str, entity_type: str, value: str, bundle_id: str | None, ordinals: tuple[int, ...]
) -> PiiEntity:
    return PiiEntity(
        entity_id=entity_id,
        entity_type=entity_type,
        policy="SYNTHESIZE",
        canonical_value=value,
        normalized_key=value.casefold(),
        bundle_id=bundle_id,
        confidence="HIGH",
        occurrences=tuple(occurrence(item, value, entity_type) for item in ordinals),
    )


def build_entity_registry() -> PiiEntityRegistry:
    """Two independent identities, each spanning different messages."""

    return PiiEntityRegistry(
        entities=(
            entity("E0001", "PERSON", "Joseph", "B0001", (1,)),
            entity("E0002", "EMAIL", "scott@northstar.io", "B0001", (2,)),
            entity("E0003", "PRIVATE_DOMAIN", "northstar.io", "B0001", (3,)),
            entity("E0004", "PERSON", "Dusko", "B0002", (4,)),
            entity("E0005", "EMAIL", "dusko@vucko.dev", "B0002", (5,)),
        ),
        bundles=(
            IdentityBundle("B0001", "PERSON_IDENTITY", ("E0001", "E0002", "E0003")),
            IdentityBundle("B0002", "PERSON_IDENTITY", ("E0004", "E0005")),
        ),
    )


def slot(slot_id: str, value: str, ordinals: tuple[int, ...]) -> SemanticSlot:
    return SemanticSlot(
        slot_id=slot_id,
        kind="BUSINESS",
        value_type="COUNT",
        unit=None,
        current_value=value,
        meaning=f"meaning of {slot_id}",
        history=(SlotHistoryEntry(ordinal=ordinals[0], op="INTRODUCE", old_value=None, new_value=value),),
        source_literals=(value,),
        message_ordinals=ordinals,
        literal_occurrences=(
            SlotLiteralOccurrence(
                ordinal=ordinals[0],
                message_id=ordinals[0],
                start=0,
                end=len(value),
                source_literal=value,
            ),
        ),
    )


def build_semantic_registry() -> SemanticRegistry:
    """One arithmetic cluster of three slots, plus one unrelated slot."""

    return SemanticRegistry(
        slots=(
            slot("WINNER_COUNT", "5", (6,)),
            slot("PRIZE", "10000", (7,)),
            slot("POOL", "50000", (8,)),
            slot("SLA_DAYS", "14", (9,)),
        ),
        relations=(
            SlotRelation(
                relation_id="R1",
                kind="PRODUCT",
                expression="WINNER_COUNT * PRIZE = POOL",
                slot_ids=("WINNER_COUNT", "PRIZE", "POOL"),
                asserted_at_ordinals=(8,),
            ),
        ),
        decisions=(),
    )


def build_plan() -> TransformationPlan:
    def ent(entity_id, entity_type, original, replacement, bundle_id):
        return EntityReplacement(
            entity_id=entity_id,
            entity_type=entity_type,
            policy="SYNTHESIZE",
            original=original,
            replacement=replacement,
            bundle_id=bundle_id,
        )

    def slot_rep(slot_id, ordinal, value):
        return SlotReplacement(
            slot_id=slot_id,
            value_type="COUNT",
            history=(
                SlotHistoryEntry(ordinal=ordinal, op="INTRODUCE", old_value=None, new_value=value),
            ),
            literal_replacements=(),
        )

    return TransformationPlan(
        plan_version=1,
        entity_replacements=(
            ent("E0001", "PERSON", "Joseph", "Marcus Feld", "B0001"),
            ent("E0002", "EMAIL", "scott@northstar.io", "marcus.f@ledgerline-demo.example", "B0001"),
            ent("E0003", "PRIVATE_DOMAIN", "northstar.io", "ledgerline-demo.example", "B0001"),
            ent("E0004", "PERSON", "Dusko", "Priya Raman", "B0002"),
            ent("E0005", "EMAIL", "dusko@vucko.dev", "priya.r@brightmill-demo.example", "B0002"),
        ),
        slot_replacements=(
            slot_rep("WINNER_COUNT", 6, "7"),
            slot_rep("PRIZE", 7, "12500"),
            slot_rep("POOL", 8, "87500"),
            slot_rep("SLA_DAYS", 9, "21"),
        ),
        secret_replacements=(),
    )


def safe_message(ordinal: int) -> SafeMessage:
    text = f"message {ordinal} body"
    return SafeMessage(
        ordinal=ordinal,
        message_id=ordinal,
        speaker="client",
        safe_text=text,
        safe_text_sha256=canonical_sha256(text),
        source_text_sha256=canonical_sha256(text),
        word_count=3,
        bucket=BUCKET_LONG,
        secret_tokens=(),
        sender_id_present=True,
    )


class ClosureTests(unittest.TestCase):
    """A slice must cover exactly what can change its correct rewrite."""

    def setUp(self) -> None:
        self.entities = build_entity_registry()
        self.semantics = build_semantic_registry()
        self.plan = build_plan()

    def slice_for(self, ordinal: int, plan: TransformationPlan | None = None):
        return plan_slice(
            plan or self.plan,
            safe_message(ordinal),
            entity_registry=self.entities,
            semantic_registry=self.semantics,
            semantics=None,
        )

    def hash_for(self, ordinal: int, plan: TransformationPlan | None = None) -> str:
        return canonical_sha256(self.slice_for(ordinal, plan).to_json())

    def mutate_entity(self, entity_id: str, value: str) -> TransformationPlan:
        return replace(
            self.plan,
            entity_replacements=tuple(
                replace(item, replacement=value) if item.entity_id == entity_id else item
                for item in self.plan.entity_replacements
            ),
        )

    def mutate_slot(self, slot_id: str, value: str) -> TransformationPlan:
        def rewrite(item: SlotReplacement) -> SlotReplacement:
            if item.slot_id != slot_id:
                return item
            return replace(
                item,
                history=tuple(
                    replace(entry, new_value=value) for entry in item.history
                ),
            )

        return replace(
            self.plan,
            slot_replacements=tuple(rewrite(item) for item in self.plan.slot_replacements),
        )

    def test_bundle_members_are_in_the_closure(self):
        """Message 2 mentions only the address, but depends on the person too."""

        entity_ids = {item.entity_id for item in self.slice_for(2).entity_replacements}
        self.assertEqual(entity_ids, {"E0001", "E0002", "E0003"})

    def test_arithmetic_cluster_is_in_the_closure(self):
        """Message 8 mentions only the pool, but depends on count and prize."""

        slot_ids = {item.slot_id for item in self.slice_for(8).slot_replacements}
        self.assertEqual(slot_ids, {"WINNER_COUNT", "PRIZE", "POOL"})

    def test_unrelated_slot_is_not_in_the_closure(self):
        slot_ids = {item.slot_id for item in self.slice_for(9).slot_replacements}
        self.assertEqual(slot_ids, {"SLA_DAYS"})

    def test_changing_a_bundle_sibling_invalidates_the_slice(self):
        """Renaming the person must invalidate the address-only message."""

        before = self.hash_for(2)
        after = self.hash_for(2, self.mutate_entity("E0001", "Different Name"))
        self.assertNotEqual(before, after)

    def test_changing_a_cluster_sibling_invalidates_the_slice(self):
        """Revaluing the count must invalidate the pool-only message."""

        before = self.hash_for(8)
        after = self.hash_for(8, self.mutate_slot("WINNER_COUNT", "9"))
        self.assertNotEqual(before, after)

    def test_changing_an_entry_outside_the_closure_is_inert(self):
        """The other identity and the unrelated slot must not touch this hash."""

        before = self.hash_for(2)
        self.assertEqual(before, self.hash_for(2, self.mutate_entity("E0004", "Someone Else")))
        self.assertEqual(before, self.hash_for(2, self.mutate_entity("E0005", "x@y-demo.example")))
        self.assertEqual(before, self.hash_for(2, self.mutate_slot("SLA_DAYS", "30")))
        self.assertEqual(before, self.hash_for(2, self.mutate_slot("POOL", "1")))

    def test_property_holds_for_every_message(self):
        """Exhaustive: in-closure entries change the hash, out-of-closure do not."""

        for ordinal in range(1, 10):
            baseline = self.hash_for(ordinal)
            in_closure_entities = {
                item.entity_id for item in self.slice_for(ordinal).entity_replacements
            }
            in_closure_slots = {
                item.slot_id for item in self.slice_for(ordinal).slot_replacements
            }
            for item in self.plan.entity_replacements:
                mutated = self.hash_for(
                    ordinal, self.mutate_entity(item.entity_id, f"Mutated {item.entity_id}")
                )
                if item.entity_id in in_closure_entities:
                    self.assertNotEqual(
                        baseline, mutated, f"ordinal {ordinal}: {item.entity_id} should matter"
                    )
                else:
                    self.assertEqual(
                        baseline, mutated, f"ordinal {ordinal}: {item.entity_id} should not matter"
                    )
            for item in self.plan.slot_replacements:
                mutated = self.hash_for(ordinal, self.mutate_slot(item.slot_id, "999999"))
                if item.slot_id in in_closure_slots:
                    self.assertNotEqual(
                        baseline, mutated, f"ordinal {ordinal}: {item.slot_id} should matter"
                    )
                else:
                    self.assertEqual(
                        baseline, mutated, f"ordinal {ordinal}: {item.slot_id} should not matter"
                    )


class ChunkingTests(unittest.TestCase):
    def test_bundles_are_never_split(self):
        registry = build_entity_registry()
        chunks = bundle_chunks(registry, max_bundles=1, max_chars=10)
        bundle_members = {
            bundle.bundle_id: set(bundle.entity_ids) for bundle in registry.bundles
        }
        for chunk in chunks:
            for bundle_id in chunk.bundle_ids:
                self.assertTrue(
                    bundle_members[bundle_id] <= set(chunk.entity_ids),
                    f"{bundle_id} was split across chunks",
                )

    def test_arithmetic_cluster_stays_in_one_call(self):
        clusters = slot_clusters(build_semantic_registry(), max_chars=1)
        tied = [item for item in clusters if len(item.slot_ids) > 1]
        self.assertEqual(len(tied), 1)
        self.assertEqual(set(tied[0].slot_ids), {"WINNER_COUNT", "PRIZE", "POOL"})

    def test_reserved_values_include_synthetic_hosts(self):
        reserved = reserved_values(build_plan().entity_by_id())
        self.assertIn("ledgerline-demo.example", reserved["domains"])
        self.assertIn("brightmill-demo.example", reserved["domains"])


class EntityValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = build_entity_registry()
        self.chunk = PlanChunk(1, ("E0001", "E0002", "E0003"), ("B0001",))

    def payload(self, **overrides: str) -> dict:
        values = {
            "E0001": "Marcus Feld",
            "E0002": "marcus.f@ledgerline-demo.example",
            "E0003": "ledgerline-demo.example",
        }
        values.update(overrides)
        return {
            "replacements": [
                {"entity_id": key, "replacement": value} for key, value in values.items()
            ]
        }

    def assert_rejected(self, payload: dict, code: str) -> None:
        with self.assertRaises(PlanConsistencyError) as caught:
            validate_entity_chunk(payload, self.chunk, self.registry, {})
        self.assertIn(code, caught.exception.failures, caught.exception.args[0])

    def test_coherent_bundle_is_accepted(self):
        result = validate_entity_chunk(self.payload(), self.chunk, self.registry, {})
        self.assertEqual(set(result), {"E0001", "E0002", "E0003"})

    def test_non_reserved_domain_is_rejected(self):
        self.assert_rejected(
            self.payload(E0003="ledgerline.io", E0002="marcus.f@ledgerline.io"),
            "PLAN_REAL_LOOKING_VALUE",
        )

    def test_replacement_equal_to_original_is_rejected(self):
        self.assert_rejected(self.payload(E0001="Joseph"), "PLAN_IDENTITY")

    def test_lightly_masked_replacement_is_rejected(self):
        self.assert_rejected(self.payload(E0001="Joseph Smith"), "PLAN_IDENTITY")

    def test_address_not_derived_from_person_is_rejected(self):
        self.assert_rejected(
            self.payload(E0002="unrelated@ledgerline-demo.example"), "PLAN_SCHEMA_INVALID"
        )

    def test_bundle_split_across_domains_is_rejected(self):
        self.assert_rejected(
            self.payload(E0002="marcus.f@other-demo.example"), "PLAN_SCHEMA_INVALID"
        )

    def test_credential_shaped_replacement_is_rejected(self):
        self.assert_rejected(
            self.payload(E0001=CREDENTIAL_SHAPED_VALUE),
            "PLAN_CREDENTIAL_GENERATED",
        )

    def test_missing_entity_is_rejected(self):
        payload = {"replacements": [{"entity_id": "E0001", "replacement": "Marcus Feld"}]}
        self.assert_rejected(payload, "PLAN_INCOMPLETE")

    def test_collision_with_reserved_value_is_rejected(self):
        with self.assertRaises(PlanConsistencyError) as caught:
            validate_entity_chunk(
                self.payload(),
                self.chunk,
                self.registry,
                {"person": ["Marcus Feld"]},
            )
        self.assertIn("PLAN_COLLISION", caught.exception.failures)


class SlotValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = build_semantic_registry()
        self.cluster = SlotCluster(1, ("WINNER_COUNT", "PRIZE", "POOL"))

    def payload(self, count: str, prize: str, pool: str) -> dict:
        def replacements(slot_id: str, replacement: str) -> list[dict]:
            occurrence = self.registry.by_id()[slot_id].literal_occurrences[0]
            return [
                {
                    "ordinal": occurrence.ordinal,
                    "message_id": occurrence.message_id,
                    "start": occurrence.start,
                    "end": occurrence.end,
                    "original": occurrence.source_literal,
                    "replacement": replacement,
                }
            ]

        return {
            "slot_replacements": [
                {
                    "slot_id": "WINNER_COUNT",
                    "history": [{"new_value": count}],
                    "literal_replacements": replacements("WINNER_COUNT", count),
                },
                {
                    "slot_id": "PRIZE",
                    "history": [{"new_value": prize}],
                    "literal_replacements": replacements("PRIZE", prize),
                },
                {
                    "slot_id": "POOL",
                    "history": [{"new_value": pool}],
                    "literal_replacements": replacements("POOL", pool),
                },
            ]
        }

    def test_arithmetically_consistent_values_are_accepted(self):
        result = validate_slot_cluster(
            self.payload("7", "12500", "87500"), self.cluster, self.registry
        )
        self.assertEqual(set(result), {"WINNER_COUNT", "PRIZE", "POOL"})
        self.assertTrue(
            all(
                occurrence.match_mode == "SEMANTIC_ONLY"
                for replacement in result.values()
                for occurrence in replacement.literal_replacements
            )
        )

    def test_broken_arithmetic_is_rejected(self):
        with self.assertRaises(PlanConsistencyError) as caught:
            validate_slot_cluster(
                self.payload("7", "12500", "80000"), self.cluster, self.registry
            )
        self.assertIn("PLAN_RELATION_BROKEN", caught.exception.failures)

    def test_unchanged_value_is_rejected(self):
        with self.assertRaises(PlanConsistencyError) as caught:
            validate_slot_cluster(
                self.payload("5", "12500", "62500"), self.cluster, self.registry
            )
        self.assertIn("PLAN_IDENTITY", caught.exception.failures)

    def test_equal_literals_at_different_positions_need_separate_records(self):
        source = slot("WINNER_COUNT", "5", (6,))
        source = replace(
            source,
            literal_occurrences=(
                SlotLiteralOccurrence(6, 6, 10, 11, "5"),
                SlotLiteralOccurrence(6, 6, 30, 31, "5"),
            ),
        )
        registry = SemanticRegistry(slots=(source,), relations=(), decisions=())
        payload = {
            "slot_replacements": [
                {
                    "slot_id": "WINNER_COUNT",
                    "history": [{"new_value": "8"}],
                    "literal_replacements": [
                        {
                            "ordinal": 6,
                            "message_id": 6,
                            "start": 10,
                            "end": 11,
                            "original": "5",
                            "replacement": "8",
                        }
                    ],
                }
            ]
        }
        with self.assertRaises(PlanConsistencyError) as caught:
            validate_slot_cluster(
                payload, SlotCluster(1, ("WINNER_COUNT",)), registry
            )
        self.assertIn("PLAN_SCHEMA_INVALID", caught.exception.failures)

        payload["slot_replacements"][0]["literal_replacements"].append(
            {
                "ordinal": 6,
                "message_id": 6,
                "start": 30,
                "end": 31,
                "original": "5",
                "replacement": "8",
            }
        )
        result = validate_slot_cluster(
            payload, SlotCluster(1, ("WINNER_COUNT",)), registry
        )
        self.assertEqual(len(result["WINNER_COUNT"].literal_replacements), 2)


class PlanAssemblyTests(unittest.TestCase):
    def test_assembly_is_deterministic(self):
        entities = build_plan().entity_by_id()
        slots = build_plan().slot_by_id()
        secrets = SecretRegistry(project_id="P", secrets=())
        semantics = build_semantic_registry()
        first = assemble_plan(entities, slots, secrets, semantics)
        second = assemble_plan(dict(reversed(list(entities.items()))), slots, secrets, semantics)
        self.assertEqual(
            canonical_sha256(first.to_json()), canonical_sha256(second.to_json())
        )

    def test_complete_plan_validates(self):
        validate_plan(
            build_plan(),
            entity_registry=build_entity_registry(),
            semantic_registry=build_semantic_registry(),
            secret_registry=SecretRegistry(project_id="P", secrets=()),
        )

    def test_incomplete_plan_is_rejected(self):
        plan = build_plan()
        trimmed = replace(plan, entity_replacements=plan.entity_replacements[:2])
        with self.assertRaises(PlanConsistencyError) as caught:
            validate_plan(
                trimmed,
                entity_registry=build_entity_registry(),
                semantic_registry=build_semantic_registry(),
                secret_registry=SecretRegistry(project_id="P", secrets=()),
            )
        self.assertIn("PLAN_INCOMPLETE", caught.exception.failures)

    def test_shared_replacement_across_entities_is_rejected(self):
        plan = build_plan()
        colliding = replace(
            plan,
            entity_replacements=tuple(
                replace(item, replacement="Marcus Feld")
                if item.entity_id in ("E0001", "E0004")
                else item
                for item in plan.entity_replacements
            ),
        )
        with self.assertRaises(PlanConsistencyError) as caught:
            validate_plan(
                colliding,
                entity_registry=build_entity_registry(),
                semantic_registry=build_semantic_registry(),
                secret_registry=SecretRegistry(project_id="P", secrets=()),
            )
        self.assertIn("PLAN_COLLISION", caught.exception.failures)


if __name__ == "__main__":
    unittest.main()


class FoldDeltaTests(unittest.TestCase):
    """Phase 1B must not ask the model to re-emit the accumulated registry.

    Regression: it originally returned the full merged registry each fold, so
    output grew with the project.  On an 824-message run the registry reached
    ~22k tokens by fold 5, fold 6 hit the response ceiling and was truncated, and
    every retry failed identically -- the project could not get past phase 1B.
    """

    def accumulator(self, slot_count: int):
        from Code.PII.models import SemanticRegistry, SemanticSlot, SlotHistoryEntry

        return SemanticRegistry(
            slots=tuple(
                SemanticSlot(
                    slot_id=f"SLOT_{index:03d}",
                    kind="BUSINESS",
                    value_type="COUNT",
                    unit=None,
                    current_value=str(index),
                    meaning=f"parameter number {index} with a reasonably long description",
                    history=tuple(
                        SlotHistoryEntry(
                            ordinal=step, op="INTRODUCE" if step == 1 else "MODIFY",
                            old_value=None if step == 1 else str(step - 1),
                            new_value=str(step),
                        )
                        for step in range(1, 6)
                    ),
                    source_literals=(str(index),),
                    message_ordinals=(index,),
                )
                for index in range(1, slot_count + 1)
            ),
            relations=(),
            decisions=(),
        )

    def test_catalogue_sent_to_the_model_omits_histories(self):
        from Code.PII.phase1b_consolidate import accumulator_catalogue
        from Code.PII.textutil import canonical_json

        accumulator = self.accumulator(150)
        full = len(canonical_json(accumulator.to_json()))
        catalogue = len(canonical_json(accumulator_catalogue(accumulator)))
        self.assertLess(
            catalogue, full / 2,
            "the catalogue must be far smaller than the registry it describes",
        )
        self.assertNotIn("history", canonical_json(accumulator_catalogue(accumulator)))

    def test_untouched_slots_are_carried_forward_without_being_mentioned(self):
        from Code.PII.phase1b_consolidate import apply_fold_delta

        accumulator = self.accumulator(120)
        merged = apply_fold_delta(
            accumulator,
            {
                "new_slots": [
                    {"slot_id": "BRAND_NEW", "kind": "BUSINESS", "value_type": "COUNT",
                     "meaning": "introduced by this chunk",
                     "history": [{"ordinal": 900, "op": "INTRODUCE", "new_value": "7"}],
                     "source_literals": ["7"], "message_ordinals": [900]}
                ],
                "updated_slots": [],
                "merged_from": {},
                "new_relations": [],
            },
        )
        self.assertEqual(len(merged.slots), 121, "nothing may be lost by omission")
        self.assertIn("BRAND_NEW", {slot.slot_id for slot in merged.slots})

    def test_appended_history_chains_continuously_without_being_asked(self):
        from Code.PII.phase1b_consolidate import apply_fold_delta

        accumulator = self.accumulator(2)
        merged = apply_fold_delta(
            accumulator,
            {
                "new_slots": [],
                # No old_value supplied; it must be derived.
                "updated_slots": [
                    {"slot_id": "SLOT_001",
                     "append_history": [{"ordinal": 42, "op": "MODIFY", "new_value": "99"}],
                     "add_source_literals": ["99"], "add_message_ordinals": [42]}
                ],
                "merged_from": {},
                "new_relations": [],
            },
        )
        slot = next(item for item in merged.slots if item.slot_id == "SLOT_001")
        self.assertEqual(slot.history[-1].new_value, "99")
        self.assertEqual(slot.history[-1].old_value, slot.history[-2].new_value)
        self.assertEqual(slot.current_value, "99")

    def test_updating_an_unknown_slot_is_rejected(self):
        from Code.PII.phase1b_consolidate import apply_fold_delta

        with self.assertRaises(PlanConsistencyError.__mro__[1]):  # PiiValidationError
            apply_fold_delta(
                self.accumulator(2),
                {"new_slots": [], "merged_from": {}, "new_relations": [],
                 "updated_slots": [{"slot_id": "NOT_THERE", "append_history": []}]},
            )


class HostedIdentityTests(unittest.TestCase):
    """Identity is judged per type, because whole-string similarity is wrong.

    A private URL's identity lives entirely in its host; its path states which
    endpoint does what, and that is Requirement content the rewrite has to carry
    through.  Comparing whole strings scored a correct host swap at 0.80 and
    rejected it, so the only replacement that could pass had to destroy the
    path -- the validator was demanding the data be broken.  Comparing hosts
    instead has its own trap in the other direction: token similarity treats a
    whole host as one token, so a host that keeps the organisation name under a
    reserved suffix scores 0.0 and would sail through.
    """

    def setUp(self) -> None:
        self.registry = PiiEntityRegistry(
            entities=(
                entity(
                    "E0001",
                    "PRIVATE_URL",
                    "https://api.northstar.io/api/webhook/contract-events",
                    None,
                    (1,),
                ),
            ),
            bundles=(),
        )
        self.chunk = PlanChunk(1, ("E0001",), ())

    def validate(self, replacement: str):
        payload = {"replacements": [{"entity_id": "E0001", "replacement": replacement}]}
        return validate_entity_chunk(payload, self.chunk, self.registry, {})

    def assert_rejected(self, replacement: str) -> None:
        with self.assertRaises(PlanConsistencyError) as caught:
            self.validate(replacement)
        self.assertIn("PLAN_IDENTITY", caught.exception.failures, caught.exception.args[0])

    def test_swapping_the_host_and_keeping_the_path_is_accepted(self):
        result = self.validate(
            "https://api.ledgerline-demo.example/api/webhook/contract-events"
        )
        self.assertEqual(set(result), {"E0001"})

    def test_keeping_the_original_host_is_rejected(self):
        self.assert_rejected("https://api.northstar.io/somewhere/else")

    def test_reserved_suffix_does_not_excuse_keeping_the_name(self):
        self.assert_rejected("https://api.northstar.example/api/webhook/contract-events")

    def test_one_character_host_mask_is_rejected(self):
        self.assert_rejected("https://api.northstars.example/api/webhook/contract-events")

    def test_original_host_as_a_subdomain_is_rejected(self):
        self.assert_rejected("https://northstar.io.ledgerline-demo.example/api")


class AddressIdentityTests(unittest.TestCase):
    """Both halves of an address identify, so both must move."""

    def setUp(self) -> None:
        self.registry = PiiEntityRegistry(
            entities=(entity("E0001", "EMAIL", "joseph@northstar.io", None, (1,)),),
            bundles=(),
        )
        self.chunk = PlanChunk(1, ("E0001",), ())

    def assert_rejected(self, replacement: str) -> None:
        payload = {"replacements": [{"entity_id": "E0001", "replacement": replacement}]}
        with self.assertRaises(PlanConsistencyError) as caught:
            validate_entity_chunk(payload, self.chunk, self.registry, {})
        self.assertIn("PLAN_IDENTITY", caught.exception.failures, caught.exception.args[0])

    def test_new_local_part_and_host_is_accepted(self):
        payload = {
            "replacements": [
                {"entity_id": "E0001", "replacement": "marcus@ledgerline-demo.example"}
            ]
        }
        self.assertEqual(
            set(validate_entity_chunk(payload, self.chunk, self.registry, {})), {"E0001"}
        )

    def test_keeping_the_local_part_is_rejected(self):
        self.assert_rejected("joseph@ledgerline-demo.example")

    def test_keeping_the_host_name_is_rejected(self):
        self.assert_rejected("marcus@northstar.example")


class BundleSplitDiagnosticTests(unittest.TestCase):
    """A member rejected *in this chunk* is not evidence of a split.

    Reporting it as one pointed the diagnosis at the chunker while the real
    fault was three rejected replacements, in a project whose entities all sat
    in a single chunk.
    """

    def setUp(self) -> None:
        self.registry = build_entity_registry()
        self.chunk = PlanChunk(1, ("E0001", "E0002", "E0003"), ("B0001",))

    def test_rejected_member_is_not_reported_as_a_split(self):
        payload = {
            "replacements": [
                {"entity_id": "E0001", "replacement": "Joseph"},  # equals original
                {"entity_id": "E0002", "replacement": "joseph@ledgerline-demo.example"},
                {"entity_id": "E0003", "replacement": "ledgerline-demo.example"},
            ]
        }
        with self.assertRaises(PlanConsistencyError) as caught:
            validate_entity_chunk(payload, self.chunk, self.registry, {})
        self.assertNotIn("split across chunks", caught.exception.args[0])

    def test_member_left_in_another_chunk_is_still_reported(self):
        partial = PlanChunk(1, ("E0001", "E0002"), ("B0001",))
        payload = {
            "replacements": [
                {"entity_id": "E0001", "replacement": "Marcus Feld"},
                {"entity_id": "E0002", "replacement": "marcus.f@ledgerline-demo.example"},
            ]
        }
        with self.assertRaises(PlanConsistencyError) as caught:
            validate_entity_chunk(payload, partial, self.registry, {})
        self.assertIn("split across chunks", caught.exception.args[0])


class WordFormValueTests(unittest.TestCase):
    """Whether a value parses as a number describes its rendering, not its type.

    Real slots record a COUNT as ``No badges``, an AMOUNT as ``free`` and a
    DURATION as ``a few minutes``.  Demanding that the replacement match that
    rendering rejected the natural re-valuation, and left a slot whose history
    held both ``0 Badges`` and ``No badges`` with no satisfiable answer at all.
    """

    def registry_for(self, *values: str) -> SemanticRegistry:
        history = tuple(
            SlotHistoryEntry(
                ordinal=10 + index,
                op="INTRODUCE" if index == 0 else "CONFIRM",
                old_value=values[index - 1] if index else None,
                new_value=value,
            )
            for index, value in enumerate(values)
        )
        return SemanticRegistry(
            slots=(
                SemanticSlot(
                    slot_id="BADGE_COUNT",
                    kind="BUSINESS",
                    value_type="COUNT",
                    unit="badges",
                    current_value=values[-1],
                    meaning="badges shown on the dashboard",
                    history=history,
                    source_literals=values,
                    message_ordinals=tuple(10 + index for index in range(len(values))),
                    literal_occurrences=tuple(
                        SlotLiteralOccurrence(
                            ordinal=10 + index,
                            message_id=10 + index,
                            start=0,
                            end=len(value),
                            source_literal=value,
                        )
                        for index, value in enumerate(values)
                    ),
                ),
            ),
            relations=(),
            decisions=(),
        )

    def validate(self, registry: SemanticRegistry, *new_values: str):
        replacements = [
            {
                "ordinal": occurrence.ordinal,
                "message_id": occurrence.message_id,
                "start": occurrence.start,
                "end": occurrence.end,
                "original": occurrence.source_literal,
                "replacement": new_value,
            }
            for occurrence, new_value in zip(
                registry.slots[0].literal_occurrences, new_values
            )
        ]
        payload = {
            "slot_replacements": [
                {
                    "slot_id": "BADGE_COUNT",
                    "history": [{"new_value": value} for value in new_values],
                    "literal_replacements": replacements,
                }
            ]
        }
        return validate_slot_cluster(
            payload, SlotCluster(1, ("BADGE_COUNT",)), registry
        )

    def test_words_may_become_a_number(self):
        registry = self.registry_for("No badges")
        self.assertEqual(set(self.validate(registry, "3 badges")), {"BADGE_COUNT"})

    def test_words_may_stay_words(self):
        registry = self.registry_for("No badges")
        self.assertEqual(set(self.validate(registry, "Plenty of badges")), {"BADGE_COUNT"})

    def test_a_mixed_history_is_satisfiable(self):
        """The case that had no valid answer: one entry numeric, one not."""

        registry = self.registry_for("0 Badges", "No badges")
        self.assertEqual(
            set(self.validate(registry, "4 Badges", "4 badges")), {"BADGE_COUNT"}
        )

    def test_dropping_an_existing_number_is_still_rejected(self):
        registry = self.registry_for("5 badges")
        with self.assertRaises(PlanConsistencyError) as caught:
            self.validate(registry, "several badges")
        self.assertIn("PLAN_SCHEMA_INVALID", caught.exception.failures)


class Phase2PromptHashTests(unittest.TestCase):
    """Phase 2 keeps two modes in one file; they must not share a hash.

    Phase 3 was split into two files for exactly this reason -- iterating on the
    short-message wording must not invalidate the long rewrites.  Phase 2 stayed
    a single document, so editing the slot rules discarded every entity chunk,
    which is the most expensive call the phase makes.
    """

    DOCUMENT = (
        "# Phase 2\n\nShared header text.\n\n"
        "## Mode `ENTITY_CHUNK`\n\nEntity rules.\n\n"
        "## Mode `SLOT_CLUSTER`\n\nSlot rules.\n"
    )

    def hashes_for(self, document: str) -> dict:
        return mode_hashes(document)

    def test_each_mode_gets_its_own_hash(self):
        hashes = self.hashes_for(self.DOCUMENT)
        self.assertEqual(
            sorted(hashes),
            [
                phase2_prompt_key("ENTITY_CHUNK"),
                phase2_prompt_key("SLOT_CLUSTER"),
            ],
        )
        self.assertNotEqual(*hashes.values())

    def test_editing_one_mode_leaves_the_other_alone(self):
        before = self.hashes_for(self.DOCUMENT)
        after = self.hashes_for(self.DOCUMENT.replace("Slot rules.", "Slot rules, revised."))
        entity = phase2_prompt_key("ENTITY_CHUNK")
        slots = phase2_prompt_key("SLOT_CLUSTER")
        self.assertEqual(before[entity], after[entity], "entity chunks must survive")
        self.assertNotEqual(before[slots], after[slots], "slot clusters must not")

    def test_editing_the_shared_header_invalidates_both(self):
        before = self.hashes_for(self.DOCUMENT)
        after = self.hashes_for(self.DOCUMENT.replace("Shared header", "Reworded header"))
        for key, value in before.items():
            self.assertNotEqual(value, after[key], f"{key} must be invalidated")

    def test_a_document_without_mode_headings_falls_back(self):
        self.assertEqual(self.hashes_for("# Phase 2\n\nNo modes here.\n"), {})


class SharedReferentTests(unittest.TestCase):
    """One real thing split into two entities must share one replacement.

    Phase 0B routinely splits a single referent -- a project written with and
    without a space, an acronym and its expansion, the same link with and
    without a scheme.  Phase 2 reconciles them by giving them one synthetic
    identity and cross-registering each other's surface forms as aliases.
    Treating that as a collision demanded the opposite: two synthetic project
    names for one real project, which is the cross-message inconsistency the
    final audit exists to catch.
    """

    EMPTY_SEMANTICS = SemanticRegistry(slots=(), relations=(), decisions=())
    NO_SECRETS = SecretRegistry(project_id="P", secrets=())

    def registry(self, *values: str) -> PiiEntityRegistry:
        return PiiEntityRegistry(
            entities=tuple(
                entity(f"E{index + 1:04d}", "PROJECT_NAME", value, None, (index + 1,))
                for index, value in enumerate(values)
            ),
            bundles=(),
        )

    def plan_for(self, *entries) -> TransformationPlan:
        return TransformationPlan(
            plan_version=1,
            entity_replacements=tuple(
                EntityReplacement(
                    entity_id=f"E{index + 1:04d}",
                    entity_type="PROJECT_NAME",
                    policy="SYNTHESIZE",
                    original=original,
                    replacement=replacement,
                    bundle_id=None,
                    aliases=tuple(
                        EntityAlias(original=a, replacement=b) for a, b in aliases
                    ),
                )
                for index, (original, replacement, aliases) in enumerate(entries)
            ),
            slot_replacements=(),
            secret_replacements=(),
        )

    def validate(self, registry, plan):
        return validate_plan(
            plan,
            entity_registry=registry,
            semantic_registry=self.EMPTY_SEMANTICS,
            secret_registry=self.NO_SECRETS,
        )

    def test_entities_sharing_a_surface_form_may_share_a_replacement(self):
        registry = self.registry("Project Rebuild", "ProjectRebuild")
        plan = self.plan_for(
            ("Project Rebuild", "BrightQuill Initiative", [("ProjectRebuild", "BrightQuillInitiative")]),
            ("ProjectRebuild", "BrightQuill Initiative", [("Project Rebuild", "BrightQuill Initiative")]),
        )
        self.validate(registry, plan)  # must not raise

    def test_acronym_and_expansion_may_share(self):
        registry = self.registry("FAMM", "FAMM (Fully Autonomous Marketing Model)")
        plan = self.plan_for(
            ("FAMM", "NOVA", [("FAMM (Fully Autonomous Marketing Model)", "NOVA (Network Visibility)")]),
            ("FAMM (Fully Autonomous Marketing Model)", "NOVA (Network Visibility)", [("FAMM", "NOVA")]),
        )
        self.validate(registry, plan)  # must not raise

    def test_unrelated_entities_still_may_not_share(self):
        """The guard against collapsing two distinct identities stays intact."""

        registry = self.registry("Project Rebuild", "Helios Ledger")
        plan = self.plan_for(
            ("Project Rebuild", "BrightQuill Initiative", []),
            ("Helios Ledger", "BrightQuill Initiative", []),
        )
        with self.assertRaises(PlanConsistencyError) as caught:
            self.validate(registry, plan)
        self.assertIn("PLAN_COLLISION", caught.exception.failures)

    def test_a_collision_is_reported_once(self):
        """An alias and its canonical form both collide; that is one fault."""

        registry = self.registry("Project Rebuild", "Helios Ledger")
        plan = self.plan_for(
            ("Project Rebuild", "BrightQuill Initiative", [("PR", "BrightQuill Initiative")]),
            ("Helios Ledger", "BrightQuill Initiative", [("HL", "BrightQuill Initiative")]),
        )
        with self.assertRaises(PlanConsistencyError) as caught:
            self.validate(registry, plan)
        self.assertEqual(caught.exception.args[0].count("PLAN_COLLISION"), 1)


class PreservedTermsInSlotsTests(unittest.TestCase):
    """The PRESERVE policy has to reach the slot channel too.

    ``TYPE_POLICY`` pins public third parties and technologies to PRESERVE so a
    prompt regression cannot resurrect v6's brand replacement -- but that guard
    only ever covered *entities*.  The slot validator was handed the semantic
    registry and had no idea which literals were public, so the same names came
    back through the slot channel: a currency ticker, an L2 and a payment
    provider were all re-valued.  That is not a privacy improvement, it states a
    different requirement, and it makes one string simultaneously PRESERVE (as
    an entity) and replaced (as a slot literal) -- which no rewrite can satisfy.
    """

    PRESERVED = frozenset({"eth", "base", "google meet"})

    def registry_for(self, value: str) -> SemanticRegistry:
        return SemanticRegistry(
            slots=(
                SemanticSlot(
                    slot_id="PAYMENT_ASSET",
                    kind="TECHNICAL",
                    value_type="OTHER",
                    unit=None,
                    current_value=value,
                    meaning="which asset the mint is priced in",
                    history=(
                        SlotHistoryEntry(
                            ordinal=10, op="INTRODUCE", old_value=None, new_value=value
                        ),
                    ),
                    source_literals=(value,),
                    message_ordinals=(10,),
                    literal_occurrences=(
                        SlotLiteralOccurrence(
                            ordinal=10,
                            message_id=10,
                            start=0,
                            end=len(value),
                            source_literal=value,
                        ),
                    ),
                ),
            ),
            relations=(),
            decisions=(),
        )

    def validate(self, registry, new_value, mapped):
        occurrence = registry.slots[0].literal_occurrences[0]
        payload = {
            "slot_replacements": [
                {
                    "slot_id": "PAYMENT_ASSET",
                    "history": [{"new_value": new_value}],
                    "literal_replacements": [
                        {
                            "ordinal": occurrence.ordinal,
                            "message_id": occurrence.message_id,
                            "start": occurrence.start,
                            "end": occurrence.end,
                            "original": occurrence.source_literal,
                            "replacement": mapped,
                        }
                    ],
                }
            ]
        }
        return validate_slot_cluster(
            payload, SlotCluster(1, ("PAYMENT_ASSET",)), registry, self.PRESERVED
        )

    def test_a_slot_that_is_a_public_name_keeps_it(self):
        """Returning it unchanged is correct, not a failure to change."""

        registry = self.registry_for("ETH")
        result = self.validate(registry, "ETH", "ETH")
        self.assertEqual(
            result["PAYMENT_ASSET"].literal_replacements[0].replacement, "ETH"
        )

    def test_re_valuing_a_public_name_is_forced_back(self):
        """The right answer is known locally, so it is applied, not rejected."""

        registry = self.registry_for("ETH")
        result = self.validate(registry, "ETH", "USDC")
        self.assertEqual(
            result["PAYMENT_ASSET"].literal_replacements[0].replacement, "ETH"
        )

    def test_dropping_a_contained_public_name_is_rejected(self):
        registry = self.registry_for("Base testnet")
        with self.assertRaises(PlanConsistencyError) as caught:
            self.validate(registry, "Arbitrum Sepolia", "Arbitrum Sepolia")
        self.assertIn("PLAN_PRESERVED_TERM_DROPPED", caught.exception.failures)

    def test_changing_the_words_around_a_public_name_is_allowed(self):
        registry = self.registry_for("Base testnet")
        result = self.validate(registry, "Base mainnet", "Base mainnet")
        self.assertEqual(
            result["PAYMENT_ASSET"].literal_replacements[0].replacement,
            "Base mainnet",
        )

    def test_a_slot_with_no_public_name_must_still_change(self):
        """The guard must not become a licence to leave values alone."""

        registry = self.registry_for("4800 users")
        with self.assertRaises(PlanConsistencyError) as caught:
            self.validate(registry, "4800 users", "4800 users")
        self.assertIn("PLAN_IDENTITY", caught.exception.failures)

    def test_numeric_identifier_may_become_an_alphanumeric_code(self):
        registry = self.registry_for("1")
        registry = replace(
            registry,
            slots=(replace(registry.slots[0], value_type="IDENTIFIER"),),
        )
        result = self.validate(registry, "NX-A", "NX-A")
        self.assertEqual(result["PAYMENT_ASSET"].history[0].new_value, "NX-A")

    def test_multi_word_terms_are_matched(self):
        self.assertEqual(
            _preserved_terms_in("we used Google Meet again", self.PRESERVED),
            {"google meet"},
        )

    def test_a_public_name_inside_a_longer_word_is_not_matched(self):
        self.assertEqual(_preserved_terms_in("database rebase", self.PRESERVED), set())

    def test_a_dropped_public_unit_is_restored_from_the_numeric_decision(self):
        values = ("no existing NFTs", "no existing NFT", "no existing NFTs")
        occurrences = tuple(
            SlotLiteralOccurrence(
                ordinal=308 + index,
                message_id=308 + index,
                start=0,
                end=len(value),
                source_literal=value,
            )
            for index, value in enumerate(values)
        )
        registry = SemanticRegistry(
            slots=(
                SemanticSlot(
                    slot_id="PREEXISTING_NFT_COUNT_AT_FIRST_MINT",
                    kind="BUSINESS",
                    value_type="COUNT",
                    unit="NFTs",
                    current_value=values[-1],
                    meaning="number of NFTs existing before the first mint",
                    history=tuple(
                        SlotHistoryEntry(
                            ordinal=occurrence.ordinal,
                            op="INTRODUCE" if index == 0 else "CONFIRM",
                            old_value=values[index - 1] if index else None,
                            new_value=value,
                        )
                        for index, (value, occurrence) in enumerate(zip(values, occurrences))
                    ),
                    source_literals=tuple(dict.fromkeys(values)),
                    message_ordinals=tuple(item.ordinal for item in occurrences),
                    literal_occurrences=occurrences,
                ),
            ),
            relations=(),
            decisions=(),
        )
        payload = {
            "slot_replacements": [
                {
                    "slot_id": "PREEXISTING_NFT_COUNT_AT_FIRST_MINT",
                    "history": [
                        {"new_value": "4 NFTs"},
                        {"new_value": "4 digital collectibles"},
                        {"new_value": "4 NFTs"},
                    ],
                    "literal_replacements": [
                        {
                            "ordinal": item.ordinal,
                            "message_id": item.message_id,
                            "start": item.start,
                            "end": item.end,
                            "original": item.source_literal,
                            "replacement": (
                                "4 digital collectibles" if index == 1 else "4 NFTs"
                            ),
                        }
                        for index, item in enumerate(occurrences)
                    ],
                }
            ]
        }

        result = validate_slot_cluster(
            payload,
            SlotCluster(1, ("PREEXISTING_NFT_COUNT_AT_FIRST_MINT",)),
            registry,
            frozenset({"nft"}),
        )

        planned = result["PREEXISTING_NFT_COUNT_AT_FIRST_MINT"]
        self.assertEqual(planned.history[1].new_value, "4 NFTs")
        self.assertEqual(planned.literal_replacements[1].replacement, "4 NFTs")


class BareNumeralEntityTests(unittest.TestCase):
    """A bare numeral cannot identify anyone, and replacing it corrupts numbers.

    ``1`` was extracted as an ACCOUNT_IDENTIFIER from ordinals and list markers.
    Planning ``1 -> 47`` asks every later phase to turn every standalone ``1``
    in the project into another number.  Length alone is the wrong test: a
    two-letter personal name is real PII.
    """

    def test_bare_numerals_are_dropped(self):
        for value in ("1", "#5", "No. 3", "2."):
            self.assertFalse(
                _is_identifying("ACCOUNT_IDENTIFIER", value),
                f"{value!r} cannot identify anything",
            )

    def test_short_names_are_kept(self):
        for value in ("Li", "Bo", "Al"):
            self.assertTrue(_is_identifying("PERSON", value), f"{value!r} is real PII")

    def test_real_identifiers_are_kept(self):
        for value in ("A1", "12345678", "acct-9931"):
            self.assertTrue(_is_identifying("ACCOUNT_IDENTIFIER", value))

    def test_public_types_are_never_dropped(self):
        """Dropping a PRESERVE entity would lose a term the rewrite must keep."""

        self.assertTrue(_is_identifying("PUBLIC_THIRD_PARTY", "GitHub"))

    def test_ordinary_lowercase_verb_is_not_a_project_alias(self):
        weak = PiiOccurrence(
            ordinal=3,
            message_id=3,
            source="rebuild",
            start=12,
            end=19,
            entity_type="PROJECT_NAME",
            policy="SYNTHESIZE",
            normalized_value="Project Rebuild",
            link_hint=None,
            confidence="MEDIUM",
        )
        self.assertFalse(_is_identifying_occurrence(weak))

    def test_proper_or_high_confidence_project_short_forms_survive(self):
        base = PiiOccurrence(
            ordinal=3,
            message_id=3,
            source="Rebuild",
            start=12,
            end=19,
            entity_type="PROJECT_NAME",
            policy="SYNTHESIZE",
            normalized_value="Project Rebuild",
            link_hint=None,
            confidence="MEDIUM",
        )
        self.assertTrue(_is_identifying_occurrence(base))
        self.assertTrue(
            _is_identifying_occurrence(
                replace(base, source="rebuild", confidence="HIGH")
            )
        )


def _safe(text: str, bucket: str) -> SafeMessage:
    """A one-message fixture for the rewrite gate."""

    return SafeMessage(
        ordinal=1,
        message_id=1,
        speaker="client",
        safe_text=text,
        safe_text_sha256=canonical_sha256(text),
        source_text_sha256=canonical_sha256(text),
        word_count=len(text.split()),
        bucket=bucket,
        secret_tokens=(),
        sender_id_present=True,
    )


class NestedEntityAndSlotRewriteTests(unittest.TestCase):
    def slice_with(
        self,
        *,
        entities: tuple[EntityReplacement, ...] = (),
        slots: tuple[SlotReplacement, ...] = (),
    ) -> MessagePlanSlice:
        return MessagePlanSlice(
            ordinal=1,
            message_id=1,
            bucket="LONG",
            safe_text_sha256="x" * 64,
            entity_replacements=entities,
            slot_replacements=slots,
            secret_tokens=(),
            preserve_literals=(),
            must_replace_terms=(),
            semantic_expectations={},
            relation_constraints=(),
            plan_version=1,
        )

    def test_name_nested_only_in_url_does_not_require_duplicate_replacement(self):
        source = "Use https://alpha.example/contact for support."
        entities = (
            EntityReplacement(
                "E0001", "PROJECT_NAME", "SYNTHESIZE", "alpha", "Blue Harbor"
            ),
            EntityReplacement(
                "E0002",
                "PRIVATE_URL",
                "SYNTHESIZE",
                "https://alpha.example/contact",
                "https://blue-harbor.example/contact",
            ),
        )
        violations = rewrite_violations(
            _safe(source, "LONG"),
            "For support, use https://blue-harbor.example/contact.",
            self.slice_with(entities=entities),
        )
        self.assertFalse(
            any("E0001 replacement was not applied" in item for item in violations),
            violations,
        )

    def test_name_inside_unplanned_address_shape_still_requires_replacement(self):
        source = "Contact alpha@example.com for support."
        decision = EntityReplacement(
            "E0001", "PROJECT_NAME", "SYNTHESIZE", "alpha", "Blue Harbor"
        )
        violations = rewrite_violations(
            _safe(source, "LONG"),
            "For support, contact the account.",
            self.slice_with(entities=(decision,)),
        )
        self.assertTrue(
            any("E0001 replacement was not applied" in item for item in violations),
            violations,
        )

    def test_original_prefix_inside_its_planned_replacement_is_not_residual(self):
        original = "https://public.example/"
        replacement = "https://public.example/sample-project"
        decision = EntityReplacement(
            "E0001", "PRIVATE_URL", "SYNTHESIZE", original, replacement
        )
        violations = rewrite_violations(
            _safe(f"Portfolio: {original}", "LONG"),
            f"The portfolio is available at {replacement}.",
            self.slice_with(entities=(decision,)),
        )
        self.assertFalse(
            any("RESIDUAL_ORIGINAL_ENTITY" in item for item in violations),
            violations,
        )

    def test_slot_inside_synthesized_entity_is_owned_by_entity_mapping(self):
        original = "https://old.example/backend"
        replacement = "https://new.example/backend"
        source = f"Use {original} now."
        start = source.index(original)
        entity_decision = EntityReplacement(
            "E0001", "PRIVATE_REPOSITORY", "SYNTHESIZE", original, replacement
        )
        slot_decision = SlotReplacement(
            slot_id="BACKEND_REPOSITORY",
            value_type="IDENTIFIER",
            history=(),
            literal_replacements=(
                SlotLiteralReplacement(
                    1,
                    1,
                    start,
                    start + len(original),
                    original,
                    replacement,
                    "EXACT",
                ),
            ),
        )
        violations = rewrite_violations(
            _safe(source, "LONG"),
            f"The repository to use now is {replacement}.",
            self.slice_with(entities=(entity_decision,), slots=(slot_decision,)),
        )
        self.assertFalse(any("BACKEND_REPOSITORY" in item for item in violations))

    def test_complete_pii_slot_replacement_is_checked_on_raw_candidate(self):
        original = "old-repo"
        replacement = "https://new.example/backend"
        source = f"Use repository {original} now."
        start = source.index(original)
        slot_decision = SlotReplacement(
            slot_id="BACKEND_REPOSITORY",
            value_type="IDENTIFIER",
            history=(),
            literal_replacements=(
                SlotLiteralReplacement(
                    1,
                    1,
                    start,
                    start + len(original),
                    original,
                    replacement,
                    "EXACT",
                ),
            ),
        )
        violations = rewrite_violations(
            _safe(source, "LONG"),
            f"The repository to use now is {replacement}.",
            self.slice_with(slots=(slot_decision,)),
        )
        self.assertFalse(any("BACKEND_REPOSITORY" in item for item in violations))


class SlotIdentityMappingTests(unittest.TestCase):
    """Phase 3 has to know that some slot literals are meant to survive.

    Phase 2 maps a public tool, network or asset name to itself, because which
    one was chosen is a requirement rather than an identity.  The rewrite gate
    still assumed every slot literal must change, so the *correct* rewrite --
    the one that kept the public name -- was reported as having "kept its
    original literal": the same blind spot as phase 2, one phase later.
    """

    def slice_with(
        self, literal: str, replacement: str, match_mode: str = "EXACT"
    ) -> MessagePlanSlice:
        return MessagePlanSlice(
            ordinal=1,
            message_id=1,
            bucket="LONG",
            safe_text_sha256="x" * 64,
            entity_replacements=(),
            slot_replacements=(
                SlotReplacement(
                    slot_id="MINT_ASSET",
                    value_type="OTHER",
                    history=(),
                    literal_replacements=(
                        SlotLiteralReplacement(
                            ordinal=1,
                            message_id=1,
                            start=0,
                            end=len(literal),
                            original=literal,
                            replacement=replacement,
                            match_mode=match_mode,
                        ),
                    ),
                ),
            ),
            secret_tokens=(),
            preserve_literals=(),
            must_replace_terms=(),
            semantic_expectations={},
            relation_constraints=(),
            plan_version=1,
        )

    def safe(self, text: str) -> SafeMessage:
        return _safe(text, "LONG")

    def slot_violations(self, source: str, candidate: str, literal, replacement):
        return [
            item
            for item in rewrite_violations(
                self.safe(source), candidate, self.slice_with(literal, replacement)
            )
            if "MINT_ASSET" in item
        ]

    def test_a_preserved_literal_may_survive(self):
        self.assertEqual(
            self.slot_violations(
                "We will price the mint in ETH for launch week.",
                "For the opening week the mint is denominated in ETH.",
                "ETH",
                "ETH",
            ),
            [],
        )

    def test_dropping_a_preserved_literal_is_a_violation(self):
        found = self.slot_violations(
            "We will price the mint in ETH for launch week.",
            "For the opening week the mint is denominated in tokens.",
            "ETH",
            "ETH",
        )
        self.assertTrue(any("PRESERVED_TERM_ALTERED" in item for item in found), found)

    def test_a_real_substitution_must_still_be_applied(self):
        found = self.slot_violations(
            "We will price the mint at $500 for launch week.",
            "For the opening week the mint is priced at $500.",
            "$500",
            "$750",
        )
        self.assertTrue(any("RESIDUAL_ORIGINAL_ENTITY" in item for item in found), found)

    def test_bare_number_is_left_to_semantic_verification(self):
        slice_ = self.slice_with("1", "3", "SEMANTIC_ONLY")
        found = [
            item
            for item in rewrite_violations(
                self.safe("On June 5, choose 1 winner."),
                "Choose three winners on June 5.",
                slice_,
            )
            if "MINT_ASSET" in item
        ]
        self.assertEqual(found, [])


class ShortPolarityTests(unittest.TestCase):
    """Polarity is what matters; negation words are only a proxy for it.

    ``Okay, no problem`` carries a negation marker and phase 1A classifies it
    AFFIRMATIVE -- correctly, it is an acknowledgement.  Requiring the marker to
    survive rejected every natural rewrite of it, so the local guard was
    contradicting the semantic judgement it exists to protect.
    """

    def slice_for(self, polarity: str) -> MessagePlanSlice:
        return MessagePlanSlice(
            ordinal=1,
            message_id=1,
            bucket="SHORT",
            safe_text_sha256="x" * 64,
            entity_replacements=(),
            slot_replacements=(),
            secret_tokens=(),
            preserve_literals=(),
            must_replace_terms=(),
            semantic_expectations={"polarity": polarity},
            relation_constraints=(),
            plan_version=1,
        )

    def safe(self, text: str) -> SafeMessage:
        return _safe(text, "SHORT")

    def polarity_violations(self, source, candidate, polarity):
        return [
            item
            for item in rewrite_violations(
                self.safe(source), candidate, self.slice_for(polarity)
            )
            if "POLARITY" in item
        ]

    def test_an_idiomatic_negation_may_disappear(self):
        self.assertEqual(
            self.polarity_violations("Okay, no problem.", "Sure, that works.", "AFFIRMATIVE"),
            [],
        )

    def test_dropping_a_real_negation_is_a_violation(self):
        self.assertTrue(
            self.polarity_violations("Please don't merge yet.", "Please merge now.", "NEGATIVE")
        )

    def test_inventing_a_negation_is_a_violation(self):
        self.assertTrue(
            self.polarity_violations("Please merge it now.", "Do not merge it.", "AFFIRMATIVE")
        )


class PaddedValueTests(unittest.TestCase):
    """Bolting a noun onto the original is not a new value.

    A slot recording a public technology name traps the model between "keep the
    public term" and "every value must change", and it satisfies both by
    padding: ``PDF`` -> ``PDF document``.  Downstream that is unsatisfiable --
    the rewrite naturally says ``PDF``, so the gate sees the original surviving
    while the padded value never appears.  The padding is itself the signal that
    the value cannot be re-valued, so it is taken as such.
    """

    def test_padding_a_name_is_detected(self):
        for original, padded in (
            ("PDF", "PDF document"),
            ("Pinata", "Pinata pinning service"),
            ("IPFS", "IPFS storage layer"),
        ):
            self.assertTrue(_pads_original(original, padded), f"{original!r}")

    def test_a_real_substitution_is_not_padding(self):
        for original, replacement in (
            ("$500", "$750"),
            ("5", "8"),
            ("only NFT holders", "access limited to verified buyers"),
        ):
            self.assertFalse(_pads_original(original, replacement), f"{original!r}")

    def test_padding_a_number_is_still_padding(self):
        """Detected here, but rejected rather than preserved -- see the caller."""

        self.assertTrue(_pads_original("5", "5 winners"))

    def test_an_unchanged_value_is_not_padding(self):
        self.assertFalse(_pads_original("PDF", "PDF"))


class ViolationSeverityTests(unittest.TestCase):
    """Safety blocks; fidelity and style defer to the independent verifier.

    Over a full 824-message project the gate raised 218 violations, 8 of them
    safety-critical and 210 fidelity or style.  Every one of the 210 is also
    judged semantically by phase 4, which reads the plan and can tell "the
    number was dropped" from "$20 was written as twenty dollars" -- a
    distinction string matching cannot make.
    """

    def test_pii_residue_always_blocks(self):
        for item in (
            "REWRITE_RESIDUAL_ORIGINAL_ENTITY: E0007 (abc123abc123) survived",
            "REWRITE_PII_REINTRODUCED: unplanned EMAIL abc123abc123",
            "REWRITE_PROTECTED_TOKEN_DAMAGED: token count 2 -> 1",
            "REWRITE_LEGACY_PLACEHOLDER: [PERSON_001] present",
            "REWRITE_FAKE_CREDENTIAL: FAKE_API_KEY_ABC present",
        ):
            self.assertEqual(split_violations([item]), ([item], []), item)

    def test_an_unchanged_rewrite_always_blocks(self):
        """The one path that would silently ship the original text."""

        item = "REWRITE_UNCHANGED: the rewrite is identical to its source"
        self.assertEqual(split_violations([item]), ([item], []))

    def test_polarity_always_blocks(self):
        item = "REWRITE_POLARITY_CHANGED: the negation was dropped"
        self.assertEqual(split_violations([item]), ([item], []))

    def test_list_marker_damage_blocks_before_the_final_audit(self):
        item = "REWRITE_LIST_MARKER_DAMAGED: ordered-list numbering changed"
        self.assertEqual(split_violations([item]), ([item], []))

    def test_slot_surface_fidelity_and_style_are_advisory(self):
        for item in (
            "REWRITE_PLAN_MAPPING_VIOLATED: slot PRIZE new value was not applied",
            "REWRITE_STRUCTURE_UNCHANGED: sentence structure was not changed",
            "REWRITE_WORD_BAND_VIOLATED: short rewrite grew to 11 words",
        ):
            self.assertEqual(split_violations([item]), ([], [item]), item)

    def test_entity_mapping_public_terms_and_semantic_anchors_block(self):
        for item in (
            "REWRITE_PLAN_MAPPING_VIOLATED: E0007 replacement was not applied",
            "REWRITE_PRESERVED_TERM_ALTERED: abc123abc123 count 2 -> 1",
            "REWRITE_SEMANTIC_ANCHOR_CHANGED: production changed to staging",
        ):
            self.assertEqual(split_violations([item]), ([item], []), item)

    def test_public_term_may_be_consolidated_but_not_removed(self):
        slice_ = MessagePlanSlice(
            ordinal=1,
            message_id=1,
            bucket="LONG",
            safe_text_sha256="x" * 64,
            entity_replacements=(),
            slot_replacements=(),
            secret_tokens=(),
            preserve_literals=("Pinata",),
            must_replace_terms=(),
            semantic_expectations={},
            relation_constraints=(),
            plan_version=1,
        )
        source = _safe("Pinata stores the file, and Pinata supplies its CID.", "LONG")
        kept = rewrite_violations(source, "The file and its CID are both managed in Pinata.", slice_)
        removed = rewrite_violations(source, "The file and its CID are managed elsewhere.", slice_)
        self.assertFalse(any("PRESERVED_TERM_ALTERED" in item for item in kept))
        self.assertTrue(any("PRESERVED_TERM_ALTERED" in item for item in removed))

    def test_a_surviving_slot_literal_is_advisory_but_an_entity_is_not(self):
        """Same code, opposite severity: one is a stale value, one is a leak."""

        slot = "REWRITE_RESIDUAL_ORIGINAL_ENTITY: slot PRIZE kept its original literal"
        entity = "REWRITE_RESIDUAL_ORIGINAL_ENTITY: E0007 (abc123abc123) survived"
        blocking, advisory = split_violations([slot, entity])
        self.assertEqual(blocking, [entity])
        self.assertEqual(advisory, [slot])


class LexicalNegationTests(unittest.TestCase):
    """Negation is often lexical, and the marker set only knows function words.

    Phase 1A calls "ETH mint attempt failed" and "access denied" NEGATIVE, which
    is right, but neither carries a ``no``/``not``/``don't``.  Requiring one to
    survive demanded the rewrite *add* a marker the original never had -- and in
    one case fought the plan, which maps "access denied" to "viewer remains
    locked".
    """

    def slice_for(self, polarity: str) -> MessagePlanSlice:
        return MessagePlanSlice(
            ordinal=1, message_id=1, bucket="SHORT", safe_text_sha256="x" * 64,
            entity_replacements=(), slot_replacements=(), secret_tokens=(),
            preserve_literals=(), must_replace_terms=(),
            semantic_expectations={"polarity": polarity},
            relation_constraints=(), plan_version=1,
        )

    def violations(self, source, candidate, polarity="NEGATIVE"):
        return [
            item
            for item in rewrite_violations(
                _safe(source, "SHORT"), candidate, self.slice_for(polarity)
            )
            if "POLARITY" in item
        ]

    def test_lexical_negation_needs_no_marker(self):
        self.assertEqual(self.violations("ETH mint attempt failed", "The mint run did not go through"), [])
        self.assertEqual(self.violations("access denied!", "viewer remains locked"), [])

    def test_dropping_an_explicit_marker_is_still_caught(self):
        self.assertTrue(self.violations("Please don't merge yet.", "Please merge it now."))

    def test_inventing_a_negation_is_still_caught(self):
        self.assertTrue(
            self.violations("Please merge it now.", "Do not merge it.", "AFFIRMATIVE")
        )


class PublicUrlTests(unittest.TestCase):
    """A vendor home page standing in the source is policy, not a leak."""

    def slice_(self) -> MessagePlanSlice:
        return MessagePlanSlice(
            ordinal=1, message_id=1, bucket="LONG", safe_text_sha256="x" * 64,
            entity_replacements=(), slot_replacements=(), secret_tokens=(),
            preserve_literals=(), must_replace_terms=(), semantic_expectations={},
            relation_constraints=(), plan_version=1,
        )

    def url_violations(self, source, candidate):
        return [
            item
            for item in rewrite_violations(_safe(source, "LONG"), candidate, self.slice_())
            if "unplanned URL" in item
        ]

    def test_a_source_url_may_survive(self):
        self.assertEqual(
            self.url_violations(
                "You can create a https://stripe.com/ account and share the keys with me.",
                "Set up an account at https://stripe.com/ and pass the credentials over.",
            ),
            [],
        )

    def test_an_invented_url_is_still_rejected(self):
        self.assertTrue(
            self.url_violations(
                "You can create an account and share the keys with me.",
                "Sign up at https://totally-made-up.example/ and send the keys.",
            )
        )


class CompositeUrlTests(unittest.TestCase):
    """A link assembled from parts must not publish the part it was built from.

    ``https://<public-explorer>/address/<real wallet>`` was planned as
    ``https://<synthetic host>/address/<real wallet>``: the public half was
    disguised and the private half shipped.  The same address therefore had two
    fates depending on whether it stood alone or sat inside a URL -- and the
    real one went out in the URL.
    """

    def test_a_replacement_carrying_another_original_is_rejected(self):
        wallet = "0xE5Ede832957259EbCc3b2034aA8367ebFC843Ce0"
        registry = PiiEntityRegistry(
            entities=(
                entity("E0001", "WALLET_ADDRESS", wallet, None, (1,)),
                entity(
                    "E0002",
                    "PRIVATE_URL",
                    f"https://northstar.io/address/{wallet}",
                    None,
                    (1,),
                ),
            ),
            bundles=(),
        )
        chunk = PlanChunk(1, ("E0001", "E0002"), ())
        payload = {
            "replacements": [
                {"entity_id": "E0001", "replacement": "0xd4b861e2a7095c3f8e1d4a67b2c9503e6f8a1d24"},
                # host swapped, real wallet left in the path
                {
                    "entity_id": "E0002",
                    "replacement": f"https://ledgerline-demo.example/address/{wallet}",
                },
            ]
        }
        with self.assertRaises(PlanConsistencyError) as caught:
            validate_entity_chunk(payload, chunk, registry, {})
        self.assertIn("PLAN_RESIDUAL_PII", caught.exception.failures)

    def test_applying_the_inner_replacement_is_accepted(self):
        wallet = "0xE5Ede832957259EbCc3b2034aA8367ebFC843Ce0"
        synthetic = "0xd4b861e2a7095c3f8e1d4a67b2c9503e6f8a1d24"
        registry = PiiEntityRegistry(
            entities=(
                entity("E0001", "WALLET_ADDRESS", wallet, None, (1,)),
                entity(
                    "E0002", "PRIVATE_URL", f"https://northstar.io/address/{wallet}", None, (1,)
                ),
            ),
            bundles=(),
        )
        chunk = PlanChunk(1, ("E0001", "E0002"), ())
        payload = {
            "replacements": [
                {"entity_id": "E0001", "replacement": synthetic},
                {
                    "entity_id": "E0002",
                    "replacement": f"https://ledgerline-demo.example/address/{synthetic}",
                },
            ]
        }
        self.assertEqual(
            set(validate_entity_chunk(payload, chunk, registry, {})), {"E0001", "E0002"}
        )

    def test_a_public_host_must_be_kept(self):
        preserved = frozenset({"explorer.example.org"})
        self.assertIn(
            "public host",
            _masking_failure(
                "PRIVATE_URL",
                "https://explorer.example.org/address/0xabc",
                "https://ledgerline-demo.example/address/0xdef",
                preserved,
            )
            or "",
        )

    def test_a_public_host_with_a_changed_path_is_accepted(self):
        preserved = frozenset({"explorer.example.org"})
        self.assertIsNone(
            _masking_failure(
                "PRIVATE_URL",
                "https://explorer.example.org/address/0xabc",
                "https://explorer.example.org/address/0xdef",
                preserved,
            )
        )

    def test_public_host_is_restored_locally_before_validation(self):
        public_company = replace(
            entity("E0001", "PUBLIC_THIRD_PARTY", "Google", None, (1,)),
            policy="PRESERVE",
        )
        private_link = entity(
            "E0002",
            "PRIVATE_URL",
            "https://docs.google.com/document/d/real-document-id/edit",
            "B0001",
            (2,),
        )
        registry = PiiEntityRegistry(
            entities=(public_company, private_link),
            bundles=(IdentityBundle("B0001", "PROJECT_IDENTITY", ("E0002",)),),
        )
        chunk = PlanChunk(1, ("E0002",), ("B0001",))
        payload = {
            "replacements": [
                {
                    "entity_id": "E0002",
                    "replacement": (
                        "https://ledgerline-demo.example/document/d/"
                        "fictional-document-id/edit"
                    ),
                }
            ]
        }

        result = validate_entity_chunk(payload, chunk, registry, {})

        self.assertEqual(
            result["E0002"].replacement,
            "https://docs.google.com/document/d/fictional-document-id/edit",
        )

    def test_public_url_must_change_more_than_its_host(self):
        preserved = frozenset({"google"})
        self.assertIn(
            "private path",
            _masking_failure(
                "PRIVATE_URL",
                "https://docs.google.com/document/d/real-document-id/edit",
                "https://docs.google.com/document/d/real-document-id/edit",
                preserved,
            )
            or "",
        )

    def test_a_private_host_still_must_change(self):
        self.assertIsNotNone(
            _masking_failure(
                "PRIVATE_URL",
                "https://northstar.io/status",
                "https://northstar.io/health",
                frozenset(),
            )
        )

    def test_public_hosted_site_brand_does_not_preserve_private_subdomain(self):
        preserved = frozenset({"webflow", "webflow.io"})
        self.assertIsNotNone(
            _masking_failure(
                "PRIVATE_URL",
                "https://private-client.webflow.io/contact",
                "https://private-client.webflow.io/revised-contact",
                preserved,
            )
        )
        self.assertIsNone(
            _masking_failure(
                "PRIVATE_URL",
                "https://private-client.webflow.io/contact",
                "https://cobalt-harbor.example/contact",
                preserved,
            )
        )

    def test_public_host_swap_cannot_hide_a_retained_private_app_id(self):
        private_id = "k6j6pbuyhm4bgcdd"
        original = f"https://dashboard.vendor.example/apps/{private_id}/webhooks"
        replacement = f"https://dashboard-demo.example/apps/{private_id}/webhooks"
        self.assertEqual(private_resource_identifiers(original), (private_id,))
        self.assertIn(
            "private resource identifier",
            _masking_failure("PRIVATE_URL", original, replacement) or "",
        )

    def test_real_meeting_host_cannot_be_reused(self):
        self.assertIn(
            "reserved synthetic host",
            _masking_failure(
                "MEETING_URL",
                "https://meet.google.com/abc-defg-hij",
                "https://meet.google.com/xyz-uvwx-rst",
            )
            or "",
        )


class SemanticAnchorRegressionTests(unittest.TestCase):
    def test_high_impact_requirement_inversions_are_detected(self):
        cases = (
            ("Deploy to production.", "Deploy to staging."),
            ("Launch crypto only.", "Launch fiat only."),
            ("Use Base Mainnet.", "Use Base Sepolia."),
            ("Apply a one-time off-chain adjustment.", "Apply an on-chain adjustment."),
            ("Continue the backend and front end milestone.", "Continue the API and QA milestone."),
        )
        for source, candidate in cases:
            self.assertTrue(semantic_anchor_differences(source, candidate), source)

    def test_candidate_only_equivalent_detail_is_not_a_local_failure(self):
        self.assertEqual(
            semantic_anchor_differences("Fix the UI.", "Fix the frontend UI."),
            (),
        )


class PreservedRequirementTermTests(unittest.TestCase):
    """Phase 1A's ``must_preserve_terms`` has to reach the phase-2 slot channel.

    ``plan_slice`` folds those terms into a slice's ``preserve_literals``, so the
    rewrite gate enforces them.  The slot validator never received them, so it
    re-valued exactly those literals -- planning ``.pdf`` -> ``.tiff`` and
    ``STEP`` -> ``IGES``.  The resulting slice demanded both "keep this
    verbatim" and "replace this", which no rewrite can satisfy: the messages
    surfaced as agent tasks no text could close, and the requirement they
    carried had quietly become a different requirement.
    """

    def semantics_with(self, *terms: str, ordinal: int = 1) -> MessageSemantics:
        return MessageSemantics(
            ordinal=ordinal,
            message_id=ordinal,
            speech_act="REQUEST",
            polarity="AFFIRMATIVE",
            execution_status="PENDING",
            ambiguity_kind="NONE",
            decisions=(),
            slots=(),
            semantic_facts=(
                {
                    "kind": "TECHNOLOGY",
                    "statement": "a delivery format is specified",
                    "polarity": "AFFIRMATIVE",
                    "must_preserve_terms": list(terms),
                },
            ),
        )

    def test_a_requirement_term_reaches_the_slot_channel(self):
        registry = build_entity_registry()
        terms = semantic_preserve_terms([self.semantics_with("PDF", "STEP")], registry)
        self.assertEqual(terms, frozenset({"pdf", "step"}))

    def test_a_term_a_synthesize_entity_owns_is_not_preserved(self):
        """Phase 1A is contracted not to file a private name here.

        When it does anyway -- a location, a client organisation, a project name
        -- honouring it would pin a real identity into the output, because the
        same slice also carries that identity's SYNTHESIZE mapping.  Identity
        removal is the higher invariant, so the entity decision wins.
        """

        registry = build_entity_registry()
        terms = semantic_preserve_terms(
            [self.semantics_with("PDF", "Joseph", "northstar.io")], registry
        )
        self.assertEqual(terms, frozenset({"pdf"}))

    def test_a_slice_drops_a_preserve_term_its_own_plan_replaces(self):
        slice_ = plan_slice(
            build_plan(),
            safe_message(1),
            entity_registry=build_entity_registry(),
            semantic_registry=build_semantic_registry(),
            semantics=self.semantics_with("PDF", "Joseph"),
        )
        self.assertIn("PDF", slice_.preserve_literals)
        self.assertNotIn("Joseph", slice_.preserve_literals)

    def test_global_preserve_term_cannot_override_identity_removal(self):
        slice_ = plan_slice(
            build_plan(),
            safe_message(1),
            entity_registry=build_entity_registry(),
            semantic_registry=build_semantic_registry(),
            semantics=self.semantics_with("PDF"),
            preserve_terms=("Joseph",),
        )
        self.assertNotIn("Joseph", slice_.preserve_literals)

    def test_preserved_phrase_cannot_embed_a_synthesized_identity(self):
        slice_ = plan_slice(
            build_plan(),
            safe_message(1),
            entity_registry=build_entity_registry(),
            semantic_registry=build_semantic_registry(),
            semantics=self.semantics_with("PDF"),
            preserve_terms=("Joseph framework",),
        )
        self.assertNotIn("Joseph framework", slice_.preserve_literals)

    def test_exact_slot_edit_overrides_a_broader_preserve_phrase(self):
        text = "Use Sales Navigator Advance for prospecting."
        start = text.index("Advance")
        semantic_slot = SemanticSlot(
            slot_id="SALES_NAVIGATOR_TIER",
            kind="BUSINESS",
            value_type="OTHER",
            unit=None,
            current_value="Advance",
            meaning="selected Sales Navigator tier",
            history=(SlotHistoryEntry(1, "INTRODUCE", None, "Advance"),),
            source_literals=("Advance",),
            message_ordinals=(1,),
            literal_occurrences=(
                SlotLiteralOccurrence(
                    1, 1, start, start + len("Advance"), "Advance"
                ),
            ),
        )
        slot_decision = SlotReplacement(
            slot_id="SALES_NAVIGATOR_TIER",
            value_type="OTHER",
            history=(SlotHistoryEntry(1, "INTRODUCE", None, "Advanced"),),
            literal_replacements=(
                SlotLiteralReplacement(
                    1,
                    1,
                    start,
                    start + len("Advance"),
                    "Advance",
                    "Advanced",
                    "EXACT",
                ),
            ),
        )
        plan = TransformationPlan(
            plan_version=1,
            entity_replacements=(),
            slot_replacements=(slot_decision,),
            secret_replacements=(),
        )
        safe = replace(
            safe_message(1),
            safe_text=text,
            safe_text_sha256=canonical_sha256(text),
            source_text_sha256=canonical_sha256(text),
            word_count=len(text.split()),
        )
        slice_ = plan_slice(
            plan,
            safe,
            entity_registry=PiiEntityRegistry(entities=(), bundles=()),
            semantic_registry=SemanticRegistry(
                slots=(semantic_slot,), relations=(), decisions=()
            ),
            semantics=self.semantics_with("Sales Navigator Advance"),
        )
        self.assertNotIn("Sales Navigator Advance", slice_.preserve_literals)


class OnlyPreservedValueTests(unittest.TestCase):
    """A slot value that *is* a requirement term has only one correct answer.

    A slot records the value as written, so one requirement arrives as ``PDF``,
    ``.pdf``, ``PDFs`` or ``PDF+DWG``, and a list of them arrives with the
    connectives that joined it.  Exact-string matching recognised only the bare
    form, so every other spelling fell through to a hard
    ``PLAN_PRESERVED_TERM_DROPPED`` -- for a value whose only correct answer is
    itself, since re-valuing it necessarily drops the term.
    """

    preserved = frozenset({"pdf", "dwg", "iges", "sat", "ifc"})

    def test_decorated_and_pluralised_spellings_are_the_same_requirement(self):
        for value in (".pdf", "PDF", "PDFs", "PDF+DWG", "SAT, IGES or IFC"):
            with self.subTest(value=value):
                self.assertTrue(_is_only_preserved(value, self.preserved))

    def test_a_value_carrying_anything_else_still_gets_re_valued(self):
        for value in ("PDF document", "3 PDFs", "the client PDF template", "300 pages"):
            with self.subTest(value=value):
                self.assertFalse(_is_only_preserved(value, self.preserved))

    def test_nothing_is_preserved_without_a_preserved_set(self):
        self.assertFalse(_is_only_preserved(".pdf", frozenset()))


class PlannedShapeContainmentTests(unittest.TestCase):
    """A PII shape inside a planned value is that value, not a second one.

    Phase 2 routinely plans a *decorated* value: a Slack mention
    ``<@id:id|Name>``, an angle-bracketed link, an autolink's ``url|label``.
    Comparing a regex match for equality against the planned set cannot see
    that the bare handle or link inside one of those already *is* planned, so
    the gate rejected correctly-planned text as having reintroduced PII -- a
    verdict no rewrite could clear, because removing the shape would drop the
    mapping the same gate demands.
    """

    def slice_with(self, *replacements: str) -> MessagePlanSlice:
        return MessagePlanSlice(
            ordinal=1,
            message_id=1,
            bucket="LONG",
            safe_text_sha256="x" * 64,
            entity_replacements=tuple(
                EntityReplacement(
                    entity_id=f"E{index:04d}",
                    entity_type="SOCIAL_ACCOUNT",
                    policy="SYNTHESIZE",
                    original=f"original-{index}",
                    replacement=value,
                    bundle_id=None,
                )
                for index, value in enumerate(replacements, start=1)
            ),
            slot_replacements=(),
            secret_tokens=(),
            preserve_literals=(),
            must_replace_terms=(),
            semantic_expectations={},
            relation_constraints=(),
            plan_version=1,
        )

    def reintroduced(self, source: str, candidate: str, *replacements: str):
        return [
            item
            for item in rewrite_violations(
                _safe(source, "LONG"), candidate, self.slice_with(*replacements)
            )
            if "REWRITE_PII_REINTRODUCED" in item
        ]

    def test_a_handle_inside_a_planned_mention_is_planned(self):
        mention = "<@1704826159032741888:1704826159032741889|Darius Mercer>"
        self.assertEqual(
            self.reintroduced(
                "Please loop in <@1691932955036610560:1691932955036610561|Cleavon Lasten>.",
                f"Could you bring {mention} into the thread?",
                mention,
            ),
            [],
        )

    def test_a_link_inside_a_planned_angle_bracket_is_planned(self):
        wrapped = "<https://www.youtube.com/@ardenvalevideo>"
        self.assertEqual(
            self.reintroduced(
                "Channel is <https://www.youtube.com/@tonalexina>",
                f"The channel lives at {wrapped}",
                wrapped,
            ),
            [],
        )

    def test_a_shape_outside_every_planned_value_is_still_reported(self):
        mention = "<@1704826159032741888:1704826159032741889|Darius Mercer>"
        violations = self.reintroduced(
            "Please loop in <@1691932955036610560:1691932955036610561|Cleavon Lasten>.",
            f"Bring {mention} in, and copy @someone_else too.",
            mention,
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("HANDLE", violations[0])

    def test_an_autolink_label_is_not_an_unplanned_address(self):
        """``|`` is Slack's label delimiter, never an address character here.

        Admitting it into the local part made the match start one character
        early, so it matched neither the planned value nor anything inside one.
        """

        planned_url = "http://elias.ward@emberfield-studio.example?"
        planned_mail = "elias.ward@emberfield-studio.example"
        self.assertEqual(
            self.reintroduced(
                "Share it with <http://joshua@fireandspark.com?|joshua@fireandspark.com?>",
                f"Please share it with <{planned_url}|{planned_mail}?>",
                planned_url,
                planned_mail,
            ),
            [],
        )

    def test_link_syntax_does_not_become_part_of_an_address(self):
        """``|`` and ``/`` are delimiters here, not local-part characters.

        Admitting them made the match start early.  The pipe form matched
        neither the planned value nor anything inside one; the slash form was
        worse, because the audit's host parser truncates at the first ``/`` and
        so read the host as empty -- reporting a reserved ``.example`` address
        as an original one.
        """

        text = (
            "<http://elias.ward@emberfield-studio.example?"
            "|elias.ward@emberfield-studio.example?>"
        )
        self.assertEqual(
            [match.group(0) for match in EMAIL_RE.finditer(text)],
            [
                "elias.ward@emberfield-studio.example",
                "elias.ward@emberfield-studio.example",
            ],
        )


class PlannedNegationTests(unittest.TestCase):
    """A negation word the plan supplied is not a negation the rewrite added.

    The guard's own subject is polarity, not function words.  One slot maps
    ``immediately`` to ``without delay`` -- the same polarity, but ``without``
    is a negation marker, so applying the plan and keeping the polarity became
    mutually exclusive and the message had no satisfiable rewrite at all.
    """

    def slice_with(self, original: str, replacement: str) -> MessagePlanSlice:
        return MessagePlanSlice(
            ordinal=1,
            message_id=1,
            bucket="SHORT",
            safe_text_sha256="x" * 64,
            entity_replacements=(),
            slot_replacements=(
                SlotReplacement(
                    slot_id="DELIVERY_TIMING",
                    value_type="OTHER",
                    history=(),
                    literal_replacements=(
                        SlotLiteralReplacement(
                            ordinal=1,
                            message_id=1,
                            start=0,
                            end=len(original),
                            original=original,
                            replacement=replacement,
                            match_mode="EXACT",
                        ),
                    ),
                ),
            ),
            secret_tokens=(),
            preserve_literals=(),
            must_replace_terms=(),
            semantic_expectations={"polarity": "AFFIRMATIVE"},
            relation_constraints=(),
            plan_version=1,
        )

    def polarity_violations(self, source: str, candidate: str, original, replacement):
        return [
            item
            for item in rewrite_violations(
                _safe(source, "SHORT"), candidate, self.slice_with(original, replacement)
            )
            if "POLARITY" in item
        ]

    def test_a_marker_carried_in_by_the_plan_is_not_a_new_negation(self):
        self.assertEqual(
            self.polarity_violations(
                "i will send immediately", "I will send without delay",
                "immediately", "without delay",
            ),
            [],
        )

    def test_a_negation_the_rewrite_invented_is_still_reported(self):
        violations = self.polarity_violations(
            "i will send immediately", "I will not send without delay",
            "immediately", "without delay",
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("a negation was introduced", violations[0])


class EntitySlotDoubleClaimTests(unittest.TestCase):
    """The two phase-2 channels must not price the same literal differently.

    Identities and requirement values are decided in separate calls, and
    nothing stops both from claiming one literal.  A message asking that a
    document's footer code match its report version had the codes mapped once
    as identities and again as footer values, to different strings.  Applying
    both satisfies each rule in isolation and destroys the relation the message
    states, so it is a re-plan, not a rewrite.
    """

    def task(self, entity_replacement: str, slot_replacement: str) -> dict:
        return {
            "must_apply_entities": [
                {
                    "entity_id": "E0011",
                    "entity_type": "ACCOUNT_IDENTIFIER",
                    "policy": "SYNTHESIZE",
                    "original_surface_forms": ["RR-01"],
                    "replacement": entity_replacement,
                    "alias_replacements": [],
                }
            ],
            "must_apply_slots": [
                {
                    "slot_id": "FOOTER_REPORT_CODE",
                    "literal_replacements": [
                        {
                            "ordinal": 1,
                            "message_id": 1,
                            "start": 0,
                            "end": 5,
                            "original": "RR-01",
                            "replacement": slot_replacement,
                            "match_mode": "EXACT",
                        }
                    ],
                }
            ],
        }

    def test_divergent_replacements_for_one_literal_are_a_conflict(self):
        self.assertEqual(
            _entity_slot_conflicts(self.task("LV21", "AX-17")),
            ["FOOTER_REPORT_CODE"],
        )

    def test_the_two_channels_agreeing_is_not_a_conflict(self):
        self.assertEqual(_entity_slot_conflicts(self.task("LV21", "LV21")), [])


class OneReferentTwoSpellingsTests(unittest.TestCase):
    """Phase 0B records one thing twice when the source spells it two ways.

    An address written ``Washington DC`` in one message and ``Washington, DC``
    in the next becomes two entities, and phase 2 correctly gives both the same
    synthetic value.  The collision guards exempt entities that share an
    original surface form, but compared those forms exactly -- so a single comma
    made the exemption miss and reported the correct plan as a collision, in
    both phase 2 and the phase-6B audit.
    """

    def plan_for(self, first: str, second: str) -> TransformationPlan:
        return TransformationPlan(
            plan_version=1,
            entity_replacements=(
                EntityReplacement(
                    entity_id="E0011", entity_type="ADDRESS", policy="SYNTHESIZE",
                    original=first, replacement="2846 Alder Lane, Philadelphia PA",
                    bundle_id=None,
                ),
                EntityReplacement(
                    entity_id="E0022", entity_type="ADDRESS", policy="SYNTHESIZE",
                    original=second, replacement="2846 Alder Lane, Philadelphia PA",
                    bundle_id=None,
                ),
            ),
            slot_replacements=(),
            secret_replacements=(),
        )

    def collisions(self, plan: TransformationPlan) -> list[str]:
        surfaces = {
            item.entity_id: {normalized_surface(o) for o, _ in item.pairs()}
            for item in plan.synthesized()
        }
        found = []
        for left in plan.synthesized():
            for right in plan.synthesized():
                if left.entity_id >= right.entity_id:
                    continue
                shares = surfaces[left.entity_id] & surfaces[right.entity_id]
                same = set(left.replacements()) & set(right.replacements())
                if same and not shares:
                    found.append(f"{left.entity_id}/{right.entity_id}")
        return found

    def test_spellings_differing_only_in_punctuation_are_one_referent(self):
        plan = self.plan_for(
            "1717 K Street NW, Washington DC 20006",
            "1717 K Street NW, Washington, DC 20006",
        )
        self.assertEqual(self.collisions(plan), [])

    def test_two_different_addresses_sharing_a_replacement_still_collide(self):
        plan = self.plan_for(
            "1717 K Street NW, Washington DC 20006",
            "40 Harbour Road, Bristol BS1 4RN",
        )
        self.assertEqual(self.collisions(plan), ["E0011/E0022"])


class ContradictoryPolicyTests(unittest.TestCase):
    """One value filed under both policies must not be preserved.

    Phase 0B can read a client's brand once as a public third party and once as
    the project's own name, giving the same literal a PRESERVE entity and a
    SYNTHESIZE one.  Keeping it in the preserved set asks the plan to preserve a
    literal it is simultaneously required to remove -- unsatisfiable, and on the
    wrong side of the invariant that outranks it.
    """

    def registry(self, *entries) -> PiiEntityRegistry:
        return PiiEntityRegistry(
            entities=tuple(
                replace(
                    entity(entity_id, entity_type, value, None, (1,)), policy=policy
                )
                for entity_id, entity_type, value, policy in entries
            ),
            bundles=(),
        )

    def test_a_value_some_entity_must_remove_is_not_preserved(self):
        forms = preserved_surface_forms(
            self.registry(
                ("E0011", "PUBLIC_THIRD_PARTY", "Fishwife", "PRESERVE"),
                ("E0018", "PROJECT_NAME", "Fishwife", "SYNTHESIZE"),
            )
        )
        self.assertNotIn("fishwife", forms)

    def test_an_uncontested_public_name_is_still_preserved(self):
        forms = preserved_surface_forms(
            self.registry(
                ("E0011", "PUBLIC_THIRD_PARTY", "Stripe", "PRESERVE"),
                ("E0018", "PROJECT_NAME", "Fishwife", "SYNTHESIZE"),
            )
        )
        self.assertIn("stripe", forms)


class SlotCarryingRealValueTests(unittest.TestCase):
    """A slot's synthetic value must not be built around a real name.

    Slots and identities are decided in separate calls, so the slot channel can
    return a filename or a deadline still containing a real project name or
    place -- publishing a true value while presenting it as synthetic.  The
    correction is forced: the entity channel has already decided what that name
    becomes.
    """

    def test_a_real_name_inside_a_slot_value_takes_the_planned_replacement(self):
        registry = PiiEntityRegistry(
            entities=(entity("E0025", "PROJECT_NAME", "Bestyrelsesseminar", None, (1,)),),
            bundles=(),
        )
        decisions = {
            "E0025": EntityReplacement(
                entity_id="E0025", entity_type="PROJECT_NAME", policy="SYNTHESIZE",
                original="Bestyrelsesseminar", replacement="Strategiforum",
                bundle_id=None,
            )
        }
        pairs = entity_substitutions(registry, decisions)
        self.assertEqual(
            _without_real_values("Bestyrelsesseminar v38.docx", pairs),
            "Strategiforum v38.docx",
        )

    def test_an_unrelated_value_is_left_alone(self):
        self.assertEqual(_without_real_values("report v38.docx", []), "report v38.docx")

    def test_entity_aliases_are_substituted_with_their_own_planned_forms(self):
        registry = PiiEntityRegistry(
            entities=(entity("E0025", "PROJECT_NAME", "Project Lighthouse", None, (1,)),),
            bundles=(),
        )
        decisions = {
            "E0025": EntityReplacement(
                entity_id="E0025",
                entity_type="PROJECT_NAME",
                policy="SYNTHESIZE",
                original="Project Lighthouse",
                replacement="Project Northstar",
                aliases=(EntityAlias(original="Lighthouse", replacement="Northstar"),),
                bundle_id=None,
            )
        }
        pairs = entity_substitutions(registry, decisions)
        self.assertEqual(_without_real_values("Lighthouse brief.pdf", pairs), "Northstar brief.pdf")

    def test_entity_decision_overrides_an_unrelated_slot_invention(self):
        pairs = [("Report-Code-17", "Report-Code-82")]
        self.assertEqual(
            _entity_authoritative_value("Report-Code-17", "Report-Code-41", pairs),
            "Report-Code-82",
        )

    def test_short_entity_surface_is_only_used_for_an_exact_slot_source(self):
        pairs = [("R2", "N7")]
        self.assertEqual(_entity_authoritative_value("R2", "Q4", pairs), "N7")
        self.assertEqual(_without_real_values("section R2", pairs), "section R2")

    def test_equal_aliases_are_disambiguated_by_message_ordinal(self):
        registry = PiiEntityRegistry(
            entities=(
                entity("E0001", "IDENTIFIER", "R2", None, (10,)),
                entity("E0002", "IDENTIFIER", "R2", None, (20,)),
            ),
            bundles=(),
        )
        decisions = {
            "E0001": EntityReplacement(
                "E0001", "IDENTIFIER", "SYNTHESIZE", "R2", "N7"
            ),
            "E0002": EntityReplacement(
                "E0002", "IDENTIFIER", "SYNTHESIZE", "R2", "K4"
            ),
        }
        contextual = entity_occurrence_substitutions(registry, decisions)
        self.assertEqual(contextual[(10, "r2")], "N7")
        self.assertEqual(contextual[(20, "r2")], "K4")

    def test_duplicate_slot_occurrence_is_applied_once(self):
        occurrence = {
            "ordinal": 1,
            "start": 5,
            "end": 8,
            "original": "ABC",
            "replacement": "XYZ",
            "match_mode": "EXACT",
        }
        task = {
            "must_apply_slots": [
                {"literal_replacements": [occurrence]},
                {"literal_replacements": [dict(occurrence)]},
            ]
        }
        self.assertEqual(_apply_slots("Code ABC", task), "Code XYZ")

    def test_nested_slot_occurrence_uses_the_outer_position_safe_edit(self):
        task = {
            "must_apply_slots": [
                {
                    "literal_replacements": [
                        {
                            "ordinal": 1,
                            "start": 5,
                            "end": 14,
                            "original": "ABC - DEF",
                            "replacement": "North Star",
                            "match_mode": "EXACT",
                        }
                    ]
                },
                {
                    "literal_replacements": [
                        {
                            "ordinal": 1,
                            "start": 9,
                            "end": 10,
                            "original": "-",
                            "replacement": "/",
                            "match_mode": "EXACT",
                        }
                    ]
                },
            ]
        }
        self.assertEqual(_apply_slots("Book ABC - DEF", task), "Book North Star")

    def test_offline_numeric_generation_keeps_units_but_changes_value(self):
        value = _synthetic_slot_value(
            "MAX_DISTANCE", "5 mm", "DIMENSION", frozenset({"mm"})
        )
        self.assertEqual(value, "10 mm")

    def test_preserved_filename_term_is_a_separate_token(self):
        value = _restore_missing_preserved_terms(
            "current BOM file", "northstar-asset.jpg", frozenset({"bom"})
        )
        self.assertIn("bom", value.casefold())
        self.assertEqual(
            _preserved_terms_in(value, frozenset({"bom"})), {"bom"}
        )
