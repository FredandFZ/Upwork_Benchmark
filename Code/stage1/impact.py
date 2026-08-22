"""Cross-Requirement impact discovery and patch translation for Stage 1.

Candidate discovery is deterministic and deliberately recall-oriented.  The
LLM receives the candidates and decides whether each one needs an Event; code
never propagates a source change merely because strings happen to match.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .preprocessing import message_index
from .storage import id_key, safe_filename


SCOPE_FIELDS = ("persistence", "components", "contexts")
IMPACT_SOURCE_EVENT_TYPES = {"MODIFY", "REMOVE"}

_GENERIC_TERMS = {
    "active",
    "attribute",
    "attributes",
    "behavior",
    "change",
    "changed",
    "client",
    "component",
    "components",
    "context",
    "contexts",
    "current",
    "event",
    "existing",
    "feature",
    "flow",
    "family",
    "frontend",
    "backend",
    "contract",
    "smart",
    "persistent",
    "persistence",
    "identifier",
    "implementation",
    "mode",
    "modify",
    "project",
    "requirement",
    "scope",
    "status",
    "system",
    "update",
    "updated",
    "value",
    "values",
    "with",
}


def source_ref_key(source_ref: dict[str, Any]) -> tuple[str, str, str, int]:
    return (
        str(source_ref.get("requirement_id")),
        id_key(source_ref.get("message_id")),
        str(source_ref.get("event_type")),
        int(source_ref.get("occurrence", 0)),
    )


def impact_case_filename(case: dict[str, Any]) -> str:
    requirement_id, message_id, event_type, occurrence = source_ref_key(case["source_event_ref"])
    return safe_filename(f"{requirement_id}_{message_id}_{event_type}_{occurrence}.json")


def _empty_state() -> dict[str, Any]:
    return {
        "attributes": {},
        "scope": {field: None for field in SCOPE_FIELDS},
        "lifecycle_status": None,
        "ambiguity": None,
    }


def _apply_event(state: dict[str, Any], event: dict[str, Any]) -> None:
    event_type = event.get("event_type")
    if event_type in {"INTRODUCE", "MODIFY"}:
        for attribute in event.get("value_removals") or []:
            state["attributes"].pop(attribute, None)
        for attribute, value in (event.get("value_updates") or {}).items():
            state["attributes"][attribute] = deepcopy(value)
        for dimension, value in (event.get("scope_updates") or {}).items():
            if dimension in SCOPE_FIELDS and value is not None:
                state["scope"][dimension] = deepcopy(value)
        if event_type == "INTRODUCE":
            state["lifecycle_status"] = "ACTIVE"
        if state.get("ambiguity") is not None:
            dimension = state["ambiguity"].get("dimension")
            if (
                (dimension == "VALUE" and (event.get("value_updates") or event.get("value_removals")))
                or (dimension == "SCOPE" and event.get("scope_updates"))
                or dimension == "LIFECYCLE"
            ):
                state["ambiguity"] = None
    elif event_type == "DEFER":
        state["lifecycle_status"] = "DEFERRED"
    elif event_type == "RESUME":
        state["lifecycle_status"] = "ACTIVE"
        state["ambiguity"] = None
    elif event_type == "REMOVE":
        state["lifecycle_status"] = "REMOVED"
        state["ambiguity"] = None
    elif event_type == "AMBIGUOUS":
        state["ambiguity"] = deepcopy(event.get("ambiguity"))


def _ordered_events(
    events: list[dict[str, Any]],
    message_order: dict[str, int],
) -> list[dict[str, Any]]:
    indexed = list(enumerate(events))
    indexed.sort(
        key=lambda pair: (
            message_order.get(id_key(pair[1].get("source_message", {}).get("message_id")), len(message_order)),
            pair[0],
        )
    )
    return [event for _, event in indexed]


def requirement_timeline(
    requirement_id: str,
    events: list[dict[str, Any]],
    message_order: dict[str, int],
) -> list[dict[str, Any]]:
    """Replay provisional Events and retain before/after snapshots and locators."""
    state = _empty_state()
    occurrences: dict[tuple[str, str], int] = {}
    timeline: list[dict[str, Any]] = []
    for event in _ordered_events(events, message_order):
        source = event.get("source_message", {})
        message_key = id_key(source.get("message_id"))
        event_type = str(event.get("event_type"))
        occurrence_key = (message_key, event_type)
        occurrences[occurrence_key] = occurrences.get(occurrence_key, 0) + 1
        before = deepcopy(state)
        _apply_event(state, event)
        timeline.append(
            {
                "position": message_order.get(message_key, len(message_order)),
                "event": event,
                "source_event_ref": {
                    "requirement_id": requirement_id,
                    "message_id": source.get("message_id"),
                    "event_type": event_type,
                    "occurrence": occurrences[occurrence_key],
                },
                "state_before": before,
                "state_after": deepcopy(state),
            }
        )
    return timeline


def state_at_position(timeline: list[dict[str, Any]], cutoff: int) -> dict[str, Any]:
    state = _empty_state()
    for entry in timeline:
        if entry["position"] > cutoff:
            break
        state = deepcopy(entry["state_after"])
    return state


def history_at_position(timeline: list[dict[str, Any]], cutoff: int) -> list[dict[str, Any]]:
    return [deepcopy(entry["event"]) for entry in timeline if entry["position"] <= cutoff]


def _flatten_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        result: list[str] = []
        for key, item in value.items():
            result.append(str(key))
            result.extend(_flatten_strings(item))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_flatten_strings(item))
        return result
    return [str(value)]


def _normalize_text(value: Any) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value))
    text = re.sub(r"[^A-Za-z0-9]+", " ", text).lower()
    return " ".join(text.split())


def _entity_aliases(values: list[Any]) -> list[str]:
    aliases: set[str] = set()
    for value in values:
        for raw in _flatten_strings(value):
            normalized = _normalize_text(raw)
            words = normalized.split()
            if not words:
                continue
            if 1 < len(words) <= 10 and len(normalized) >= 5:
                aliases.add(normalized)
            for size in (2, 3, 4):
                for start in range(0, len(words) - size + 1):
                    phrase_words = words[start : start + size]
                    if all(word in _GENERIC_TERMS for word in phrase_words):
                        continue
                    aliases.add(" ".join(phrase_words))
            for word in words:
                if len(word) >= 4 and word not in _GENERIC_TERMS and not word.isdigit():
                    aliases.add(word)
    return sorted(aliases, key=lambda item: (-len(item.split()), -len(item), item))


def _source_alias_values(
    requirement: dict[str, Any],
    family: dict[str, Any] | None,
    entry: dict[str, Any],
) -> list[Any]:
    event = entry["event"]
    before = entry["state_before"]
    after = entry["state_after"]
    values: list[Any] = [
        requirement.get("requirement_id", "").replace("REQ_", ""),
        requirement.get("title"),
        (family or {}).get("family_id"),
        (family or {}).get("title"),
        event.get("value_updates"),
        event.get("value_removals"),
        event.get("scope_updates"),
    ]
    if event.get("event_type") == "REMOVE":
        values.extend(
            [
                before.get("attributes"),
                before.get("scope", {}).get("contexts"),
            ]
        )
    else:
        for key in event.get("value_removals") or []:
            values.extend([key, before.get("attributes", {}).get(key)])
        for key, new_value in (event.get("value_updates") or {}).items():
            values.extend([key, before.get("attributes", {}).get(key), new_value])
        for key, new_value in (event.get("scope_updates") or {}).items():
            if new_value is not None:
                values.extend([key, before.get("scope", {}).get(key), after.get("scope", {}).get(key)])
    return values


def _candidate_documents(
    requirement: dict[str, Any],
    family: dict[str, Any] | None,
    state: dict[str, Any],
    history: list[dict[str, Any]],
) -> tuple[str, str]:
    current_values: list[Any] = [
        requirement.get("requirement_id", "").replace("REQ_", ""),
        requirement.get("title"),
        (family or {}).get("family_id"),
        (family or {}).get("title"),
        state.get("attributes"),
        state.get("scope"),
    ]
    history_values: list[Any] = []
    for event in history:
        history_values.extend(
            [
                event.get("source_message", {}).get("text"),
                event.get("value_updates"),
                event.get("value_removals"),
                event.get("scope_updates"),
            ]
        )
    return (
        _normalize_text(" ".join(_flatten_strings(current_values))),
        _normalize_text(" ".join(_flatten_strings(history_values))),
    )


def _alias_matches(aliases: list[str], document: str) -> tuple[int, list[str]]:
    score = 0
    matched: list[str] = []
    padded = f" {document} "
    for alias in aliases:
        if f" {alias} " not in padded:
            continue
        words = alias.split()
        if len(words) >= 2:
            weight = min(12, 3 + len(words))
        elif len(alias) >= 8:
            weight = 3
        elif len(alias) >= 5:
            weight = 2
        else:
            weight = 1
        score += weight
        matched.append(alias)
    return score, matched[:16]


def _trigger_reasons(entry: dict[str, Any]) -> list[str]:
    event = entry["event"]
    if event.get("event_type") == "REMOVE":
        return ["REQUIREMENT_REMOVED"]
    reasons: list[str] = []
    if event.get("value_removals"):
        reasons.append("ATTRIBUTE_REMOVAL")
    if event.get("value_updates"):
        reasons.append("VALUE_CHANGE")
    if event.get("scope_updates"):
        reasons.append("SCOPE_CHANGE")
    return reasons


def build_impact_cases(
    inventory: dict[str, Any],
    events_by_requirement: dict[str, list[dict[str, Any]]],
    normalized: dict[str, Any],
    *,
    max_candidates_per_event: int = 12,
) -> list[dict[str, Any]]:
    """Build temporally bounded candidates for every material MODIFY/REMOVE."""
    _, message_order = message_index(normalized)
    requirements = {
        requirement["requirement_id"]: requirement
        for requirement in inventory.get("requirements", [])
        if isinstance(requirement, dict) and requirement.get("requirement_id")
    }
    families = {
        family.get("family_id"): family
        for family in inventory.get("requirement_families", [])
        if isinstance(family, dict) and family.get("family_id")
    }
    timelines = {
        requirement_id: requirement_timeline(
            requirement_id,
            events_by_requirement.get(requirement_id, []),
            message_order,
        )
        for requirement_id in requirements
    }

    cases: list[dict[str, Any]] = []
    for source_requirement_id, source_requirement in requirements.items():
        source_family = families.get(source_requirement.get("family_id"))
        for entry in timelines[source_requirement_id]:
            event = entry["event"]
            if event.get("event_type") not in IMPACT_SOURCE_EVENT_TYPES:
                continue
            aliases = _entity_aliases(_source_alias_values(source_requirement, source_family, entry))
            if not aliases:
                continue
            candidates: list[dict[str, Any]] = []
            for candidate_id, candidate_requirement in requirements.items():
                if candidate_id == source_requirement_id:
                    continue
                state = state_at_position(timelines[candidate_id], entry["position"])
                history = history_at_position(timelines[candidate_id], entry["position"])
                if not history or state.get("lifecycle_status") == "REMOVED":
                    continue
                candidate_family = families.get(candidate_requirement.get("family_id"))
                current_document, history_document = _candidate_documents(
                    candidate_requirement,
                    candidate_family,
                    state,
                    history,
                )
                current_score, current_matches = _alias_matches(aliases, current_document)
                history_score, history_matches = _alias_matches(aliases, history_document)
                score = current_score * 4 + history_score
                matched_aliases = list(dict.fromkeys(current_matches + history_matches))[:16]
                same_family = bool(
                    source_requirement.get("family_id")
                    and source_requirement.get("family_id") == candidate_requirement.get("family_id")
                )
                if score <= 0:
                    continue
                if same_family:
                    score += 1
                candidates.append(
                    {
                        "candidate_requirement_id": candidate_id,
                        "title": candidate_requirement.get("title"),
                        "family_id": candidate_requirement.get("family_id"),
                        "candidate_score": score,
                        "matched_entity_aliases": matched_aliases,
                        "current_state_at_source_event": state,
                        "requirement_history_through_source_event": history,
                    }
                )
            candidates.sort(
                key=lambda item: (
                    -int(item["candidate_score"]),
                    str(item["candidate_requirement_id"]),
                )
            )
            candidates = candidates[:max_candidates_per_event]
            if not candidates:
                continue
            cases.append(
                {
                    "source_event_ref": deepcopy(entry["source_event_ref"]),
                    "source_requirement": {
                        "requirement_id": source_requirement_id,
                        "title": source_requirement.get("title"),
                        "family_id": source_requirement.get("family_id"),
                    },
                    "source_event": deepcopy(event),
                    "source_state_before": deepcopy(entry["state_before"]),
                    "source_state_after": deepcopy(entry["state_after"]),
                    "trigger_reasons": _trigger_reasons(entry),
                    "entity_aliases": aliases[:40],
                    "candidates": candidates,
                }
            )
    return cases


def _event_locator(events: list[dict[str, Any]], target_index: int) -> dict[str, Any]:
    target = events[target_index]
    source = target.get("source_message", {})
    target_message = id_key(source.get("message_id"))
    target_type = target.get("event_type")
    occurrence = 0
    for event in events[: target_index + 1]:
        event_source = event.get("source_message", {})
        if id_key(event_source.get("message_id")) == target_message and event.get("event_type") == target_type:
            occurrence += 1
    return {
        "message_id": source.get("message_id"),
        "event_type": target_type,
        "occurrence": occurrence,
    }


def _semantic_payload(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_type": event.get("event_type"),
        "value_updates": deepcopy(event.get("value_updates")),
        "value_removals": deepcopy(event.get("value_removals")),
        "scope_updates": deepcopy(event.get("scope_updates")),
        "ambiguity": deepcopy(event.get("ambiguity")),
        "execution": deepcopy(event.get("execution")),
    }


def _merge_modify_event(existing: dict[str, Any], proposed: dict[str, Any]) -> dict[str, Any]:
    existing_updates = deepcopy(existing.get("value_updates") or {})
    proposed_updates = deepcopy(proposed.get("value_updates") or {})
    removals: list[str] = []
    for attribute in (existing.get("value_removals") or []) + (proposed.get("value_removals") or []):
        if attribute not in removals:
            removals.append(attribute)
    for attribute in proposed_updates:
        if attribute in removals:
            removals.remove(attribute)
    for attribute in proposed.get("value_removals") or []:
        existing_updates.pop(attribute, None)
    updates = {**existing_updates, **proposed_updates}

    scope = deepcopy(existing.get("scope_updates") or {})
    for dimension, value in (proposed.get("scope_updates") or {}).items():
        if value is not None:
            scope[dimension] = deepcopy(value)
    return {
        "event_type": "MODIFY",
        "value_updates": updates or None,
        "value_removals": removals or None,
        "scope_updates": scope or None,
        "ambiguity": None,
        "execution": None,
    }


def impact_decisions_to_patches(
    case: dict[str, Any],
    audit: dict[str, Any],
    events_by_requirement: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Translate accepted pair decisions into ordinary Stage 1 audit patches."""
    patches: list[dict[str, Any]] = []
    human_review: list[dict[str, Any]] = []
    source_event = case["source_event"]
    source_message = source_event.get("source_message", {})
    source_message_key = id_key(source_message.get("message_id"))

    for decision in audit.get("decisions", []):
        record = {
            "source": "CROSS_REQUIREMENT_IMPACT_AUDIT",
            "source_event_ref": deepcopy(case["source_event_ref"]),
            **deepcopy(decision),
        }
        action = decision.get("decision")
        if action in {"NO_IMPACT", "HUMAN_REVIEW"} or decision.get("confidence") != "HIGH":
            if action != "NO_IMPACT":
                human_review.append(record)
            continue

        requirement_id = decision["candidate_requirement_id"]
        proposed = deepcopy(decision.get("new_event") or {})
        proposed.setdefault("value_removals", None)
        proposed_source = proposed.get("source_message", {})
        if id_key(proposed_source.get("message_id")) != source_message_key:
            record["application_error"] = "new_event must use the source impact Event's message_id"
            human_review.append(record)
            continue
        candidate_events = events_by_requirement.get(requirement_id, [])

        target_index: int | None = None
        if action == "EDIT_EVENT":
            locator = decision.get("event_locator") or {}
            wanted_message = id_key(locator.get("message_id"))
            wanted_type = locator.get("event_type")
            wanted_occurrence = int(locator.get("occurrence", 1))
            occurrence = 0
            for index, event in enumerate(candidate_events):
                if (
                    id_key(event.get("source_message", {}).get("message_id")) == wanted_message
                    and event.get("event_type") == wanted_type
                ):
                    occurrence += 1
                    if occurrence == wanted_occurrence:
                        target_index = index
                        break
            if target_index is None:
                record["application_error"] = "EDIT_EVENT locator does not identify an existing candidate Event"
                human_review.append(record)
                continue
        else:
            same_message_modifies = [
                index
                for index, event in enumerate(candidate_events)
                if event.get("event_type") == "MODIFY"
                and id_key(event.get("source_message", {}).get("message_id")) == source_message_key
            ]
            if len(same_message_modifies) == 1:
                target_index = same_message_modifies[0]
            elif len(same_message_modifies) > 1:
                record["application_error"] = "Several same-message MODIFY Events exist; explicit EDIT_EVENT is required"
                human_review.append(record)
                continue

        operation = "ADD_EVENT"
        targets: dict[str, Any] = {"requirement_id": requirement_id}
        replacement: dict[str, Any]
        if target_index is not None:
            operation = "EDIT_EVENT"
            targets["event_locator"] = _event_locator(candidate_events, target_index)
            replacement = _merge_modify_event(candidate_events[target_index], proposed)
        else:
            replacement = {
                "source_message": deepcopy(source_message),
                "supporting_message_ids": [],
                **_semantic_payload(proposed),
            }

        patches.append(
            {
                "operation": operation,
                "targets": targets,
                "replacement": replacement,
                "evidence_message_ids": [source_message.get("message_id")],
                "decision_note": decision.get("reason"),
                "confidence": "HIGH",
                "source_event_ref": deepcopy(case["source_event_ref"]),
            }
        )
    return patches, human_review


def resolve_source_event_ids(report: dict[str, Any], annotation: dict[str, Any]) -> dict[str, Any]:
    """Attach final Event IDs to audit records after deterministic assembly."""
    lookup: dict[tuple[str, str, str, int], str] = {}
    for requirement in annotation.get("requirements", []):
        requirement_id = requirement.get("requirement_id")
        occurrences: dict[tuple[str, str], int] = {}
        for event in requirement.get("events", []):
            source = event.get("source_message", {})
            pair = (id_key(source.get("message_id")), str(event.get("event_type")))
            occurrences[pair] = occurrences.get(pair, 0) + 1
            lookup[(str(requirement_id), pair[0], pair[1], occurrences[pair])] = event.get("event_id")

    resolved = deepcopy(report)
    for record in resolved.get("records", []):
        source_ref = record.get("source_event_ref")
        if isinstance(source_ref, dict):
            record["source_event_id"] = lookup.get(source_ref_key(source_ref))
    return resolved
