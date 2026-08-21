from __future__ import annotations

from copy import deepcopy
from typing import Any


def filter_short_requirements(
    inventory: dict[str, Any],
    events: dict[str, list[dict[str, Any]]],
    minimum_events: int,
    discarded_after: str,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Remove Requirements whose current lifecycle is shorter than the benchmark minimum."""
    retained_requirements: list[dict[str, Any]] = []
    discarded: list[dict[str, Any]] = []
    retained_events: dict[str, list[dict[str, Any]]] = {}

    for requirement in inventory.get("requirements", []):
        requirement_id = requirement.get("requirement_id")
        requirement_events = deepcopy(events.get(requirement_id, []))
        event_count = len(requirement_events)
        if event_count < minimum_events:
            discarded.append(
                {
                    "requirement_id": requirement_id,
                    "title": requirement.get("title"),
                    "family_id": requirement.get("family_id"),
                    "event_count": event_count,
                    "minimum_events": minimum_events,
                    "discarded_after": discarded_after,
                    "reason": "Lifecycle contains fewer events than the configured instance-construction minimum.",
                    "events": requirement_events,
                }
            )
            continue
        retained_requirements.append(deepcopy(requirement))
        retained_events[requirement_id] = requirement_events

    family_counts: dict[str, int] = {}
    for requirement in retained_requirements:
        family_id = requirement.get("family_id")
        if family_id:
            family_counts[family_id] = family_counts.get(family_id, 0) + 1
    retained_family_ids = {family_id for family_id, count in family_counts.items() if count >= 2}
    for requirement in retained_requirements:
        if requirement.get("family_id") not in retained_family_ids:
            requirement["family_id"] = None

    filtered_inventory = deepcopy(inventory)
    filtered_inventory["requirements"] = retained_requirements
    filtered_inventory["requirement_families"] = [
        deepcopy(family)
        for family in inventory.get("requirement_families", [])
        if family.get("family_id") in retained_family_ids
    ]
    return filtered_inventory, retained_events, discarded


def merge_discarded_requirements(
    existing: list[dict[str, Any]],
    additional: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge lifecycle-filter records, preferring the newest stage for duplicate IDs."""
    merged = [deepcopy(item) for item in existing]
    positions = {item.get("requirement_id"): index for index, item in enumerate(merged)}
    for item in additional:
        requirement_id = item.get("requirement_id")
        if requirement_id in positions:
            merged[positions[requirement_id]] = deepcopy(item)
        else:
            positions[requirement_id] = len(merged)
            merged.append(deepcopy(item))
    return merged
