from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


ALLOWED_RESOLVER_EVENT_TYPES = {"INTRODUCE", "MODIFY", "DEFER", "RESUME", "REMOVE"}


@dataclass
class AmbiguityLinkApplication:
    events: dict[str, list[dict[str, Any]]]
    human_review: list[dict[str, Any]] = field(default_factory=list)
    applied_link_count: int = 0
    resolved_ambiguity_count: int = 0


def ambiguity_requirement_ids(
    events_by_requirement: dict[str, list[dict[str, Any]]],
) -> list[str]:
    return [
        requirement_id
        for requirement_id, events in events_by_requirement.items()
        if any(event.get("event_type") == "AMBIGUOUS" for event in events)
    ]


def _review_item(
    requirement_id: str,
    reason: str,
    decision: dict[str, Any] | None,
    event_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    decision = deepcopy(decision) if isinstance(decision, dict) else None
    ambiguity_id = decision.get("ambiguity_event_id") if decision else None
    resolver_id = decision.get("resolver_event_id") if decision else None
    message_ids: list[Any] = []
    for event_id in (ambiguity_id, resolver_id):
        event = event_by_id.get(event_id)
        source = event.get("source_message") if isinstance(event, dict) else None
        if isinstance(source, dict) and "message_id" in source:
            message_id = source["message_id"]
            if message_id not in message_ids:
                message_ids.append(message_id)
    return {
        "source": "AMBIGUITY_LINKING",
        "operation": "HUMAN_REVIEW",
        "targets": {
            "requirement_id": requirement_id,
            "ambiguity_event_id": ambiguity_id,
            "resolver_event_id": resolver_id,
        },
        "replacement": None,
        "evidence_message_ids": message_ids,
        "reason": reason,
        "decision_note": (
            decision.get("decision_note")
            if decision and isinstance(decision.get("decision_note"), str)
            else reason
        ),
        "confidence": decision.get("confidence") if decision else "LOW",
        "linking_decision": decision,
    }


def apply_ambiguity_links(
    events_by_requirement: dict[str, list[dict[str, Any]]],
    decisions_by_requirement: dict[str, list[dict[str, Any]]],
) -> AmbiguityLinkApplication:
    """Apply only structurally valid HIGH-confidence ambiguity resolutions.

    Events must already be chronologically sorted and contain their final IDs.
    Invalid, duplicate, or non-HIGH decisions are retained for human review and
    never partially applied.
    """
    updated = deepcopy(events_by_requirement)
    result = AmbiguityLinkApplication(events=updated)

    for requirement_id, events in updated.items():
        for event in events:
            event["resolves_ambiguity_event_ids"] = None

        event_by_id = {
            event.get("event_id"): event
            for event in events
            if isinstance(event.get("event_id"), str) and event.get("event_id")
        }
        position_by_id = {
            event["event_id"]: position
            for position, event in enumerate(events)
            if isinstance(event.get("event_id"), str) and event.get("event_id")
        }
        expected_ambiguities = [
            event["event_id"]
            for event in events
            if event.get("event_type") == "AMBIGUOUS" and event.get("event_id") in event_by_id
        ]
        if not expected_ambiguities:
            continue

        raw_decisions = decisions_by_requirement.get(requirement_id, [])
        grouped: dict[str, list[dict[str, Any]]] = {}
        for decision in raw_decisions:
            ambiguity_id = decision.get("ambiguity_event_id") if isinstance(decision, dict) else None
            if not isinstance(ambiguity_id, str) or not ambiguity_id:
                result.human_review.append(
                    _review_item(
                        requirement_id,
                        "Linking decision has no valid ambiguity_event_id.",
                        decision if isinstance(decision, dict) else None,
                        event_by_id,
                    )
                )
                continue
            grouped.setdefault(ambiguity_id, []).append(decision)

        for unexpected_id in sorted(set(grouped).difference(expected_ambiguities)):
            for decision in grouped[unexpected_id]:
                result.human_review.append(
                    _review_item(
                        requirement_id,
                        "Decision references an AMBIGUOUS Event outside this Requirement.",
                        decision,
                        event_by_id,
                    )
                )

        resolved_ids: set[str] = set()
        pending_links: dict[str, list[str]] = {}
        for ambiguity_id in expected_ambiguities:
            candidates = grouped.get(ambiguity_id, [])
            if not candidates:
                result.human_review.append(
                    _review_item(
                        requirement_id,
                        "No linking decision was returned for this AMBIGUOUS Event.",
                        {"ambiguity_event_id": ambiguity_id, "confidence": "LOW"},
                        event_by_id,
                    )
                )
                continue
            if len(candidates) != 1:
                for decision in candidates:
                    result.human_review.append(
                        _review_item(
                            requirement_id,
                            "The same AMBIGUOUS Event received multiple linking decisions.",
                            decision,
                            event_by_id,
                        )
                    )
                continue

            decision = candidates[0]
            status = decision.get("resolution_status")
            confidence = decision.get("confidence")
            if status == "UNRESOLVED":
                if confidence != "HIGH":
                    result.human_review.append(
                        _review_item(
                            requirement_id,
                            "UNRESOLVED decision is not HIGH confidence; ambiguity remains OPEN.",
                            decision,
                            event_by_id,
                        )
                    )
                continue
            if status != "RESOLVED":
                result.human_review.append(
                    _review_item(
                        requirement_id,
                        "Unsupported resolution_status; ambiguity remains OPEN.",
                        decision,
                        event_by_id,
                    )
                )
                continue
            if confidence != "HIGH":
                result.human_review.append(
                    _review_item(
                        requirement_id,
                        "Only HIGH-confidence RESOLVED decisions are applied.",
                        decision,
                        event_by_id,
                    )
                )
                continue

            resolver_id = decision.get("resolver_event_id")
            resolver = event_by_id.get(resolver_id)
            invalid_reason: str | None = None
            if ambiguity_id in resolved_ids:
                invalid_reason = "The AMBIGUOUS Event was already resolved by another Event."
            elif resolver is None:
                invalid_reason = "resolver_event_id does not exist in the same Requirement."
            elif position_by_id[resolver_id] <= position_by_id[ambiguity_id]:
                invalid_reason = "Resolver must occur after the AMBIGUOUS Event."
            elif resolver.get("event_type") not in ALLOWED_RESOLVER_EVENT_TYPES:
                invalid_reason = (
                    "Resolver Event type is not one of INTRODUCE, MODIFY, DEFER, RESUME, or REMOVE."
                )
            if invalid_reason is not None:
                result.human_review.append(
                    _review_item(requirement_id, invalid_reason, decision, event_by_id)
                )
                continue

            resolved_ids.add(ambiguity_id)
            pending_links.setdefault(resolver_id, []).append(ambiguity_id)

        for resolver_id, ambiguity_ids in pending_links.items():
            ambiguity_ids.sort(key=position_by_id.__getitem__)
            event_by_id[resolver_id]["resolves_ambiguity_event_ids"] = ambiguity_ids
            result.applied_link_count += len(ambiguity_ids)
        result.resolved_ambiguity_count += len(resolved_ids)

    return result
