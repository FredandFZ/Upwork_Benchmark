"""Phase 2: one coherent project-wide synthetic transformation plan.

The design problem is that "one plan, consistent across the whole project" has
to coexist with projects of 1000+ messages.  The resolution is to chunk so that
every constraint is *intra-chunk*, and to enforce every *global* invariant
locally:

* **Entity chunks are whole identity bundles.**  A person with their address and
  username, or an organization with its domain, repository and links, is never
  split -- so intra-bundle coherence is structural rather than checked.
  Cross-chunk uniqueness is handled by passing ``RESERVED_VALUES`` (everything
  already allocated, in deterministic order) and rejecting collisions by name.
* **Slot chunks are arithmetic closures.**  ``{winner_count, prize, pool}`` is
  decided in a single call, so ``5 x 10000 = 50000`` can become
  ``7 x 12500 = 87500`` coherently.  The validator recomputes every relation
  with :class:`~decimal.Decimal` instead of trusting the model.
* **Assembly is local and deterministic**, so ``plan.json``'s output hash is
  stable whenever the chunks are -- which is what keeps every phase-3 slice hash
  stable, and therefore what makes per-message rewrite checkpoints reusable.

:func:`plan_slice` computes the **transitive closure** of the plan decisions a
message must honour.  That closure is the soundness condition for per-message
checkpointing: without it, a rewrite referencing a replacement that changed
elsewhere would restore as valid and the contradiction would only surface in the
final project-wide audit, with no trail back to its cause.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence

from .config import RESERVED_DOMAIN_SUFFIX
from .errors import PlanConsistencyError, marked
from .models import (
    EntityAlias,
    EntityReplacement,
    MessagePlanSlice,
    MessageSemantics,
    PiiEntity,
    PiiEntityRegistry,
    SafeMessage,
    SecretPlanEntry,
    SecretRegistry,
    SemanticRegistry,
    SlotHistoryEntry,
    SlotReplacement,
    TransformationPlan,
)
from .phase0b_entities import (
    POLICY_PRESERVE,
    POLICY_PROTECTED,
    POLICY_SYNTHESIZE,
)
from .phase1b_consolidate import evaluate_relation, numeric_value, relation_clusters
from .secret_shield import nominate_secret_spans
from .textutil import (
    EMAIL_RE,
    FAKE_CREDENTIAL_RE,
    INTERNAL_TOKEN_RE,
    LEGACY_PLACEHOLDER_RE,
    PHONE_RE,
    RESERVED_DOMAIN_RE,
    URL_RE,
    WORD_RE,
    canonical_json,
    contains_value,
    similarity_ratio,
)

MODE_ENTITY_CHUNK = "ENTITY_CHUNK"
MODE_SLOT_CLUSTER = "SLOT_CLUSTER"

# Types whose replacement must itself look like that kind of value.
HOSTED_TYPES = frozenset({"EMAIL", "PRIVATE_URL", "MEETING_URL", "PRIVATE_REPOSITORY"})

# A replacement this similar to its original is a light mask, not a replacement.
MAX_SIMILARITY = 0.7

TASK_ENTITIES = (
    "Generate realistic but fictional replacements for the supplied private entities, "
    "keeping every entity inside one identity bundle mutually consistent."
)
TASK_SLOTS = (
    "Generate substantially different replacement values for the supplied requirement "
    "slots, preserving data types, history chains and arithmetic relations."
)

REPAIR_INSTRUCTION_ENTITIES = (
    "The previous response failed local validation. Return one replacement for every "
    "supplied entity_id. A PRESERVE entity must keep its original value unchanged. A "
    "SYNTHESIZE replacement must differ substantially from its original, must not be a "
    "lightly masked variant of it, must not equal any reserved value or any other "
    f"entity's original, and every synthetic domain must end in '{RESERVED_DOMAIN_SUFFIX}'. "
    "Within one bundle, the address local part must derive from the synthetic person name "
    "and every address, link and repository must use that bundle's synthetic domain. Never "
    "produce a value that looks like a usable credential."
)
REPAIR_INSTRUCTION_SLOTS = (
    "The previous response failed local validation. Return one replacement for every "
    "supplied slot_id. Keep the same number of history entries with the same ordinals and "
    "ops, keep the data type and unit, make every new value different from the original, "
    "and choose values that make every supplied relation hold exactly."
)


@dataclass(frozen=True)
class PlanChunk:
    """Whole identity bundles, never split."""

    index: int
    entity_ids: tuple[str, ...]
    bundle_ids: tuple[str, ...]

    @property
    def chunk_id(self) -> str:
        return f"chunk_{self.index:04d}"


@dataclass(frozen=True)
class SlotCluster:
    """Slots tied by arithmetic, decided in one call."""

    index: int
    slot_ids: tuple[str, ...]

    @property
    def cluster_id(self) -> str:
        return f"cluster_{self.index:04d}"


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #


def planned_entities(registry: PiiEntityRegistry) -> tuple[PiiEntity, ...]:
    """Entities the plan must decide: everything except shielded secrets."""

    return tuple(
        entity for entity in registry.entities if entity.policy != POLICY_PROTECTED
    )


def bundle_groups(registry: PiiEntityRegistry) -> list[tuple[str | None, tuple[str, ...]]]:
    """Bundles first (in id order), then unbundled entities as singletons."""

    grouped: list[tuple[str | None, tuple[str, ...]]] = []
    planned = {entity.entity_id for entity in planned_entities(registry)}
    for bundle in registry.bundles:
        members = tuple(item for item in bundle.entity_ids if item in planned)
        if members:
            grouped.append((bundle.bundle_id, members))
    bundled = {item for _bundle_id, members in grouped for item in members}
    for entity in planned_entities(registry):
        if entity.entity_id not in bundled:
            grouped.append((None, (entity.entity_id,)))
    return grouped


def bundle_chunks(
    registry: PiiEntityRegistry, *, max_bundles: int, max_chars: int
) -> list[PlanChunk]:
    groups = bundle_groups(registry)
    by_id = registry.by_id()
    chunks: list[PlanChunk] = []
    current_entities: list[str] = []
    current_bundles: list[str] = []
    current_chars = 0
    for bundle_id, members in groups:
        size = sum(
            len(by_id[item].canonical_value) + 80 for item in members if item in by_id
        )
        if current_entities and (
            len(current_bundles) >= max_bundles or current_chars + size > max_chars
        ):
            chunks.append(
                PlanChunk(len(chunks) + 1, tuple(current_entities), tuple(current_bundles))
            )
            current_entities, current_bundles, current_chars = [], [], 0
        current_entities.extend(members)
        if bundle_id is not None:
            current_bundles.append(bundle_id)
        current_chars += size
    if current_entities:
        chunks.append(
            PlanChunk(len(chunks) + 1, tuple(current_entities), tuple(current_bundles))
        )
    return chunks


def slot_clusters(registry: SemanticRegistry, *, max_chars: int) -> list[SlotCluster]:
    """Arithmetic closures as their own clusters; isolated slots batched freely."""

    clusters = relation_clusters(registry)
    tied = [group for group in clusters if len(group) > 1]
    loose = [group[0] for group in clusters if len(group) == 1]

    result: list[SlotCluster] = []
    for group in tied:
        result.append(SlotCluster(len(result) + 1, group))

    by_id = registry.by_id()
    current: list[str] = []
    current_chars = 0
    for slot_id in loose:
        slot = by_id.get(slot_id)
        size = len(canonical_json(slot.to_json())) if slot is not None else 120
        if current and current_chars + size > max_chars:
            result.append(SlotCluster(len(result) + 1, tuple(current)))
            current, current_chars = [], 0
        current.append(slot_id)
        current_chars += size
    if current:
        result.append(SlotCluster(len(result) + 1, tuple(current)))
    return result


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


def build_entity_sections(
    chunk: PlanChunk,
    registry: PiiEntityRegistry,
    reserved: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    by_id = registry.by_id()
    bundle_by_id = registry.bundle_by_id()
    return {
        "MODE": MODE_ENTITY_CHUNK,
        "POLICY": {
            "reserved_domain_suffix": RESERVED_DOMAIN_SUFFIX,
            "max_similarity_to_original": MAX_SIMILARITY,
        },
        "PII_ENTITIES": [
            {
                "entity_id": entity_id,
                "entity_type": by_id[entity_id].entity_type,
                "policy": by_id[entity_id].policy,
                "original": by_id[entity_id].canonical_value,
                "surface_forms": list(by_id[entity_id].surface_forms()),
                "bundle_id": by_id[entity_id].bundle_id,
            }
            for entity_id in chunk.entity_ids
            if entity_id in by_id
        ],
        "IDENTITY_BUNDLES": [
            bundle_by_id[bundle_id].to_json()
            for bundle_id in chunk.bundle_ids
            if bundle_id in bundle_by_id
        ],
        "RESERVED_VALUES": {key: list(values) for key, values in sorted(reserved.items())},
    }


def build_slot_sections(
    cluster: SlotCluster, registry: SemanticRegistry
) -> dict[str, Any]:
    by_id = registry.by_id()
    relations = [
        relation.to_json()
        for relation in registry.relations
        if set(relation.slot_ids) & set(cluster.slot_ids)
    ]
    return {
        "MODE": MODE_SLOT_CLUSTER,
        "SLOT_CLUSTER": [
            by_id[slot_id].to_json() for slot_id in cluster.slot_ids if slot_id in by_id
        ],
        "CONSTRAINTS": relations,
    }


# --------------------------------------------------------------------------- #
# Entity chunk validation
# --------------------------------------------------------------------------- #


def _domain_of(value: str) -> str:
    host = value.split("://", 1)[-1]
    host = host.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    host = host.split("@", 1)[-1]
    return host.split(":", 1)[0].strip("<>").casefold()


def _local_part(value: str) -> str:
    return value.split("@", 1)[0].casefold()


def _retains_original(original: str, replacement: str) -> bool:
    """Whether the replacement keeps the original value intact.

    ``Joseph`` -> ``Joseph Smith`` scores only 0.67 on token similarity yet
    preserves the identifying name completely, so containment is checked
    separately in both directions.
    """

    left = original.strip()
    right = replacement.strip()
    if len(left) < 3 or len(right) < 3:
        return False
    return contains_value(right, left) or contains_value(left, right)


def _looks_like_credential(value: str) -> bool:
    return bool(
        nominate_secret_spans(value)
        or FAKE_CREDENTIAL_RE.search(value)
        or INTERNAL_TOKEN_RE.search(value)
        or LEGACY_PLACEHOLDER_RE.search(value)
    )


def _type_shape_failure(entity_type: str, replacement: str) -> str | None:
    if entity_type == "EMAIL":
        if not EMAIL_RE.fullmatch(replacement):
            return "replacement is not a syntactically valid address"
    elif entity_type == "PHONE":
        if not PHONE_RE.search(replacement):
            return "replacement is not phone-shaped"
    elif entity_type in {"PRIVATE_URL", "MEETING_URL"}:
        if not URL_RE.match(replacement):
            return "replacement is not a link"
    elif entity_type == "PERSON":
        if any(character.isdigit() for character in replacement) or "@" in replacement:
            return "a person name must not contain digits or '@'"
    elif entity_type == "PRIVATE_DOMAIN":
        if "/" in replacement or "@" in replacement or " " in replacement:
            return "a domain must not contain '/', '@' or spaces"
    return None


def validate_entity_chunk(
    payload: Mapping[str, Any],
    chunk: PlanChunk,
    registry: PiiEntityRegistry,
    reserved: Mapping[str, Sequence[str]],
) -> dict[str, EntityReplacement]:
    failures: list[str] = []

    def fail(code: str, detail: str) -> None:
        failures.append(f"{code}: {detail}")

    raw = payload.get("replacements")
    if not isinstance(raw, list):
        raise PlanConsistencyError(
            marked("PLAN_SCHEMA_INVALID: response must contain a replacements list"),
            failures=("PLAN_SCHEMA_INVALID",),
        )

    by_id = registry.by_id()
    wanted = [item for item in chunk.entity_ids if item in by_id]
    reserved_flat = {
        value.casefold() for values in reserved.values() for value in values
    }
    all_originals = {
        entity.canonical_value.casefold(): entity.entity_id
        for entity in registry.entities
    }

    result: dict[str, EntityReplacement] = {}
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            fail("PLAN_SCHEMA_INVALID", f"replacements[{index}] must be an object")
            continue
        entity_id = entry.get("entity_id")
        if entity_id not in by_id or entity_id not in chunk.entity_ids:
            fail("PLAN_SCHEMA_INVALID", f"replacements[{index}] has an unknown entity_id")
            continue
        if entity_id in result:
            fail("PLAN_SCHEMA_INVALID", f"{entity_id} appears twice")
            continue
        entity = by_id[entity_id]
        replacement = entry.get("replacement")
        if not isinstance(replacement, str) or not replacement.strip():
            fail("PLAN_SCHEMA_INVALID", f"{entity_id} has no replacement")
            continue
        replacement = replacement.strip()

        if _looks_like_credential(replacement):
            # Checked before everything else: a generated credential is the most
            # severe failure class, and an earlier rejection must not mask it.
            fail(
                "PLAN_CREDENTIAL_GENERATED",
                f"{entity_id} replacement looks like a usable credential",
            )
            continue

        if entity.policy == POLICY_PRESERVE:
            if replacement != entity.canonical_value:
                fail(
                    "PLAN_SCHEMA_INVALID",
                    f"{entity_id} is PRESERVE and must keep its original value",
                )
                continue
        else:
            if replacement.casefold() == entity.canonical_value.casefold():
                fail("PLAN_IDENTITY", f"{entity_id} replacement equals its original")
                continue
            if similarity_ratio(entity.canonical_value, replacement) > MAX_SIMILARITY:
                fail(
                    "PLAN_IDENTITY",
                    f"{entity_id} replacement is a lightly masked variant of the original",
                )
                continue
            if _retains_original(entity.canonical_value, replacement):
                fail(
                    "PLAN_IDENTITY",
                    f"{entity_id} replacement still contains the original value",
                )
                continue
            owner = all_originals.get(replacement.casefold())
            if owner is not None and owner != entity_id:
                fail(
                    "PLAN_COLLISION",
                    f"{entity_id} replacement equals another entity's original",
                )
                continue
            if replacement.casefold() in reserved_flat:
                fail("PLAN_COLLISION", f"{entity_id} replacement is already reserved")
                continue
            shape = _type_shape_failure(entity.entity_type, replacement)
            if shape is not None:
                fail("PLAN_SCHEMA_INVALID", f"{entity_id} {shape}")
                continue
            if entity.entity_type == "PRIVATE_DOMAIN" and not RESERVED_DOMAIN_RE.search(
                replacement
            ):
                fail(
                    "PLAN_REAL_LOOKING_VALUE",
                    f"{entity_id} synthetic domain must end in {RESERVED_DOMAIN_SUFFIX}",
                )
                continue
            if entity.entity_type in HOSTED_TYPES and not RESERVED_DOMAIN_RE.search(
                _domain_of(replacement)
            ):
                fail(
                    "PLAN_REAL_LOOKING_VALUE",
                    f"{entity_id} host {_domain_of(replacement)!r} is not a reserved domain",
                )
                continue
        if _looks_like_credential(replacement):
            fail(
                "PLAN_CREDENTIAL_GENERATED",
                f"{entity_id} replacement looks like a usable credential",
            )
            continue

        aliases: list[EntityAlias] = []
        for alias in entry.get("aliases") or []:
            if not isinstance(alias, dict):
                continue
            original = alias.get("original")
            value = alias.get("replacement")
            if (
                isinstance(original, str)
                and isinstance(value, str)
                and original.strip()
                and value.strip()
                and original.strip() in entity.surface_forms()
            ):
                if value.strip().casefold() == original.strip().casefold():
                    fail("PLAN_IDENTITY", f"{entity_id} alias replacement equals its original")
                    continue
                aliases.append(
                    EntityAlias(original=original.strip(), replacement=value.strip())
                )

        result[entity_id] = EntityReplacement(
            entity_id=entity_id,
            entity_type=entity.entity_type,
            policy=entity.policy,
            original=entity.canonical_value,
            replacement=replacement,
            bundle_id=entity.bundle_id,
            aliases=tuple(aliases),
            depends_on=tuple(
                item
                for item in (entry.get("depends_on") or [])
                if isinstance(item, str) and item in by_id
            ),
        )

    missing = [item for item in wanted if item not in result]
    if missing:
        fail("PLAN_INCOMPLETE", f"no replacement for {missing[:20]}")

    failures.extend(_bundle_failures(result, registry, chunk))

    if failures:
        raise PlanConsistencyError(
            marked("phase 2 entity chunk invalid: " + "; ".join(failures[:10])),
            failures=tuple(item.split(":", 1)[0] for item in failures),
        )
    return result


def _bundle_failures(
    replacements: Mapping[str, EntityReplacement],
    registry: PiiEntityRegistry,
    chunk: PlanChunk,
) -> list[str]:
    """Intra-bundle coherence: one identity, one domain, one derived local part."""

    failures: list[str] = []
    by_id = registry.by_id()
    for bundle_id in chunk.bundle_ids:
        bundle = registry.bundle_by_id().get(bundle_id)
        if bundle is None:
            continue
        members = [
            replacements[item]
            for item in bundle.entity_ids
            if item in replacements and replacements[item].policy == POLICY_SYNTHESIZE
        ]
        if not members:
            continue
        domains = {
            _domain_of(item.replacement)
            for item in members
            if item.entity_type in HOSTED_TYPES or item.entity_type == "PRIVATE_DOMAIN"
        }
        domains.discard("")
        if len(domains) > 1:
            failures.append(
                f"PLAN_SCHEMA_INVALID: bundle {bundle_id} spreads across domains "
                f"{sorted(domains)}"
            )
        persons = [item for item in members if item.entity_type == "PERSON"]
        emails = [item for item in members if item.entity_type == "EMAIL"]
        if len(persons) == 1 and emails:
            tokens = {
                token.casefold()
                for token in WORD_RE.findall(persons[0].replacement)
                if len(token) >= 3
            }
            for email in emails:
                local = _local_part(email.replacement)
                if tokens and not any(token in local for token in tokens):
                    failures.append(
                        f"PLAN_SCHEMA_INVALID: bundle {bundle_id} address local part "
                        "does not derive from the synthetic person name"
                    )
        # Every member of a bundle must actually be in this chunk.
        absent = [
            item
            for item in bundle.entity_ids
            if item in by_id
            and by_id[item].policy != POLICY_PROTECTED
            and item not in replacements
        ]
        if absent:
            failures.append(
                f"PLAN_INCOMPLETE: bundle {bundle_id} was split across chunks ({absent[:5]})"
            )
    return failures


# --------------------------------------------------------------------------- #
# Slot cluster validation
# --------------------------------------------------------------------------- #


def validate_slot_cluster(
    payload: Mapping[str, Any], cluster: SlotCluster, registry: SemanticRegistry
) -> dict[str, SlotReplacement]:
    failures: list[str] = []

    def fail(code: str, detail: str) -> None:
        failures.append(f"{code}: {detail}")

    raw = payload.get("slot_replacements")
    if not isinstance(raw, list):
        raise PlanConsistencyError(
            marked("PLAN_SCHEMA_INVALID: response must contain a slot_replacements list"),
            failures=("PLAN_SCHEMA_INVALID",),
        )

    by_id = registry.by_id()
    result: dict[str, SlotReplacement] = {}

    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            fail("PLAN_SCHEMA_INVALID", f"slot_replacements[{index}] must be an object")
            continue
        slot_id = entry.get("slot_id")
        if slot_id not in by_id or slot_id not in cluster.slot_ids:
            fail("PLAN_SCHEMA_INVALID", f"slot_replacements[{index}] unknown slot_id")
            continue
        if slot_id in result:
            fail("PLAN_SCHEMA_INVALID", f"{slot_id} appears twice")
            continue
        slot = by_id[slot_id]
        raw_history = entry.get("history")
        if not isinstance(raw_history, list) or len(raw_history) != len(slot.history):
            fail(
                "PLAN_SCHEMA_INVALID",
                f"{slot_id} must keep exactly {len(slot.history)} history entries",
            )
            continue
        history: list[SlotHistoryEntry] = []
        broken = False
        for position, (source, item) in enumerate(zip(slot.history, raw_history)):
            if not isinstance(item, dict):
                fail("PLAN_SCHEMA_INVALID", f"{slot_id} history[{position}] must be an object")
                broken = True
                break
            new_value = item.get("new_value")
            if not isinstance(new_value, str) or not new_value.strip():
                fail("PLAN_SCHEMA_INVALID", f"{slot_id} history[{position}] has no new_value")
                broken = True
                break
            if new_value.strip() == source.new_value:
                fail(
                    "PLAN_IDENTITY",
                    f"{slot_id} history[{position}] keeps the original value",
                )
                broken = True
                break
            if (numeric_value(source.new_value) is None) != (
                numeric_value(new_value) is None
            ):
                fail(
                    "PLAN_SCHEMA_INVALID",
                    f"{slot_id} history[{position}] changed the value's data type",
                )
                broken = True
                break
            history.append(
                SlotHistoryEntry(
                    ordinal=source.ordinal,
                    op=source.op,
                    old_value=history[-1].new_value if history else None,
                    new_value=new_value.strip(),
                )
            )
        if broken:
            continue

        raw_map = entry.get("literal_map")
        if not isinstance(raw_map, dict):
            fail("PLAN_SCHEMA_INVALID", f"{slot_id} has no literal_map")
            continue
        literal_map: dict[str, str] = {}
        for key, value in raw_map.items():
            if not isinstance(key, str) or not isinstance(value, str) or not value.strip():
                fail("PLAN_SCHEMA_INVALID", f"{slot_id} literal_map has a malformed entry")
                continue
            if value.strip() == key:
                fail("PLAN_IDENTITY", f"{slot_id} literal_map keeps a literal unchanged")
                continue
            literal_map[key] = value.strip()
        expected_literals = set(slot.source_literals)
        if expected_literals and set(literal_map) != expected_literals:
            fail(
                "PLAN_SCHEMA_INVALID",
                f"{slot_id} literal_map keys must be exactly the recorded source literals",
            )
            continue
        for value in literal_map.values():
            if _looks_like_credential(value):
                fail("PLAN_CREDENTIAL_GENERATED", f"{slot_id} literal looks like a credential")
                break

        result[slot_id] = SlotReplacement(
            slot_id=slot_id,
            value_type=slot.value_type,
            history=tuple(history),
            literal_map=literal_map,
        )

    missing = [item for item in cluster.slot_ids if item in by_id and item not in result]
    if missing:
        fail("PLAN_INCOMPLETE", f"no replacement for slots {missing[:20]}")

    # Relations must hold under the *new* values, exactly.
    if not failures:
        failures.extend(_relation_failures(result, cluster, registry))

    if failures:
        raise PlanConsistencyError(
            marked("phase 2 slot cluster invalid: " + "; ".join(failures[:10])),
            failures=tuple(item.split(":", 1)[0] for item in failures),
        )
    return result


def _relation_failures(
    replacements: Mapping[str, SlotReplacement],
    cluster: SlotCluster,
    registry: SemanticRegistry,
) -> list[str]:
    failures: list[str] = []
    cluster_ids = set(cluster.slot_ids)
    for relation in registry.relations:
        if not set(relation.slot_ids) & cluster_ids:
            continue
        if not set(relation.slot_ids) <= set(replacements):
            # The relation reaches outside this cluster; it is checked once the
            # plan is assembled.
            continue
        for ordinal in relation.asserted_at_ordinals or (None,):
            values: dict[str, Decimal] = {}
            for slot_id in relation.slot_ids:
                value = _value_at(replacements[slot_id], ordinal)
                parsed = numeric_value(value)
                if parsed is not None:
                    values[slot_id] = parsed
            if len(values) != len(relation.slot_ids):
                continue
            if evaluate_relation(relation.expression, values) is False:
                failures.append(
                    "PLAN_RELATION_BROKEN: "
                    f"{relation.relation_id} does not hold under the new values at "
                    f"ordinal {ordinal}"
                )
                break
    return failures


def _value_at(replacement: SlotReplacement, ordinal: int | None) -> str:
    if not replacement.history:
        return ""
    if ordinal is None:
        return replacement.history[-1].new_value
    current = replacement.history[0].new_value
    for entry in replacement.history:
        if entry.ordinal <= ordinal:
            current = entry.new_value
    return current


# --------------------------------------------------------------------------- #
# Assembly and global validation
# --------------------------------------------------------------------------- #


def reserved_values(replacements: Mapping[str, EntityReplacement]) -> dict[str, list[str]]:
    """Everything already allocated, grouped for the next chunk's prompt."""

    buckets: dict[str, list[str]] = {}
    for item in sorted(replacements.values(), key=lambda value: value.entity_id):
        if item.policy != POLICY_SYNTHESIZE:
            continue
        key = "domains" if item.entity_type == "PRIVATE_DOMAIN" else item.entity_type.lower()
        for value in item.replacements():
            buckets.setdefault(key, []).append(value)
        if item.entity_type in HOSTED_TYPES:
            host = _domain_of(item.replacement)
            if host:
                buckets.setdefault("domains", []).append(host)
    return {key: sorted(set(values)) for key, values in sorted(buckets.items())}


