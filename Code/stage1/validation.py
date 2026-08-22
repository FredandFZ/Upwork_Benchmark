from __future__ import annotations

import re
from typing import Any

from .preprocessing import message_index
from .schemas import EVENT_TYPES
from .storage import id_key


PERSISTENCE_VALUES = {"PROJECT_PERSISTENT", "MILESTONE_LOCAL", "TASK_LOCAL"}
AMBIGUITY_DIMENSIONS = {"VALUE", "SCOPE", "LIFECYCLE"}
EXECUTION_STATUS = {
    "IMPLEMENTATION_CLAIM": "CLAIMED_WORKING",
    "RUNTIME_FAILURE": "FAILED",
    "RUNTIME_VERIFICATION": "VERIFIED_WORKING",
}
CANONICAL_EVENT_FIELDS = {
    "event_id",
    "source_message",
    "event_type",
    "value_updates",
    "value_removals",
    "scope_updates",
    "ambiguity",
    "execution",
}


class Stage1ValidationError(ValueError):
    pass


def _error(message: str) -> None:
    raise Stage1ValidationError(message)


def canonicalize_event_source_texts(events: list[dict[str, Any]], normalized: dict[str, Any]) -> int:
    """Restore exact raw source text when an LLM correctly identifies its message.

    Models commonly decode HTML entities or normalize Unicode while copying a
    source message.  The message ID and speaker remain the provenance keys; if
    both match an input message, replace only the display text with the exact
    original transcript text.  Unknown IDs and speaker mismatches are left
    untouched so the normal strict validator still rejects them.
    """
    message_by_id, _ = message_index(normalized)
    corrections = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        source = event.get("source_message")
        if not isinstance(source, dict):
            continue
        raw = message_by_id.get(id_key(source.get("message_id")))
        if raw is None or source.get("speaker") != raw.get("speaker"):
            continue
        if source.get("text") != raw.get("text"):
            source["text"] = raw["text"]
            corrections += 1
    return corrections


def canonicalize_event_payload_fields(events: list[dict[str, Any]]) -> int:
    """Add newly introduced nullable fields to provisional/legacy Events.

    Intermediate checkpoints predate annotation v0.6 and may not contain
    ``value_removals``.  Treat omission as null while ensuring every newly
    generated final Event has the canonical field.
    """
    additions = 0
    for event in events:
        if isinstance(event, dict) and "value_removals" not in event:
            event["value_removals"] = None
            additions += 1
    return additions


def validate_intermediate_events(events: list[dict[str, Any]], normalized: dict[str, Any]) -> None:
    message_by_id, order = message_index(normalized)
    previous = -1
    current_attributes: dict[str, Any] = {}
    for number, event in enumerate(events, start=1):
        source = event.get("source_message")
        if not isinstance(source, dict):
            _error(f"Intermediate Event {number} has no source_message")
        key = id_key(source.get("message_id"))
        raw = message_by_id.get(key)
        if raw is None:
            _error(f"Intermediate Event {number} references an unknown message_id")
        if source.get("speaker") != raw.get("speaker"):
            _error(f"Intermediate Event {number} source speaker differs from raw message")
        if source.get("text") != raw.get("text"):
            _error(f"Intermediate Event {number} source text differs from raw message")
        if order[key] < previous:
            _error("Intermediate Events are not chronological")
        previous = order[key]
        _validate_event_payload(event, f"Intermediate Event {number}")
        removals = event.get("value_removals") or []
        missing = [attribute for attribute in removals if attribute not in current_attributes]
        if missing:
            _error(
                f"Intermediate Event {number}.value_removals references attributes that do not exist "
                f"before the Event: {', '.join(sorted(missing))}"
            )
        for attribute in removals:
            current_attributes.pop(attribute, None)
        for attribute, value in (event.get("value_updates") or {}).items():
            current_attributes[attribute] = value


