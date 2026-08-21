from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .storage import id_key


ONTOLOGY_OPERATIONS = {"ADD_REQUIREMENT", "MERGE_REQUIREMENTS", "SPLIT_REQUIREMENT", "DELETE_REQUIREMENT"}


@dataclass
class PatchResult:
    inventory: dict[str, Any]
    events: dict[str, list[dict[str, Any]]]
    affected_requirements: set[str] = field(default_factory=set)
    boundary_changed: bool = False
    human_review: list[dict[str, Any]] = field(default_factory=list)
    applied_count: int = 0


def _requirement_map(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["requirement_id"]: item for item in inventory.get("requirements", [])}


def has_valid_requirement_ids(inventory: dict[str, Any]) -> bool:
    requirements = inventory.get("requirements")
    if not isinstance(requirements, list):
        return False
    requirement_ids: list[str] = []
    for requirement in requirements:
        if not isinstance(requirement, dict):
            return False
        requirement_id = requirement.get("requirement_id")
        if not isinstance(requirement_id, str) or not requirement_id.strip():
            return False
        requirement_ids.append(requirement_id)
    return len(requirement_ids) == len(set(requirement_ids))


def _event_index(events: list[dict[str, Any]], locator: dict[str, Any]) -> int:
    wanted_id = id_key(locator.get("message_id"))
    wanted_type = locator.get("event_type")
    wanted_occurrence = int(locator.get("occurrence", 1))
    occurrence = 0
    for index, event in enumerate(events):
        source_id = id_key(event.get("source_message", {}).get("message_id"))
        if source_id == wanted_id and event.get("event_type") == wanted_type:
            occurrence += 1
            if occurrence == wanted_occurrence:
                return index
    raise ValueError(f"Event locator not found: {locator}")


def _replacement_requirement(value: dict[str, Any], old: dict[str, Any] | None = None) -> dict[str, Any]:
    base = deepcopy(old or {})
    base.update(deepcopy(value))
    base.setdefault("definition", "")
    base.setdefault("anchor_message_ids", [])
    base.setdefault("scope_hypothesis", None)
    base.setdefault("boundary_note", "Changed by consistency audit.")
    base.setdefault("confidence", "HIGH")
    return base