def assemble_plan(
    entity_parts: Mapping[str, EntityReplacement],
    slot_parts: Mapping[str, SlotReplacement],
    secret_registry: SecretRegistry,
    semantic_registry: SemanticRegistry,
    *,
    plan_version: int = 1,
    amendments: Sequence[Mapping[str, Any]] = (),
) -> TransformationPlan:
    """Merge the chunks deterministically.

    Pure and order-independent, so the plan's output hash is stable whenever its
    chunks are -- which is what keeps phase-3 slice hashes reusable.
    """

    entities = tuple(entity_parts[key] for key in sorted(entity_parts))
    slots = tuple(slot_parts[key] for key in sorted(slot_parts))
    secrets = tuple(
        SecretPlanEntry(
            secret_id=entry.secret_id,
            internal_token=entry.internal_token,
            kind=entry.kind,
        )
        for entry in secret_registry.secrets
    )
    checks: list[dict[str, Any]] = []
    for relation in semantic_registry.relations:
        if not set(relation.slot_ids) <= set(slot_parts):
            continue
        values = {
            slot_id: numeric_value(_value_at(slot_parts[slot_id], None))
            for slot_id in relation.slot_ids
        }
        if any(value is None for value in values.values()):
            checks.append(
                {"relation_id": relation.relation_id, "satisfied": None, "evaluated": None}
            )
            continue
        outcome = evaluate_relation(
            relation.expression, {key: value for key, value in values.items() if value}
        )
        checks.append(
            {
                "relation_id": relation.relation_id,
                "satisfied": outcome,
                "evaluated": relation.expression,
            }
        )
    return TransformationPlan(
        plan_version=plan_version,
        entity_replacements=entities,
        slot_replacements=slots,
        secret_replacements=secrets,
        relation_checks=tuple(checks),
        reserved_values={
            key: tuple(values) for key, values in reserved_values(entity_parts).items()
        },
        amendments=tuple(dict(item) for item in amendments),
    )


