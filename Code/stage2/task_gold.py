"""Build task-centered Gold States and RQ1--RQ4 evaluation Gold.

The Requirement State Graph is the semantic and temporal source of truth.  A
Stage 1 annotation supplies the original source-message metadata that is not
duplicated in the graph.  All construction in this module is deterministic;
raw project history and model inference are deliberately out of scope.
"""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


TASK_CHANGING_EVENT_TYPES = {
    "INTRODUCE",
    "MODIFY",
    "DEFER",
    "RESUME",
    "REMOVE",
    "AMBIGUOUS",
}
EXECUTION_EVENT_TYPES = {
    "IMPLEMENTATION_CLAIM",
    "RUNTIME_FAILURE",
    "RUNTIME_VERIFICATION",
}
SCOPE_FIELDS = ("persistence", "components", "contexts")


class TaskGoldError(ValueError):
    """Raised when Task Gold cannot be derived without guessing."""


@dataclass(frozen=True)
class RequirementTransition:
    """An in-memory affected-Requirement transition.

    This object is intentionally never serialized into ``gold_states.json``.
    """

    requirement_id: str
    before_state: dict[str, Any] | None
    after_state: dict[str, Any]


@dataclass(frozen=True)
class _EdgeRef:
    requirement_id: str
    family_id: str | None
    graph_position: int
    edge_position: int
    edge: dict[str, Any]


