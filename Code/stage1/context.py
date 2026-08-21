from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Iterable

from .storage import id_key


def chunk_messages(messages: list[dict[str, Any]], size: int, overlap: int) -> list[list[dict[str, Any]]]:
    if not messages:
        return []
    chunks: list[list[dict[str, Any]]] = []
    step = size - overlap
    start = 0
    while start < len(messages):
        chunks.append(messages[start : start + size])
        if start + size >= len(messages):
            break
        start += step
    return chunks


def merge_evidence_scans(scans: Iterable[dict[str, Any]]) -> dict[str, Any]:
    confidence_rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for scan in scans:
        for candidate in scan.get("candidates", []):
            key = id_key(candidate.get("message_id"))
            if key not in merged:
                merged[key] = {
                    "message_id": candidate.get("message_id"),
                    "evidence_tags": [],
                    "topic_hints": [],
                    "context_message_ids": [],
                    "confidence": candidate.get("confidence", "LOW"),
                }
                order.append(key)
            target = merged[key]
            for field in ("evidence_tags", "topic_hints", "context_message_ids"):
                for value in candidate.get(field, []):
                    if value not in target[field]:
                        target[field].append(value)
            if confidence_rank.get(candidate.get("confidence"), -1) > confidence_rank.get(target["confidence"], -1):
                target["confidence"] = candidate["confidence"]
    return {"run_mode": "EVIDENCE_SCAN", "candidates": [merged[key] for key in order]}


def messages_with_context(
    messages: list[dict[str, Any]],
    message_ids: Iterable[Any],
    window: int,
) -> list[dict[str, Any]]:
    positions = {id_key(message["message_id"]): index for index, message in enumerate(messages)}
    selected: set[int] = set()
    for message_id in message_ids:
        position = positions.get(id_key(message_id))
        if position is None:
            continue
        selected.update(range(max(0, position - window), min(len(messages), position + window + 1)))
    return [messages[index] for index in sorted(selected)]


def evidence_messages(
    messages: list[dict[str, Any]],
    evidence: dict[str, Any],
    window: int,
) -> list[dict[str, Any]]:
    ids: list[Any] = []
    for candidate in evidence.get("candidates", []):
        ids.append(candidate.get("message_id"))
        ids.extend(candidate.get("context_message_ids", []))
    return messages_with_context(messages, ids, window)


_GENERIC_TERMS = {
    "also",
    "been",
    "being",
    "change",
    "changes",
    "client",
    "current",
    "each",
    "existing",
    "feature",
    "from",
    "have",
    "include",
    "independently",
    "into",
    "must",
    "only",
    "other",
    "project",
    "provide",
    "requirement",
    "separate",
    "should",
    "state",
    "support",
    "system",
    "that",
    "their",
    "this",
    "through",
    "used",
    "user",
    "users",
    "using",
    "when",
    "where",
    "which",
    "will",
    "with",
    "without",
    "work",
    "working",
}


def _signal_terms(*values: Any) -> set[str]:
    terms: set[str] = set()
    for value in values:
        for term in re.findall(r"[A-Za-z0-9]{3,}", str(value).lower()):
            if term not in _GENERIC_TERMS:
                terms.add(term)
    return terms


def focused_inventory(
    inventory: dict[str, Any],
    requirement: dict[str, Any],
    *,
    include_family_siblings: bool,
) -> dict[str, Any]:
    """Return only inventory entries needed to preserve the target boundary."""
    requirement_id = requirement.get("requirement_id")
    family_id = requirement.get("family_id")
    selected_requirements = []
    for item in inventory.get("requirements", []):
        if item.get("requirement_id") == requirement_id or (
            include_family_siblings and family_id and item.get("family_id") == family_id
        ):
            selected_requirements.append(deepcopy(item))
        else:
            selected_requirements.append(
                {
                    "requirement_id": item.get("requirement_id"),
                    "title": item.get("title"),
                    "family_id": item.get("family_id"),
                }
            )
    selected_families = [deepcopy(item) for item in inventory.get("requirement_families", [])]
    return {
        "requirement_families": selected_families,
        "requirements": selected_requirements,
    }


