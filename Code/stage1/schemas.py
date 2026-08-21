from __future__ import annotations

from typing import Any

from .storage import id_key


EVENT_TYPES = {
    "INTRODUCE",
    "MODIFY",
    "DEFER",
    "RESUME",
    "REMOVE",
    "AMBIGUOUS",
    "IMPLEMENTATION_CLAIM",
    "RUNTIME_FAILURE",
    "RUNTIME_VERIFICATION",
}
EVIDENCE_TAGS = {
    "REQUIREMENT_INTRODUCTION",
    "REQUIREMENT_CHANGE",
    "SCOPE_CHANGE",
    "LIFECYCLE_CHANGE",
    "AMBIGUITY_OR_CONFLICT",
    "IMPLEMENTATION_CLAIM",
    "RUNTIME_FAILURE",
    "RUNTIME_VERIFICATION",
    "CLIENT_ACCEPTANCE",
    "FAMILY_LEVEL_STATEMENT",
    "EXPECTED_BEHAVIOR_EVIDENCE",
}
CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
AUDIT_OPERATIONS = {
    "ADD_REQUIREMENT",
    "MERGE_REQUIREMENTS",
    "SPLIT_REQUIREMENT",
    "DELETE_REQUIREMENT",
    "CHANGE_FAMILY",
    "ADD_EVENT",
    "DELETE_EVENT",
    "EDIT_EVENT",
    "MOVE_EVENT",
    "CHANGE_SESSION",
    "HUMAN_REVIEW",
}


class PassSchemaError(ValueError):
    pass


