"""Phase 1A: per-message semantic extraction.

The job is to bind each business or technical value to a *meaning*, not to a
shape.  v6 classified numbers into ``NUMBER``/``AMOUNT``/``DATE``, which cannot
express that two occurrences of ``5`` are the same parameter or that ``$10,000``
is the per-winner prize rather than the pool total.  Naming the slot by meaning
is what lets phase 1B build a history and phase 2 satisfy arithmetic.

This phase must not emit PII.  The validator enforces it, and that enforcement
is what licenses the dependency edge that phase 1A does *not* have on phase 0B
(see ``config.UPSTREAM``): tightening the PII taxonomy and rerunning 0B leaves
every 1A result valid, which on the largest project preserves ~1075 calls.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .errors import PiiValidationError, marked
from .models import MessageSemantics, MessageSlot, SafeMessage
from .textutil import (
    ANGLE_URL_RE,
    EMAIL_RE,
    HANDLE_RE,
    INTERNAL_TOKEN_RE,
    URL_RE,
)

SPEECH_ACTS: tuple[str, ...] = (
    "REQUEST",
    "COMMITMENT",
    "ACCEPTANCE",
    "REJECTION",
    "QUESTION",
    "ANSWER",
    "STATEMENT",
    "REPORT",
    "ACKNOWLEDGEMENT",
    "PROPOSAL",
    "COMPLAINT",
    "OTHER",
)

POLARITIES: tuple[str, ...] = ("AFFIRMATIVE", "NEGATIVE", "CONDITIONAL", "UNCERTAIN")

EXECUTION_STATES: tuple[str, ...] = (
    "NOT_STARTED",
    "IN_PROGRESS",
    "DELIVERED",
    "VERIFIED",
    "BLOCKED",
    "FAILED",
    "ABANDONED",
    "NOT_APPLICABLE",
)

AMBIGUITY_KINDS: tuple[str, ...] = (
    "NONE",
    "UNDERSPECIFIED",
    "CONFLICTING",
    "OPEN_QUESTION",
    "RESOLVED",
)

DECISION_KINDS: tuple[str, ...] = (
    "APPROVE",
    "REJECT",
    "DEFER",
    "CHANGE",
    "CONFIRM",
    "CANCEL",
)

VALUE_TYPES: tuple[str, ...] = (
    "COUNT",
    "AMOUNT",
    "PERCENTAGE",
    "DURATION",
    "DATE",
    "VERSION",
    "FILENAME",
    "IDENTIFIER",
    "THRESHOLD",
    "RATE",
    "DIMENSION",
    "OTHER",
)

SLOT_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")

TASK = (
    "Extract the project semantics of each message and bind every business or "
    "technical value to a meaning-named slot. Do not rewrite the messages."
)

REPAIR_INSTRUCTION = (
    "The previous response failed local validation. Return exactly one record for every "
    "supplied message. Use only the allowed enum values. Every slot must carry an "
    "UPPER_SNAKE_CASE slot_name, a value_type from the allowed list, a non-empty meaning, "
    "and a source_literal that is an exact substring of that message's text. Give the same "
    "literal two different slot_names when it plays two different roles. Never emit an "
    "email address, link, social handle or any other personally identifying value in any "
    "field."
)


def build_sections(
    items: Sequence[SafeMessage], *, neighbors: Mapping[int, Sequence[Mapping[str, Any]]]
) -> dict[str, Any]:
    return {
        "POLICY": {
            "speech_acts": list(SPEECH_ACTS),
            "polarities": list(POLARITIES),
            "execution_states": list(EXECUTION_STATES),
            "ambiguity_kinds": list(AMBIGUITY_KINDS),
            "decision_kinds": list(DECISION_KINDS),
            "value_types": list(VALUE_TYPES),
            "slot_name_pattern": SLOT_NAME_RE.pattern,
        },
        "SAFE_MESSAGES": [
            {
                "ordinal": item.ordinal,
                "message_id": item.message_id,
                "speaker": item.speaker,
                "text": item.safe_text,
            }
            for item in items
        ],
        "NEIGHBOR_CONTEXT": {
            str(item.ordinal): list(neighbors.get(item.ordinal, ())) for item in items
        },
    }


def neighbor_context(
    safe_messages: Sequence[SafeMessage], *, window: int, excerpt_chars: int = 400
) -> dict[int, list[dict[str, Any]]]:
    """Read-only surrounding messages.

    ``Yes, do that`` cannot be interpreted without its neighbours.  The window
    is part of the shard scope, so editing message 41 invalidates 1A for
    39..43 -- accepted, because without context slot assignment measurably
    degrades, and slot assignment is this phase's entire job.
    """

    by_index = list(safe_messages)
    context: dict[int, list[dict[str, Any]]] = {}
    for index, item in enumerate(by_index):
        if window <= 0:
            context[item.ordinal] = []
            continue
        start = max(0, index - window)
        end = min(len(by_index), index + window + 1)
        context[item.ordinal] = [
            {
                "ordinal": other.ordinal,
                "speaker": other.speaker,
                "excerpt": other.safe_text[:excerpt_chars],
            }
            for position, other in enumerate(by_index[start:end], start=start)
            if position != index
        ]
    return context


def shard_sizer(item: SafeMessage) -> int:
    return len(item.safe_text) + 200


def _pii_egress(value: str) -> str | None:
    """Whether a model-authored string leaked a PII-shaped value."""

    for pattern, label in (
        (EMAIL_RE, "EMAIL"),
        (ANGLE_URL_RE, "URL"),
        (URL_RE, "URL"),
        (HANDLE_RE, "HANDLE"),
    ):
        if pattern.search(value):
            return label
    return None


def validate_semantics_response(
    payload: Mapping[str, Any], items: Sequence[SafeMessage]
) -> dict[int, MessageSemantics]:
    failures: list[str] = []

    def fail(code: str, detail: str) -> None:
        failures.append(f"{code}: {detail}")

    records = payload.get("records")
    if not isinstance(records, list):
        raise PiiValidationError(
            marked("EXTRACTION_SCHEMA_INVALID: response must contain a records list"),
            failures=("EXTRACTION_SCHEMA_INVALID",),
        )

    expected = {item.ordinal: item for item in items}
    seen: set[int] = set()
    result: dict[int, MessageSemantics] = {}

    for index, entry in enumerate(records):
        if not isinstance(entry, dict):
            fail("EXTRACTION_SCHEMA_INVALID", f"records[{index}] must be an object")
            continue
        ordinal = entry.get("ordinal")
        if not isinstance(ordinal, int) or ordinal not in expected:
            fail("EXTRACTION_SCHEMA_INVALID", f"records[{index}] has an unknown ordinal")
            continue
        if ordinal in seen:
            fail("EXTRACTION_SCHEMA_INVALID", f"ordinal {ordinal} appears twice")
            continue
        seen.add(ordinal)
        message = expected[ordinal]

        speech_act = entry.get("speech_act")
        polarity = entry.get("polarity")
        execution_status = entry.get("execution_status")
        ambiguity_kind = entry.get("ambiguity_kind")
        for value, allowed, label in (
            (speech_act, SPEECH_ACTS, "speech_act"),
            (polarity, POLARITIES, "polarity"),
            (execution_status, EXECUTION_STATES, "execution_status"),
            (ambiguity_kind, AMBIGUITY_KINDS, "ambiguity_kind"),
        ):
            if value not in allowed:
                fail(
                    "EXTRACTION_SCHEMA_INVALID",
                    f"ordinal {ordinal} has invalid {label}={value!r}",
                )

        raw_decisions = entry.get("decisions") or []
        decisions: list[dict[str, Any]] = []
        if not isinstance(raw_decisions, list):
            fail("EXTRACTION_SCHEMA_INVALID", f"ordinal {ordinal} decisions must be a list")
        else:
            for position, decision in enumerate(raw_decisions):
                if not isinstance(decision, dict):
                    fail(
                        "EXTRACTION_SCHEMA_INVALID",
                        f"ordinal {ordinal} decision {position} must be an object",
                    )
                    continue
                kind = decision.get("kind")
                statement = decision.get("statement")
                if kind not in DECISION_KINDS:
                    fail(
                        "EXTRACTION_SCHEMA_INVALID",
                        f"ordinal {ordinal} decision kind {kind!r} is invalid",
                    )
                    continue
                if not isinstance(statement, str) or not statement.strip():
                    fail(
                        "EXTRACTION_SCHEMA_INVALID",
                        f"ordinal {ordinal} decision {position} has no statement",
                    )
                    continue
                leaked = _pii_egress(statement)
                if leaked is not None:
                    fail(
                        "EXTRACTION_PII_EGRESS",
                        f"ordinal {ordinal} decision statement contains a {leaked}",
                    )
                    continue
                decisions.append(
                    {
                        "kind": kind,
                        "statement": statement.strip(),
                        "slot_names": [
                            str(name)
                            for name in (decision.get("slot_names") or [])
                            if isinstance(name, str)
                        ],
                    }
                )

        raw_slots = entry.get("slots") or []
        slots: list[MessageSlot] = []
        if not isinstance(raw_slots, list):
            fail("EXTRACTION_SCHEMA_INVALID", f"ordinal {ordinal} slots must be a list")
        else:
            names: set[str] = set()
            for position, slot in enumerate(raw_slots):
                where = f"ordinal {ordinal} slot {position}"
                if not isinstance(slot, dict):
                    fail("EXTRACTION_SCHEMA_INVALID", f"{where} must be an object")
                    continue
                name = slot.get("slot_name")
                value_type = slot.get("value_type")
                literal = slot.get("source_literal")
                meaning = slot.get("meaning")
                if not isinstance(name, str) or not SLOT_NAME_RE.fullmatch(name):
                    fail("EXTRACTION_SLOT_INVALID", f"{where} slot_name {name!r} is invalid")
                    continue
                if name in names:
                    fail("EXTRACTION_SLOT_INVALID", f"{where} repeats slot_name {name}")
                    continue
                if value_type not in VALUE_TYPES:
                    fail("EXTRACTION_SLOT_INVALID", f"{where} value_type {value_type!r}")
                    continue
                if not isinstance(literal, str) or not literal.strip():
                    fail("EXTRACTION_SLOT_INVALID", f"{where} has no source_literal")
                    continue
                if literal not in message.safe_text:
                    fail(
                        "EXTRACTION_SPAN_NOT_FOUND",
                        f"{where} source_literal is not a substring of the message",
                    )
                    continue
                if INTERNAL_TOKEN_RE.search(literal):
                    fail(
                        "EXTRACTION_SLOT_INVALID",
                        f"{where} source_literal covers a shielded secret token",
                    )
                    continue
                if not isinstance(meaning, str) or not meaning.strip():
                    fail("EXTRACTION_SLOT_INVALID", f"{where} has no meaning")
                    continue
                leaked = _pii_egress(f"{name} {meaning}")
                if leaked is not None:
                    fail("EXTRACTION_PII_EGRESS", f"{where} meaning contains a {leaked}")
                    continue
                names.add(name)
                slots.append(
                    MessageSlot(
                        slot_name=name,
                        value_type=value_type,
                        source_literal=literal,
                        meaning=meaning.strip(),
                        unit=(
                            slot.get("unit").strip()
                            if isinstance(slot.get("unit"), str) and slot.get("unit").strip()
                            else None
                        ),
                        op=(
                            slot.get("op")
                            if slot.get("op") in ("INTRODUCE", "MODIFY", "CONFIRM", "REMOVE")
                            else "INTRODUCE"
                        ),
                    )
                )

        relations = [
            str(item)
            for item in (entry.get("relations") or [])
            if isinstance(item, str) and item.strip()
        ]

        result[ordinal] = MessageSemantics(
            ordinal=ordinal,
            message_id=message.message_id,
            speech_act=speech_act if speech_act in SPEECH_ACTS else "OTHER",
            polarity=polarity if polarity in POLARITIES else "AFFIRMATIVE",
            execution_status=(
                execution_status if execution_status in EXECUTION_STATES else "NOT_APPLICABLE"
            ),
            ambiguity_kind=ambiguity_kind if ambiguity_kind in AMBIGUITY_KINDS else "NONE",
            decisions=tuple(decisions),
            slots=tuple(slots),
            relations=tuple(relations),
        )

    missing = sorted(set(expected).difference(seen))
    if missing:
        fail("EXTRACTION_SCHEMA_INVALID", f"omitted ordinals {missing[:20]}")

    if failures:
        raise PiiValidationError(
            marked("phase 1A validation failed: " + "; ".join(failures[:10])),
            failures=tuple(item.split(":", 1)[0] for item in failures),
        )
    return result


def validate_cached_semantics(body: Any) -> None:
    """Re-validate a restored 1A checkpoint against the current enums."""

    record = MessageSemantics.from_json(body)
    if record.speech_act not in SPEECH_ACTS:
        raise PiiValidationError(marked(f"cached speech_act {record.speech_act} is unknown"))
    if record.execution_status not in EXECUTION_STATES:
        raise PiiValidationError(
            marked(f"cached execution_status {record.execution_status} is unknown")
        )
    for slot in record.slots:
        if not SLOT_NAME_RE.fullmatch(slot.slot_name):
            raise PiiValidationError(marked(f"cached slot_name {slot.slot_name} is invalid"))
        if slot.value_type not in VALUE_TYPES:
            raise PiiValidationError(
                marked(f"cached value_type {slot.value_type} is unknown")
            )