def apply_audit_patches(
    inventory: dict[str, Any],
    events: dict[str, list[dict[str, Any]]],
    patches: list[dict[str, Any]],
) -> PatchResult:
    updated_inventory = deepcopy(inventory)
    updated_events = deepcopy(events)
    result = PatchResult(updated_inventory, updated_events)
    requirements = updated_inventory.setdefault("requirements", [])

    for patch in patches:
        if patch.get("confidence") != "HIGH" or patch.get("operation") == "HUMAN_REVIEW":
            result.human_review.append(deepcopy(patch))
            continue
        operation = patch.get("operation")
        targets = patch.get("targets", {})
        replacement = patch.get("replacement")
        req_map = _requirement_map(updated_inventory)
        try:
            if operation == "ADD_REQUIREMENT":
                new = _replacement_requirement(replacement)
                if new["requirement_id"] in req_map:
                    raise ValueError("ADD_REQUIREMENT ID already exists")
                requirements.append(new)
                updated_events[new["requirement_id"]] = []
                result.affected_requirements.add(new["requirement_id"])
                result.boundary_changed = True
            elif operation == "MERGE_REQUIREMENTS":
                source_ids = list(targets.get("requirement_ids", []))
                if len(source_ids) < 2 or any(value not in req_map for value in source_ids):
                    raise ValueError("MERGE_REQUIREMENTS targets are invalid")
                if not isinstance(replacement, dict):
                    raise ValueError("MERGE_REQUIREMENTS replacement is invalid")
                merged_id = replacement.get("requirement_id")
                if not isinstance(merged_id, str) or not merged_id.strip():
                    raise ValueError("MERGE_REQUIREMENTS replacement ID is empty")
                merged = _replacement_requirement(replacement, req_map.get(merged_id))
                removed_ids = set(source_ids)
                removed_ids.add(merged_id)
                requirements[:] = [item for item in requirements if item["requirement_id"] not in removed_ids]
                requirements.append(merged)
                for source_id in removed_ids:
                    updated_events.pop(source_id, None)
                updated_events[merged_id] = []
                result.affected_requirements.add(merged_id)
                result.boundary_changed = True
            elif operation == "SPLIT_REQUIREMENT":
                source_id = targets.get("requirement_id")
                if source_id not in req_map:
                    raise ValueError("SPLIT_REQUIREMENT target is invalid")
                if not isinstance(replacement, dict):
                    raise ValueError("SPLIT_REQUIREMENT replacement is invalid")
                parts = replacement.get("requirements", [])
                if not isinstance(parts, list) or len(parts) < 2:
                    raise ValueError("SPLIT_REQUIREMENT requires at least two parts")
                normalized_parts: list[dict[str, Any]] = []
                part_ids: list[str] = []
                for part in parts:
                    if not isinstance(part, dict):
                        raise ValueError("SPLIT_REQUIREMENT part is invalid")
                    part_id = part.get("requirement_id")
                    if not isinstance(part_id, str) or not part_id.strip():
                        raise ValueError("SPLIT_REQUIREMENT part ID is empty")
                    part_ids.append(part_id)
                    normalized_parts.append(_replacement_requirement(part, req_map.get(part_id)))
                if len(part_ids) != len(set(part_ids)):
                    raise ValueError("SPLIT_REQUIREMENT part IDs must be unique")

                # A split may route one part into an already-existing canonical
                # Requirement. Replace that record instead of appending a duplicate.
                replaced_ids = set(part_ids)
                replaced_ids.add(source_id)
                requirements[:] = [
                    item for item in requirements if item["requirement_id"] not in replaced_ids
                ]
                requirements.extend(normalized_parts)
                for replaced_id in replaced_ids:
                    updated_events.pop(replaced_id, None)
                for part_id in part_ids:
                    updated_events[part_id] = []
                    result.affected_requirements.add(part_id)
                result.boundary_changed = True
            elif operation == "DELETE_REQUIREMENT":
                requirement_id = targets.get("requirement_id")
                requirements[:] = [item for item in requirements if item["requirement_id"] != requirement_id]
                updated_events.pop(requirement_id, None)
                result.boundary_changed = True
            elif operation == "CHANGE_FAMILY":
                requirement_id = targets.get("requirement_id")
                req_map[requirement_id]["family_id"] = replacement.get("family_id")
                result.affected_requirements.add(requirement_id)
            elif operation == "ADD_EVENT":
                requirement_id = targets.get("requirement_id")
                updated_events[requirement_id].append(deepcopy(replacement))
                result.affected_requirements.add(requirement_id)
            elif operation == "DELETE_EVENT":
                requirement_id = targets.get("requirement_id")
                index = _event_index(updated_events[requirement_id], targets.get("event_locator", {}))
                updated_events[requirement_id].pop(index)
                result.affected_requirements.add(requirement_id)
            elif operation == "EDIT_EVENT":
                requirement_id = targets.get("requirement_id")
                index = _event_index(updated_events[requirement_id], targets.get("event_locator", {}))
                source = deepcopy(updated_events[requirement_id][index].get("source_message"))
                supporting = deepcopy(updated_events[requirement_id][index].get("supporting_message_ids", []))
                updated_events[requirement_id][index] = {
                    "source_message": source,
                    "supporting_message_ids": supporting,
                    **deepcopy(replacement),
                }
                result.affected_requirements.add(requirement_id)
            elif operation == "MOVE_EVENT":
                source_id = targets.get("from_requirement_id")
                target_id = targets.get("to_requirement_id")
                index = _event_index(updated_events[source_id], targets.get("event_locator", {}))
                updated_events[target_id].append(updated_events[source_id].pop(index))
                result.affected_requirements.update({source_id, target_id})
            elif operation == "CHANGE_SESSION":
                session_id = targets.get("session_id")
                session = next(item for item in updated_inventory.get("sessions", []) if item.get("session_id") == session_id)
                session.update(deepcopy(replacement))
            else:
                raise ValueError(f"Unsupported audit operation: {operation}")
        except (KeyError, TypeError, StopIteration, ValueError) as exc:
            failed = deepcopy(patch)
            failed["application_error"] = str(exc)
            result.human_review.append(failed)
            continue
        result.applied_count += 1
    return result


def apply_verification(
    events: list[dict[str, Any]],
    verification: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int], list[dict[str, Any]]]:
    updated = deepcopy(events)
    edits = 0
    deletions = 0
    edit_actions: list[tuple[int, dict[str, Any]]] = []
    delete_indices: list[int] = []
    for verdict in verification.get("verdicts", []):
        if verdict.get("verdict") == "KEEP":
            continue
        index = _event_index(events, verdict.get("event_locator", {}))
        if verdict.get("verdict") == "DELETE":
            delete_indices.append(index)
        elif verdict.get("verdict") == "EDIT":
            edit_actions.append((index, verdict))
    for index, verdict in edit_actions:
        if index in delete_indices:
            continue
        source = deepcopy(updated[index].get("source_message"))
        supporting = deepcopy(updated[index].get("supporting_message_ids", []))
        updated[index] = {
            "source_message": source,
            "supporting_message_ids": supporting,
            **deepcopy(verdict.get("replacement", {})),
        }
        edits += 1
    for index in sorted(set(delete_indices), reverse=True):
        updated.pop(index)
        deletions += 1
    review = [
        {
            "source": "EVENT_VERIFICATION",
            "requirement_id": verification.get("requirement_id"),
            "missing_event_candidate": deepcopy(candidate),
        }
        for candidate in verification.get("missing_event_candidates", [])
    ]
    return updated, {"edits": edits, "deletions": deletions}, review
