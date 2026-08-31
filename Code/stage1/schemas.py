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
IMPACT_DECISIONS = {"ADD_EVENT", "EDIT_EVENT", "NO_IMPACT", "HUMAN_REVIEW"}
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


def _locator_key(locator: dict[str, Any], *, include_requirement: bool) -> tuple[Any, ...]:
    prefix: tuple[Any, ...] = ()
    if include_requirement:
        prefix = (str(locator.get("requirement_id")),)
    try:
        occurrence = int(locator.get("occurrence", 0))
    except (TypeError, ValueError) as exc:
        raise PassSchemaError("event locator occurrence must be an integer") from exc
    return prefix + (
        id_key(locator.get("message_id")),
        str(locator.get("event_type")),
        occurrence,
    )


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


def validate_cross_requirement_impact_audit(
    data: dict[str, Any],
    source_event_ref: dict[str, Any],
    candidate_requirement_ids: set[str],
) -> None:
    _run_mode(data, "CROSS_REQUIREMENT_IMPACT_AUDIT")
    received_source = _dict(data.get("source_event_ref"), "source_event_ref")
    if _locator_key(received_source, include_requirement=True) != _locator_key(
        source_event_ref, include_requirement=True
    ):
        raise PassSchemaError("Impact audit returned the wrong source_event_ref")

    received_candidates: list[str] = []
    for index, decision_value in enumerate(_list(data.get("decisions"), "decisions")):
        decision = _dict(decision_value, f"decisions[{index}]")
        candidate_id = decision.get("candidate_requirement_id")
        if not isinstance(candidate_id, str) or candidate_id not in candidate_requirement_ids:
            raise PassSchemaError(f"Unknown impact candidate Requirement: {candidate_id!r}")
        received_candidates.append(candidate_id)
        action = decision.get("decision")
        if action not in IMPACT_DECISIONS:
            raise PassSchemaError(f"Unsupported impact decision: {action!r}")
        if decision.get("confidence") not in CONFIDENCE:
            raise PassSchemaError("Unsupported impact decision confidence")
        if not isinstance(decision.get("reason"), str) or not decision.get("reason"):
            raise PassSchemaError("Impact decision reason must be a non-empty string")

        new_event = decision.get("new_event")
        event_locator = decision.get("event_locator")
        if action in {"ADD_EVENT", "EDIT_EVENT"}:
            event = _dict(new_event, "impact decision new_event")
            validate_event_shape(event)
            if event.get("event_type") != "MODIFY":
                raise PassSchemaError("Cross-Requirement propagation may only add/edit MODIFY Events")
            if action == "EDIT_EVENT":
                _dict(event_locator, "impact decision event_locator")
            elif event_locator is not None:
                raise PassSchemaError("ADD_EVENT event_locator must be null")
        elif new_event is not None or event_locator is not None:
            raise PassSchemaError(f"{action} must not contain new_event or event_locator")

    if len(received_candidates) != len(set(received_candidates)) or set(received_candidates) != candidate_requirement_ids:
        raise PassSchemaError("Impact audit must return exactly one decision for every candidate Requirement")


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


def validate_ambiguity_linking(data: dict[str, Any], requirement_id: str) -> None:
    """Validate response shape; semantic link safety is checked during apply."""
    _run_mode(data, "AMBIGUITY_LINKING")
    if data.get("requirement_id") != requirement_id:
        raise PassSchemaError("AMBIGUITY_LINKING returned the wrong requirement_id")
    for index, decision_value in enumerate(_list(data.get("decisions"), "decisions")):
        decision = _dict(decision_value, f"decisions[{index}]")
        ambiguity_event_id = decision.get("ambiguity_event_id")
        if not isinstance(ambiguity_event_id, str) or not ambiguity_event_id:
            raise PassSchemaError("ambiguity_event_id must be a non-empty string")
        affected_paths = _list(decision.get("affected_state_paths"), "affected_state_paths")
        if not affected_paths or any(not isinstance(path, str) or not path for path in affected_paths):
            raise PassSchemaError("affected_state_paths must be a non-empty string array")
        status = decision.get("resolution_status")
        if status not in {"RESOLVED", "UNRESOLVED"}:
            raise PassSchemaError("resolution_status must be RESOLVED or UNRESOLVED")
        resolver_event_id = decision.get("resolver_event_id")
        if status == "RESOLVED":
            if not isinstance(resolver_event_id, str) or not resolver_event_id:
                raise PassSchemaError("RESOLVED decision requires resolver_event_id")
        elif resolver_event_id is not None:
            raise PassSchemaError("UNRESOLVED decision resolver_event_id must be null")
        intermediate_ids = _list(
            decision.get("non_resolving_intermediate_event_ids"),
            "non_resolving_intermediate_event_ids",
        )
        if any(not isinstance(event_id, str) or not event_id for event_id in intermediate_ids):
            raise PassSchemaError(
                "non_resolving_intermediate_event_ids must contain non-empty strings"
            )
        if len(intermediate_ids) != len(set(intermediate_ids)):
            raise PassSchemaError("non_resolving_intermediate_event_ids must not contain duplicates")
        if not isinstance(decision.get("decision_note"), str) or not decision.get("decision_note"):
            raise PassSchemaError("decision_note must be a non-empty string")
        if decision.get("confidence") not in CONFIDENCE:
            raise PassSchemaError("Unsupported ambiguity-linking confidence")