def _id_key(value: Any) -> str:
    """Match Stage 1's type-preserving message-ID identity rule."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TaskGoldError(f"{label} must be an object")
    return value


def _require_array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise TaskGoldError(f"{label} must be an array")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TaskGoldError(f"{label} must be a non-empty string")
    return value


def _message_number(value: Any) -> Decimal:
    """Return a comparable chronology value for ordinary numeric message IDs.

    Stage 1 keeps opaque message identifiers type-sensitive.  The final Stage 1
    artifact does not retain a global message-order table, so non-numeric IDs
    cannot be ordered safely here and are rejected instead of guessed.
    """
    if isinstance(value, bool):
        raise TaskGoldError("boolean message IDs do not define a chronology")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TaskGoldError("non-finite message IDs do not define a chronology")
        return Decimal(str(value))
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
        try:
            return Decimal(value)
        except InvalidOperation as exc:  # pragma: no cover - guarded by regex
            raise TaskGoldError(f"invalid numeric message ID: {value!r}") from exc
    raise TaskGoldError(
        f"message ID {value!r} is not chronologically comparable; "
        "provide Stage 1 data with numeric message IDs"
    )


class _GraphIndex:
    def __init__(self, graph: dict[str, Any]) -> None:
        graph = _require_object(graph, "state_graph")
        project_id = graph.get("project_id")
        if project_id is None or isinstance(project_id, (dict, list, bool)):
            raise TaskGoldError("state_graph.project_id must be a scalar value")
        self.project_id = str(project_id)
        if not self.project_id:
            raise TaskGoldError("state_graph.project_id must not be empty")

        self.graphs = _require_array(
            graph.get("requirement_graphs"), "state_graph.requirement_graphs"
        )
        self.requirement_order: list[str] = []
        self.graph_by_requirement: dict[str, dict[str, Any]] = {}
        self.node_by_state_id: dict[str, dict[str, Any]] = {}
        self.state_requirement: dict[str, str] = {}
        self.edge_by_event_id: dict[str, _EdgeRef] = {}
        self.edge_by_state_id: dict[str, _EdgeRef] = {}
        self.edges_by_message: dict[str, list[_EdgeRef]] = {}
        self.message_ids: dict[str, Any] = {}

        for graph_position, raw_requirement_graph in enumerate(self.graphs):
            requirement_graph = _require_object(
                raw_requirement_graph,
                f"state_graph.requirement_graphs[{graph_position}]",
            )
            requirement_id = _require_string(
                requirement_graph.get("requirement_id"),
                f"requirement_graphs[{graph_position}].requirement_id",
            )
            if requirement_id in self.graph_by_requirement:
                raise TaskGoldError(f"duplicate requirement_id: {requirement_id}")
            self.requirement_order.append(requirement_id)
            self.graph_by_requirement[requirement_id] = requirement_graph

            nodes = _require_array(
                requirement_graph.get("nodes"), f"{requirement_id}.nodes"
            )
            edges = _require_array(
                requirement_graph.get("edges"), f"{requirement_id}.edges"
            )
            if len(nodes) != len(edges):
                raise TaskGoldError(
                    f"{requirement_id} has {len(nodes)} nodes but {len(edges)} edges"
                )
            previous_state_id: str | None = None
            previous_message_number: Decimal | None = None
            for edge_position, (raw_node, raw_edge) in enumerate(zip(nodes, edges)):
                node = _require_object(
                    raw_node, f"{requirement_id}.nodes[{edge_position}]"
                )
                edge = _require_object(
                    raw_edge, f"{requirement_id}.edges[{edge_position}]"
                )
                state_id = _require_string(
                    node.get("state_id"),
                    f"{requirement_id}.nodes[{edge_position}].state_id",
                )
                event_id = _require_string(
                    edge.get("event_id"),
                    f"{requirement_id}.edges[{edge_position}].event_id",
                )
                if state_id in self.node_by_state_id:
                    raise TaskGoldError(f"duplicate state_id: {state_id}")
                if event_id in self.edge_by_event_id:
                    raise TaskGoldError(f"duplicate graph event_id: {event_id}")
                if edge.get("from_state_id") != previous_state_id:
                    raise TaskGoldError(
                        f"{event_id}.from_state_id does not match the preceding state"
                    )
                if edge.get("to_state_id") != state_id:
                    raise TaskGoldError(
                        f"{event_id}.to_state_id does not match {state_id}"
                    )
                if "source_message_id" not in edge:
                    raise TaskGoldError(f"{event_id}.source_message_id is required")
                message_id = edge["source_message_id"]
                message_number = _message_number(message_id)
                if (
                    previous_message_number is not None
                    and message_number < previous_message_number
                ):
                    raise TaskGoldError(
                        f"{requirement_id} graph edges are not in message chronology"
                    )
                previous_message_number = message_number

                message_key = _id_key(message_id)
                if (
                    message_key in self.message_ids
                    and self.message_ids[message_key] != message_id
                ):
                    raise TaskGoldError(f"ambiguous message ID identity: {message_id!r}")
                self.message_ids[message_key] = message_id
                edge_ref = _EdgeRef(
                    requirement_id=requirement_id,
                    family_id=requirement_graph.get("family_id"),
                    graph_position=graph_position,
                    edge_position=edge_position,
                    edge=edge,
                )
                self.node_by_state_id[state_id] = node
                self.state_requirement[state_id] = requirement_id
                self.edge_by_event_id[event_id] = edge_ref
                self.edge_by_state_id[state_id] = edge_ref
                self.edges_by_message.setdefault(message_key, []).append(edge_ref)
                previous_state_id = state_id

        positions: dict[str, Decimal] = {}
        position_owner: dict[Decimal, str] = {}
        for message_key, message_id in self.message_ids.items():
            position = _message_number(message_id)
            owner = position_owner.get(position)
            if owner is not None and owner != message_key:
                raise TaskGoldError(
                    f"distinct message IDs share chronology position {position}: "
                    f"{self.message_ids[owner]!r} and {message_id!r}"
                )
            positions[message_key] = position
            position_owner[position] = message_key
        self.message_positions = positions

        for state_id, node in self.node_by_state_id.items():
            state_edge = self.edge_by_state_id[state_id]
            state_position = state_edge.edge_position
            for event_id in _require_array(
                node.get("supporting_event_ids"),
                f"{state_id}.supporting_event_ids",
            ):
                support = self.edge_by_event_id.get(event_id)
                if support is None:
                    raise TaskGoldError(
                        f"{state_id} references unknown supporting event {event_id!r}"
                    )
                if support.requirement_id != state_edge.requirement_id:
                    raise TaskGoldError(
                        f"{state_id} references another Requirement's event {event_id}"
                    )
                if support.edge_position > state_position:
                    raise TaskGoldError(
                        f"{state_id} contains future supporting event {event_id}"
                    )

    def ordered_message_keys(self) -> list[str]:
        return sorted(self.message_ids, key=self.message_positions.__getitem__)

    def snapshot(self, message_id: Any, *, inclusive: bool) -> list[dict[str, str]]:
        boundary = _message_number(message_id)
        snapshot: list[dict[str, str]] = []
        for requirement_id in self.requirement_order:
            graph = self.graph_by_requirement[requirement_id]
            latest_state_id: str | None = None
            for edge in graph["edges"]:
                position = _message_number(edge["source_message_id"])
                if position < boundary or (inclusive and position == boundary):
                    latest_state_id = edge["to_state_id"]
                elif position > boundary:
                    break
            if latest_state_id is not None:
                snapshot.append(
                    {
                        "requirement_id": requirement_id,
                        "state_id": latest_state_id,
                    }
                )
        return snapshot


def _stage1_indexes(
    stage1_source: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Index messages and Events from supported Stage 1 artifacts.

    Supported inputs are the canonical assembled annotation, an upgrade run's
    ``verified_events.json`` (Requirement ID -> Event array), or an upgrade
    run's ``normalized_project.json`` message catalog.  Verified Events have no
    persisted Event IDs, so their canonical IDs are reconstructed from their
    already ordered per-Requirement arrays for optional provenance auditing.
    """
    stage1_source = _require_object(stage1_source, "stage1_source")
    messages: dict[str, dict[str, Any]] = {}
    events: dict[str, dict[str, Any]] = {}

    def add_message(source: dict[str, Any], label: str) -> None:
        if "message_id" not in source:
            raise TaskGoldError(f"{label}.message_id is required")
        if not isinstance(source.get("speaker"), str):
            raise TaskGoldError(f"{label}.speaker must be a string")
        if not isinstance(source.get("text"), str):
            raise TaskGoldError(f"{label}.text must be a string")
        message_key = _id_key(source["message_id"])
        canonical = {
            "source_message_id": source["message_id"],
            "speaker": source["speaker"],
            "text": source["text"],
        }
        previous = messages.get(message_key)
        if previous is not None and previous != canonical:
            raise TaskGoldError(
                f"conflicting Stage 1 metadata for message {source['message_id']!r}"
            )
        messages[message_key] = canonical

    if isinstance(stage1_source.get("messages"), list):
        for position, raw_message in enumerate(stage1_source["messages"]):
            add_message(
                _require_object(raw_message, f"stage1_source.messages[{position}]"),
                f"stage1_source.messages[{position}]",
            )
        return messages, events

    if isinstance(stage1_source.get("requirements"), list):
        requirement_rows = [
            (
                _require_string(
                    _require_object(raw_requirement, f"requirements[{position}]").get(
                        "requirement_id"
                    ),
                    f"requirements[{position}].requirement_id",
                ),
                _require_array(
                    _require_object(raw_requirement, f"requirements[{position}]").get(
                        "events"
                    ),
                    f"requirements[{position}].events",
                ),
            )
            for position, raw_requirement in enumerate(stage1_source["requirements"])
        ]
        events_have_ids = True
    else:
        requirement_rows = []
        for requirement_id, raw_events in stage1_source.items():
            if not isinstance(requirement_id, str) or not requirement_id:
                raise TaskGoldError("verified_events has an invalid Requirement ID")
            requirement_rows.append(
                (
                    requirement_id,
                    _require_array(raw_events, f"verified_events.{requirement_id}"),
                )
            )
        events_have_ids = False

    for requirement_position, (requirement_id, requirement_events) in enumerate(
        requirement_rows
    ):
        for event_position, raw_event in enumerate(
            requirement_events
        ):
            event = _require_object(
                raw_event, f"{requirement_id}.events[{event_position}]"
            )
            event_id = (
                _require_string(
                    event.get("event_id"),
                    f"{requirement_id}.events[{event_position}].event_id",
                )
                if events_have_ids
                else f"{requirement_id}_E{event_position + 1:03d}"
            )
            if event_id in events:
                raise TaskGoldError(f"duplicate Stage 1 event_id: {event_id}")
            events[event_id] = event
            source = _require_object(
                event.get("source_message"), f"{event_id}.source_message"
            )
            if "message_id" not in source:
                raise TaskGoldError(f"{event_id}.source_message.message_id is required")
            add_message(source, f"{event_id}.source_message")
    return messages, events


