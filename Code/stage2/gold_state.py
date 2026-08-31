"""Build task-centered Gold States.

The Requirement State Graph is the semantic and temporal source of truth.  A
Stage 1 annotation supplies the original source-message metadata that is not
duplicated in the graph.  All construction in this module is deterministic;
raw project history and model inference are deliberately out of scope.
"""

from __future__ import annotations

import json
import math
import random
import re
from copy import deepcopy
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


TASK_CHANGING_EVENT_TYPES = {
    "INTRODUCE",
    "MODIFY",
    "DEFER",
    "RESUME",
    "REMOVE",
    "AMBIGUOUS",
}
POSITION_BUCKETS = ("early", "middle", "late")
PRIORITY_RANK = {"low": 0, "medium": 1, "high": 2}
DEFAULT_EVENT_PRIORITY = {
    "AMBIGUOUS": "high",
    "REMOVE": "high",
    "DEFER": "high",
    "RESUME": "high",
    "MODIFY": "medium",
    "INTRODUCE": "low",
}
DEFAULT_POSITION_RATIO = {"early": 0.20, "middle": 0.30, "late": 0.50}


class TaskGoldError(ValueError):
    """Raised when Task Gold cannot be derived without guessing."""


@dataclass(frozen=True)
class TaskSelectionConfig:
    """Deterministic, configurable Task sampling preferences."""

    event_priority: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_EVENT_PRIORITY)
    )
    position_ratio: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_POSITION_RATIO)
    )
    include_execution_only_tasks: bool = False
    max_tasks_per_project: int | None = None
    random_seed: int = 42

    @classmethod
    def from_mapping(
        cls, value: dict[str, Any] | None = None
    ) -> "TaskSelectionConfig":
        """Validate a JSON-compatible configuration mapping."""
        raw = {} if value is None else _require_object(value, "selection_config")
        unknown = set(raw).difference(
            {
                "event_priority",
                "position_ratio",
                "include_execution_only_tasks",
                "max_tasks_per_project",
                "random_seed",
            }
        )
        if unknown:
            raise TaskGoldError(
                "selection_config has unsupported fields: "
                + ", ".join(sorted(unknown))
            )

        event_priority = dict(DEFAULT_EVENT_PRIORITY)
        event_priority.update(
            _require_object(raw.get("event_priority", {}), "event_priority")
        )
        if any(
            not isinstance(event_type, str)
            or priority not in PRIORITY_RANK
            for event_type, priority in event_priority.items()
        ):
            raise TaskGoldError(
                "selection_config.event_priority must map Event types to "
                "high, medium, or low"
            )

        position_ratio = dict(DEFAULT_POSITION_RATIO)
        position_ratio.update(
            _require_object(raw.get("position_ratio", {}), "position_ratio")
        )
        if set(position_ratio) != set(POSITION_BUCKETS):
            raise TaskGoldError(
                "selection_config.position_ratio must contain early, middle, and late"
            )
        if any(
            isinstance(ratio, bool)
            or not isinstance(ratio, (int, float))
            or not math.isfinite(ratio)
            or ratio < 0
            for ratio in position_ratio.values()
        ) or sum(position_ratio.values()) <= 0:
            raise TaskGoldError(
                "selection_config.position_ratio values must be finite, non-negative, "
                "and have a positive sum"
            )

        include_execution = raw.get("include_execution_only_tasks", False)
        if not isinstance(include_execution, bool):
            raise TaskGoldError(
                "selection_config.include_execution_only_tasks must be a boolean"
            )
        max_tasks = raw.get("max_tasks_per_project")
        if max_tasks is not None and (
            isinstance(max_tasks, bool)
            or not isinstance(max_tasks, int)
            or max_tasks < 1
        ):
            raise TaskGoldError(
                "selection_config.max_tasks_per_project must be a positive integer or null"
            )
        random_seed = raw.get("random_seed", 42)
        if isinstance(random_seed, bool) or not isinstance(random_seed, int):
            raise TaskGoldError("selection_config.random_seed must be an integer")
        return cls(
            event_priority=event_priority,
            position_ratio={key: float(position_ratio[key]) for key in POSITION_BUCKETS},
            include_execution_only_tasks=include_execution,
            max_tasks_per_project=max_tasks,
            random_seed=random_seed,
        )