def _dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PassSchemaError(f"{label} must be an object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise PassSchemaError(f"{label} must be an array")
    return value


def _run_mode(data: dict[str, Any], expected: str) -> None:
    if data.get("run_mode") != expected:
        raise PassSchemaError(f"Expected run_mode={expected}, got {data.get('run_mode')!r}")


def validate_evidence_scan(data: dict[str, Any], valid_message_ids: set[str]) -> None:
    _run_mode(data, "EVIDENCE_SCAN")
    for index, candidate_value in enumerate(_list(data.get("candidates"), "candidates")):
        candidate = _dict(candidate_value, f"candidates[{index}]")
        if id_key(candidate.get("message_id")) not in valid_message_ids:
            raise PassSchemaError(f"Unknown candidate message_id: {candidate.get('message_id')!r}")
        tags = _list(candidate.get("evidence_tags"), "evidence_tags")
        if any(tag not in EVIDENCE_TAGS for tag in tags):
            raise PassSchemaError("Unsupported evidence tag")
        _list(candidate.get("topic_hints"), "topic_hints")
        context_ids = _list(candidate.get("context_message_ids"), "context_message_ids")
        if any(id_key(value) not in valid_message_ids for value in context_ids):
            raise PassSchemaError("Unknown context_message_id")
        if candidate.get("confidence") not in CONFIDENCE:
            raise PassSchemaError("Unsupported evidence confidence")


def validate_requirement_discovery(data: dict[str, Any]) -> None:
    _run_mode(data, "REQUIREMENT_DISCOVERY")
    sessions = _list(data.get("sessions"), "sessions")
    families = _list(data.get("requirement_families"), "requirement_families")
    requirements = _list(data.get("requirements"), "requirements")
    _list(data.get("unresolved_candidates"), "unresolved_candidates")
    session_ids = [str(_dict(value, "session").get("session_id", "")) for value in sessions]
    family_ids = [str(_dict(value, "family").get("family_id", "")) for value in families]
    requirement_ids = [str(_dict(value, "requirement").get("requirement_id", "")) for value in requirements]
    for label, values in (("session", session_ids), ("family", family_ids), ("requirement", requirement_ids)):
        if any(not value for value in values) or len(values) != len(set(values)):
            raise PassSchemaError(f"{label} IDs must be non-empty and unique")
    family_set = set(family_ids)
    for requirement in requirements:
        if requirement.get("family_id") is not None and requirement.get("family_id") not in family_set:
            raise PassSchemaError(f"Unknown family_id: {requirement.get('family_id')}")
        _list(requirement.get("anchor_message_ids"), "anchor_message_ids")
        if requirement.get("confidence") not in CONFIDENCE:
            raise PassSchemaError("Unsupported requirement confidence")


def validate_event_shape(event: dict[str, Any], allow_supporting: bool = True) -> None:
    if event.get("event_type") not in EVENT_TYPES:
        raise PassSchemaError(f"Unsupported event_type: {event.get('event_type')!r}")
    source = _dict(event.get("source_message"), "source_message")
    if "message_id" not in source or not isinstance(source.get("speaker"), str) or not isinstance(source.get("text"), str):
        raise PassSchemaError("source_message requires message_id, speaker, and text")
    if "event_id" in event and event.get("event_id") is not None:
        raise PassSchemaError("The LLM must not generate event_id")
    if allow_supporting and "supporting_message_ids" in event:
        _list(event.get("supporting_message_ids"), "supporting_message_ids")


def validate_event_extraction(data: dict[str, Any], requirement_id: str) -> None:
    _run_mode(data, "EVENT_EXTRACTION")
    if data.get("requirement_id") != requirement_id:
        raise PassSchemaError("EVENT_EXTRACTION returned the wrong requirement_id")
    for event_value in _list(data.get("events"), "events"):
        validate_event_shape(_dict(event_value, "event"))
    _list(data.get("routing_warnings"), "routing_warnings")
    _list(data.get("missing_requirement_candidates"), "missing_requirement_candidates")


def validate_consistency_audit(data: dict[str, Any]) -> None:
    _run_mode(data, "CONSISTENCY_AUDIT")
    for patch_value in _list(data.get("patches"), "patches"):
        patch = _dict(patch_value, "patch")
        if patch.get("operation") not in AUDIT_OPERATIONS:
            raise PassSchemaError(f"Unsupported audit operation: {patch.get('operation')!r}")
        _dict(patch.get("targets"), "patch.targets")
        _list(patch.get("evidence_message_ids"), "patch.evidence_message_ids")
        if patch.get("confidence") not in CONFIDENCE:
            raise PassSchemaError("Unsupported patch confidence")
        if not isinstance(patch.get("decision_note"), str):
            raise PassSchemaError("patch.decision_note must be a string")


def event_locators(events: list[dict[str, Any]]) -> list[tuple[str, str, int]]:
    occurrences: dict[tuple[str, str], int] = {}
    result: list[tuple[str, str, int]] = []
    for event in events:
        source = event.get("source_message", {})
        pair = (id_key(source.get("message_id")), str(event.get("event_type")))
        occurrences[pair] = occurrences.get(pair, 0) + 1
        result.append((pair[0], pair[1], occurrences[pair]))
    return result


def validate_event_verification(data: dict[str, Any], requirement_id: str, events: list[dict[str, Any]]) -> None:
    _run_mode(data, "EVENT_VERIFICATION")
    if data.get("requirement_id") != requirement_id:
        raise PassSchemaError("EVENT_VERIFICATION returned the wrong requirement_id")
    expected = set(event_locators(events))
    received: list[tuple[str, str, int]] = []
    for verdict_value in _list(data.get("verdicts"), "verdicts"):
        verdict = _dict(verdict_value, "verdict")
        locator = _dict(verdict.get("event_locator"), "event_locator")
        key = (
            id_key(locator.get("message_id")),
            str(locator.get("event_type")),
            int(locator.get("occurrence", 0)),
        )
        received.append(key)
        if verdict.get("verdict") not in {"KEEP", "EDIT", "DELETE"}:
            raise PassSchemaError("Unsupported verifier verdict")
        if verdict.get("confidence") not in CONFIDENCE:
            raise PassSchemaError("Unsupported verifier confidence")
        if verdict.get("verdict") == "EDIT" and not isinstance(verdict.get("replacement"), dict):
            raise PassSchemaError("EDIT verdict requires a replacement object")
        if verdict.get("verdict") == "DELETE" and verdict.get("replacement") is not None:
            raise PassSchemaError("DELETE verdict replacement must be null")
    if len(received) != len(set(received)) or set(received) != expected:
        raise PassSchemaError("Verifier must return exactly one verdict for every provisional Event")
    _list(data.get("missing_event_candidates"), "missing_event_candidates")