def audit_event_provenance(
    stage1_source: dict[str, Any], state_graph: dict[str, Any]
) -> list[dict[str, Any]]:
    """Report graph/Stage-1 Event provenance mismatches without repairing them."""
    _, annotation_events = _stage1_indexes(stage1_source)
    if not annotation_events:
        raise TaskGoldError(
            "Event provenance cannot be audited from a message-only Stage 1 source"
        )
    index = _GraphIndex(state_graph)
    issues: list[dict[str, Any]] = []
    for event_id, edge_ref in index.edge_by_event_id.items():
        graph_edge = edge_ref.edge
        stage1_event = annotation_events.get(event_id)
        if stage1_event is None:
            issues.append(
                {
                    "code": "GRAPH_EVENT_MISSING_FROM_STAGE1",
                    "event_id": event_id,
                    "requirement_id": edge_ref.requirement_id,
                    "graph_source_message_id": graph_edge["source_message_id"],
                }
            )
            continue
        source = stage1_event["source_message"]
        differences: dict[str, Any] = {}
        if _id_key(source["message_id"]) != _id_key(graph_edge["source_message_id"]):
            differences["source_message_id"] = {
                "graph": graph_edge["source_message_id"],
                "stage1": source["message_id"],
            }
        if stage1_event.get("event_type") != graph_edge.get("event_type"):
            differences["event_type"] = {
                "graph": graph_edge.get("event_type"),
                "stage1": stage1_event.get("event_type"),
            }
        if differences:
            issues.append(
                {
                    "code": "GRAPH_EVENT_STAGE1_MISMATCH",
                    "event_id": event_id,
                    "requirement_id": edge_ref.requirement_id,
                    "differences": differences,
                }
            )
    return issues