def load_selection_config(path: str | Path) -> TaskSelectionConfig:
    """Load and validate Task selection configuration from JSON."""
    config_path = Path(path)
    try:
        value = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaskGoldError(
            f"cannot load Task selection config {config_path}: {exc}"
        ) from exc
    return TaskSelectionConfig.from_mapping(value)


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
    stage1_source: dict[str, Any] | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Index messages and Events from supported Stage 1 artifacts.

    Supported inputs are the canonical assembled annotation, an upgrade run's
    ``verified_events.json`` (Requirement ID -> Event array), or an upgrade
    run's ``normalized_project.json`` message catalog.  Verified Events have no
    persisted Event IDs, so their canonical IDs are reconstructed from their
    already ordered per-Requirement arrays for optional provenance auditing.
    """
    messages: dict[str, dict[str, Any]] = {}
    events: dict[str, dict[str, Any]] = {}
    if stage1_source is None:
        return messages, events
    stage1_source = _require_object(stage1_source, "stage1_source")

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
    stage1_source: dict[str, Any] | None,
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
            source = {
                "source_message_id": message_id,
                "speaker": None,
                "text": None,
            }
        elif source["speaker"] not in allowed_speakers:
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


def _candidate_position_bucket(
    message_id: Any, ordered_project_message_ids: list[Any]
) -> str:
    """Map a Task to the early, middle, or late third of Project history."""
    ordered_keys = [_id_key(item) for item in ordered_project_message_ids]
    try:
        position = ordered_keys.index(_id_key(message_id))
    except ValueError as exc:  # pragma: no cover - guarded by candidate discovery
        raise TaskGoldError(
            f"Task message {message_id!r} is absent from history"
        ) from exc
    fraction = (position + 0.5) / len(ordered_keys)
    if fraction < 1 / 3:
        return "early"
    if fraction < 2 / 3:
        return "middle"
    return "late"


def _position_quotas(
    sample_size: int,
    capacities: dict[str, int],
    ratios: dict[str, float],
) -> dict[str, int]:
    """Allocate approximate position quotas and redistribute unavailable slots."""
    ratio_total = sum(ratios.values())
    raw = {
        bucket: sample_size * ratios[bucket] / ratio_total
        for bucket in POSITION_BUCKETS
    }
    quotas = {
        bucket: min(capacities[bucket], int(math.floor(raw[bucket])))
        for bucket in POSITION_BUCKETS
    }
    while sum(quotas.values()) < sample_size:
        available = [
            bucket
            for bucket in POSITION_BUCKETS
            if quotas[bucket] < capacities[bucket]
        ]
        if not available:
            break
        bucket = max(
            available,
            key=lambda item: (
                raw[item] - quotas[item],
                ratios[item],
                POSITION_BUCKETS.index(item),
            ),
        )
        quotas[bucket] += 1
    return quotas


def sample_target_tasks(
    candidates: list[dict[str, Any]],
    stage1_source: dict[str, Any] | None,
    state_graph: dict[str, Any],
    config: TaskSelectionConfig,
) -> list[dict[str, Any]]:
    """Sample Tasks by timeline position and highest Event-type priority.

    With ``max_tasks_per_project=null`` every candidate is retained.  When a
    cap is set, position ratios allocate approximate quotas across timeline
    thirds.  Within each third, the highest-priority Event on a Task determines
    its preference; seeded shuffling only breaks ties.
    """
    maximum = config.max_tasks_per_project
    if maximum is None or maximum >= len(candidates):
        return list(candidates)

    index = _GraphIndex(state_graph)
    messages, _ = _stage1_indexes(stage1_source)
    if messages:
        ordered_message_ids = sorted(
            (message["source_message_id"] for message in messages.values()),
            key=_message_number,
        )
    else:
        ordered_message_ids = [
            index.message_ids[key] for key in index.ordered_message_keys()
        ]

    by_bucket: dict[str, list[dict[str, Any]]] = {
        bucket: [] for bucket in POSITION_BUCKETS
    }
    for candidate in candidates:
        message_id = candidate["target_task"]["source_message_id"]
        bucket = _candidate_position_bucket(message_id, ordered_message_ids)
        by_bucket[bucket].append(candidate)

    quotas = _position_quotas(
        maximum,
        {bucket: len(items) for bucket, items in by_bucket.items()},
        config.position_ratio,
    )
    rng = random.Random(config.random_seed)
    selected: list[dict[str, Any]] = []
    for bucket in POSITION_BUCKETS:
        items = list(by_bucket[bucket])
        rng.shuffle(items)

        def candidate_priority(candidate: dict[str, Any]) -> int:
            event_types = {
                index.edge_by_event_id[event_id].edge.get("event_type")
                for event_id in candidate["task_event_ids"]
            }
            return max(
                (
                    PRIORITY_RANK.get(
                        config.event_priority.get(str(event_type), "low"), 0
                    )
                    for event_type in event_types
                ),
                default=0,
            )

        items.sort(key=candidate_priority, reverse=True)
        selected.extend(items[: quotas[bucket]])

    return sorted(
        selected,
        key=lambda item: _message_number(item["target_task"]["source_message_id"]),
    )


def build_gold_states(
    stage1_source: dict[str, Any] | None,
    state_graph: dict[str, Any],
    *,
    task_speakers: Iterable[str] = ("client",),
    include_execution_only_tasks: bool | None = None,
    selection_config: TaskSelectionConfig | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build complete task-centered Pre/Post Project snapshots."""
    index = _GraphIndex(state_graph)
    config = (
        selection_config
        if isinstance(selection_config, TaskSelectionConfig)
        else TaskSelectionConfig.from_mapping(selection_config)
    )
    if include_execution_only_tasks is not None:
        config = replace(
            config,
            include_execution_only_tasks=include_execution_only_tasks,
        )
    source_project_id: Any = None
    if stage1_source is not None and isinstance(stage1_source.get("project"), dict):
        source_project_id = stage1_source["project"].get("project_id")
    elif stage1_source is not None and "project_id" in stage1_source:
        source_project_id = stage1_source.get("project_id")
    if source_project_id is not None and str(source_project_id) != index.project_id:
        raise TaskGoldError("Stage 1 source and State Graph have different project IDs")
    candidates = discover_task_candidates(
        stage1_source,
        state_graph,
        task_speakers=task_speakers,
        include_execution_only_tasks=config.include_execution_only_tasks,
    )
    candidates = sample_target_tasks(candidates, stage1_source, state_graph, config)
    task_gold_states: list[dict[str, Any]] = []
    for candidate in candidates:
        message_id = candidate["target_task"]["source_message_id"]
        pre_snapshot = index.snapshot(message_id, inclusive=False)
        affected = candidate["affected_requirement_ids"]
        preserved = [
            item["requirement_id"]
            for item in pre_snapshot
            if item["requirement_id"] not in affected
        ]
        task_gold_states.append(
            {
                "task_gold_id": f"{index.project_id}_TASK_{message_id}_GOLD",
                "target_task": candidate["target_task"],
                "task_event_ids": candidate["task_event_ids"],
                "affected_requirement_ids": affected,
                "preserved_requirement_ids": preserved,
                "pre_task_gold_state": {
                    "boundary": {"before_message_id": message_id},
                    "requirement_states": pre_snapshot,
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
            context = (
                f"project_id={index.project_id} target_message_id={message_id!r}"
            )
            for metadata_field in ("speaker", "text"):
                metadata = target.get(metadata_field)
                if metadata is not None and not isinstance(metadata, str):
                    errors.append(
                        f"{context}: target_task.{metadata_field} must be a string or null"
                    )
            message_key = _id_key(message_id)
            if message_key not in index.message_ids:
                errors.append(
                    f"{context}: target message is absent from the State Graph"
                )
                continue
            expected_pre = index.snapshot(message_id, inclusive=False)
            expected_post = index.snapshot(message_id, inclusive=True)
            actual_pre = task_gold["pre_task_gold_state"]["requirement_states"]
            actual_post = task_gold["post_task_gold_state"]["requirement_states"]
            if actual_pre != expected_pre:
                errors.append(
                    f"{context}: expected the complete State Graph snapshot before "
                    "the Task; observed an incomplete or temporally wrong snapshot"
                )
            if actual_post != expected_post:
                errors.append(
                    f"{context}: expected the complete State Graph snapshot through "
                    "the Task; observed an incomplete or temporally wrong snapshot"
                )
            if task_gold["pre_task_gold_state"].get("boundary") != {
                "before_message_id": message_id
            }:
                errors.append(f"{context}: invalid Pre-task boundary")
            if task_gold["post_task_gold_state"].get("boundary") != {
                "through_message_id": message_id
            }:
                errors.append(f"{context}: invalid Post-task boundary")

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
                errors.append(
                    f"{context}: expected Task Events {expected_events!r}, observed "
                    f"{task_gold.get('task_event_ids')!r}"
                )
            for event_id in task_gold.get("task_event_ids", []):
                if event_id not in index.edge_by_event_id:
                    errors.append(
                        f"{context}: task_event_id {event_id!r} is absent from the "
                        "State Graph"
                    )
            if task_gold.get("affected_requirement_ids") != expected_affected:
                errors.append(
                    f"{context}: expected affected Requirements {expected_affected!r}, "
                    f"observed {task_gold.get('affected_requirement_ids')!r}"
                )

            pre_map = {item["requirement_id"]: item["state_id"] for item in actual_pre}
            post_map = {item["requirement_id"]: item["state_id"] for item in actual_post}
            if len(pre_map) != len(actual_pre):
                errors.append(f"{context}: duplicate Requirement IDs in Pre-task snapshot")
            if len(post_map) != len(actual_post):
                errors.append(f"{context}: duplicate Requirement IDs in Post-task snapshot")
            expected_preserved = [
                item["requirement_id"]
                for item in expected_pre
                if item["requirement_id"] not in expected_affected
            ]
            if task_gold.get("preserved_requirement_ids") != expected_preserved:
                errors.append(
                    f"{context}: preserved Requirements must equal Pre-task Requirements "
                    "minus affected Requirements"
                )
            for item in actual_pre + actual_post:
                state_id = item.get("state_id")
                requirement_id = item.get("requirement_id")
                if state_id not in index.node_by_state_id:
                    errors.append(
                        f"{context} requirement_id={requirement_id}: unknown state_id "
                        f"{state_id!r}"
                    )
                elif index.state_requirement[state_id] != requirement_id:
                    errors.append(
                        f"{context} requirement_id={requirement_id}: state_id "
                        f"{state_id!r} belongs to "
                        f"{index.state_requirement[state_id]!r}"
                    )
            for requirement_id in set(pre_map).intersection(post_map).difference(
                expected_affected
            ):
                if pre_map[requirement_id] != post_map[requirement_id]:
                    errors.append(
                        f"{context} requirement_id={requirement_id}: unaffected "
                        f"Requirement changed from {pre_map[requirement_id]!r} to "
                        f"{post_map[requirement_id]!r}"
                    )
            for requirement_id in task_gold.get("preserved_requirement_ids", []):
                if any(item.requirement_id == requirement_id for item in edge_refs):
                    errors.append(
                        f"{context} requirement_id={requirement_id}: preserved "
                        "Requirement has an Event at the target message"
                    )
                if pre_map.get(requirement_id) != post_map.get(requirement_id):
                    errors.append(
                        f"{context} requirement_id={requirement_id}: expected identical "
                        f"Pre/Post state IDs, observed {pre_map.get(requirement_id)!r} -> "
                        f"{post_map.get(requirement_id)!r}"
                    )

            task_edges_by_requirement: dict[str, list[_EdgeRef]] = {}
            for item in edge_refs:
                task_edges_by_requirement.setdefault(item.requirement_id, []).append(
                    item
                )
            for requirement_id, requirement_edges in task_edges_by_requirement.items():
                final_edge = max(requirement_edges, key=lambda item: item.edge_position)
                expected_final_state = final_edge.edge["to_state_id"]
                if post_map.get(requirement_id) != expected_final_state:
                    errors.append(
                        f"{context} requirement_id={requirement_id}: expected final "
                        f"same-message state {expected_final_state!r}, observed "
                        f"{post_map.get(requirement_id)!r}"
                    )
            for item in edge_refs:
                requirement_id = item.requirement_id
                if (
                    item.edge.get("event_type") == "INTRODUCE"
                    and item.edge.get("from_state_id") is None
                ):
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


def build_statistics(
    state_graph: dict[str, Any],
    gold_states: dict[str, Any],
    *,
    provenance_issue_count: int = 0,
) -> dict[str, int]:
    graphs = state_graph["requirement_graphs"]
    tasks = gold_states["task_gold_states"]
    statistics = {
        "requirements": len(graphs),
        "requirement_states": sum(len(graph["nodes"]) for graph in graphs),
        "task_candidates": len(tasks),
        "multi_requirement_tasks": sum(
            len(task["affected_requirement_ids"]) > 1 for task in tasks
        ),
        "generated_task_gold_states": len(tasks),
        "provenance_validation_errors": provenance_issue_count,
    }
    return statistics
