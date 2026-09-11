"""Frozen data contracts that flow between phases.

This module is the reason the nine phase modules never import one another: they
all speak these types.  It is pure -- no filesystem, no regex, no LLM.

``from_json`` implementations are deliberately strict.  Every one of these
structures is also read back from a checkpoint, so a silently-coerced field
would resurrect a stale shape instead of triggering a clean regeneration.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping

from .errors import PiiError

# --------------------------------------------------------------------------- #
# Coercion helpers
# --------------------------------------------------------------------------- #


def _obj(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PiiError(f"{what} must be a JSON object")
    return value


def _text(value: Any, what: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise PiiError(f"{what} must be a string")
    if not allow_empty and not value.strip():
        raise PiiError(f"{what} must be a non-empty string")
    return value


def _opt_text(value: Any, what: str) -> str | None:
    if value is None:
        return None
    return _text(value, what, allow_empty=True)


def _integer(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PiiError(f"{what} must be an integer")
    return value


def _boolean(value: Any, what: str) -> bool:
    if not isinstance(value, bool):
        raise PiiError(f"{what} must be a boolean")
    return value


def _sequence(value: Any, what: str) -> list[Any]:
    if not isinstance(value, list):
        raise PiiError(f"{what} must be a JSON array")
    return value


def _texts(value: Any, what: str) -> tuple[str, ...]:
    return tuple(_text(item, f"{what}[]", allow_empty=True) for item in _sequence(value, what))


# --------------------------------------------------------------------------- #
# Phase 0A -- secret shield
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SecretOccurrence:
    """Where one secret value appears, as offsets into the raw message text."""

    ordinal: int
    message_id: Any
    start: int
    end: int

    def to_json(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "message_id": self.message_id,
            "start": self.start,
            "end": self.end,
        }

    @classmethod
    def from_json(cls, value: Any) -> "SecretOccurrence":
        body = _obj(value, "secret occurrence")
        return cls(
            ordinal=_integer(body.get("ordinal"), "occurrence.ordinal"),
            message_id=body.get("message_id"),
            start=_integer(body.get("start"), "occurrence.start"),
            end=_integer(body.get("end"), "occurrence.end"),
        )


@dataclass(frozen=True)
class SecretEntry:
    """One shielded credential.

    Deliberately holds no raw value: only offsets, a length, a character-class
    signature and a hash.  Masking is re-derived from the source text on resume,
    which makes it structurally impossible for a run artifact to leak a live
    credential.  (v6's ``PlaceholderRegistry`` held raw values in memory and
    merely never happened to serialize them -- ``PII_Clean.py:783``.)
    """

    secret_id: str
    kind: str
    occurrences: tuple[SecretOccurrence, ...]
    length: int
    value_sha256: str
    charclass_signature: str
    detectors: tuple[str, ...]
    confidence: str

    @property
    def internal_token(self) -> str:
        return f"<SECRET_CANDIDATE:{self.secret_id}>"

    def to_json(self) -> dict[str, Any]:
        return {
            "secret_id": self.secret_id,
            "internal_token": self.internal_token,
            "kind": self.kind,
            "occurrences": [item.to_json() for item in self.occurrences],
            "length": self.length,
            "value_sha256": self.value_sha256,
            "charclass_signature": self.charclass_signature,
            "detectors": list(self.detectors),
            "confidence": self.confidence,
        }

    @classmethod
    def from_json(cls, value: Any) -> "SecretEntry":
        body = _obj(value, "secret entry")
        return cls(
            secret_id=_text(body.get("secret_id"), "secret_id"),
            kind=_text(body.get("kind"), "secret.kind"),
            occurrences=tuple(
                SecretOccurrence.from_json(item)
                for item in _sequence(body.get("occurrences"), "secret.occurrences")
            ),
            length=_integer(body.get("length"), "secret.length"),
            value_sha256=_text(body.get("value_sha256"), "secret.value_sha256"),
            charclass_signature=_text(
                body.get("charclass_signature"), "secret.charclass_signature"
            ),
            detectors=_texts(body.get("detectors"), "secret.detectors"),
            confidence=_text(body.get("confidence"), "secret.confidence"),
        )


@dataclass(frozen=True)
class SecretRegistry:
    project_id: str
    secrets: tuple[SecretEntry, ...]

    def by_id(self) -> dict[str, SecretEntry]:
        return {entry.secret_id: entry for entry in self.secrets}

    def tokens(self) -> tuple[str, ...]:
        return tuple(entry.internal_token for entry in self.secrets)

    def value_hashes(self) -> frozenset[str]:
        return frozenset(entry.value_sha256 for entry in self.secrets)

    def occurrences_for(self, ordinal: int) -> tuple[tuple[SecretEntry, SecretOccurrence], ...]:
        return tuple(
            (entry, occurrence)
            for entry in self.secrets
            for occurrence in entry.occurrences
            if occurrence.ordinal == ordinal
        )

    def counts_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.secrets:
            counts[entry.kind] = counts.get(entry.kind, 0) + 1
        return dict(sorted(counts.items()))

    def to_json(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "secrets": [entry.to_json() for entry in self.secrets],
            "counts_by_kind": self.counts_by_kind(),
        }

    @classmethod
    def from_json(cls, value: Any) -> "SecretRegistry":
        body = _obj(value, "secret registry")
        return cls(
            project_id=_text(body.get("project_id"), "registry.project_id"),
            secrets=tuple(
                SecretEntry.from_json(item)
                for item in _sequence(body.get("secrets"), "registry.secrets")
            ),
        )


@dataclass(frozen=True)
class SafeMessage:
    """A message with live credentials replaced by internal tokens.

    This is the only form of the text that may be sent to a model, written to a
    run artifact, or shown to a repairing agent.
    """

    ordinal: int
    message_id: Any
    speaker: str | None
    safe_text: str
    safe_text_sha256: str
    source_text_sha256: str
    word_count: int
    bucket: str
    secret_tokens: tuple[str, ...]
    sender_id_present: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "message_id": self.message_id,
            "speaker": self.speaker,
            "safe_text": self.safe_text,
            "safe_text_sha256": self.safe_text_sha256,
            "source_text_sha256": self.source_text_sha256,
            "word_count": self.word_count,
            "bucket": self.bucket,
            "secret_tokens": list(self.secret_tokens),
            "sender_id_present": self.sender_id_present,
        }

    @classmethod
    def from_json(cls, value: Any) -> "SafeMessage":
        body = _obj(value, "safe message")
        return cls(
            ordinal=_integer(body.get("ordinal"), "safe.ordinal"),
            message_id=body.get("message_id"),
            speaker=_opt_text(body.get("speaker"), "safe.speaker"),
            safe_text=_text(body.get("safe_text"), "safe.safe_text", allow_empty=True),
            safe_text_sha256=_text(body.get("safe_text_sha256"), "safe.safe_text_sha256"),
            source_text_sha256=_text(
                body.get("source_text_sha256"), "safe.source_text_sha256"
            ),
            word_count=_integer(body.get("word_count"), "safe.word_count"),
            bucket=_text(body.get("bucket"), "safe.bucket"),
            secret_tokens=_texts(body.get("secret_tokens"), "safe.secret_tokens"),
            sender_id_present=_boolean(
                body.get("sender_id_present"), "safe.sender_id_present"
            ),
        )

    def with_bucket(self, bucket: str) -> "SafeMessage":
        return replace(self, bucket=bucket)


# --------------------------------------------------------------------------- #
# Phase 0B -- PII discovery
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PiiOccurrence:
    ordinal: int
    message_id: Any
    source: str
    start: int
    end: int
    entity_type: str
    policy: str
    normalized_value: str
    link_hint: str | None
    confidence: str

    def to_json(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "message_id": self.message_id,
            "source": self.source,
            "start": self.start,
            "end": self.end,
            "entity_type": self.entity_type,
            "policy": self.policy,
            "normalized_value": self.normalized_value,
            "link_hint": self.link_hint,
            "confidence": self.confidence,
        }

    @classmethod
    def from_json(cls, value: Any) -> "PiiOccurrence":
        body = _obj(value, "pii occurrence")
        return cls(
            ordinal=_integer(body.get("ordinal"), "occurrence.ordinal"),
            message_id=body.get("message_id"),
            source=_text(body.get("source"), "occurrence.source"),
            start=_integer(body.get("start"), "occurrence.start"),
            end=_integer(body.get("end"), "occurrence.end"),
            entity_type=_text(body.get("entity_type"), "occurrence.entity_type"),
            policy=_text(body.get("policy"), "occurrence.policy"),
            normalized_value=_text(
                body.get("normalized_value"), "occurrence.normalized_value"
            ),
            link_hint=_opt_text(body.get("link_hint"), "occurrence.link_hint"),
            confidence=_text(body.get("confidence"), "occurrence.confidence"),
        )


@dataclass(frozen=True)
class PiiEntity:
    """One real-world thing, with every surface form it appears under."""

    entity_id: str
    entity_type: str
    policy: str
    canonical_value: str
    normalized_key: str
    bundle_id: str | None
    confidence: str
    occurrences: tuple[PiiOccurrence, ...]

    def surface_forms(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for occurrence in self.occurrences:
            seen.setdefault(occurrence.source, None)
        return tuple(seen)

    def ordinals(self) -> tuple[int, ...]:
        return tuple(sorted({occurrence.ordinal for occurrence in self.occurrences}))

    def to_json(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "policy": self.policy,
            "canonical_value": self.canonical_value,
            "normalized_key": self.normalized_key,
            "bundle_id": self.bundle_id,
            "confidence": self.confidence,
            "occurrences": [item.to_json() for item in self.occurrences],
        }

    @classmethod
    def from_json(cls, value: Any) -> "PiiEntity":
        body = _obj(value, "pii entity")
        return cls(
            entity_id=_text(body.get("entity_id"), "entity.entity_id"),
            entity_type=_text(body.get("entity_type"), "entity.entity_type"),
            policy=_text(body.get("policy"), "entity.policy"),
            canonical_value=_text(body.get("canonical_value"), "entity.canonical_value"),
            normalized_key=_text(body.get("normalized_key"), "entity.normalized_key"),
            bundle_id=_opt_text(body.get("bundle_id"), "entity.bundle_id"),
            confidence=_text(body.get("confidence"), "entity.confidence"),
            occurrences=tuple(
                PiiOccurrence.from_json(item)
                for item in _sequence(body.get("occurrences"), "entity.occurrences")
            ),
        )


@dataclass(frozen=True)
class IdentityBundle:
    """Entities that must be synthesized together to stay mutually consistent.

    A person and their addresses/usernames; an organization and its domains,
    repositories and URLs.  Phase 2 never splits a bundle across chunks, which
    is what makes intra-bundle consistency automatic rather than checked.
    """

    bundle_id: str
    kind: str
    entity_ids: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "kind": self.kind,
            "entity_ids": list(self.entity_ids),
        }

    @classmethod
    def from_json(cls, value: Any) -> "IdentityBundle":
        body = _obj(value, "identity bundle")
        return cls(
            bundle_id=_text(body.get("bundle_id"), "bundle.bundle_id"),
            kind=_text(body.get("kind"), "bundle.kind"),
            entity_ids=_texts(body.get("entity_ids"), "bundle.entity_ids"),
        )


@dataclass(frozen=True)
class PiiEntityRegistry:
    entities: tuple[PiiEntity, ...]
    bundles: tuple[IdentityBundle, ...]

    def by_id(self) -> dict[str, PiiEntity]:
        return {entity.entity_id: entity for entity in self.entities}

    def bundle_by_id(self) -> dict[str, IdentityBundle]:
        return {bundle.bundle_id: bundle for bundle in self.bundles}

    def for_ordinal(self, ordinal: int) -> tuple[PiiEntity, ...]:
        return tuple(
            entity
            for entity in self.entities
            if any(item.ordinal == ordinal for item in entity.occurrences)
        )

    def counts_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entity in self.entities:
            counts[entity.entity_type] = counts.get(entity.entity_type, 0) + 1
        return dict(sorted(counts.items()))

    def to_json(self) -> dict[str, Any]:
        return {
            "entities": [entity.to_json() for entity in self.entities],
            "bundles": [bundle.to_json() for bundle in self.bundles],
            "counts_by_type": self.counts_by_type(),
        }

    @classmethod
    def from_json(cls, value: Any) -> "PiiEntityRegistry":
        body = _obj(value, "entity registry")
        return cls(
            entities=tuple(
                PiiEntity.from_json(item)
                for item in _sequence(body.get("entities"), "registry.entities")
            ),
            bundles=tuple(
                IdentityBundle.from_json(item)
                for item in _sequence(body.get("bundles"), "registry.bundles")
            ),
        )


# --------------------------------------------------------------------------- #
# Phase 1A / 1B -- semantics
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SlotHistoryEntry:
    ordinal: int
    op: str
    old_value: str | None
    new_value: str

    def to_json(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "op": self.op,
            "old_value": self.old_value,
            "new_value": self.new_value,
        }

    @classmethod
    def from_json(cls, value: Any) -> "SlotHistoryEntry":
        body = _obj(value, "slot history entry")
        return cls(
            ordinal=_integer(body.get("ordinal"), "history.ordinal"),
            op=_text(body.get("op"), "history.op"),
            old_value=_opt_text(body.get("old_value"), "history.old_value"),
            new_value=_text(body.get("new_value"), "history.new_value"),
        )


@dataclass(frozen=True)
class MessageSlot:
    """A business/technical value bound to a meaning, as seen in one message."""

    slot_name: str
    value_type: str
    source_literal: str
    meaning: str
    unit: str | None = None
    op: str = "INTRODUCE"

    def to_json(self) -> dict[str, Any]:
        return {
            "slot_name": self.slot_name,
            "value_type": self.value_type,
            "source_literal": self.source_literal,
            "meaning": self.meaning,
            "unit": self.unit,
            "op": self.op,
        }

    @classmethod
    def from_json(cls, value: Any) -> "MessageSlot":
        body = _obj(value, "message slot")
        return cls(
            slot_name=_text(body.get("slot_name"), "slot.slot_name"),
            value_type=_text(body.get("value_type"), "slot.value_type"),
            source_literal=_text(body.get("source_literal"), "slot.source_literal"),
            meaning=_text(body.get("meaning"), "slot.meaning"),
            unit=_opt_text(body.get("unit"), "slot.unit"),
            op=_text(body.get("op"), "slot.op"),
        )


@dataclass(frozen=True)
class MessageSemantics:
    ordinal: int
    message_id: Any
    speech_act: str
    polarity: str
    execution_status: str
    ambiguity_kind: str
    decisions: tuple[dict[str, Any], ...]
    slots: tuple[MessageSlot, ...]
    relations: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "message_id": self.message_id,
            "speech_act": self.speech_act,
            "polarity": self.polarity,
            "execution_status": self.execution_status,
            "ambiguity_kind": self.ambiguity_kind,
            "decisions": [dict(item) for item in self.decisions],
            "slots": [item.to_json() for item in self.slots],
            "relations": list(self.relations),
        }

    @classmethod
    def from_json(cls, value: Any) -> "MessageSemantics":
        body = _obj(value, "message semantics")
        return cls(
            ordinal=_integer(body.get("ordinal"), "semantics.ordinal"),
            message_id=body.get("message_id"),
            speech_act=_text(body.get("speech_act"), "semantics.speech_act"),
            polarity=_text(body.get("polarity"), "semantics.polarity"),
            execution_status=_text(
                body.get("execution_status"), "semantics.execution_status"
            ),
            ambiguity_kind=_text(body.get("ambiguity_kind"), "semantics.ambiguity_kind"),
            decisions=tuple(
                _obj(item, "semantics.decisions[]")
                for item in _sequence(body.get("decisions"), "semantics.decisions")
            ),
            slots=tuple(
                MessageSlot.from_json(item)
                for item in _sequence(body.get("slots"), "semantics.slots")
            ),
            relations=_texts(body.get("relations", []), "semantics.relations"),
        )


@dataclass(frozen=True)
class SemanticSlot:
    """A project-level parameter with its full history."""

    slot_id: str
    kind: str
    value_type: str
    unit: str | None
    current_value: str
    meaning: str
    history: tuple[SlotHistoryEntry, ...]
    source_literals: tuple[str, ...]
    message_ordinals: tuple[int, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "kind": self.kind,
            "value_type": self.value_type,
            "unit": self.unit,
            "current_value": self.current_value,
            "meaning": self.meaning,
            "history": [item.to_json() for item in self.history],
            "source_literals": list(self.source_literals),
            "message_ordinals": list(self.message_ordinals),
        }

    @classmethod
    def from_json(cls, value: Any) -> "SemanticSlot":
        body = _obj(value, "semantic slot")
        return cls(
            slot_id=_text(body.get("slot_id"), "slot.slot_id"),
            kind=_text(body.get("kind"), "slot.kind"),
            value_type=_text(body.get("value_type"), "slot.value_type"),
            unit=_opt_text(body.get("unit"), "slot.unit"),
            current_value=_text(body.get("current_value"), "slot.current_value"),
            meaning=_text(body.get("meaning"), "slot.meaning"),
            history=tuple(
                SlotHistoryEntry.from_json(item)
                for item in _sequence(body.get("history"), "slot.history")
            ),
            source_literals=_texts(body.get("source_literals"), "slot.source_literals"),
            message_ordinals=tuple(
                _integer(item, "slot.message_ordinals[]")
                for item in _sequence(body.get("message_ordinals"), "slot.message_ordinals")
            ),
        )


@dataclass(frozen=True)
class SlotRelation:
    """An arithmetic invariant over slots, e.g. ``a * b = c``."""

    relation_id: str
    kind: str
    expression: str
    slot_ids: tuple[str, ...]
    asserted_at_ordinals: tuple[int, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "kind": self.kind,
            "expression": self.expression,
            "slot_ids": list(self.slot_ids),
            "asserted_at_ordinals": list(self.asserted_at_ordinals),
        }

    @classmethod
    def from_json(cls, value: Any) -> "SlotRelation":
        body = _obj(value, "slot relation")
        return cls(
            relation_id=_text(body.get("relation_id"), "relation.relation_id"),
            kind=_text(body.get("kind"), "relation.kind"),
            expression=_text(body.get("expression"), "relation.expression"),
            slot_ids=_texts(body.get("slot_ids"), "relation.slot_ids"),
            asserted_at_ordinals=tuple(
                _integer(item, "relation.asserted_at_ordinals[]")
                for item in _sequence(
                    body.get("asserted_at_ordinals"), "relation.asserted_at_ordinals"
                )
            ),
        )


@dataclass(frozen=True)
class SemanticRegistry:
    slots: tuple[SemanticSlot, ...]
    relations: tuple[SlotRelation, ...]
    decisions: tuple[dict[str, Any], ...]
    merged_from: Mapping[str, str] = field(default_factory=dict)
    unsatisfiable_relations: tuple[dict[str, Any], ...] = ()

    def by_id(self) -> dict[str, SemanticSlot]:
        return {slot.slot_id: slot for slot in self.slots}

    def for_ordinal(self, ordinal: int) -> tuple[SemanticSlot, ...]:
        return tuple(slot for slot in self.slots if ordinal in slot.message_ordinals)

    def relations_for(self, slot_id: str) -> tuple[SlotRelation, ...]:
        return tuple(
            relation for relation in self.relations if slot_id in relation.slot_ids
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "slots": [slot.to_json() for slot in self.slots],
            "relations": [relation.to_json() for relation in self.relations],
            "decisions": [dict(item) for item in self.decisions],
            "merged_from": dict(self.merged_from),
            "unsatisfiable_relations": [dict(item) for item in self.unsatisfiable_relations],
        }

    @classmethod
    def from_json(cls, value: Any) -> "SemanticRegistry":
        body = _obj(value, "semantic registry")
        merged = _obj(body.get("merged_from", {}), "registry.merged_from")
        return cls(
            slots=tuple(
                SemanticSlot.from_json(item)
                for item in _sequence(body.get("slots"), "registry.slots")
            ),
            relations=tuple(
                SlotRelation.from_json(item)
                for item in _sequence(body.get("relations"), "registry.relations")
            ),
            decisions=tuple(
                _obj(item, "registry.decisions[]")
                for item in _sequence(body.get("decisions"), "registry.decisions")
            ),
            merged_from={
                _text(key, "merged_from key"): _text(item, "merged_from value")
                for key, item in merged.items()
            },
            unsatisfiable_relations=tuple(
                _obj(item, "registry.unsatisfiable_relations[]")
                for item in _sequence(
                    body.get("unsatisfiable_relations", []),
                    "registry.unsatisfiable_relations",
                )
            ),
        )


# --------------------------------------------------------------------------- #
# Phase 2 -- transformation plan
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EntityAlias:
    original: str
    replacement: str

    def to_json(self) -> dict[str, Any]:
        return {"original": self.original, "replacement": self.replacement}

    @classmethod
    def from_json(cls, value: Any) -> "EntityAlias":
        body = _obj(value, "entity alias")
        return cls(
            original=_text(body.get("original"), "alias.original"),
            replacement=_text(body.get("replacement"), "alias.replacement"),
        )


@dataclass(frozen=True)
class EntityReplacement:
    entity_id: str
    entity_type: str
    policy: str
    original: str
    replacement: str
    bundle_id: str | None = None
    aliases: tuple[EntityAlias, ...] = ()
    depends_on: tuple[str, ...] = ()

    def originals(self) -> tuple[str, ...]:
        return (self.original, *(alias.original for alias in self.aliases))

    def replacements(self) -> tuple[str, ...]:
        return (self.replacement, *(alias.replacement for alias in self.aliases))

    def pairs(self) -> tuple[tuple[str, str], ...]:
        return ((self.original, self.replacement),) + tuple(
            (alias.original, alias.replacement) for alias in self.aliases
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "policy": self.policy,
            "original": self.original,
            "replacement": self.replacement,
            "bundle_id": self.bundle_id,
            "aliases": [alias.to_json() for alias in self.aliases],
            "depends_on": list(self.depends_on),
        }

    @classmethod
    def from_json(cls, value: Any) -> "EntityReplacement":
        body = _obj(value, "entity replacement")
        return cls(
            entity_id=_text(body.get("entity_id"), "replacement.entity_id"),
            entity_type=_text(body.get("entity_type"), "replacement.entity_type"),
            policy=_text(body.get("policy"), "replacement.policy"),
            original=_text(body.get("original"), "replacement.original"),
            replacement=_text(body.get("replacement"), "replacement.replacement"),
            bundle_id=_opt_text(body.get("bundle_id"), "replacement.bundle_id"),
            aliases=tuple(
                EntityAlias.from_json(item)
                for item in _sequence(body.get("aliases", []), "replacement.aliases")
            ),
            depends_on=_texts(body.get("depends_on", []), "replacement.depends_on"),
        )


@dataclass(frozen=True)
class SlotReplacement:
    slot_id: str
    value_type: str
    history: tuple[SlotHistoryEntry, ...]
    literal_map: Mapping[str, str]

    def to_json(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "value_type": self.value_type,
            "history": [item.to_json() for item in self.history],
            "literal_map": dict(self.literal_map),
        }

    @classmethod
    def from_json(cls, value: Any) -> "SlotReplacement":
        body = _obj(value, "slot replacement")
        literal_map = _obj(body.get("literal_map"), "slot_replacement.literal_map")
        return cls(
            slot_id=_text(body.get("slot_id"), "slot_replacement.slot_id"),
            value_type=_text(body.get("value_type"), "slot_replacement.value_type"),
            history=tuple(
                SlotHistoryEntry.from_json(item)
                for item in _sequence(body.get("history"), "slot_replacement.history")
            ),
            literal_map={
                _text(key, "literal_map key"): _text(item, "literal_map value")
                for key, item in literal_map.items()
            },
        )


@dataclass(frozen=True)
class SecretPlanEntry:
    """A secret's plan entry.  ``replacement`` is always ``None``.

    Phase 6A renders credentials locally and deterministically, so no model --
    and no repairing agent -- ever authors a credential-shaped string.
    """

    secret_id: str
    internal_token: str
    kind: str
    replacement: None = None
    rendered_by: str = "PHASE_6A"

    def to_json(self) -> dict[str, Any]:
        return {
            "secret_id": self.secret_id,
            "internal_token": self.internal_token,
            "kind": self.kind,
            "replacement": None,
            "rendered_by": self.rendered_by,
        }

    @classmethod
    def from_json(cls, value: Any) -> "SecretPlanEntry":
        body = _obj(value, "secret plan entry")
        if body.get("replacement") is not None:
            raise PiiError("secret plan entries must not carry a replacement value")
        return cls(
            secret_id=_text(body.get("secret_id"), "secret_plan.secret_id"),
            internal_token=_text(body.get("internal_token"), "secret_plan.internal_token"),
            kind=_text(body.get("kind"), "secret_plan.kind"),
            rendered_by=_text(body.get("rendered_by"), "secret_plan.rendered_by"),
        )


@dataclass(frozen=True)
class TransformationPlan:
    plan_version: int
    entity_replacements: tuple[EntityReplacement, ...]
    slot_replacements: tuple[SlotReplacement, ...]
    secret_replacements: tuple[SecretPlanEntry, ...]
    relation_checks: tuple[dict[str, Any], ...] = ()
    reserved_values: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    amendments: tuple[dict[str, Any], ...] = ()

    def entity_by_id(self) -> dict[str, EntityReplacement]:
        return {item.entity_id: item for item in self.entity_replacements}

    def slot_by_id(self) -> dict[str, SlotReplacement]:
        return {item.slot_id: item for item in self.slot_replacements}

    def synthesized(self) -> tuple[EntityReplacement, ...]:
        return tuple(
            item for item in self.entity_replacements if item.policy == "SYNTHESIZE"
        )

    def preserved(self) -> tuple[EntityReplacement, ...]:
        return tuple(
            item for item in self.entity_replacements if item.policy == "PRESERVE"
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "plan_version": self.plan_version,
            "entity_replacements": [item.to_json() for item in self.entity_replacements],
            "slot_replacements": [item.to_json() for item in self.slot_replacements],
            "secret_replacements": [item.to_json() for item in self.secret_replacements],
            "relation_checks": [dict(item) for item in self.relation_checks],
            "reserved_values": {
                key: list(values) for key, values in sorted(self.reserved_values.items())
            },
            "amendments": [dict(item) for item in self.amendments],
        }

    @classmethod
    def from_json(cls, value: Any) -> "TransformationPlan":
        body = _obj(value, "transformation plan")
        reserved = _obj(body.get("reserved_values", {}), "plan.reserved_values")
        return cls(
            plan_version=_integer(body.get("plan_version"), "plan.plan_version"),
            entity_replacements=tuple(
                EntityReplacement.from_json(item)
                for item in _sequence(
                    body.get("entity_replacements"), "plan.entity_replacements"
                )
            ),
            slot_replacements=tuple(
                SlotReplacement.from_json(item)
                for item in _sequence(
                    body.get("slot_replacements"), "plan.slot_replacements"
                )
            ),
            secret_replacements=tuple(
                SecretPlanEntry.from_json(item)
                for item in _sequence(
                    body.get("secret_replacements"), "plan.secret_replacements"
                )
            ),
            relation_checks=tuple(
                _obj(item, "plan.relation_checks[]")
                for item in _sequence(body.get("relation_checks", []), "plan.relation_checks")
            ),
            reserved_values={
                _text(key, "reserved_values key"): _texts(item, "reserved_values value")
                for key, item in reserved.items()
            },
            amendments=tuple(
                _obj(item, "plan.amendments[]")
                for item in _sequence(body.get("amendments", []), "plan.amendments")
            ),
        )


@dataclass(frozen=True)
class MessagePlanSlice:
    """Every plan decision one message must honour, as a transitive closure.

    The closure -- the message's own entities *plus every entity in the same
    identity bundle* plus *every slot in the same relation cluster* plus the
    secret tokens present -- is what makes a per-message rewrite checkpoint
    sound.  Without it, ``slice_sha256`` equality would wrongly preserve a
    rewrite that references a replacement which changed elsewhere, and the
    contradiction would only surface in the final project-wide audit with no
    trail back to its cause.
    """

    ordinal: int
    message_id: Any
    bucket: str
    safe_text_sha256: str
    entity_replacements: tuple[EntityReplacement, ...]
    slot_replacements: tuple[SlotReplacement, ...]
    secret_tokens: tuple[str, ...]
    preserve_literals: tuple[str, ...]
    must_replace_terms: tuple[str, ...]
    semantic_expectations: Mapping[str, Any]
    relation_constraints: tuple[str, ...] = ()
    plan_version: int = 1

    def to_json(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "message_id": self.message_id,
            "bucket": self.bucket,
            "safe_text_sha256": self.safe_text_sha256,
            "entity_replacements": [item.to_json() for item in self.entity_replacements],
            "slot_replacements": [item.to_json() for item in self.slot_replacements],
            "secret_tokens": list(self.secret_tokens),
            "preserve_literals": list(self.preserve_literals),
            "must_replace_terms": list(self.must_replace_terms),
            "semantic_expectations": dict(self.semantic_expectations),
            "relation_constraints": list(self.relation_constraints),
            "plan_version": self.plan_version,
        }

    @classmethod
    def from_json(cls, value: Any) -> "MessagePlanSlice":
        body = _obj(value, "plan slice")
        return cls(
            ordinal=_integer(body.get("ordinal"), "slice.ordinal"),
            message_id=body.get("message_id"),
            bucket=_text(body.get("bucket"), "slice.bucket"),
            safe_text_sha256=_text(body.get("safe_text_sha256"), "slice.safe_text_sha256"),
            entity_replacements=tuple(
                EntityReplacement.from_json(item)
                for item in _sequence(
                    body.get("entity_replacements"), "slice.entity_replacements"
                )
            ),
            slot_replacements=tuple(
                SlotReplacement.from_json(item)
                for item in _sequence(
                    body.get("slot_replacements"), "slice.slot_replacements"
                )
            ),
            secret_tokens=_texts(body.get("secret_tokens"), "slice.secret_tokens"),
            preserve_literals=_texts(body.get("preserve_literals"), "slice.preserve_literals"),
            must_replace_terms=_texts(
                body.get("must_replace_terms", []), "slice.must_replace_terms"
            ),
            semantic_expectations=_obj(
                body.get("semantic_expectations", {}), "slice.semantic_expectations"
            ),
            relation_constraints=_texts(
                body.get("relation_constraints", []), "slice.relation_constraints"
            ),
            plan_version=_integer(body.get("plan_version", 1), "slice.plan_version"),
        )


# --------------------------------------------------------------------------- #
# Phase 3 / 5 -- rewrites
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RewriteRecord:
    ordinal: int
    message_id: Any
    bucket: str
    text: str
    text_sha256: str
    applied_entity_ids: tuple[str, ...]
    applied_slot_ids: tuple[str, ...]
    retained_secret_tokens: tuple[str, ...]
    structural_change: bool
    source: str
    attempt: int = 1

    def to_json(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "message_id": self.message_id,
            "bucket": self.bucket,
            "text": self.text,
            "text_sha256": self.text_sha256,
            "applied_entity_ids": list(self.applied_entity_ids),
            "applied_slot_ids": list(self.applied_slot_ids),
            "retained_secret_tokens": list(self.retained_secret_tokens),
            "structural_change": self.structural_change,
            "source": self.source,
            "attempt": self.attempt,
        }

    @classmethod
    def from_json(cls, value: Any) -> "RewriteRecord":
        body = _obj(value, "rewrite record")
        return cls(
            ordinal=_integer(body.get("ordinal"), "rewrite.ordinal"),
            message_id=body.get("message_id"),
            bucket=_text(body.get("bucket"), "rewrite.bucket"),
            text=_text(body.get("text"), "rewrite.text", allow_empty=True),
            text_sha256=_text(body.get("text_sha256"), "rewrite.text_sha256"),
            applied_entity_ids=_texts(
                body.get("applied_entity_ids"), "rewrite.applied_entity_ids"
            ),
            applied_slot_ids=_texts(body.get("applied_slot_ids"), "rewrite.applied_slot_ids"),
            retained_secret_tokens=_texts(
                body.get("retained_secret_tokens"), "rewrite.retained_secret_tokens"
            ),
            structural_change=_boolean(
                body.get("structural_change"), "rewrite.structural_change"
            ),
            source=_text(body.get("source"), "rewrite.source"),
            attempt=_integer(body.get("attempt", 1), "rewrite.attempt"),
        )


# --------------------------------------------------------------------------- #
# Phase 4 -- verification
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class VerdictFinding:
    """One verifier objection.

    ``evidence`` is always a *pointer* -- a decision id, slot id, entity id,
    relation id or span -- never a quoted excerpt.  That keeps verdicts safe to
    persist, safe to log and safe to hand to a repairing agent.
    """

    code: str
    detail: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    severity: str = "HIGH"

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "detail": self.detail,
            "evidence": dict(self.evidence),
            "severity": self.severity,
        }

    @classmethod
    def from_json(cls, value: Any) -> "VerdictFinding":
        body = _obj(value, "verdict finding")
        return cls(
            code=_text(body.get("code"), "finding.code"),
            detail=_text(body.get("detail"), "finding.detail", allow_empty=True),
            evidence=_obj(body.get("evidence", {}), "finding.evidence"),
            severity=_text(body.get("severity", "HIGH"), "finding.severity"),
        )


@dataclass(frozen=True)
class VerdictRecord:
    ordinal: int
    message_id: Any
    status: str
    checks: Mapping[str, str]
    findings: tuple[VerdictFinding, ...]
    verified_against: Mapping[str, str]

    def to_json(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "message_id": self.message_id,
            "status": self.status,
            "checks": dict(self.checks),
            "findings": [item.to_json() for item in self.findings],
            "verified_against": dict(self.verified_against),
        }

    @classmethod
    def from_json(cls, value: Any) -> "VerdictRecord":
        body = _obj(value, "verdict record")
        checks = _obj(body.get("checks"), "verdict.checks")
        against = _obj(body.get("verified_against"), "verdict.verified_against")
        return cls(
            ordinal=_integer(body.get("ordinal"), "verdict.ordinal"),
            message_id=body.get("message_id"),
            status=_text(body.get("status"), "verdict.status"),
            checks={
                _text(key, "checks key"): _text(item, "checks value")
                for key, item in checks.items()
            },
            findings=tuple(
                VerdictFinding.from_json(item)
                for item in _sequence(body.get("findings"), "verdict.findings")
            ),
            verified_against={
                _text(key, "verified_against key"): _text(item, "verified_against value")
                for key, item in against.items()
            },
        )


# --------------------------------------------------------------------------- #
# Per-message run state
# --------------------------------------------------------------------------- #

STATUS_PENDING = "PENDING"
STATUS_DONE = "DONE"
STATUS_QUARANTINED = "QUARANTINED"

PROVENANCE_LLM_REWRITE = "LLM_REWRITE"
PROVENANCE_LLM_REPAIR = "LLM_REPAIR"
PROVENANCE_AGENT_REPAIR = "AGENT_REPAIR"
PROVENANCE_PRESERVED = "PRESERVED_VERIFIED"
ALLOWED_PROVENANCE = frozenset(
    {
        PROVENANCE_LLM_REWRITE,
        PROVENANCE_LLM_REPAIR,
        PROVENANCE_AGENT_REPAIR,
        PROVENANCE_PRESERVED,
    }
)


@dataclass
class MessageState:
    """The authoritative per-message record that phase 6 iterates over.

    ``final_text`` is ``None`` until a validated, verified text exists.  There is
    no code path that assigns the original text except the ``PRESERVED_VERIFIED``
    provenance, which requires ``requires_change is False``.  v6 pre-seeded this
    map with the original text for every message
    (``Code/PII_Clean.py:3196``) and relied solely on an abort to stop it
    reaching the output -- so relaxing that abort to "skip and continue" would
    have published raw text.  Here "skip" cannot degrade into "reuse".
    """

    ordinal: int
    message_id: Any
    bucket: str
    requires_change: bool
    status: str = STATUS_PENDING
    provenance: str | None = None
    final_text: str | None = None
    text_sha256: str | None = None
    verified: bool = False
    attempts: int = 0

    def mark_done(self, text: str, *, provenance: str, text_sha256: str, verified: bool) -> None:
        if provenance not in ALLOWED_PROVENANCE:
            raise PiiError(f"invalid provenance: {provenance}")
        if provenance == PROVENANCE_PRESERVED and self.requires_change:
            raise PiiError(
                f"message {self.message_id!r} requires change; it cannot be preserved verbatim"
            )
        self.final_text = text
        self.text_sha256 = text_sha256
        self.provenance = provenance
        self.verified = verified
        self.status = STATUS_DONE

    def quarantine(self) -> None:
        """Isolate the message.  Any previously accepted text is discarded."""

        self.status = STATUS_QUARANTINED
        self.final_text = None
        self.text_sha256 = None
        self.provenance = None
        self.verified = False

    def require_final_text(self) -> str:
        if self.status != STATUS_DONE or self.final_text is None:
            raise PiiError(
                f"message {self.message_id!r} has no accepted text (status={self.status})"
            )
        return self.final_text

    def to_json(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "message_id": self.message_id,
            "bucket": self.bucket,
            "requires_change": self.requires_change,
            "status": self.status,
            "provenance": self.provenance,
            "text_sha256": self.text_sha256,
            "verified": self.verified,
            "attempts": self.attempts,
        }


def index_by_ordinal(items: Iterable[Any]) -> dict[int, Any]:
    return {item.ordinal: item for item in items}


def index_by_message_id(items: Iterable[Any], key: Any) -> dict[str, Any]:
    return {key(item.message_id): item for item in items}


__all__ = [
    "ALLOWED_PROVENANCE",
    "EntityAlias",
    "EntityReplacement",
    "IdentityBundle",
    "MessagePlanSlice",
    "MessageSemantics",
    "MessageSlot",
    "MessageState",
    "PROVENANCE_AGENT_REPAIR",
    "PROVENANCE_LLM_REPAIR",
    "PROVENANCE_LLM_REWRITE",
    "PROVENANCE_PRESERVED",
    "PiiEntity",
    "PiiEntityRegistry",
    "PiiOccurrence",
    "RewriteRecord",
    "STATUS_DONE",
    "STATUS_PENDING",
    "STATUS_QUARANTINED",
    "SafeMessage",
    "SecretEntry",
    "SecretOccurrence",
    "SecretPlanEntry",
    "SecretRegistry",
    "SemanticRegistry",
    "SemanticSlot",
    "SlotHistoryEntry",
    "SlotRelation",
    "SlotReplacement",
    "TransformationPlan",
    "VerdictFinding",
    "VerdictRecord",
    "index_by_message_id",
    "index_by_ordinal",
]