def validate_plan(
    plan: TransformationPlan,
    *,
    entity_registry: PiiEntityRegistry,
    semantic_registry: SemanticRegistry,
    secret_registry: SecretRegistry,
) -> None:
    """Every global invariant, enforced locally after assembly."""

    failures: list[str] = []

    planned_ids = {entity.entity_id for entity in planned_entities(entity_registry)}
    covered = set(plan.entity_by_id())
    missing = sorted(planned_ids.difference(covered))
    if missing:
        failures.append(f"PLAN_INCOMPLETE: entities without a decision {missing[:20]}")
    unexpected = sorted(covered.difference(planned_ids))
    if unexpected:
        failures.append(f"PLAN_SCHEMA_INVALID: unknown entities in plan {unexpected[:20]}")

    slot_ids = {slot.slot_id for slot in semantic_registry.slots}
    slot_missing = sorted(slot_ids.difference(plan.slot_by_id()))
    if slot_missing:
        failures.append(f"PLAN_INCOMPLETE: slots without a decision {slot_missing[:20]}")

    secret_ids = {entry.secret_id for entry in secret_registry.secrets}
    plan_secret_ids = {entry.secret_id for entry in plan.secret_replacements}
    if secret_ids != plan_secret_ids:
        failures.append("PLAN_INCOMPLETE: secret entries do not match the shield registry")
    for entry in plan.secret_replacements:
        if entry.replacement is not None:
            failures.append(
                f"PLAN_CREDENTIAL_GENERATED: secret {entry.secret_id} carries a value; "
                "phase 6A owns credential rendering"
            )

    # Uniqueness across the whole plan, per type.
    by_type: dict[str, dict[str, str]] = {}
    for item in plan.synthesized():
        owners = by_type.setdefault(item.entity_type, {})
        for value in item.replacements():
            key = value.casefold()
            if key in owners and owners[key] != item.entity_id:
                failures.append(
                    f"PLAN_COLLISION: {item.entity_type} replacement shared by "
                    f"{owners[key]} and {item.entity_id}"
                )
            owners[key] = item.entity_id

    originals = {
        entity.canonical_value.casefold(): entity.entity_id
        for entity in entity_registry.entities
    }
    for item in plan.synthesized():
        for value in item.replacements():
            owner = originals.get(value.casefold())
            if owner is not None and owner != item.entity_id:
                failures.append(
                    f"PLAN_COLLISION: {item.entity_id} reuses {owner}'s original value"
                )
        for value in item.replacements():
            if _looks_like_credential(value):
                failures.append(
                    f"PLAN_CREDENTIAL_GENERATED: {item.entity_id} value looks like a credential"
                )

    # Relations must hold across cluster boundaries too.
    all_slots = plan.slot_by_id()
    for relation in semantic_registry.relations:
        if not set(relation.slot_ids) <= set(all_slots):
            continue
        for ordinal in relation.asserted_at_ordinals or (None,):
            values = {}
            for slot_id in relation.slot_ids:
                parsed = numeric_value(_value_at(all_slots[slot_id], ordinal))
                if parsed is not None:
                    values[slot_id] = parsed
            if len(values) != len(relation.slot_ids):
                continue
            if evaluate_relation(relation.expression, values) is False:
                failures.append(
                    f"PLAN_RELATION_BROKEN: {relation.relation_id} fails at ordinal {ordinal}"
                )
                break

    if failures:
        raise PlanConsistencyError(
            marked("transformation plan invalid: " + "; ".join(failures[:10])),
            failures=tuple(item.split(":", 1)[0] for item in failures),
        )


