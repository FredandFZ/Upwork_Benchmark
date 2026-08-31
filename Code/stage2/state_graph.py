"""Build a project Requirement State Graph from a Stage 1 annotation.

Stage 1 already establishes the ordered Requirement Events.  This module does
not reinterpret source messages: it applies the transition rules from chapters
7 and 8 of the ReqMemBench annotation guideline.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


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
EXECUTION_STATUS_BY_EVENT = {
    "IMPLEMENTATION_CLAIM": "CLAIMED_WORKING",
    "RUNTIME_FAILURE": "FAILED",
    "RUNTIME_VERIFICATION": "VERIFIED_WORKING",
}
SCOPE_FIELDS = ("persistence", "components", "contexts")
AMBIGUITY_DIMENSIONS = {"VALUE", "SCOPE", "LIFECYCLE"}
AMBIGUITY_RESOLVER_EVENT_TYPES = {"INTRODUCE", "MODIFY", "DEFER", "RESUME", "REMOVE"}


class Stage2ReplayError(ValueError):
    """Raised when Stage 1 data cannot be replayed without guessing."""


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Stage2ReplayError(f"{label} must be an object")
    return value


def _require_array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise Stage2ReplayError(f"{label} must be an array")
    return value


def _non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise Stage2ReplayError(f"{label} must be a non-empty string")
    return value


@dataclass
class _ReplayState:
    attributes: dict[str, Any] = field(default_factory=dict)
    scope: dict[str, Any] = field(
        default_factory=lambda: {
            "persistence": None,
            "components": None,
            "contexts": None,
        }
    )
    lifecycle_status: str | None = None
    open_ambiguities: dict[str, dict[str, Any]] = field(default_factory=dict)
    execution: dict[str, Any] | None = None
    attribute_sources: dict[str, str] = field(default_factory=dict)
    attribute_removal_sources: dict[str, str] = field(default_factory=dict)
    scope_sources: dict[str, str] = field(default_factory=dict)
    lifecycle_source: str | None = None
    execution_source: str | None = None
    # False means the visible history began after the Requirement may already
    # have existed.  In that case, removing an attribute absent from the
    # observed state is still replayable: the Event establishes its current
    # absence even though its earlier value was outside the dataset window.
    baseline_complete: bool = False

    def supporting_event_ids(self, event_positions: dict[str, int]) -> list[str]:
        """Return only Events that still directly establish the current state."""
        sources = set(self.attribute_sources.values())
        sources.update(self.attribute_removal_sources.values())
        sources.update(self.scope_sources.values())
        sources.update(self.open_ambiguities)
        for source in (self.lifecycle_source, self.execution_source):
            if source is not None:
                sources.add(source)
        return sorted(sources, key=event_positions.__getitem__)

    def node(self, state_id: str, event_positions: dict[str, int]) -> dict[str, Any]:
        return {
            "state_id": state_id,
            "attributes": deepcopy(self.attributes),
            "scope": deepcopy(self.scope),
            "lifecycle_status": self.lifecycle_status,
            "ambiguity": deepcopy(self.open_ambiguities) or None,
            "execution": deepcopy(self.execution),
            "supporting_event_ids": self.supporting_event_ids(event_positions),
        }


def _validate_event(event: Any, requirement_id: str, number: int) -> dict[str, Any]:
    label = f"{requirement_id}.events[{number - 1}]"
    event = deepcopy(_require_object(event, label))
    event_id = _non_empty_string(event.get("event_id"), f"{label}.event_id")
    event_type = event.get("event_type")
    if event_type not in EVENT_TYPES:
        raise Stage2ReplayError(f"{event_id} has unsupported event_type {event_type!r}")

    source = _require_object(event.get("source_message"), f"{event_id}.source_message")
    if "message_id" not in source:
        raise Stage2ReplayError(f"{event_id}.source_message.message_id is required")

    value_updates = event.get("value_updates")
    value_removals = event.get("value_removals")
    scope_updates = event.get("scope_updates")
    ambiguity = event.get("ambiguity")
    execution = event.get("execution")
    resolution_ids = event.get("resolves_ambiguity_event_ids")
    if resolution_ids is not None:
        if not isinstance(resolution_ids, list) or not resolution_ids or any(
            not isinstance(ambiguity_id, str) or not ambiguity_id
            for ambiguity_id in resolution_ids
        ):
            raise Stage2ReplayError(
                f"{event_id}.resolves_ambiguity_event_ids must be null or a non-empty string array"
            )
        if len(resolution_ids) != len(set(resolution_ids)):
            raise Stage2ReplayError(
                f"{event_id}.resolves_ambiguity_event_ids contains duplicates"
            )
        if event_type not in AMBIGUITY_RESOLVER_EVENT_TYPES:
            raise Stage2ReplayError(
                f"{event_id} has an unsupported ambiguity resolver Event type"
            )
    event["resolves_ambiguity_event_ids"] = resolution_ids
    if value_updates is not None and not isinstance(value_updates, dict):
        raise Stage2ReplayError(f"{event_id}.value_updates must be an object or null")
    if value_removals is not None:
        if not isinstance(value_removals, list) or not value_removals or any(
            not isinstance(attribute, str) or not attribute for attribute in value_removals
        ):
            raise Stage2ReplayError(
                f"{event_id}.value_removals must be a non-empty string array or null"
            )
        if len(value_removals) != len(set(value_removals)):
            raise Stage2ReplayError(f"{event_id}.value_removals contains duplicates")
        overlap = set(value_removals).intersection((value_updates or {}).keys())
        if overlap:
            raise Stage2ReplayError(
                f"{event_id} updates and removes the same attribute: {', '.join(sorted(overlap))}"
            )
    if scope_updates is not None:
        scope_updates = _require_object(scope_updates, f"{event_id}.scope_updates")
        unknown = set(scope_updates).difference(SCOPE_FIELDS)
        if unknown:
            raise Stage2ReplayError(
                f"{event_id}.scope_updates has unsupported fields: {', '.join(sorted(unknown))}"
            )

    if event_type == "INTRODUCE":
        if value_removals is not None:
            raise Stage2ReplayError(f"{event_id} INTRODUCE cannot remove attributes")
        if value_updates is None and scope_updates is None:
            raise Stage2ReplayError(f"{event_id} must update value or scope")
        if ambiguity is not None or execution is not None:
            raise Stage2ReplayError(f"{event_id} has an invalid definition-event payload")
    elif event_type == "MODIFY":
        if value_updates is None and value_removals is None and scope_updates is None:
            raise Stage2ReplayError(f"{event_id} must update/remove value or update scope")
        if ambiguity is not None or execution is not None:
            raise Stage2ReplayError(f"{event_id} has an invalid definition-event payload")
    elif event_type in {"DEFER", "RESUME", "REMOVE"}:
        if any(item is not None for item in (value_updates, value_removals, scope_updates, ambiguity, execution)):
            raise Stage2ReplayError(f"{event_id} lifecycle payload fields must be null")
    elif event_type == "AMBIGUOUS":
        ambiguity = _require_object(ambiguity, f"{event_id}.ambiguity")
        if ambiguity.get("dimension") not in AMBIGUITY_DIMENSIONS:
            raise Stage2ReplayError(f"{event_id} has an invalid ambiguity dimension")
        _non_empty_string(ambiguity.get("description"), f"{event_id}.ambiguity.description")
        if value_updates is not None or value_removals is not None or scope_updates is not None or execution is not None:
            raise Stage2ReplayError(f"{event_id} has an invalid ambiguity-event payload")
    else:
        execution = _require_object(execution, f"{event_id}.execution")
        expected_status = EXECUTION_STATUS_BY_EVENT[event_type]
        if execution.get("status") != expected_status:
            raise Stage2ReplayError(
                f"{event_id}.execution.status must be {expected_status}"
            )
        _non_empty_string(
            execution.get("observed_behavior"),
            f"{event_id}.execution.observed_behavior",
        )
        if value_updates is not None or value_removals is not None or scope_updates is not None or ambiguity is not None:
            raise Stage2ReplayError(f"{event_id} has an invalid execution-event payload")
    return event


def _close_linked_ambiguities(state: _ReplayState, event: dict[str, Any]) -> None:
    for ambiguity_id in event.get("resolves_ambiguity_event_ids") or []:
        if ambiguity_id not in state.open_ambiguities:
            raise Stage2ReplayError(
                f"{event['event_id']} cannot close ambiguity {ambiguity_id!r} because it is not OPEN"
            )
        del state.open_ambiguities[ambiguity_id]


def _apply_event(
    state: _ReplayState,
    event: dict[str, Any],
    *,
    introduction_seen: bool,
    has_previous_state: bool,
) -> None:
    event_id = event["event_id"]
    event_type = event["event_type"]

    if state.lifecycle_status == "REMOVED":
        raise Stage2ReplayError(f"{event_id} occurs after the Requirement was REMOVED")
    if event_type == "INTRODUCE" and introduction_seen:
        raise Stage2ReplayError(f"{event_id} is a duplicate INTRODUCE Event")

    if event_type in {"INTRODUCE", "MODIFY"}:
        value_updates = event.get("value_updates")
        value_removals = event.get("value_removals")
        scope_updates = event.get("scope_updates")
        for key in value_removals or []:
            if key not in state.attributes:
                if state.baseline_complete or key in state.attribute_removal_sources:
                    raise Stage2ReplayError(
                        f"{event_id}.value_removals references absent attribute {key!r}"
                    )
            state.attributes.pop(key, None)
            state.attribute_sources.pop(key, None)
            state.attribute_removal_sources[key] = event_id
        for key, value in (value_updates or {}).items():
            state.attributes[key] = deepcopy(value)
            state.attribute_sources[key] = event_id
            state.attribute_removal_sources.pop(key, None)
        for key in SCOPE_FIELDS:
            value = (scope_updates or {}).get(key)
            # In Stage 1, null means this Event did not modify that dimension.
            if value is not None:
                state.scope[key] = deepcopy(value)
                state.scope_sources[key] = event_id
        if event_type == "INTRODUCE":
            state.lifecycle_status = "ACTIVE"
            state.lifecycle_source = event_id
            state.baseline_complete = True
            if has_previous_state:
                # Earlier observed-history Events remain represented by their
                # own Nodes and Edges. Execution from an unknown pre-introduction
                # baseline does not carry into the formally introduced version.
                # Ambiguities close only through explicit Stage 1 links.
                state.execution = None
                state.execution_source = None
        else:
            # A Requirement change creates a new semantic version. Execution
            # evidence for the previous version must not be carried forward.
            state.execution = None
            state.execution_source = None
        _close_linked_ambiguities(state, event)
        return

    if event_type == "DEFER":
        state.lifecycle_status = "DEFERRED"
        state.lifecycle_source = event_id
        _close_linked_ambiguities(state, event)
        return

    if event_type == "RESUME":
        state.lifecycle_status = "ACTIVE"
        state.lifecycle_source = event_id
        _close_linked_ambiguities(state, event)
        return

    if event_type == "REMOVE":
        state.lifecycle_status = "REMOVED"
        state.lifecycle_source = event_id
        _close_linked_ambiguities(state, event)
        return

    if event_type == "AMBIGUOUS":
        ambiguity = event["ambiguity"]
        state.open_ambiguities[event_id] = {
            "status": "OPEN",
            "dimension": ambiguity["dimension"],
            "description": ambiguity["description"],
            "source_event_id": event_id,
        }
        return

    execution = event["execution"]
    state.execution = {
        "status": execution["status"],
        "observed_behavior": execution["observed_behavior"],
        "source_event_id": event_id,
    }
    state.execution_source = event_id


def _build_requirement_graph(
    requirement: dict[str, Any],
    project_event_ids: set[str],
) -> dict[str, Any]:
    requirement_id = _non_empty_string(requirement.get("requirement_id"), "requirement_id")
    events = _require_array(requirement.get("events"), f"{requirement_id}.events")
    validated_events: list[dict[str, Any]] = []
    for number, raw_event in enumerate(events, start=1):
        event = _validate_event(raw_event, requirement_id, number)
        event_id = event["event_id"]
        if event_id in project_event_ids:
            raise Stage2ReplayError(f"duplicate event_id: {event_id}")
        project_event_ids.add(event_id)
        validated_events.append(event)

    local_event_positions = {
        event["event_id"]: position for position, event in enumerate(validated_events)
    }
    local_event_by_id = {event["event_id"]: event for event in validated_events}
    resolved_ambiguities: set[str] = set()
    for resolver_position, event in enumerate(validated_events):
        for ambiguity_id in event.get("resolves_ambiguity_event_ids") or []:
            ambiguity_event = local_event_by_id.get(ambiguity_id)
            if ambiguity_event is None:
                raise Stage2ReplayError(
                    f"{event['event_id']} references unknown or cross-Requirement ambiguity "
                    f"Event {ambiguity_id!r}"
                )
            if local_event_positions[ambiguity_id] >= resolver_position:
                raise Stage2ReplayError(
                    f"{event['event_id']} must resolve an earlier AMBIGUOUS Event"
                )
            if ambiguity_event.get("event_type") != "AMBIGUOUS":
                raise Stage2ReplayError(
                    f"{event['event_id']} resolution target {ambiguity_id} is not AMBIGUOUS"
                )
            if ambiguity_id in resolved_ambiguities:
                raise Stage2ReplayError(
                    f"AMBIGUOUS Event {ambiguity_id} is resolved more than once"
                )
            resolved_ambiguities.add(ambiguity_id)

    # Preserve every Stage 1 Requirement and every valid Event.  When visible
    # history starts without INTRODUCE, replay begins from an incomplete,
    # observed baseline: unknown attributes/scope/lifecycle remain empty/null
    # until an Event establishes them.  A later INTRODUCE is a formal baseline
    # transition, not a reason to discard the earlier observations.
    replay_events = validated_events
    introduce_positions = [
        index
        for index, event in enumerate(replay_events)
        if event["event_type"] == "INTRODUCE"
    ]
    if len(introduce_positions) > 1:
        duplicate = replay_events[introduce_positions[1]]["event_id"]
        raise Stage2ReplayError(f"{duplicate} is a duplicate INTRODUCE Event")
    if not replay_events:
        initialization_mode = "NO_EVENTS"
    elif introduce_positions == [0]:
        initialization_mode = "EXPLICIT_INTRODUCE"
    else:
        initialization_mode = "OBSERVED_HISTORY"

    event_positions = {
        event["event_id"]: position
        for position, event in enumerate(replay_events)
    }
    state = _ReplayState()
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    previous_state_id: str | None = None
    introduction_seen = False

    # The canonical Stage 1 assembler has already sorted Events by original
    # project-history position.  Array order is retained because message IDs
    # can be arbitrary strings, and same-message Events have an explicit order.
    for event in replay_events:
        _apply_event(
            state,
            event,
            introduction_seen=introduction_seen,
            has_previous_state=bool(nodes),
        )
        if event["event_type"] == "INTRODUCE":
            introduction_seen = True
        state_id = f"{requirement_id}_S{len(nodes) + 1:03d}"
        nodes.append(state.node(state_id, event_positions))
        edges.append(
            {
                "from_state_id": previous_state_id,
                "to_state_id": state_id,
                "event_id": event["event_id"],
                "event_type": event["event_type"],
                "source_message_id": event["source_message"]["message_id"],
                "value_removals": deepcopy(event.get("value_removals")),
            }
        )
        previous_state_id = state_id

    return {
        "graph_id": f"{requirement_id}_GRAPH",
        "requirement_id": requirement_id,
        "title": requirement.get("title"),
        "family_id": requirement.get("family_id"),
        "initialization_mode": initialization_mode,
        "has_explicit_introduce": bool(introduce_positions),
        "nodes": nodes,
        "edges": edges,
    }


def build_requirement_state_graph(annotation: dict[str, Any]) -> dict[str, Any]:
    """Replay one complete Stage 1 Project Annotation into its State Graph."""
    annotation = _require_object(annotation, "annotation")
    project = _require_object(annotation.get("project"), "project")
    project_id = project.get("project_id")
    if project_id is None or isinstance(project_id, (dict, list)):
        raise Stage2ReplayError("project.project_id must be a scalar value")
    project_id = str(project_id)
    if not project_id:
        raise Stage2ReplayError("project.project_id must not be empty")
    project_title = project.get("project_title")
    if project_title is not None and not isinstance(project_title, str):
        raise Stage2ReplayError("project.project_title must be a string or null")

    requirements = _require_array(annotation.get("requirements"), "requirements")
    requirement_ids: set[str] = set()
    project_event_ids: set[str] = set()
    requirement_graphs: list[dict[str, Any]] = []
    for index, raw_requirement in enumerate(requirements):
        requirement = _require_object(raw_requirement, f"requirements[{index}]")
        requirement_id = _non_empty_string(
            requirement.get("requirement_id"),
            f"requirements[{index}].requirement_id",
        )
        if requirement_id in requirement_ids:
            raise Stage2ReplayError(f"duplicate requirement_id: {requirement_id}")
        requirement_ids.add(requirement_id)
        requirement_graphs.append(_build_requirement_graph(requirement, project_event_ids))

    return {
        "project_id": project_id,
        "project_title": project_title,
        "requirement_graphs": requirement_graphs,
    }
