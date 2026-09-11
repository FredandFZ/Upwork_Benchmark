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
from dataclasses import replace

from Code.PII.config import BUCKET_LONG
from Code.PII.errors import PlanConsistencyError
from Code.PII.models import (
    EntityReplacement,
    IdentityBundle,
    PiiEntity,
    PiiEntityRegistry,
    PiiOccurrence,
    SafeMessage,
    SecretRegistry,
    SemanticRegistry,
    SemanticSlot,
    SlotHistoryEntry,
    SlotRelation,
    SlotReplacement,
    TransformationPlan,
)
from Code.PII.phase2_plan import (
    PlanChunk,
    SlotCluster,
    assemble_plan,
    bundle_chunks,
    plan_slice,
    reserved_values,
    slot_clusters,
    validate_entity_chunk,
    validate_plan,
    validate_slot_cluster,
)
from Code.PII.textutil import canonical_sha256


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
            literal_map={},
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
            self.payload(E0001="sk_" "live_51H8xYzAbCdEfGhIjKlMnOpQr"),
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
        return {
            "slot_replacements": [
                {
                    "slot_id": "WINNER_COUNT",
                    "history": [{"new_value": count}],
                    "literal_map": {"5": count},
                },
                {
                    "slot_id": "PRIZE",
                    "history": [{"new_value": prize}],
                    "literal_map": {"10000": prize},
                },
                {
                    "slot_id": "POOL",
                    "history": [{"new_value": pool}],
                    "literal_map": {"50000": pool},
                },
            ]
        }

    def test_arithmetically_consistent_values_are_accepted(self):
        result = validate_slot_cluster(
            self.payload("7", "12500", "87500"), self.cluster, self.registry
        )
        self.assertEqual(set(result), {"WINNER_COUNT", "PRIZE", "POOL"})

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