def discover_task_candidates(
    stage1_source: dict[str, Any],
    state_graph: dict[str, Any],
    *,
    task_speakers: Iterable[str] = ("client",),
    include_execution_only_tasks: bool = False,
) -> list[dict[str, Any]]:
    """Discover real task messages represented by State Graph Edges.

    A default candidate is a Client message with at least one definition,
    lifecycle, or ambiguity Event.  Once selected, *all* graph Events from that
    same source message belong to the Task.
    """
    messages, _ = _stage1_indexes(stage1_source)
    index = _GraphIndex(state_graph)
    allowed_speakers = set(task_speakers)
    candidates: list[dict[str, Any]] = []
    for message_key in index.ordered_message_keys():
        message_id = index.message_ids[message_key]
        source = messages.get(message_key)
        if source is None:
            raise TaskGoldError(
                f"source-message metadata cannot be resolved for message {message_id!r}"
            )
        if source["speaker"] not in allowed_speakers:
            continue
        edge_refs = sorted(
            index.edges_by_message[message_key],
            key=lambda item: (item.graph_position, item.edge_position),
        )
        event_types = {item.edge.get("event_type") for item in edge_refs}
        if not include_execution_only_tasks and not event_types.intersection(
            TASK_CHANGING_EVENT_TYPES
        ):
            continue
        affected_requirement_ids: list[str] = []
        for item in edge_refs:
            if item.requirement_id not in affected_requirement_ids:
                affected_requirement_ids.append(item.requirement_id)
        candidates.append(
            {
                "target_task": deepcopy(source),
                "task_event_ids": [item.edge["event_id"] for item in edge_refs],
                "affected_requirement_ids": affected_requirement_ids,
            }
        )
    return candidates


def build_gold_states(
    stage1_source: dict[str, Any],
    state_graph: dict[str, Any],
    *,
    task_speakers: Iterable[str] = ("client",),
    include_execution_only_tasks: bool = False,
) -> dict[str, Any]:
    """Build complete task-centered Pre/Post Project snapshots."""
    index = _GraphIndex(state_graph)
    source_project_id: Any = None
    if isinstance(stage1_source.get("project"), dict):
        source_project_id = stage1_source["project"].get("project_id")
    elif "project_id" in stage1_source:
        source_project_id = stage1_source.get("project_id")
    if source_project_id is not None and str(source_project_id) != index.project_id:
        raise TaskGoldError("Stage 1 source and State Graph have different project IDs")
    candidates = discover_task_candidates(
        stage1_source,
        state_graph,
        task_speakers=task_speakers,
        include_execution_only_tasks=include_execution_only_tasks,
    )
    task_gold_states: list[dict[str, Any]] = []
    for candidate in candidates:
        message_id = candidate["target_task"]["source_message_id"]
        task_gold_states.append(
            {
                "task_gold_id": f"{index.project_id}_TASK_{message_id}_GOLD",
                "target_task": candidate["target_task"],
                "task_event_ids": candidate["task_event_ids"],
                "affected_requirement_ids": candidate["affected_requirement_ids"],
                "pre_task_gold_state": {
                    "boundary": {"before_message_id": message_id},
                    "requirement_states": index.snapshot(message_id, inclusive=False),
                },
                "post_task_gold_state": {
                    "boundary": {"through_message_id": message_id},
                    "requirement_states": index.snapshot(message_id, inclusive=True),
                },
            }
        )
    result = {
        "project_id": index.project_id,
        "task_gold_states": task_gold_states,
    }
    errors = validate_gold_states(result, state_graph)
    if errors:
        raise TaskGoldError("Gold State validation failed: " + "; ".join(errors))
    return result


def _snapshot_map(task_gold: dict[str, Any], field: str) -> dict[str, str]:
    return {
        item["requirement_id"]: item["state_id"]
        for item in task_gold[field]["requirement_states"]
    }