def requirement_context(
    normalized: dict[str, Any],
    evidence: dict[str, Any],
    inventory: dict[str, Any],
    requirement: dict[str, Any],
    mode: str,
    window: int,
    max_messages: int = 160,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    messages = normalized["messages"]
    if mode == "full_history":
        return messages, list(evidence.get("candidates", []))

    scope = requirement.get("scope_hypothesis") or {}
    title_terms = _signal_terms(
        str(requirement.get("requirement_id", "")).replace("REQ_", ""),
        requirement.get("title", ""),
        scope.get("components", []),
        scope.get("contexts", []),
    )
    definition_terms = _signal_terms(requirement.get("definition", ""), requirement.get("boundary_note", ""))
    anchor_ids: list[Any] = list(requirement.get("anchor_message_ids", []))

    anchor_keys = {id_key(value) for value in anchor_ids}
    scored_candidates: list[tuple[int, int, dict[str, Any]]] = []
    message_order = {id_key(message["message_id"]): index for index, message in enumerate(messages)}
    for candidate in evidence.get("candidates", []):
        candidate_key = id_key(candidate.get("message_id"))
        hint_terms = _signal_terms(candidate.get("topic_hints", []))
        title_matches = len(title_terms.intersection(hint_terms))
        definition_matches = len(definition_terms.intersection(hint_terms))
        anchored = candidate_key in anchor_keys
        if not anchored and title_matches == 0 and definition_matches < 2:
            continue
        confidence_score = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(candidate.get("confidence"), 0)
        score = (100 if anchored else 0) + title_matches * 10 + definition_matches * 2 + confidence_score
        scored_candidates.append((score, message_order.get(candidate_key, len(messages)), candidate))

    # Keep the strongest evidence while retaining chronological coverage for long lifecycles.
    scored_candidates.sort(key=lambda item: (-item[0], item[1]))
    strongest = scored_candidates[:40]
    strongest_ids = {id_key(item[2].get("message_id")) for item in strongest}
    coverage_pool = sorted(
        (item for item in scored_candidates[40:] if id_key(item[2].get("message_id")) not in strongest_ids),
        key=lambda item: item[1],
    )
    coverage_indexes = _evenly_spaced(list(range(len(coverage_pool))), min(40, len(coverage_pool)))
    relevant_candidates = [item[2] for item in strongest]
    relevant_candidates.extend(coverage_pool[index][2] for index in coverage_indexes)
    relevant_candidates.sort(key=lambda item: message_order.get(id_key(item.get("message_id")), len(messages)))
    if not relevant_candidates:
        relevant_candidates = [
            candidate for candidate in evidence.get("candidates", []) if id_key(candidate.get("message_id")) in anchor_keys
        ]

    primary_ids = list(anchor_ids)
    secondary_ids: list[Any] = []
    for candidate in relevant_candidates:
        primary_ids.append(candidate.get("message_id"))
        secondary_ids.extend(candidate.get("context_message_ids", []))
    selected_messages = _bounded_context_messages(
        messages,
        primary_ids,
        secondary_ids,
        window,
        max_messages,
    )
    return selected_messages, relevant_candidates


def verification_context(
    normalized: dict[str, Any],
    events: list[dict[str, Any]],
    window: int,
    max_messages: int = 160,
) -> list[dict[str, Any]]:
    primary_ids: list[Any] = []
    secondary_ids: list[Any] = []
    for event in events:
        source = event.get("source_message", {})
        primary_ids.append(source.get("message_id"))
        secondary_ids.extend(event.get("supporting_message_ids", []))
    return _bounded_context_messages(
        normalized["messages"],
        primary_ids,
        secondary_ids,
        window,
        max_messages,
    )


def _bounded_context_messages(
    messages: list[dict[str, Any]],
    primary_ids: Iterable[Any],
    secondary_ids: Iterable[Any],
    window: int,
    limit: int,
) -> list[dict[str, Any]]:
    positions = {id_key(message["message_id"]): index for index, message in enumerate(messages)}
    primary = _unique_positions(primary_ids, positions)
    secondary = [position for position in _unique_positions(secondary_ids, positions) if position not in set(primary)]

    selected: list[int] = []
    selected_set: set[int] = set()

    def add_positions(values: list[int]) -> None:
        available = limit - len(selected)
        if available <= 0:
            return
        chosen = values if len(values) <= available else _evenly_spaced(values, available)
        for position in chosen:
            if position not in selected_set:
                selected.append(position)
                selected_set.add(position)

    add_positions(primary)
    add_positions(secondary)
    seeds = list(selected)
    for radius in range(1, window + 1):
        neighbors: list[int] = []
        for position in seeds:
            for candidate in (position - radius, position + radius):
                if 0 <= candidate < len(messages) and candidate not in selected_set:
                    neighbors.append(candidate)
        add_positions(sorted(set(neighbors)))
        if len(selected) >= limit:
            break
    return [messages[index] for index in sorted(selected)]


def _unique_positions(ids: Iterable[Any], positions: dict[str, int]) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for value in ids:
        position = positions.get(id_key(value))
        if position is not None and position not in seen:
            result.append(position)
            seen.add(position)
    return sorted(result)


def _evenly_spaced(values: list[int], count: int) -> list[int]:
    if count <= 0:
        return []
    if count >= len(values):
        return values
    if count == 1:
        return [values[len(values) // 2]]
    indexes = {round(index * (len(values) - 1) / (count - 1)) for index in range(count)}
    return [values[index] for index in sorted(indexes)]