# --------------------------------------------------------------------------- #
# Per-message slice -- the transitive closure
# --------------------------------------------------------------------------- #


def plan_slice(
    plan: TransformationPlan,
    safe: SafeMessage,
    *,
    entity_registry: PiiEntityRegistry,
    semantic_registry: SemanticRegistry,
    semantics: MessageSemantics | None,
    preserve_terms: Sequence[str] = (),
) -> MessagePlanSlice:
    """Every plan decision this message must honour, as a transitive closure.

    The closure is the message's own entities, **plus every entity in the same
    identity bundle** (changing a person must invalidate a message that only
    mentions their address), **plus every slot in the same arithmetic cluster**
    (changing a count must invalidate a message that only mentions the total),
    plus the secret tokens present.  Given that, slice-hash equality really does
    imply the cached rewrite is still correct.
    """

    entity_by_id = plan.entity_by_id()
    bundles = entity_registry.bundle_by_id()

    own = [
        entity.entity_id
        for entity in entity_registry.for_ordinal(safe.ordinal)
        if entity.entity_id in entity_by_id
    ]
    closure: set[str] = set(own)
    for entity_id in own:
        replacement = entity_by_id[entity_id]
        if replacement.bundle_id and replacement.bundle_id in bundles:
            closure.update(
                item
                for item in bundles[replacement.bundle_id].entity_ids
                if item in entity_by_id
            )
        closure.update(item for item in replacement.depends_on if item in entity_by_id)

    slot_by_id = plan.slot_by_id()
    own_slots = [
        slot.slot_id
        for slot in semantic_registry.for_ordinal(safe.ordinal)
        if slot.slot_id in slot_by_id
    ]
    slot_closure: set[str] = set(own_slots)
    for group in relation_clusters(semantic_registry):
        if slot_closure & set(group):
            slot_closure.update(item for item in group if item in slot_by_id)

    relation_constraints = tuple(
        relation.expression
        for relation in semantic_registry.relations
        if set(relation.slot_ids) & slot_closure
    )

    expectations: dict[str, Any] = {}
    if semantics is not None:
        expectations = {
            "speech_act": semantics.speech_act,
            "polarity": semantics.polarity,
            "execution_status": semantics.execution_status,
            "ambiguity_kind": semantics.ambiguity_kind,
            "decisions": [dict(item) for item in semantics.decisions],
            "relations": list(semantics.relations),
        }

    preserved = tuple(
        item.replacement
        for item in plan.preserved()
        if any(
            occurrence.ordinal == safe.ordinal
            for entity in (entity_registry.by_id().get(item.entity_id),)
            if entity is not None
            for occurrence in entity.occurrences
        )
    )

    return MessagePlanSlice(
        ordinal=safe.ordinal,
        message_id=safe.message_id,
        bucket=safe.bucket,
        safe_text_sha256=safe.safe_text_sha256,
        entity_replacements=tuple(
            entity_by_id[entity_id] for entity_id in sorted(closure)
        ),
        slot_replacements=tuple(slot_by_id[slot_id] for slot_id in sorted(slot_closure)),
        secret_tokens=safe.secret_tokens,
        preserve_literals=tuple(sorted({*preserved, *preserve_terms})),
        must_replace_terms=(),
        semantic_expectations=expectations,
        relation_constraints=relation_constraints,
        plan_version=plan.plan_version,
    )
