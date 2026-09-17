"""Phase 1B: fold per-message semantics into one project-level registry.

A **linear** fold, not a pairwise tree: merging is order-dependent (history
chains and canonical naming both depend on what came before), so a tree fold
would produce different registries for different parallelization and destroy
hash stability.  Each fold's scope includes the previous fold's output hash, so
a change at message 300 invalidates only the folds covering 300..N.

The accumulator has a hard size cap and **raises rather than truncating**.
Silently dropping part of the accumulator would lose requirement history, which
is the single thing this phase exists to preserve.

Arithmetic is re-checked locally with :class:`~decimal.Decimal`.  Asking a model
to be careful with ``5 x 10000 = 50000`` is far less reliable than recomputing
it, and phase 2 depends on these relations being true.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from decimal import Decimal, DecimalException
from typing import Any, Mapping, Sequence

from .errors import PiiError, PiiValidationError, marked
from .models import (
    MessageSemantics,
    SemanticRegistry,
    SemanticSlot,
    SlotHistoryEntry,
    SlotLiteralOccurrence,
    SlotRelation,
)
from .textutil import canonical_json

MODE_SEED = "SEED"
MODE_FOLD = "FOLD"

SLOT_KINDS: tuple[str, ...] = ("BUSINESS", "TECHNICAL", "SCHEDULE", "PROCESS", "OTHER")
HISTORY_OPS: tuple[str, ...] = ("INTRODUCE", "MODIFY", "CONFIRM", "REMOVE")
RELATION_KINDS: tuple[str, ...] = ("PRODUCT", "SUM", "RATIO", "DIFFERENCE", "EQUALITY", "OTHER")

SLOT_ID_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")

TASK = (
    "Consolidate the supplied per-message semantic records into one project-level "
    "registry, preserving every requirement history chain and arithmetic relation."
)

REPAIR_INSTRUCTION = (
    "The previous response failed local validation. Return only a delta: new_slots, "
    "updated_slots, merged_from, new_relations, new_decisions. Do not re-emit the "
    "accumulator -- anything you do not mention is carried forward for you. Every slot "
    "named in the supplied records must be accounted for exactly once, as a new slot, as "
    "an updated slot, or as a key of merged_from. History entries carry only ordinal, op "
    "and new_value, in message order. Every relation expression must use the form "
    "'LHS = RHS' over existing slot_ids and must evaluate exactly."
)


@dataclass(frozen=True)
class SemanticFold:
    index: int
    records: tuple[MessageSemantics, ...]

    @property
    def fold_id(self) -> str:
        return f"fold_{self.index:04d}"


def build_folds(
    records: Sequence[MessageSemantics], *, max_chars: int, max_records: int
) -> list[SemanticFold]:
    """Chunk records in ordinal order by serialized size and count."""

    ordered = sorted(records, key=lambda item: item.ordinal)
    folds: list[SemanticFold] = []
    current: list[MessageSemantics] = []
    current_chars = 0
    for record in ordered:
        size = len(canonical_json(record.to_json()))
        if current and (len(current) >= max_records or current_chars + size > max_chars):
            folds.append(SemanticFold(len(folds) + 1, tuple(current)))
            current = []
            current_chars = 0
        current.append(record)
        current_chars += size
    if current:
        folds.append(SemanticFold(len(folds) + 1, tuple(current)))
    return folds


def accumulator_catalogue(accumulator: SemanticRegistry | None) -> dict[str, Any]:
    """A compact index of what already exists, without the histories.

    The model needs the accumulator to decide *which* existing slot a new
    mention belongs to.  It does not need each slot's full history to make that
    decision, and sending it back only inflates the response it has to produce.
    """

    if accumulator is None:
        return {"slots": [], "relations": []}
    return {
        "slots": [
            {
                "slot_id": slot.slot_id,
                "kind": slot.kind,
                "value_type": slot.value_type,
                "unit": slot.unit,
                "current_value": slot.current_value,
                "meaning": slot.meaning,
            }
            for slot in accumulator.slots
        ],
        "relations": [
            {"relation_id": item.relation_id, "expression": item.expression}
            for item in accumulator.relations
        ],
    }


def build_sections(
    fold: SemanticFold, accumulator: SemanticRegistry | None
) -> dict[str, Any]:
    return {
        "MODE": MODE_SEED if accumulator is None else MODE_FOLD,
        "POLICY": {
            "slot_kinds": list(SLOT_KINDS),
            "history_ops": list(HISTORY_OPS),
            "relation_kinds": list(RELATION_KINDS),
            "slot_id_pattern": SLOT_ID_RE.pattern,
        },
        "SEMANTIC_ACCUMULATOR": accumulator_catalogue(accumulator),
        "SEMANTIC_RECORDS": [record.to_json() for record in fold.records],
    }


# --------------------------------------------------------------------------- #
# Numeric evaluation
# --------------------------------------------------------------------------- #

_NUMERIC_RE = re.compile(r"-?\d+(?:[\d,]*\d)?(?:\.\d+)?")

_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.USub,
    ast.UAdd,
)


def numeric_value(text: str) -> Decimal | None:
    """Best-effort numeric reading of a slot literal.

    Handles ``5``, ``5 winners``, ``$10,000``, ``12.5%`` and ``50,000 sales``.
    Returns ``None`` when there is no number to read, which makes the relation
    non-checkable rather than false.
    """

    if text is None:
        return None
    match = _NUMERIC_RE.search(str(text))
    if match is None:
        return None
    candidate = match.group(0).replace(",", "")
    try:
        return Decimal(candidate)
    except (DecimalException, ValueError):
        return None


def _evaluate_node(node: ast.AST, values: Mapping[str, Decimal]) -> Decimal:
    if not isinstance(node, _ALLOWED_NODES):
        raise ValueError(f"unsupported expression element {type(node).__name__}")
    if isinstance(node, ast.Expression):
        return _evaluate_node(node.body, values)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("only numeric constants are allowed")
        return Decimal(str(node.value))
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise ValueError(f"unknown slot {node.id}")
        return values[node.id]
    if isinstance(node, ast.UnaryOp):
        operand = _evaluate_node(node.operand, values)
        return -operand if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.BinOp):
        left = _evaluate_node(node.left, values)
        right = _evaluate_node(node.right, values)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ValueError("division by zero")
            return left / right
    raise ValueError("unsupported expression")


def evaluate_relation(expression: str, values: Mapping[str, Decimal]) -> bool | None:
    """Whether ``LHS = RHS`` holds exactly.

    ``None`` means "not checkable" (a missing value or an unparseable side) --
    deliberately distinct from ``False``, so an unreadable relation is recorded
    rather than treated as a violation.
    """

    if "=" not in expression:
        return None
    left_text, _, right_text = expression.partition("=")
    if not left_text.strip() or not right_text.strip():
        return None
    try:
        left = _evaluate_node(ast.parse(left_text.strip(), mode="eval"), values)
        right = _evaluate_node(ast.parse(right_text.strip(), mode="eval"), values)
    except (SyntaxError, ValueError, DecimalException):
        return None
    return left == right


def slot_values_at(
    registry: SemanticRegistry, ordinal: int | None = None
) -> dict[str, Decimal]:
    """Numeric slot values, optionally as of one ordinal."""

    values: dict[str, Decimal] = {}
    for slot in registry.slots:
        if ordinal is None:
            candidate = slot.current_value
        else:
            candidate = None
            for entry in slot.history:
                if entry.ordinal <= ordinal:
                    candidate = entry.new_value
            if candidate is None:
                candidate = slot.current_value
        parsed = numeric_value(candidate)
        if parsed is not None:
            values[slot.slot_id] = parsed
    return values


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def apply_fold_delta(
    accumulator: SemanticRegistry | None, delta: Mapping[str, Any]
) -> SemanticRegistry:
    """Fold a delta into the accumulator locally.

    The model reports only what this chunk *adds*: brand-new slots, history
    entries to append to existing slots, merge decisions, and any new relations
    or decisions.  Carrying the accumulated registry forward is mechanical, so
    doing it here keeps the response size proportional to the chunk instead of
    to the whole project.

    That distinction is load-bearing.  Asking the model to re-emit the merged
    registry each fold made the output grow quadratically: on an 824-message
    project the registry reached ~22k tokens by fold 5, the fold-6 response hit
    the output ceiling and was truncated, and every retry failed the same way.
    Slots were also silently dropped between folds as the model struggled to
    reproduce them.

    Chain continuity is enforced here rather than requested: appended entries
    take their ``old_value`` from the slot's current value, so a history chain
    cannot be discontinuous no matter what the model returns.
    """

    slots: dict[str, SemanticSlot] = {
        slot.slot_id: slot for slot in (accumulator.slots if accumulator else ())
    }
    relations: dict[str, SlotRelation] = {
        item.relation_id: item for item in (accumulator.relations if accumulator else ())
    }
    decisions = list(accumulator.decisions if accumulator else ())
    merged_from = dict(accumulator.merged_from if accumulator else {})
    unsatisfiable = list(accumulator.unsatisfiable_relations if accumulator else ())

    for item in _objects(delta.get("new_slots")):
        slot = SemanticSlot.from_json(_normalized_new_slot(item))
        slots[slot.slot_id] = slot

    for item in _objects(delta.get("updated_slots")):
        slot_id = item.get("slot_id")
        existing = slots.get(slot_id) if isinstance(slot_id, str) else None
        if existing is None:
            raise PiiValidationError(
                marked(
                    "CONSOLIDATION_SLOT_MERGE_CONFLICT: updated_slots names unknown slot "
                    f"{slot_id!r}"
                ),
                failures=("CONSOLIDATION_SLOT_MERGE_CONFLICT",),
            )
        history = list(existing.history)
        for entry in _objects(item.get("append_history")):
            new_value = entry.get("new_value")
            ordinal = entry.get("ordinal")
            if not isinstance(new_value, str) or not new_value.strip():
                continue
            if not isinstance(ordinal, int):
                continue
            op = entry.get("op")
            history.append(
                SlotHistoryEntry(
                    ordinal=ordinal,
                    op=op if op in HISTORY_OPS else "MODIFY",
                    # Continuity by construction, not by request.
                    old_value=history[-1].new_value if history else None,
                    new_value=new_value.strip(),
                )
            )
        literals = list(existing.source_literals)
        for value in item.get("add_source_literals") or []:
            if isinstance(value, str) and value and value not in literals:
                literals.append(value)
        ordinals = set(existing.message_ordinals)
        for value in item.get("add_message_ordinals") or []:
            if isinstance(value, int):
                ordinals.add(value)
        slots[slot_id] = SemanticSlot(
            slot_id=existing.slot_id,
            kind=existing.kind,
            value_type=existing.value_type,
            unit=existing.unit,
            current_value=history[-1].new_value if history else existing.current_value,
            meaning=str(item.get("meaning") or existing.meaning),
            history=tuple(history),
            source_literals=tuple(literals),
            message_ordinals=tuple(sorted(ordinals)),
            literal_occurrences=existing.literal_occurrences,
        )

    for key, value in (delta.get("merged_from") or {}).items():
        if isinstance(key, str) and isinstance(value, str):
            merged_from[key] = value

    for item in _objects(delta.get("new_relations")):
        try:
            relation = SlotRelation.from_json(item)
        except PiiError:
            continue
        relations[relation.relation_id] = relation

    for item in _objects(delta.get("new_decisions")):
        decisions.append(dict(item))

    for item in _objects(delta.get("unsatisfiable_relations")):
        unsatisfiable.append(dict(item))

    return SemanticRegistry(
        slots=tuple(slots[key] for key in sorted(slots)),
        relations=tuple(relations[key] for key in sorted(relations)),
        decisions=tuple(decisions),
        merged_from=merged_from,
        unsatisfiable_relations=tuple(unsatisfiable),
    )


def _objects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _normalized_new_slot(item: Mapping[str, Any]) -> dict[str, Any]:
    """Coerce a new slot into a valid shape with a continuous history."""

    body = dict(item)
    raw_history = _objects(body.get("history"))
    history: list[dict[str, Any]] = []
    for entry in raw_history:
        new_value = entry.get("new_value")
        ordinal = entry.get("ordinal")
        if not isinstance(new_value, str) or not new_value.strip():
            continue
        if not isinstance(ordinal, int):
            continue
        op = entry.get("op")
        history.append(
            {
                "ordinal": ordinal,
                "op": ("INTRODUCE" if not history else (op if op in HISTORY_OPS else "MODIFY")),
                "old_value": history[-1]["new_value"] if history else None,
                "new_value": new_value.strip(),
            }
        )
    body["history"] = history
    if history:
        body["current_value"] = history[-1]["new_value"]
    body.setdefault("unit", None)
    body.setdefault("source_literals", [])
    body.setdefault("message_ordinals", [])
    body.setdefault("literal_occurrences", [])
    return body


def attach_literal_occurrences(
    registry: SemanticRegistry, records: Sequence[MessageSemantics]
) -> SemanticRegistry:
    """Bind consolidated slots to exact phase-1A source spans locally.

    Phase 1B is allowed to rename and merge semantic slots, but it is not
    allowed to invent lexical evidence.  Reattaching the original occurrences
    after the fold keeps that evidence message-local and makes duplicate bare
    values distinguishable by position.
    """

    by_id = registry.by_id()

    def target_for(source_name: str) -> str | None:
        current = source_name
        seen: set[str] = set()
        while current not in seen:
            if current in by_id:
                return current
            seen.add(current)
            next_name = registry.merged_from.get(current)
            if next_name is None:
                return None
            current = next_name
        return None

    grouped: dict[str, list[SlotLiteralOccurrence]] = {
        slot_id: [] for slot_id in by_id
    }
    for record in records:
        for message_slot in record.slots:
            target = target_for(message_slot.slot_name)
            if target is None:
                continue
            if message_slot.start is None or message_slot.end is None:
                raise PiiValidationError(
                    marked(
                        "CONSOLIDATION_SCHEMA_INVALID: phase 1A slot occurrence "
                        f"{message_slot.slot_name} at ordinal {record.ordinal} has no span"
                    ),
                    failures=("CONSOLIDATION_SCHEMA_INVALID",),
                )
            grouped[target].append(
                SlotLiteralOccurrence(
                    ordinal=record.ordinal,
                    message_id=record.message_id,
                    start=message_slot.start,
                    end=message_slot.end,
                    source_literal=message_slot.source_literal,
                )
            )

    slots: list[SemanticSlot] = []
    for slot in registry.slots:
        seen: set[tuple[int, int, int, str]] = set()
        occurrences: list[SlotLiteralOccurrence] = []
        for occurrence in sorted(
            grouped.get(slot.slot_id, ()),
            key=lambda item: (item.ordinal, item.start, item.end, item.source_literal),
        ):
            key = (
                occurrence.ordinal,
                occurrence.start,
                occurrence.end,
                occurrence.source_literal,
            )
            if key in seen:
                continue
            seen.add(key)
            occurrences.append(occurrence)
        literals = tuple(dict.fromkeys(item.source_literal for item in occurrences))
        ordinals = tuple(sorted({item.ordinal for item in occurrences}))
        slots.append(
            SemanticSlot(
                slot_id=slot.slot_id,
                kind=slot.kind,
                value_type=slot.value_type,
                unit=slot.unit,
                current_value=slot.current_value,
                meaning=slot.meaning,
                history=slot.history,
                source_literals=literals,
                message_ordinals=ordinals,
                literal_occurrences=tuple(occurrences),
            )
        )
    return SemanticRegistry(
        slots=tuple(slots),
        relations=registry.relations,
        decisions=registry.decisions,
        merged_from=registry.merged_from,
        unsatisfiable_relations=registry.unsatisfiable_relations,
    )


def registry_size(registry: SemanticRegistry) -> int:
    return len(canonical_json(registry.to_json()))


def validate_fold_response(
    payload: Mapping[str, Any],
    fold: SemanticFold,
    accumulator: SemanticRegistry | None,
) -> SemanticRegistry:
    """Validate one fold step and return the new accumulator.

    Judges the *response*.  The size of the accumulated registry is checked by
    the caller instead: it is a deterministic property of state the model no
    longer controls -- most of the registry is carried forward locally -- so
    retrying a model call cannot fix it, and treating it as a validation failure
    burned eight retries on an unfixable condition.
    """

    if not isinstance(payload, dict) or not any(
        key in payload
        for key in ("new_slots", "updated_slots", "merged_from", "new_relations")
    ):
        raise PiiValidationError(
            marked(
                "CONSOLIDATION_SCHEMA_INVALID: response must contain new_slots, "
                "updated_slots, merged_from and new_relations"
            ),
            failures=("CONSOLIDATION_SCHEMA_INVALID",),
        )
    try:
        registry = apply_fold_delta(accumulator, payload)
    except PiiValidationError:
        raise
    except Exception as exc:
        raise PiiValidationError(
            marked(f"CONSOLIDATION_SCHEMA_INVALID: {exc}"),
            failures=("CONSOLIDATION_SCHEMA_INVALID",),
        ) from exc

    failures = _registry_failures(registry, fold.records, accumulator)

    if failures:
        raise PiiValidationError(
            marked("phase 1B validation failed: " + "; ".join(failures[:10])),
            failures=tuple(item.split(":", 1)[0] for item in failures),
        )
    return registry


def _registry_failures(
    registry: SemanticRegistry,
    records: Sequence[MessageSemantics],
    accumulator: SemanticRegistry | None,
) -> list[str]:
    failures: list[str] = []
    slot_ids = {slot.slot_id for slot in registry.slots}

    for slot in registry.slots:
        if not SLOT_ID_RE.fullmatch(slot.slot_id):
            failures.append(
                f"CONSOLIDATION_SCHEMA_INVALID: slot_id {slot.slot_id!r} is invalid"
            )
        if slot.kind not in SLOT_KINDS:
            failures.append(
                f"CONSOLIDATION_SCHEMA_INVALID: {slot.slot_id} kind {slot.kind!r}"
            )
        if not slot.history:
            failures.append(
                f"CONSOLIDATION_HISTORY_BROKEN: {slot.slot_id} has no history"
            )
            continue
        ordinals = [entry.ordinal for entry in slot.history]
        if ordinals != sorted(ordinals):
            failures.append(
                f"CONSOLIDATION_HISTORY_BROKEN: {slot.slot_id} history is not ordered"
            )
        if slot.history[0].op != "INTRODUCE" or slot.history[0].old_value is not None:
            failures.append(
                f"CONSOLIDATION_HISTORY_BROKEN: {slot.slot_id} must open with "
                "INTRODUCE and a null old_value"
            )
        for previous, entry in zip(slot.history, slot.history[1:]):
            if entry.op not in HISTORY_OPS:
                failures.append(
                    f"CONSOLIDATION_HISTORY_BROKEN: {slot.slot_id} op {entry.op!r}"
                )
            if entry.old_value != previous.new_value:
                failures.append(
                    f"CONSOLIDATION_HISTORY_BROKEN: {slot.slot_id} chain is discontinuous "
                    f"at ordinal {entry.ordinal}"
                )
        if slot.current_value != slot.history[-1].new_value:
            failures.append(
                f"CONSOLIDATION_HISTORY_BROKEN: {slot.slot_id} current_value does not "
                "match the last history entry"
            )

    # Coverage: every slot named in this fold's records must be consumed once.
    for record in records:
        for slot in record.slots:
            if slot.slot_name in slot_ids:
                continue
            if slot.slot_name in registry.merged_from:
                target = registry.merged_from[slot.slot_name]
                if target not in slot_ids:
                    failures.append(
                        "CONSOLIDATION_SLOT_MERGE_CONFLICT: "
                        f"{slot.slot_name} merges into unknown slot {target}"
                    )
                continue
            failures.append(
                "CONSOLIDATION_SLOT_MERGE_CONFLICT: "
                f"slot {slot.slot_name} from ordinal {record.ordinal} was dropped"
            )

    # Every accumulator slot must survive the merge.
    if accumulator is not None:
        for slot in accumulator.slots:
            if slot.slot_id not in slot_ids and slot.slot_id not in registry.merged_from:
                failures.append(
                    "CONSOLIDATION_SLOT_MERGE_CONFLICT: "
                    f"accumulator slot {slot.slot_id} disappeared"
                )

    # Relations must reference real slots and evaluate exactly.
    for relation in registry.relations:
        if relation.kind not in RELATION_KINDS:
            failures.append(
                f"CONSOLIDATION_SCHEMA_INVALID: relation kind {relation.kind!r}"
            )
        unknown = sorted(set(relation.slot_ids).difference(slot_ids))
        if unknown:
            failures.append(
                f"CONSOLIDATION_SCHEMA_INVALID: relation {relation.relation_id} "
                f"references unknown slots {unknown}"
            )
            continue
        for ordinal in relation.asserted_at_ordinals or (None,):
            outcome = evaluate_relation(
                relation.expression, slot_values_at(registry, ordinal)
            )
            if outcome is False:
                failures.append(
                    "CONSOLIDATION_RELATION_UNSATISFIABLE: "
                    f"{relation.relation_id} does not hold at ordinal {ordinal}"
                )
                break
    return failures


def validate_semantic_registry(
    registry: SemanticRegistry, records: Sequence[MessageSemantics]
) -> None:
    """Final coverage and consistency check over the consolidated registry."""

    failures = _registry_failures(registry, records, None)
    expected = {
        (record.ordinal, slot.start, slot.end, slot.source_literal)
        for record in records
        for slot in record.slots
    }
    actual = {
        (item.ordinal, item.start, item.end, item.source_literal)
        for slot in registry.slots
        for item in slot.literal_occurrences
    }
    if expected != actual:
        failures.append(
            "CONSOLIDATION_SLOT_OCCURRENCE_LOST: exact phase 1A occurrence coverage "
            f"changed (missing={len(expected - actual)}, extra={len(actual - expected)})"
        )
    if failures:
        raise PiiValidationError(
            marked("consolidated registry is invalid: " + "; ".join(failures[:10])),
            failures=tuple(item.split(":", 1)[0] for item in failures),
        )


def relation_clusters(registry: SemanticRegistry) -> list[tuple[str, ...]]:
    """Slot groups that must be re-valued together.

    A relation ties its slots arithmetically, so phase 2 has to decide them in
    one call or the new values cannot satisfy the constraint.
    """

    parent: dict[str, str] = {slot.slot_id: slot.slot_id for slot in registry.slots}

    def find(key: str) -> str:
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        if right_root < left_root:
            left_root, right_root = right_root, left_root
        parent[right_root] = left_root

    for relation in registry.relations:
        members = [item for item in relation.slot_ids if item in parent]
        for other in members[1:]:
            union(members[0], other)

    groups: dict[str, list[str]] = {}
    for slot in registry.slots:
        groups.setdefault(find(slot.slot_id), []).append(slot.slot_id)
    return [tuple(sorted(members)) for _root, members in sorted(groups.items())]
