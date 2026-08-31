from __future__ import annotations

from copy import deepcopy
from typing import Any

from .preprocessing import message_index
from .storage import id_key


def _canonical_event(event: dict[str, Any], event_id: str) -> dict[str, Any]:
    source = event.get("source_message") or {}
    return {
        "event_id": event_id,
        "source_message": {
            "message_id": source.get("message_id"),
            "speaker": source.get("speaker"),
            "text": source.get("text"),
        },
        "event_type": event.get("event_type"),
        "value_updates": deepcopy(event.get("value_updates")),
        "value_removals": deepcopy(event.get("value_removals")),
        "scope_updates": deepcopy(event.get("scope_updates")),
        "ambiguity": deepcopy(event.get("ambiguity")),
        "execution": deepcopy(event.get("execution")),
        "resolves_ambiguity_event_ids": deepcopy(
            event.get("resolves_ambiguity_event_ids")
        ),
    }


def sort_events_by_message_order(
    normalized: dict[str, Any],
    events_by_requirement: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Return a stable chronological copy of every Requirement's Events.

    This is the single ordering implementation used by checkpoints, ambiguity
    linking, and final assembly. Stable same-message ordering is inherited from
    the input list.
    """
    _, order = message_index(normalized)
    result: dict[str, list[dict[str, Any]]] = {}
    for requirement_id, provisional in events_by_requirement.items():
        indexed = list(enumerate(provisional))
        indexed.sort(
            key=lambda pair: (
                order.get(_message_key(pair[1]), len(order)),
                pair[0],
            )
        )
        result[requirement_id] = [deepcopy(event) for _, event in indexed]
    return result


def preallocate_event_ids(
    normalized: dict[str, Any],
    events_by_requirement: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Sort Events and assign the exact IDs that final assembly will use."""
    ordered = sort_events_by_message_order(normalized, events_by_requirement)
    for requirement_id, events in ordered.items():
        for number, event in enumerate(events, start=1):
            event["event_id"] = f"{requirement_id}_E{number:03d}"
            event.setdefault("resolves_ambiguity_event_ids", None)
    return ordered


def _remove_meaningless_families(inventory: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requirements = deepcopy(inventory.get("requirements", []))
    counts: dict[str, int] = {}
    for requirement in requirements:
        family_id = requirement.get("family_id")
        if family_id:
            counts[family_id] = counts.get(family_id, 0) + 1
    retained_ids = {family_id for family_id, count in counts.items() if count >= 2}
    families = [
        {"family_id": family.get("family_id"), "title": family.get("title")}
        for family in inventory.get("requirement_families", [])
        if family.get("family_id") in retained_ids
    ]
    for requirement in requirements:
        if requirement.get("family_id") not in retained_ids:
            requirement["family_id"] = None
    return families, requirements


def assemble_stage1_annotation(
    normalized: dict[str, Any],
    inventory: dict[str, Any],
    events_by_requirement: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    families, requirements = _remove_meaningless_families(inventory)
    preallocated = preallocate_event_ids(normalized, events_by_requirement)
    final_requirements: list[dict[str, Any]] = []
    for requirement in requirements:
        requirement_id = requirement["requirement_id"]
        events = [
            _canonical_event(event, event["event_id"])
            for event in preallocated.get(requirement_id, [])
        ]
        final_requirements.append(
            {
                "requirement_id": requirement_id,
                "title": requirement.get("title"),
                "family_id": requirement.get("family_id"),
                "events": events,
            }
        )

    sessions = [
        {
            "session_id": session.get("session_id"),
            "start": session.get("start"),
            "end": session.get("end"),
            "milestone": session.get("milestone"),
        }
        for session in inventory.get("sessions", [])
    ]
    return {
        "benchmark": "ReqMemBench",
        "annotation_version": "v0.6",
        "project": {
            "project_id": normalized["project_id"],
            "project_title": normalized.get("project_title") or normalized["project_id"],
            "sessions": sessions,
        },
        "requirement_families": families,
        "requirements": final_requirements,
    }


def _message_key(event: dict[str, Any]) -> str:
    return id_key(event.get("source_message", {}).get("message_id"))