def _derive_transitions(
    task_gold: dict[str, Any], index: _GraphIndex
) -> dict[str, RequirementTransition]:
    pre = _snapshot_map(task_gold, "pre_task_gold_state")
    post = _snapshot_map(task_gold, "post_task_gold_state")
    transitions: dict[str, RequirementTransition] = {}
    for requirement_id in task_gold["affected_requirement_ids"]:
        after_state_id = post.get(requirement_id)
        if after_state_id is None:
            raise TaskGoldError(
                f"affected Requirement {requirement_id} is absent from Post-task Gold"
            )
        before_state_id = pre.get(requirement_id)
        transitions[requirement_id] = RequirementTransition(
            requirement_id=requirement_id,
            before_state=(
                index.node_by_state_id[before_state_id]
                if before_state_id is not None
                else None
            ),
            after_state=index.node_by_state_id[after_state_id],
        )
    return transitions


def _mapping_changes(
    before: dict[str, Any] | None, after: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    before = before or {}
    ordered_keys = list(before)
    ordered_keys.extend(key for key in after if key not in before)
    changes: dict[str, dict[str, Any]] = {}
    for key in ordered_keys:
        before_present = key in before
        after_present = key in after
        before_value = before.get(key)
        after_value = after.get(key)
        if before_present != after_present or before_value != after_value:
            changes[key] = {
                "before": deepcopy(before_value),
                "after": deepcopy(after_value),
            }
    return changes


def _open_ambiguity(state: dict[str, Any], dimension: str | None = None) -> bool:
    ambiguity = state.get("ambiguity")
    return (
        isinstance(ambiguity, dict)
        and ambiguity.get("status") == "OPEN"
        and (dimension is None or ambiguity.get("dimension") == dimension)
    )


def build_rq1_gold(
    task_gold: dict[str, Any], index: _GraphIndex
) -> dict[str, Any]:
    pre = _snapshot_map(task_gold, "pre_task_gold_state")
    historical_evidence: dict[str, list[str]] = {}
    for requirement_id in task_gold["affected_requirement_ids"]:
        state_id = pre.get(requirement_id)
        historical_evidence[requirement_id] = (
            list(index.node_by_state_id[state_id]["supporting_event_ids"])
            if state_id is not None
            else []
        )
    return {
        "affected_requirement_ids": list(task_gold["affected_requirement_ids"]),
        "historical_evidence": historical_evidence,
    }


def build_rq2_gold(
    transitions: dict[str, RequirementTransition],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for requirement_id, transition in transitions.items():
        if transition.before_state is None:
            continue
        before_scope = transition.before_state.get("scope")
        after_scope = transition.after_state.get("scope")
        if not isinstance(before_scope, dict) or not isinstance(after_scope, dict):
            raise TaskGoldError(f"{requirement_id} has an invalid Scope object")
        if _open_ambiguity(transition.after_state, "SCOPE"):
            label = "UNRESOLVED"
        elif before_scope == after_scope:
            label = "PRESERVED"
        else:
            label = "UPDATED"
        result[requirement_id] = {
            "scope_before": deepcopy(before_scope),
            "scope_after": deepcopy(after_scope),
            "scope_transition": label,
        }
    return result


def build_rq3_gold(
    transitions: dict[str, RequirementTransition],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for requirement_id, transition in transitions.items():
        before = transition.before_state
        after = transition.after_state
        item: dict[str, Any] = {
            "before_state_id": before.get("state_id") if before else None,
            "after_state_id": after["state_id"],
            "lifecycle_before": before.get("lifecycle_status") if before else None,
            "lifecycle_after": after.get("lifecycle_status"),
            "attributes_after": deepcopy(after.get("attributes")),
            "scope_after": deepcopy(after.get("scope")),
            "ambiguity_after": deepcopy(after.get("ambiguity")),
            "execution_after": deepcopy(after.get("execution")),
            "attribute_changes": _mapping_changes(
                before.get("attributes") if before else None,
                _require_object(after.get("attributes"), f"{after['state_id']}.attributes"),
            ),
            "scope_changes": _mapping_changes(
                before.get("scope") if before else None,
                _require_object(after.get("scope"), f"{after['state_id']}.scope"),
            ),
        }
        before_ambiguity = before.get("ambiguity") if before else None
        if before_ambiguity != after.get("ambiguity"):
            item["ambiguity_change"] = {
                "before": deepcopy(before_ambiguity),
                "after": deepcopy(after.get("ambiguity")),
            }
        before_execution = before.get("execution") if before else None
        if before_execution != after.get("execution"):
            item["execution_change"] = {
                "before": deepcopy(before_execution),
                "after": deepcopy(after.get("execution")),
            }
        result[requirement_id] = item
    return {"requirement_transitions": result}


def build_rq4_gold(
    transitions: dict[str, RequirementTransition],
) -> dict[str, Any]:
    """Derive conservative historical-memory actions.

    No IGNORE distractors are emitted by default because the current schema has
    no explicit semantic-relation field with which to prove irrelevance.
    """
    result: dict[str, Any] = {}
    for requirement_id, transition in transitions.items():
        before = transition.before_state
        after = transition.after_state
        if _open_ambiguity(after):
            result[requirement_id] = {
                "requirement_action": "CLARIFY",
                "ambiguity_dimension": after["ambiguity"].get("dimension"),
            }
            continue
        if before is None:
            # There is no historical Requirement memory to use or override.
            continue
        actions: dict[str, str] = {}
        before_attributes = _require_object(
            before.get("attributes"), f"{before['state_id']}.attributes"
        )
        after_attributes = _require_object(
            after.get("attributes"), f"{after['state_id']}.attributes"
        )
        for key, before_value in before_attributes.items():
            actions[key] = (
                "USE"
                if key in after_attributes and before_value == after_attributes[key]
                else "OVERRIDE"
            )

        before_scope = _require_object(
            before.get("scope"), f"{before['state_id']}.scope"
        )
        after_scope = _require_object(after.get("scope"), f"{after['state_id']}.scope")
        for field in SCOPE_FIELDS:
            before_value = before_scope.get(field)
            if before_value is not None:
                actions[f"scope.{field}"] = (
                    "USE" if before_value == after_scope.get(field) else "OVERRIDE"
                )

        lifecycle_before = before.get("lifecycle_status")
        if lifecycle_before is not None:
            actions["lifecycle_status"] = (
                "USE"
                if lifecycle_before == after.get("lifecycle_status")
                else "OVERRIDE"
            )
        for field in ("ambiguity", "execution"):
            before_value = before.get(field)
            if before_value is not None:
                actions[field] = (
                    "USE" if before_value == after.get(field) else "OVERRIDE"
                )
        if actions:
            result[requirement_id] = {"dimension_actions": actions}
    return result


def build_evaluation_instances(
    gold_states: dict[str, Any], state_graph: dict[str, Any]
) -> dict[str, Any]:
    """Derive RQ1--RQ4 Gold solely from Task Gold and the State Graph."""
    index = _GraphIndex(state_graph)
    if str(gold_states.get("project_id")) != index.project_id:
        raise TaskGoldError("Gold States and State Graph have different project IDs")
    instances: list[dict[str, Any]] = []
    for task_gold in _require_array(
        gold_states.get("task_gold_states"), "gold_states.task_gold_states"
    ):
        transitions = _derive_transitions(task_gold, index)
        rq1 = build_rq1_gold(task_gold, index)
        rq2 = build_rq2_gold(transitions)
        rq3 = build_rq3_gold(transitions)
        rq4 = build_rq4_gold(transitions)
        message_id = task_gold["target_task"]["source_message_id"]
        instances.append(
            {
                "instance_id": f"{index.project_id}_TASK_{message_id}",
                "task_gold_id": task_gold["task_gold_id"],
                "target_task": deepcopy(task_gold["target_task"]),
                "affected_requirement_ids": list(
                    task_gold["affected_requirement_ids"]
                ),
                "rq_eligibility": {
                    "RQ1": bool(task_gold["affected_requirement_ids"]),
                    "RQ2": bool(rq2),
                    "RQ3": bool(rq3["requirement_transitions"]),
                    "RQ4": bool(rq4),
                },
                "rq_gold": {
                    "RQ1": rq1,
                    "RQ2": rq2,
                    "RQ3": rq3,
                    "RQ4": rq4,
                },
            }
        )
    result = {"project_id": index.project_id, "instances": instances}
    errors = validate_evaluation_instances(result, gold_states, state_graph)
    if errors:
        raise TaskGoldError("RQ instance validation failed: " + "; ".join(errors))
    return result


def validate_gold_states(
    gold_states: dict[str, Any], state_graph: dict[str, Any]
) -> list[str]:
    """Validate state existence, boundaries, completeness, and no leakage."""
    errors: list[str] = []
    try:
        index = _GraphIndex(state_graph)
        if str(gold_states.get("project_id")) != index.project_id:
            errors.append("project_id does not match the State Graph")
        task_gold_states = _require_array(
            gold_states.get("task_gold_states"), "gold_states.task_gold_states"
        )
        seen_gold_ids: set[str] = set()
        for task_number, task_gold in enumerate(task_gold_states):
            label = f"task_gold_states[{task_number}]"
            task_gold = _require_object(task_gold, label)
            if "requirement_transitions" in task_gold:
                errors.append(f"{label} must not persist requirement_transitions")
            gold_id = task_gold.get("task_gold_id")
            if gold_id in seen_gold_ids:
                errors.append(f"duplicate task_gold_id: {gold_id}")
            seen_gold_ids.add(gold_id)
            target = _require_object(task_gold.get("target_task"), f"{label}.target_task")
            message_id = target.get("source_message_id")
            message_key = _id_key(message_id)
            if message_key not in index.message_ids:
                errors.append(f"{label} target message is absent from the State Graph")
                continue
            expected_pre = index.snapshot(message_id, inclusive=False)
            expected_post = index.snapshot(message_id, inclusive=True)
            actual_pre = task_gold["pre_task_gold_state"]["requirement_states"]
            actual_post = task_gold["post_task_gold_state"]["requirement_states"]
            if actual_pre != expected_pre:
                errors.append(f"{label} Pre-task snapshot is incomplete or temporally wrong")
            if actual_post != expected_post:
                errors.append(f"{label} Post-task snapshot is incomplete or temporally wrong")
            if task_gold["pre_task_gold_state"].get("boundary") != {
                "before_message_id": message_id
            }:
                errors.append(f"{label} has an invalid Pre-task boundary")
            if task_gold["post_task_gold_state"].get("boundary") != {
                "through_message_id": message_id
            }:
                errors.append(f"{label} has an invalid Post-task boundary")

            edge_refs = sorted(
                index.edges_by_message[message_key],
                key=lambda item: (item.graph_position, item.edge_position),
            )
            expected_events = [item.edge["event_id"] for item in edge_refs]
            expected_affected: list[str] = []
            for item in edge_refs:
                if item.requirement_id not in expected_affected:
                    expected_affected.append(item.requirement_id)
            if task_gold.get("task_event_ids") != expected_events:
                errors.append(f"{label} Task Events do not match the target message")
            if task_gold.get("affected_requirement_ids") != expected_affected:
                errors.append(f"{label} affected Requirements do not match Task Events")

            pre_map = {item["requirement_id"]: item["state_id"] for item in actual_pre}
            post_map = {item["requirement_id"]: item["state_id"] for item in actual_post}
            for item in actual_pre + actual_post:
                state_id = item.get("state_id")
                requirement_id = item.get("requirement_id")
                if state_id not in index.node_by_state_id:
                    errors.append(f"{label} references unknown state_id {state_id!r}")
                elif index.state_requirement[state_id] != requirement_id:
                    errors.append(
                        f"{label} maps {state_id} to the wrong Requirement"
                    )
            for requirement_id in set(pre_map).intersection(post_map).difference(
                expected_affected
            ):
                if pre_map[requirement_id] != post_map[requirement_id]:
                    errors.append(
                        f"{label} changes unaffected Requirement {requirement_id}"
                    )
            for item in edge_refs:
                requirement_id = item.requirement_id
                if item.edge.get("event_type") == "INTRODUCE":
                    if requirement_id in pre_map or requirement_id not in post_map:
                        errors.append(
                            f"{label} mishandles newly introduced {requirement_id}"
                        )
                if item.edge.get("event_type") == "REMOVE":
                    state_id = post_map.get(requirement_id)
                    if state_id is None:
                        errors.append(
                            f"{label} drops removed Requirement {requirement_id}"
                        )
                    elif index.node_by_state_id[state_id].get("lifecycle_status") != "REMOVED":
                        errors.append(
                            f"{label} does not retain the REMOVED state for {requirement_id}"
                        )

            boundary = _message_number(message_id)
            for field, inclusive in (
                ("pre_task_gold_state", False),
                ("post_task_gold_state", True),
            ):
                for state_ref in task_gold[field]["requirement_states"]:
                    state_id = state_ref["state_id"]
                    node = index.node_by_state_id.get(state_id)
                    if node is None:
                        continue
                    for event_id in node["supporting_event_ids"]:
                        support_position = _message_number(
                            index.edge_by_event_id[event_id].edge["source_message_id"]
                        )
                        if support_position > boundary or (
                            not inclusive and support_position == boundary
                        ):
                            errors.append(
                                f"{label} leaks future supporting event {event_id} into {field}"
                            )
    except (KeyError, TypeError, TaskGoldError) as exc:
        errors.append(str(exc))
    return errors


def validate_evaluation_instances(
    evaluation_instances: dict[str, Any],
    gold_states: dict[str, Any],
    state_graph: dict[str, Any],
) -> list[str]:
    """Validate RQ provenance and RQ1 historical no-future-leakage."""
    errors: list[str] = []
    try:
        index = _GraphIndex(state_graph)
        task_gold_by_id = {
            item["task_gold_id"]: item for item in gold_states["task_gold_states"]
        }
        instances = _require_array(
            evaluation_instances.get("instances"), "evaluation_instances.instances"
        )
        seen_ids: set[str] = set()
        for number, instance in enumerate(instances):
            label = f"instances[{number}]"
            instance_id = instance.get("instance_id")
            if instance_id in seen_ids:
                errors.append(f"duplicate instance_id: {instance_id}")
            seen_ids.add(instance_id)
            task_gold = task_gold_by_id.get(instance.get("task_gold_id"))
            if task_gold is None:
                errors.append(f"{label} references unknown Task Gold")
                continue
            if instance.get("target_task") != task_gold.get("target_task"):
                errors.append(f"{label} target_task differs from Task Gold")
            if instance.get("affected_requirement_ids") != task_gold.get(
                "affected_requirement_ids"
            ):
                errors.append(f"{label} affected Requirements differ from Task Gold")
            rq1 = instance["rq_gold"]["RQ1"]
            if rq1.get("affected_requirement_ids") != task_gold.get(
                "affected_requirement_ids"
            ):
                errors.append(f"{label} RQ1 affected Requirements are inconsistent")
            boundary = _message_number(
                task_gold["target_task"]["source_message_id"]
            )
            for requirement_id, event_ids in rq1["historical_evidence"].items():
                for event_id in event_ids:
                    edge_ref = index.edge_by_event_id.get(event_id)
                    if edge_ref is None:
                        errors.append(f"{label} RQ1 references unknown event {event_id}")
                    elif edge_ref.requirement_id != requirement_id:
                        errors.append(
                            f"{label} RQ1 assigns {event_id} to the wrong Requirement"
                        )
                    elif _message_number(
                        edge_ref.edge["source_message_id"]
                    ) >= boundary:
                        errors.append(f"{label} RQ1 leaks non-historical event {event_id}")
            eligibility = instance.get("rq_eligibility", {})
            rq_gold = instance.get("rq_gold", {})
            expected_eligibility = {
                "RQ1": bool(instance.get("affected_requirement_ids")),
                "RQ2": bool(rq_gold.get("RQ2")),
                "RQ3": bool(
                    rq_gold.get("RQ3", {}).get("requirement_transitions")
                ),
                "RQ4": bool(rq_gold.get("RQ4")),
            }
            if eligibility != expected_eligibility:
                errors.append(f"{label} rq_eligibility is inconsistent with RQ Gold")
    except (KeyError, TypeError, TaskGoldError) as exc:
        errors.append(str(exc))
    return errors


def build_statistics(
    state_graph: dict[str, Any],
    gold_states: dict[str, Any],
    evaluation_instances: dict[str, Any],
    *,
    provenance_issue_count: int = 0,
) -> dict[str, int]:
    graphs = state_graph["requirement_graphs"]
    tasks = gold_states["task_gold_states"]
    instances = evaluation_instances["instances"]
    action_counts = {"USE": 0, "OVERRIDE": 0, "CLARIFY": 0, "IGNORE": 0}
    for instance in instances:
        for item in instance["rq_gold"]["RQ4"].values():
            action = item.get("requirement_action")
            if action in action_counts:
                action_counts[action] += 1
            for dimension_action in item.get("dimension_actions", {}).values():
                if dimension_action in action_counts:
                    action_counts[dimension_action] += 1
    statistics = {
        "requirements": len(graphs),
        "requirement_states": sum(len(graph["nodes"]) for graph in graphs),
        "task_candidates": len(tasks),
        "multi_requirement_tasks": sum(
            len(task["affected_requirement_ids"]) > 1 for task in tasks
        ),
        "generated_task_gold_states": len(tasks),
        "RQ1_eligible_instances": sum(
            instance["rq_eligibility"]["RQ1"] for instance in instances
        ),
        "RQ2_eligible_instances": sum(
            instance["rq_eligibility"]["RQ2"] for instance in instances
        ),
        "RQ3_eligible_instances": sum(
            instance["rq_eligibility"]["RQ3"] for instance in instances
        ),
        "RQ4_eligible_instances": sum(
            instance["rq_eligibility"]["RQ4"] for instance in instances
        ),
        "USE_labels": action_counts["USE"],
        "OVERRIDE_labels": action_counts["OVERRIDE"],
        "CLARIFY_labels": action_counts["CLARIFY"],
        "safe_IGNORE_distractors": action_counts["IGNORE"],
        "provenance_validation_errors": provenance_issue_count,
    }
    return statistics