def validate_stage1_annotation(annotation: dict[str, Any], normalized: dict[str, Any]) -> None:
    if annotation.get("benchmark") != "ReqMemBench":
        _error("benchmark must equal ReqMemBench")
    if annotation.get("annotation_version") != "v0.6":
        _error("annotation_version must equal v0.6")
    project = annotation.get("project")
    if not isinstance(project, dict) or project.get("project_id") != normalized.get("project_id"):
        _error("project.project_id does not match normalized input")
    sessions = project.get("sessions")
    families = annotation.get("requirement_families")
    requirements = annotation.get("requirements")
    if not isinstance(sessions, list) or not isinstance(families, list) or not isinstance(requirements, list):
        _error("sessions, requirement_families, and requirements must be arrays")

    session_ids = [session.get("session_id") for session in sessions if isinstance(session, dict)]
    if len(session_ids) != len(sessions) or len(session_ids) != len(set(session_ids)) or any(not value for value in session_ids):
        _error("Session IDs must be non-empty and unique")
    family_ids = [family.get("family_id") for family in families if isinstance(family, dict)]
    if len(family_ids) != len(families) or len(family_ids) != len(set(family_ids)) or any(not value for value in family_ids):
        _error("Family IDs must be non-empty and unique")
    requirement_ids = [requirement.get("requirement_id") for requirement in requirements if isinstance(requirement, dict)]
    if len(requirement_ids) != len(requirements) or len(requirement_ids) != len(set(requirement_ids)) or any(not value for value in requirement_ids):
        _error("Requirement IDs must be non-empty and unique")

    family_set = set(family_ids)
    family_counts = {family_id: 0 for family_id in family_ids}
    message_by_id, message_order = message_index(normalized)
    all_event_ids: set[str] = set()
    for requirement in requirements:
        requirement_id = requirement["requirement_id"]
        family_id = requirement.get("family_id")
        if family_id is not None:
            if family_id not in family_set:
                _error(f"{requirement_id} references unknown family_id {family_id}")
            family_counts[family_id] += 1
        events = requirement.get("events")
        if not isinstance(events, list):
            _error(f"{requirement_id}.events must be an array")
        previous_position = -1
        current_attributes: dict[str, Any] = {}
        for number, event in enumerate(events, start=1):
            if not isinstance(event, dict) or set(event) != CANONICAL_EVENT_FIELDS:
                _error(f"{requirement_id} event {number} has non-canonical fields")
            expected_id = f"{requirement_id}_E{number:03d}"
            if event.get("event_id") != expected_id:
                _error(f"Expected contiguous event_id {expected_id}")
            if expected_id in all_event_ids:
                _error(f"Duplicate event_id: {expected_id}")
            all_event_ids.add(expected_id)
            source = event.get("source_message")
            if not isinstance(source, dict) or set(source) != {"message_id", "speaker", "text"}:
                _error(f"{expected_id}.source_message must be an object")
            key = id_key(source.get("message_id"))
            raw = message_by_id.get(key)
            if raw is None:
                _error(f"{expected_id} references unknown message_id")
            if source.get("speaker") != raw.get("speaker"):
                _error(f"{expected_id} source speaker differs from raw message")
            if source.get("text") != raw.get("text"):
                _error(f"{expected_id} source text differs from raw message")
            position = message_order[key]
            if position < previous_position:
                _error(f"{requirement_id} Events are not chronological")
            previous_position = position
            _validate_event_payload(event, expected_id)
            removals = event.get("value_removals") or []
            missing = [attribute for attribute in removals if attribute not in current_attributes]
            if missing:
                _error(
                    f"{expected_id}.value_removals references attributes that do not exist before the Event: "
                    f"{', '.join(sorted(missing))}"
                )
            for attribute in removals:
                current_attributes.pop(attribute, None)
            for attribute, value in (event.get("value_updates") or {}).items():
                current_attributes[attribute] = value
    one_member = [family_id for family_id, count in family_counts.items() if count < 2]
    if one_member:
        _error(f"Meaningless one-member/empty Families remain: {', '.join(one_member)}")


def _validate_event_payload(event: dict[str, Any], event_id: str) -> None:
    event_type = event.get("event_type")
    if event_type not in EVENT_TYPES:
        _error(f"{event_id} has invalid event_type {event_type!r}")
    value = event.get("value_updates")
    removals = event.get("value_removals")
    scope = event.get("scope_updates")
    ambiguity = event.get("ambiguity")
    execution = event.get("execution")
    if value is not None and not isinstance(value, dict):
        _error(f"{event_id}.value_updates must be an object or null")
    if removals is not None:
        if not isinstance(removals, list) or not removals or any(
            not isinstance(key, str) or not key for key in removals
        ):
            _error(f"{event_id}.value_removals must be a non-empty array of non-empty strings or null")
        if len(removals) != len(set(removals)):
            _error(f"{event_id}.value_removals must not contain duplicates")
        overlap = set(removals).intersection((value or {}).keys())
        if overlap:
            _error(f"{event_id} cannot update and remove the same attribute: {', '.join(sorted(overlap))}")
    if event_type == "INTRODUCE":
        if removals is not None or ambiguity is not None or execution is not None or (value is None and scope is None):
            _error(f"{event_id} violates INTRODUCE field constraints")
    elif event_type == "MODIFY":
        if ambiguity is not None or execution is not None or (value is None and scope is None and removals is None):
            _error(f"{event_id} violates MODIFY field constraints")
    elif event_type in {"DEFER", "RESUME", "REMOVE"}:
        if any(item is not None for item in (value, removals, scope, ambiguity, execution)):
            _error(f"{event_id} lifecycle Event payload must be null")
    elif event_type == "AMBIGUOUS":
        if value is not None or removals is not None or scope is not None or execution is not None or not isinstance(ambiguity, dict):
            _error(f"{event_id} violates AMBIGUOUS field constraints")
        if ambiguity.get("dimension") not in AMBIGUITY_DIMENSIONS:
            _error(f"{event_id} has invalid ambiguity dimension")
        if not isinstance(ambiguity.get("description"), str) or not ambiguity.get("description"):
            _error(f"{event_id} ambiguity.description must be a non-empty string")
    else:
        expected = EXECUTION_STATUS[event_type]
        if value is not None or removals is not None or scope is not None or ambiguity is not None or not isinstance(execution, dict):
            _error(f"{event_id} violates execution Event field constraints")
        if execution.get("status") != expected:
            _error(f"{event_id} execution.status must equal {expected}")
        if not isinstance(execution.get("observed_behavior"), str) or not execution.get("observed_behavior"):
            _error(f"{event_id} execution.observed_behavior must be a non-empty string")
    if scope is not None:
        if not isinstance(scope, dict):
            _error(f"{event_id}.scope_updates must be an object or null")
        persistence = scope.get("persistence")
        if persistence is not None and persistence not in PERSISTENCE_VALUES:
            _error(f"{event_id} has invalid persistence")
        for field in ("components", "contexts"):
            values = scope.get(field)
            if values is not None:
                if not isinstance(values, list) or any(
                    not isinstance(item, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", item) for item in values
                ):
                    _error(f"{event_id}.{field} must use uppercase SNAKE_CASE")
