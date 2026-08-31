"""Select target Tasks with an LLM and build deterministic Gold States.

Rules create Candidate Tasks and construct their history-bounded packets.  An
injected LLM client evaluates benchmark value only.  Coverage, score-threshold
or human-review finalization, Requirement State Graph replay, and Gold
validation remain deterministic and auditable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol


CANDIDATE_EVENT_TYPES = {
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
ALL_STAGE1_EVENT_TYPES = CANDIDATE_EVENT_TYPES | EXECUTION_EVENT_TYPES | {"INTRODUCE"}
EVALUATION_LEVELS = ("LOW", "MEDIUM", "HIGH")
EVALUATION_LEVEL_RANK = {value: position for position, value in enumerate(EVALUATION_LEVELS)}
EVALUATION_DIMENSIONS = (
    "historical_dependency",
    "requirement_evolution",
    "reconstruction_risk",
    "ambiguity_decision_value",
    "multi_requirement_value",
)
MAX_AI_SELECTION_SCORE = len(EVALUATION_DIMENSIONS) * max(
    EVALUATION_LEVEL_RANK.values()
)
DEFAULT_ALLOWED_RQ_TARGETS = ("RQ1", "RQ2", "RQ3", "RQ4", "RQ5")
TARGET_SELECTION_SCHEMA_VERSION = "target-selection-v1"
PACKET_SCHEMA_VERSION = "target-candidate-packet-v1"
SELECTED_TARGETS_SCHEMA_VERSION = "selected-target-times-v1"
GOLD_SCHEMA_VERSION = "task-gold-v2"


class TaskGoldError(ValueError):
    """Raised when Task Gold cannot be derived without guessing."""


@dataclass(frozen=True)
class TargetSelectionConfig:
    """Validated Candidate, LLM-runtime, and coverage configuration."""

    candidate_event_types: tuple[str, ...] = tuple(sorted(CANDIDATE_EVENT_TYPES))
    include_introduce_candidates: bool = True
    include_execution_only_tasks: bool = False
    allowed_rq_targets: tuple[str, ...] = DEFAULT_ALLOWED_RQ_TARGETS
    max_selected_targets: int | None = None
    model: str = "gpt-5.6-sol"
    reasoning_effort: str = "high"
    max_concurrent_requests: int = 4
    retries: int = 3
    timeout_seconds: float = 900.0
    max_reason_length: int = 2000

    @classmethod
    def from_mapping(
        cls, value: dict[str, Any] | None = None
    ) -> "TargetSelectionConfig":
        """Validate the target-selection JSON configuration."""
        raw = {} if value is None else _require_object(value, "selection_config")
        legacy = set(raw).intersection(
            {"event_priority", "position_ratio", "max_tasks_per_project", "random_seed"}
        )
        if legacy:
            raise TaskGoldError(
                "legacy Task sampler fields are no longer supported: "
                + ", ".join(sorted(legacy))
            )
        unknown = set(raw).difference(
            {
                "candidate_event_types",
                "include_introduce_candidates",
                "include_execution_only_tasks",
                "allowed_rq_targets",
                "max_selected_targets",
                "model",
                "reasoning_effort",
                "max_concurrent_requests",
                "retries",
                "timeout_seconds",
                "max_reason_length",
            }
        )
        if unknown:
            raise TaskGoldError(
                "selection_config has unsupported fields: "
                + ", ".join(sorted(unknown))
            )

        candidate_types = raw.get("candidate_event_types", sorted(CANDIDATE_EVENT_TYPES))
        if not isinstance(candidate_types, list) or not candidate_types:
            raise TaskGoldError(
                "selection_config.candidate_event_types must be a non-empty array"
            )
        if any(not isinstance(item, str) or item not in ALL_STAGE1_EVENT_TYPES for item in candidate_types):
            raise TaskGoldError(
                "selection_config.candidate_event_types contains an unsupported Event type"
            )
        if len(set(candidate_types)) != len(candidate_types):
            raise TaskGoldError(
                "selection_config.candidate_event_types must not contain duplicates"
            )
        allowed_rqs = raw.get("allowed_rq_targets", list(DEFAULT_ALLOWED_RQ_TARGETS))
        if (
            not isinstance(allowed_rqs, list)
            or not allowed_rqs
            or any(not isinstance(item, str) or not item for item in allowed_rqs)
            or len(set(allowed_rqs)) != len(allowed_rqs)
        ):
            raise TaskGoldError(
                "selection_config.allowed_rq_targets must be a non-empty unique string array"
            )
        bool_fields = {
            "include_introduce_candidates": raw.get("include_introduce_candidates", True),
            "include_execution_only_tasks": raw.get("include_execution_only_tasks", False),
        }
        for name, value_item in bool_fields.items():
            if not isinstance(value_item, bool):
                raise TaskGoldError(f"selection_config.{name} must be a boolean")
        maximum = raw.get("max_selected_targets")
        if maximum is not None and (
            isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1
        ):
            raise TaskGoldError(
                "selection_config.max_selected_targets must be a positive integer or null"
            )
        model = raw.get("model", "gpt-5.6-sol")
        reasoning_effort = raw.get("reasoning_effort", "high")
        if not isinstance(model, str) or not model.strip():
            raise TaskGoldError("selection_config.model must be a non-empty string")
        if reasoning_effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise TaskGoldError(
                "selection_config.reasoning_effort must be low, medium, high, xhigh, or max"
            )
        integer_defaults = {
            "max_concurrent_requests": 4,
            "retries": 3,
            "max_reason_length": 2000,
        }
        integers: dict[str, int] = {}
        for name, default in integer_defaults.items():
            item = raw.get(name, default)
            minimum = 0 if name == "retries" else 1
            if isinstance(item, bool) or not isinstance(item, int) or item < minimum:
                raise TaskGoldError(
                    f"selection_config.{name} must be an integer >= {minimum}"
                )
            integers[name] = item
        timeout = raw.get("timeout_seconds", 900.0)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise TaskGoldError(
                "selection_config.timeout_seconds must be a positive finite number"
            )
        return cls(
            candidate_event_types=tuple(candidate_types),
            include_introduce_candidates=bool_fields["include_introduce_candidates"],
            include_execution_only_tasks=bool_fields["include_execution_only_tasks"],
            allowed_rq_targets=tuple(allowed_rqs),
            max_selected_targets=maximum,
            model=model.strip(),
            reasoning_effort=reasoning_effort,
            max_concurrent_requests=integers["max_concurrent_requests"],
            retries=integers["retries"],
            timeout_seconds=float(timeout),
            max_reason_length=integers["max_reason_length"],
        )


def load_selection_config(path: str | Path) -> TargetSelectionConfig:
    """Load and validate target-selection configuration from JSON."""
    config_path = Path(path)
    try:
        value = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaskGoldError(
            f"cannot load Task selection config {config_path}: {exc}"
        ) from exc
    return TargetSelectionConfig.from_mapping(value)


class LLMClientProtocol(Protocol):
    """The subset of the repository API client used by target selection."""

    async def call(
        self,
        *,
        project_id: str,
        run_mode: str,
        messages: list[dict[str, str]],
        target_requirement: str | None = None,
        validator: Callable[[dict[str, Any]], None] | None = None,
        failed_response_redactor: Callable[[str], str] | None = None,
    ) -> dict[str, Any]: ...


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
    """Fallback chronology for callers that do not provide a message catalog.

    The new selection pipeline always supplies ``normalized_project.json`` and
    therefore supports opaque IDs.  Numeric comparison remains available for
    standalone provenance and legacy graph validation calls.
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


def _project_id_from_annotation(annotation: dict[str, Any]) -> str:
    project = annotation.get("project")
    value = project.get("project_id") if isinstance(project, dict) else annotation.get("project_id")
    if value is None or isinstance(value, (dict, list, bool)) or not str(value):
        raise TaskGoldError("Stage 1 annotation has no valid project_id")
    return str(value)


def _stable_unique(values: Iterable[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = _id_key(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _MessageIndex:
    """Ordered, type-sensitive index over ``normalized_project.messages``."""

    def __init__(self, normalized_project: dict[str, Any]) -> None:
        normalized_project = _require_object(normalized_project, "normalized_project")
        project_id = normalized_project.get("project_id")
        if project_id is None or isinstance(project_id, (dict, list, bool)):
            raise TaskGoldError("normalized_project.project_id must be a scalar value")
        self.project_id = str(project_id)
        if not self.project_id:
            raise TaskGoldError("normalized_project.project_id must not be empty")
        rows = _require_array(
            normalized_project.get("messages"), "normalized_project.messages"
        )
        self.messages: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        self.positions: dict[str, int] = {}
        seen_original_indexes: set[int] = set()
        previous_original_index: int | None = None
        for position, raw_message in enumerate(rows):
            message = _require_object(
                raw_message, f"normalized_project.messages[{position}]"
            )
            if "message_id" not in message:
                raise TaskGoldError(
                    f"normalized_project.messages[{position}].message_id is required"
                )
            if not isinstance(message.get("speaker"), str):
                raise TaskGoldError(
                    f"normalized_project.messages[{position}].speaker must be a string"
                )
            if not isinstance(message.get("text"), str):
                raise TaskGoldError(
                    f"normalized_project.messages[{position}].text must be a string"
                )
            original_index = message.get("original_index")
            if isinstance(original_index, bool) or not isinstance(original_index, int):
                raise TaskGoldError(
                    f"normalized_project.messages[{position}].original_index must be an integer"
                )
            if original_index in seen_original_indexes:
                raise TaskGoldError(f"duplicate original_index: {original_index}")
            if (
                previous_original_index is not None
                and original_index <= previous_original_index
            ):
                raise TaskGoldError(
                    "normalized_project.messages must be in increasing original_index order"
                )
            previous_original_index = original_index
            seen_original_indexes.add(original_index)
            key = _id_key(message["message_id"])
            if key in self.by_key:
                raise TaskGoldError(f"duplicate message_id: {message['message_id']!r}")
            canonical = deepcopy(message)
            self.messages.append(canonical)
            self.by_key[key] = canonical
            self.positions[key] = position

    def position(self, message_id: Any) -> int:
        key = _id_key(message_id)
        if key not in self.positions:
            raise TaskGoldError(
                f"message_id {message_id!r} is absent from normalized_project"
            )
        return self.positions[key]

    def message(self, message_id: Any) -> dict[str, Any]:
        key = _id_key(message_id)
        if key not in self.by_key:
            raise TaskGoldError(
                f"message_id {message_id!r} is absent from normalized_project"
            )
        return self.by_key[key]

    def source_record(self, message_id: Any) -> dict[str, Any]:
        message = self.message(message_id)
        return {
            "source_message_id": message["message_id"],
            "speaker": message["speaker"],
            "text": message["text"],
        }


@dataclass(frozen=True)
class _AnnotationEventRef:
    requirement_id: str
    requirement_position: int
    event_position: int
    event: dict[str, Any]


class _AnnotationIndex:
    """Index the canonical Stage 1 annotation without replaying it."""

    def __init__(self, annotation: dict[str, Any]) -> None:
        self.annotation = _require_object(annotation, "annotation")
        self.project_id = _project_id_from_annotation(self.annotation)
        requirements = _require_array(
            self.annotation.get("requirements"), "annotation.requirements"
        )
        self.requirement_order: list[str] = []
        self.events_by_id: dict[str, _AnnotationEventRef] = {}
        self.events_by_message: dict[str, list[_AnnotationEventRef]] = {}
        self.events_by_requirement: dict[str, list[_AnnotationEventRef]] = {}
        for requirement_position, raw_requirement in enumerate(requirements):
            requirement = _require_object(
                raw_requirement, f"annotation.requirements[{requirement_position}]"
            )
            requirement_id = _require_string(
                requirement.get("requirement_id"),
                f"annotation.requirements[{requirement_position}].requirement_id",
            )
            if requirement_id in self.events_by_requirement:
                raise TaskGoldError(f"duplicate requirement_id: {requirement_id}")
            self.requirement_order.append(requirement_id)
            refs: list[_AnnotationEventRef] = []
            for event_position, raw_event in enumerate(
                _require_array(requirement.get("events"), f"{requirement_id}.events")
            ):
                event = _require_object(
                    raw_event, f"{requirement_id}.events[{event_position}]"
                )
                event_id = _require_string(
                    event.get("event_id"),
                    f"{requirement_id}.events[{event_position}].event_id",
                )
                if event_id in self.events_by_id:
                    raise TaskGoldError(f"duplicate Stage 1 event_id: {event_id}")
                event_type = _require_string(
                    event.get("event_type"), f"{event_id}.event_type"
                )
                if event_type not in ALL_STAGE1_EVENT_TYPES:
                    raise TaskGoldError(
                        f"{event_id}.event_type {event_type!r} is unsupported"
                    )
                source = _require_object(
                    event.get("source_message"), f"{event_id}.source_message"
                )
                if "message_id" not in source:
                    raise TaskGoldError(f"{event_id}.source_message.message_id is required")
                resolution_ids = event.get("resolves_ambiguity_event_ids")
                if resolution_ids is not None and (
                    not isinstance(resolution_ids, list)
                    or not resolution_ids
                    or any(not isinstance(item, str) or not item for item in resolution_ids)
                    or len(set(resolution_ids)) != len(resolution_ids)
                ):
                    raise TaskGoldError(
                        f"{event_id}.resolves_ambiguity_event_ids must be null or a non-empty unique string array"
                    )
                ref = _AnnotationEventRef(
                    requirement_id=requirement_id,
                    requirement_position=requirement_position,
                    event_position=event_position,
                    event=event,
                )
                refs.append(ref)
                self.events_by_id[event_id] = ref
                self.events_by_message.setdefault(
                    _id_key(source["message_id"]), []
                ).append(ref)
            self.events_by_requirement[requirement_id] = refs


class _GraphIndex:
    def __init__(
        self,
        graph: dict[str, Any],
        message_positions: dict[str, int] | None = None,
    ) -> None:
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
            previous_message_number: int | Decimal | None = None
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
                message_key = _id_key(message_id)
                if message_positions is not None:
                    if message_key not in message_positions:
                        raise TaskGoldError(
                            f"{event_id}.source_message_id {message_id!r} is absent from normalized_project"
                        )
                    message_number: int | Decimal = message_positions[message_key]
                else:
                    message_number = _message_number(message_id)
                if (
                    previous_message_number is not None
                    and message_number < previous_message_number
                ):
                    raise TaskGoldError(
                        f"{requirement_id} graph edges are not in message chronology"
                    )
                previous_message_number = message_number

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

        positions: dict[str, int | Decimal] = {}
        position_owner: dict[int | Decimal, str] = {}
        for message_key, message_id in self.message_ids.items():
            position = (
                message_positions[message_key]
                if message_positions is not None
                else _message_number(message_id)
            )
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
        message_key = _id_key(message_id)
        if message_key not in self.message_positions:
            raise TaskGoldError(f"message_id {message_id!r} is absent from the State Graph")
        boundary = self.message_positions[message_key]
        snapshot: list[dict[str, str]] = []
        for requirement_id in self.requirement_order:
            graph = self.graph_by_requirement[requirement_id]
            latest_state_id: str | None = None
            for edge in graph["edges"]:
                position = self.message_positions[_id_key(edge["source_message_id"])]
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

    def position(self, message_id: Any) -> int | Decimal:
        key = _id_key(message_id)
        if key not in self.message_positions:
            raise TaskGoldError(f"message_id {message_id!r} is absent from the State Graph")
        return self.message_positions[key]

    def state_before(
        self, requirement_id: str, message_id: Any
    ) -> dict[str, Any] | None:
        graph = self.graph_by_requirement.get(requirement_id)
        if graph is None:
            raise TaskGoldError(f"unknown requirement_id: {requirement_id}")
        boundary = self.position(message_id)
        latest_state_id: str | None = None
        for edge in graph["edges"]:
            position = self.position(edge["source_message_id"])
            if position < boundary:
                latest_state_id = edge["to_state_id"]
            else:
                break
        return deepcopy(self.node_by_state_id[latest_state_id]) if latest_state_id else None


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
    stage1_source: dict[str, Any],
    state_graph: dict[str, Any],
    normalized_project: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Report exact graph/Stage-1 Event provenance differences."""
    _, annotation_events = _stage1_indexes(stage1_source)
    if not annotation_events:
        raise TaskGoldError(
            "Event provenance cannot be audited from a message-only Stage 1 source"
        )
    message_positions = (
        _MessageIndex(normalized_project).positions
        if normalized_project is not None
        else None
    )
    index = _GraphIndex(state_graph, message_positions)
    annotation_requirements: dict[str, str] = {}
    if isinstance(stage1_source.get("requirements"), list):
        annotation_index = _AnnotationIndex(stage1_source)
        annotation_requirements = {
            event_id: ref.requirement_id
            for event_id, ref in annotation_index.events_by_id.items()
        }
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
        stage1_requirement = annotation_requirements.get(event_id)
        if stage1_requirement is not None and stage1_requirement != edge_ref.requirement_id:
            differences["requirement_id"] = {
                "graph": edge_ref.requirement_id,
                "stage1": stage1_requirement,
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
    for event_id in sorted(set(annotation_events).difference(index.edge_by_event_id)):
        issues.append(
            {
                "code": "STAGE1_EVENT_MISSING_FROM_GRAPH",
                "event_id": event_id,
                "requirement_id": annotation_requirements.get(event_id),
            }
        )
    return issues


def validate_selection_inputs(
    annotation: dict[str, Any],
    normalized_project: dict[str, Any],
    state_graph: dict[str, Any],
) -> None:
    """Require aligned annotation, normalized messages, and State Graph."""
    messages = _MessageIndex(normalized_project)
    annotated = _AnnotationIndex(annotation)
    graph = _GraphIndex(state_graph, messages.positions)
    if len({messages.project_id, annotated.project_id, graph.project_id}) != 1:
        raise TaskGoldError(
            "annotation, normalized_project, and State Graph have different project IDs"
        )
    issues = audit_event_provenance(annotation, state_graph, normalized_project)
    if issues:
        raise TaskGoldError(
            f"Stage 1 / State Graph provenance audit failed with {len(issues)} issue(s): "
            + json.dumps(issues[:3], ensure_ascii=False)
        )
    for event_id, ref in annotated.events_by_id.items():
        source = _require_object(ref.event.get("source_message"), f"{event_id}.source_message")
        message = messages.message(source["message_id"])
        for field_name in ("speaker", "text"):
            if source.get(field_name) != message.get(field_name):
                raise TaskGoldError(
                    f"{event_id}.source_message.{field_name} differs from normalized_project"
                )
        supporting = ref.event.get("supporting_message_ids") or []
        if not isinstance(supporting, list):
            raise TaskGoldError(f"{event_id}.supporting_message_ids must be an array or null")
        for supporting_id in supporting:
            messages.message(supporting_id)


def _candidate_id(project_id: str, message_id: Any, used: set[str]) -> str:
    readable = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(message_id)).strip("._") or "MESSAGE"
    base = f"{project_id}_CANDIDATE_MSG_{readable}"
    candidate_id = base
    if candidate_id in used:
        candidate_id = f"{base}_{hashlib.sha256(_id_key(message_id).encode('utf-8')).hexdigest()[:8]}"
    if candidate_id in used:
        raise TaskGoldError(f"cannot derive a unique candidate_id for {message_id!r}")
    used.add(candidate_id)
    return candidate_id


def _input_fingerprint(
    annotation: dict[str, Any],
    normalized_project: dict[str, Any],
    state_graph: dict[str, Any],
) -> dict[str, str]:
    return {
        "annotation_sha256": _sha256_json(annotation),
        "normalized_project_sha256": _sha256_json(normalized_project),
        "state_graph_sha256": _sha256_json(state_graph),
    }


def generate_candidate_tasks(
    annotation: dict[str, Any],
    normalized_project: dict[str, Any],
    state_graph: dict[str, Any],
    config: TargetSelectionConfig | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate high-recall, message-grouped target-time Candidates."""
    selection_config = (
        config
        if isinstance(config, TargetSelectionConfig)
        else TargetSelectionConfig.from_mapping(config)
    )
    validate_selection_inputs(annotation, normalized_project, state_graph)
    messages = _MessageIndex(normalized_project)
    annotated = _AnnotationIndex(annotation)
    graph = _GraphIndex(state_graph, messages.positions)
    configured_types = set(selection_config.candidate_event_types)
    used_candidate_ids: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for message in messages.messages:
        message_id = message["message_id"]
        message_key = _id_key(message_id)
        if message_key not in graph.edges_by_message or message["speaker"] != "client":
            continue
        edge_refs = sorted(
            graph.edges_by_message[message_key],
            key=lambda item: (item.graph_position, item.edge_position),
        )
        event_ids = [item.edge["event_id"] for item in edge_refs]
        event_refs = [annotated.events_by_id[event_id] for event_id in event_ids]
        event_types = _stable_unique(ref.event["event_type"] for ref in event_refs)
        requirement_ids = _stable_unique(item.requirement_id for item in edge_refs)
        has_resolution = any(
            bool(ref.event.get("resolves_ambiguity_event_ids")) for ref in event_refs
        )
        introduce_only = all(event_type == "INTRODUCE" for event_type in event_types)
        any_prior_graph_state = any(
            position < messages.position(message_id)
            for position in graph.message_positions.values()
        )
        eligible = bool(set(event_types).intersection(configured_types)) or has_resolution
        if (
            not eligible
            and selection_config.include_introduce_candidates
            and "INTRODUCE" in event_types
        ):
            eligible = (
                len(requirement_ids) > 1
                or any(event_type != "INTRODUCE" for event_type in event_types)
                or any_prior_graph_state
            )
        if (
            not eligible
            and selection_config.include_execution_only_tasks
            and set(event_types).issubset(EXECUTION_EVENT_TYPES)
        ):
            eligible = True
        if not eligible:
            continue
        coverage_tags = [
            event_type
            for event_type in event_types
            if event_type in CANDIDATE_EVENT_TYPES or event_type == "INTRODUCE"
        ]
        if has_resolution:
            coverage_tags.append("AMBIGUITY_RESOLUTION")
        coverage_tags.append(
            "MULTI_REQUIREMENT" if len(requirement_ids) > 1 else "SINGLE_REQUIREMENT"
        )
        position = messages.position(message_id)
        candidates.append(
            {
                "candidate_id": _candidate_id(
                    graph.project_id, message_id, used_candidate_ids
                ),
                "message_id": message_id,
                "conversation_turn_index": position + 1,
                "history_turn_count": position,
                "speaker": message["speaker"],
                "text": message["text"],
                "event_ids": event_ids,
                "requirement_ids": requirement_ids,
                "event_types": event_types,
                "coverage_tags": _stable_unique(coverage_tags),
                "introduce_only": introduce_only,
            }
        )
    return {
        "schema_version": TARGET_SELECTION_SCHEMA_VERSION,
        "project_id": graph.project_id,
        "input_fingerprint": _input_fingerprint(
            annotation, normalized_project, state_graph
        ),
        "candidates": candidates,
    }


def _event_history_record(ref: _AnnotationEventRef) -> dict[str, Any]:
    event = ref.event
    return {
        "event_id": event["event_id"],
        "event_type": event["event_type"],
        "source_message_id": event["source_message"]["message_id"],
        "supporting_message_ids": deepcopy(event.get("supporting_message_ids") or []),
        "value_updates": deepcopy(event.get("value_updates")),
        "value_removals": deepcopy(event.get("value_removals")),
        "scope_updates": deepcopy(event.get("scope_updates")),
        "ambiguity": deepcopy(event.get("ambiguity")),
        "execution": deepcopy(event.get("execution")),
        "resolves_ambiguity_event_ids": deepcopy(
            event.get("resolves_ambiguity_event_ids")
        ),
    }


def build_candidate_contexts(
    candidates: dict[str, Any],
    annotation: dict[str, Any],
    normalized_project: dict[str, Any],
    state_graph: dict[str, Any],
) -> dict[str, Any]:
    """Construct relevant history strictly before each Candidate Task."""
    validate_selection_inputs(annotation, normalized_project, state_graph)
    messages = _MessageIndex(normalized_project)
    annotated = _AnnotationIndex(annotation)
    graph = _GraphIndex(state_graph, messages.positions)
    if str(candidates.get("project_id")) != graph.project_id:
        raise TaskGoldError("candidate_tasks.project_id does not match inputs")
    candidate_rows = _require_array(candidates.get("candidates"), "candidate_tasks.candidates")
    contexts: list[dict[str, Any]] = []
    seen_candidates: set[str] = set()
    for candidate_position, raw_candidate in enumerate(candidate_rows):
        candidate = _require_object(raw_candidate, f"candidates[{candidate_position}]")
        candidate_id = _require_string(
            candidate.get("candidate_id"), f"candidates[{candidate_position}].candidate_id"
        )
        if candidate_id in seen_candidates:
            raise TaskGoldError(f"duplicate candidate_id: {candidate_id}")
        seen_candidates.add(candidate_id)
        message_id = candidate.get("message_id")
        boundary = messages.position(message_id)
        if candidate.get("conversation_turn_index") != boundary + 1:
            raise TaskGoldError(f"{candidate_id} has an invalid conversation_turn_index")
        if candidate.get("history_turn_count") != boundary:
            raise TaskGoldError(f"{candidate_id} has an invalid history_turn_count")
        event_ids = _require_array(candidate.get("event_ids"), f"{candidate_id}.event_ids")
        requirement_ids = _require_array(
            candidate.get("requirement_ids"), f"{candidate_id}.requirement_ids"
        )
        triggered_events: list[dict[str, Any]] = []
        for event_id in event_ids:
            ref = annotated.events_by_id.get(str(event_id))
            if ref is None:
                raise TaskGoldError(f"{candidate_id} references unknown Event {event_id!r}")
            row = _event_history_record(ref)
            row["requirement_id"] = ref.requirement_id
            triggered_events.append(row)
        pre_states = [
            {
                "requirement_id": requirement_id,
                "state": graph.state_before(requirement_id, message_id),
            }
            for requirement_id in requirement_ids
        ]
        requirement_history: list[dict[str, Any]] = []
        evidence_ids: list[Any] = []
        for requirement_id in requirement_ids:
            history_events: list[dict[str, Any]] = []
            for ref in annotated.events_by_requirement.get(requirement_id, []):
                source_id = ref.event["source_message"]["message_id"]
                source_position = messages.position(source_id)
                if source_position >= boundary:
                    continue
                history_events.append(_event_history_record(ref))
                evidence_ids.append(source_id)
                for supporting_id in ref.event.get("supporting_message_ids") or []:
                    if messages.position(supporting_id) >= boundary:
                        raise TaskGoldError(
                            f"{ref.event['event_id']} leaks current/future supporting message "
                            f"{supporting_id!r} into {candidate_id}"
                        )
                    evidence_ids.append(supporting_id)
            requirement_history.append(
                {"requirement_id": requirement_id, "events": history_events}
            )
        evidence_messages: list[dict[str, Any]] = []
        for evidence_id in sorted(
            _stable_unique(evidence_ids), key=messages.position
        ):
            evidence = messages.message(evidence_id)
            evidence_messages.append(
                {
                    "message_id": evidence["message_id"],
                    "conversation_turn_index": messages.position(evidence_id) + 1,
                    "speaker": evidence["speaker"],
                    "text": evidence["text"],
                    "created_ts": evidence.get("created_ts"),
                    "original_index": evidence["original_index"],
                }
            )
        contexts.append(
            {
                "candidate_id": candidate_id,
                "message_id": message_id,
                "conversation_turn_index": boundary + 1,
                "history_turn_count": boundary,
                "triggered_events": triggered_events,
                "pre_task_requirement_states": pre_states,
                "requirement_history": requirement_history,
                "historical_evidence_messages": evidence_messages,
            }
        )
    return {
        "schema_version": TARGET_SELECTION_SCHEMA_VERSION,
        "project_id": graph.project_id,
        "input_fingerprint": deepcopy(candidates.get("input_fingerprint")),
        "contexts": contexts,
    }


def build_candidate_packets(
    candidates: dict[str, Any], contexts: dict[str, Any]
) -> list[dict[str, Any]]:
    """Join Candidate metadata and history context into one packet per call."""
    if str(candidates.get("project_id")) != str(contexts.get("project_id")):
        raise TaskGoldError("candidate_tasks and candidate_contexts have different project IDs")
    context_rows = _require_array(contexts.get("contexts"), "candidate_contexts.contexts")
    context_by_id: dict[str, dict[str, Any]] = {}
    for raw_context in context_rows:
        context = _require_object(raw_context, "candidate context")
        candidate_id = _require_string(
            context.get("candidate_id"), "context.candidate_id"
        )
        if candidate_id in context_by_id:
            raise TaskGoldError(f"duplicate Candidate Context for {candidate_id}")
        context_by_id[candidate_id] = context
    packets: list[dict[str, Any]] = []
    for raw_candidate in _require_array(candidates.get("candidates"), "candidate_tasks.candidates"):
        candidate = _require_object(raw_candidate, "candidate")
        candidate_id = _require_string(candidate.get("candidate_id"), "candidate.candidate_id")
        context = context_by_id.get(candidate_id)
        if context is None:
            raise TaskGoldError(f"missing Candidate Context for {candidate_id}")
        packets.append(
            {
                "schema_version": PACKET_SCHEMA_VERSION,
                "project_id": str(candidates.get("project_id")),
                "candidate_id": candidate_id,
                "candidate_task": {
                    key: deepcopy(candidate[key])
                    for key in (
                        "message_id",
                        "conversation_turn_index",
                        "history_turn_count",
                        "speaker",
                        "text",
                    )
                },
                "triggered_events": deepcopy(context["triggered_events"]),
                "pre_task_requirement_states": deepcopy(
                    context["pre_task_requirement_states"]
                ),
                "requirement_history": deepcopy(context["requirement_history"]),
                "historical_evidence_messages": deepcopy(
                    context["historical_evidence_messages"]
                ),
            }
        )
    if set(context_by_id) != {packet["candidate_id"] for packet in packets}:
        raise TaskGoldError("candidate_contexts contains unknown or duplicate Candidates")
    return packets


def _evaluation_fields() -> set[str]:
    return {
        "candidate_id",
        "message_id",
        "valid_task",
        *EVALUATION_DIMENSIONS,
        "history_sensitive",
        "recommended",
        "primary_rq_targets",
        "reason",
    }


def _evaluation_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(record.get(key)) for key in _evaluation_fields()}


def validate_llm_evaluation(
    evaluation: dict[str, Any],
    packet: dict[str, Any],
    config: TargetSelectionConfig | dict[str, Any] | None = None,
) -> None:
    """Strictly validate one model response against its Candidate Packet."""
    selection_config = (
        config
        if isinstance(config, TargetSelectionConfig)
        else TargetSelectionConfig.from_mapping(config)
    )
    evaluation = _require_object(evaluation, "llm_evaluation")
    if set(evaluation) != _evaluation_fields():
        missing = sorted(_evaluation_fields().difference(evaluation))
        extra = sorted(set(evaluation).difference(_evaluation_fields()))
        raise TaskGoldError(
            f"LLM evaluation fields do not match the schema; missing={missing}, extra={extra}"
        )
    if evaluation["candidate_id"] != packet.get("candidate_id"):
        raise TaskGoldError("LLM evaluation candidate_id does not match the packet")
    expected_message_id = _require_object(
        packet.get("candidate_task"), "packet.candidate_task"
    ).get("message_id")
    if _id_key(evaluation["message_id"]) != _id_key(expected_message_id):
        raise TaskGoldError("LLM evaluation message_id does not match the packet")
    for name in ("valid_task", "history_sensitive", "recommended"):
        if not isinstance(evaluation[name], bool):
            raise TaskGoldError(f"LLM evaluation {name} must be a boolean")
    for name in EVALUATION_DIMENSIONS:
        if evaluation[name] not in EVALUATION_LEVELS:
            raise TaskGoldError(
                f"LLM evaluation {name} must be LOW, MEDIUM, or HIGH"
            )
    rq_targets = evaluation["primary_rq_targets"]
    if (
        not isinstance(rq_targets, list)
        or len(set(rq_targets)) != len(rq_targets)
        or any(item not in selection_config.allowed_rq_targets for item in rq_targets)
    ):
        raise TaskGoldError(
            "LLM evaluation primary_rq_targets must be unique configured RQ IDs"
        )
    reason = evaluation["reason"]
    if (
        not isinstance(reason, str)
        or not reason.strip()
        or len(reason) > selection_config.max_reason_length
    ):
        raise TaskGoldError(
            "LLM evaluation reason must be non-empty and within max_reason_length"
        )
    if evaluation["recommended"] and not (
        evaluation["valid_task"] and evaluation["history_sensitive"]
    ):
        raise TaskGoldError(
            "recommended=true requires valid_task=true and history_sensitive=true"
        )


def evaluation_fingerprint(
    packet: dict[str, Any], prompt: str, config: TargetSelectionConfig
) -> dict[str, str]:
    return {
        "packet_sha256": _sha256_json(packet),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "model": config.model,
        "reasoning_effort": config.reasoning_effort,
    }


async def evaluate_candidate_packets(
    packets: list[dict[str, Any]],
    *,
    api: LLMClientProtocol,
    prompt: str,
    config: TargetSelectionConfig,
    existing_evaluations: Iterable[dict[str, Any]] = (),
    force: bool = False,
    on_evaluation: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate packets concurrently, reusing only exact validated fingerprints."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise TaskGoldError("target-selection prompt must be non-empty")
    existing_by_candidate: dict[str, dict[str, Any]] = {}
    for row in existing_evaluations:
        if isinstance(row, dict) and isinstance(row.get("candidate_id"), str):
            existing_by_candidate[row["candidate_id"]] = row
    results: dict[str, dict[str, Any]] = {}
    pending: list[asyncio.Task[dict[str, Any]]] = []

    async def evaluate_one(packet: dict[str, Any]) -> dict[str, Any]:
        fingerprint = evaluation_fingerprint(packet, prompt, config)

        def validator(value: dict[str, Any]) -> None:
            validate_llm_evaluation(value, packet, config)

        response = await api.call(
            project_id=str(packet["project_id"]),
            run_mode="TARGET_TIME_EVALUATION",
            target_requirement=str(packet["candidate_id"]),
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(packet, ensure_ascii=False, sort_keys=True),
                },
            ],
            validator=validator,
        )
        record = deepcopy(response)
        record["_evaluation_metadata"] = fingerprint
        return record

    seen_packet_ids: set[str] = set()
    for packet in packets:
        candidate_id = _require_string(packet.get("candidate_id"), "packet.candidate_id")
        if candidate_id in seen_packet_ids:
            raise TaskGoldError(f"duplicate packet candidate_id: {candidate_id}")
        seen_packet_ids.add(candidate_id)
        fingerprint = evaluation_fingerprint(packet, prompt, config)
        cached = existing_by_candidate.get(candidate_id)
        if not force and cached is not None and cached.get("_evaluation_metadata") == fingerprint:
            payload = _evaluation_payload(cached)
            validate_llm_evaluation(payload, packet, config)
            results[candidate_id] = deepcopy(cached)
        else:
            pending.append(asyncio.create_task(evaluate_one(packet)))
    try:
        for task in asyncio.as_completed(pending):
            record = await task
            candidate_id = _require_string(
                record.get("candidate_id"), "evaluation.candidate_id"
            )
            results[candidate_id] = record
            if on_evaluation is not None:
                on_evaluation(deepcopy(record))
    except BaseException:
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        raise
    if set(results) != seen_packet_ids:
        missing = sorted(seen_packet_ids.difference(results))
        raise TaskGoldError(f"missing LLM evaluations for Candidates: {missing}")
    return [results[packet["candidate_id"]] for packet in packets]


def select_recommended_candidates(
    candidates: dict[str, Any],
    evaluations: Iterable[dict[str, Any]],
    config: TargetSelectionConfig,
) -> dict[str, Any]:
    """Keep only valid, recommended, history-sensitive model evaluations."""
    candidate_rows = _require_array(candidates.get("candidates"), "candidate_tasks.candidates")
    evaluation_by_id: dict[str, dict[str, Any]] = {}
    for evaluation in evaluations:
        candidate_id = _require_string(
            evaluation.get("candidate_id"), "evaluation.candidate_id"
        )
        if candidate_id in evaluation_by_id:
            raise TaskGoldError(f"duplicate LLM evaluation for {candidate_id}")
        evaluation_by_id[candidate_id] = evaluation
    recommended: list[dict[str, Any]] = []
    for candidate in candidate_rows:
        candidate_id = _require_string(candidate.get("candidate_id"), "candidate.candidate_id")
        evaluation = evaluation_by_id.get(candidate_id)
        if evaluation is None:
            raise TaskGoldError(f"missing LLM evaluation for {candidate_id}")
        packet_stub = {
            "candidate_id": candidate_id,
            "candidate_task": {"message_id": candidate.get("message_id")},
        }
        payload = _evaluation_payload(evaluation)
        validate_llm_evaluation(payload, packet_stub, config)
        if payload["valid_task"] and payload["recommended"] and payload["history_sensitive"]:
            row = deepcopy(candidate)
            row["llm_evaluation"] = payload
            row["evaluation_metadata"] = deepcopy(
                evaluation.get("_evaluation_metadata")
            )
            recommended.append(row)
    unknown = set(evaluation_by_id).difference(
        candidate["candidate_id"] for candidate in candidate_rows
    )
    if unknown:
        raise TaskGoldError(f"LLM evaluations reference unknown Candidates: {sorted(unknown)}")
    return {
        "schema_version": TARGET_SELECTION_SCHEMA_VERSION,
        "project_id": str(candidates.get("project_id")),
        "input_fingerprint": deepcopy(candidates.get("input_fingerprint")),
        "recommended_candidates": recommended,
    }


def calculate_ai_selection_score(evaluation: dict[str, Any]) -> int:
    """Convert the five LOW/MEDIUM/HIGH judgments into a stable 0-10 score."""
    score = 0
    for name in EVALUATION_DIMENSIONS:
        level = evaluation.get(name)
        if level not in EVALUATION_LEVEL_RANK:
            raise TaskGoldError(
                f"LLM evaluation {name} must be LOW, MEDIUM, or HIGH"
            )
        score += EVALUATION_LEVEL_RANK[level]
    return score


def _validate_ai_score_threshold(score_threshold: int) -> None:
    if (
        isinstance(score_threshold, bool)
        or not isinstance(score_threshold, int)
        or not 0 <= score_threshold <= MAX_AI_SELECTION_SCORE
    ):
        raise TaskGoldError(
            f"AI score threshold must be an integer from 0 to {MAX_AI_SELECTION_SCORE}"
        )


def select_ai_candidates_by_score(
    candidates: dict[str, Any],
    evaluations: Iterable[dict[str, Any]],
    config: TargetSelectionConfig,
    score_threshold: int,
) -> dict[str, Any]:
    """Select every AI-recommended Candidate whose derived score meets the cutoff."""
    _validate_ai_score_threshold(score_threshold)
    candidate_rows = _require_array(
        candidates.get("candidates"), "candidate_tasks.candidates"
    )
    evaluation_by_id: dict[str, dict[str, Any]] = {}
    for evaluation in evaluations:
        candidate_id = _require_string(
            evaluation.get("candidate_id"), "evaluation.candidate_id"
        )
        if candidate_id in evaluation_by_id:
            raise TaskGoldError(f"duplicate LLM evaluation for {candidate_id}")
        evaluation_by_id[candidate_id] = evaluation

    selected: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    for candidate in candidate_rows:
        candidate_id = _require_string(
            candidate.get("candidate_id"), "candidate.candidate_id"
        )
        evaluation = evaluation_by_id.get(candidate_id)
        if evaluation is None:
            raise TaskGoldError(f"missing LLM evaluation for {candidate_id}")
        packet_stub = {
            "candidate_id": candidate_id,
            "candidate_task": {"message_id": candidate.get("message_id")},
        }
        payload = _evaluation_payload(evaluation)
        validate_llm_evaluation(payload, packet_stub, config)
        score = calculate_ai_selection_score(payload)
        eligible = bool(
            payload["valid_task"]
            and payload["history_sensitive"]
            and payload["recommended"]
        )
        accepted = eligible and score >= score_threshold
        trace.append(
            {
                "candidate_id": candidate_id,
                "ai_selection_score": score,
                "score_threshold": score_threshold,
                "eligible": eligible,
                "selected": accepted,
                "reason": (
                    "AI recommendation meets score threshold"
                    if accepted
                    else (
                        "AI did not mark the Candidate valid, history-sensitive, and recommended"
                        if not eligible
                        else "AI recommendation is below score threshold"
                    )
                ),
            }
        )
        if accepted:
            row = deepcopy(candidate)
            row["llm_evaluation"] = payload
            row["evaluation_metadata"] = deepcopy(
                evaluation.get("_evaluation_metadata")
            )
            row["ai_selection_score"] = score
            row["score_threshold"] = score_threshold
            selected.append(row)
    unknown = set(evaluation_by_id).difference(
        candidate["candidate_id"] for candidate in candidate_rows
    )
    if unknown:
        raise TaskGoldError(
            f"LLM evaluations reference unknown Candidates: {sorted(unknown)}"
        )
    selected.sort(key=lambda item: item["conversation_turn_index"])
    return {
        "schema_version": TARGET_SELECTION_SCHEMA_VERSION,
        "project_id": str(candidates.get("project_id")),
        "input_fingerprint": deepcopy(candidates.get("input_fingerprint")),
        "selection_mode": "AI_SCORE_THRESHOLD",
        "score_scale": deepcopy(EVALUATION_LEVEL_RANK),
        "score_threshold": score_threshold,
        "maximum_score": MAX_AI_SELECTION_SCORE,
        "selected_candidates": selected,
        "selection_trace": trace,
    }


def _coverage_tags(candidate: dict[str, Any]) -> set[str]:
    evaluation = candidate["llm_evaluation"]
    tags = {str(tag) for tag in candidate.get("coverage_tags", [])}
    tags.update(f"RQ:{rq}" for rq in evaluation.get("primary_rq_targets", []))
    if evaluation.get("history_sensitive"):
        tags.add("HISTORY_SENSITIVE")
    return tags


def _semantic_rank(candidate: dict[str, Any]) -> tuple[int, ...]:
    evaluation = candidate["llm_evaluation"]
    return tuple(EVALUATION_LEVEL_RANK[evaluation[name]] for name in EVALUATION_DIMENSIONS)


def _challenge_fingerprint(
    candidate: dict[str, Any], context: dict[str, Any]
) -> str:
    event_tags = sorted(
        tag
        for tag in candidate.get("coverage_tags", [])
        if tag not in {"SINGLE_REQUIREMENT", "MULTI_REQUIREMENT"}
    )
    pre_pattern: list[dict[str, Any]] = []
    for row in context.get("pre_task_requirement_states", []):
        state = row.get("state")
        ambiguity = state.get("ambiguity") if isinstance(state, dict) else None
        pre_pattern.append(
            {
                "requirement_id": row.get("requirement_id"),
                "lifecycle_status": (
                    state.get("lifecycle_status") if isinstance(state, dict) else None
                ),
                "has_open_ambiguity": bool(ambiguity),
            }
        )
    return _sha256_json(
        {
            "affected_requirement_ids": sorted(candidate.get("requirement_ids", [])),
            "event_tags": event_tags,
            "pre_task_pattern": sorted(
                pre_pattern, key=lambda item: str(item["requirement_id"])
            ),
        }
    )


def _representative_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -len(_coverage_tags(candidate)),
        *(-value for value in _semantic_rank(candidate)),
        candidate["candidate_id"],
    )


def apply_coverage_and_deduplication(
    recommended_candidates: dict[str, Any],
    contexts: dict[str, Any],
    config: TargetSelectionConfig,
) -> dict[str, Any]:
    """Deterministically deduplicate challenges and optionally apply set cover."""
    if str(recommended_candidates.get("project_id")) != str(contexts.get("project_id")):
        raise TaskGoldError("recommended_candidates and contexts have different project IDs")
    context_by_id = {
        row["candidate_id"]: row
        for row in _require_array(contexts.get("contexts"), "candidate_contexts.contexts")
    }
    groups: dict[str, list[dict[str, Any]]] = {}
    for candidate in _require_array(
        recommended_candidates.get("recommended_candidates"),
        "recommended_candidates.recommended_candidates",
    ):
        candidate_id = candidate.get("candidate_id")
        if candidate_id not in context_by_id:
            raise TaskGoldError(f"missing context for recommended Candidate {candidate_id}")
        fingerprint = _challenge_fingerprint(candidate, context_by_id[candidate_id])
        groups.setdefault(fingerprint, []).append(candidate)
    representatives: list[dict[str, Any]] = []
    deduplication: list[dict[str, Any]] = []
    for fingerprint in sorted(groups):
        group = sorted(groups[fingerprint], key=_representative_key)
        kept = deepcopy(group[0])
        kept["challenge_fingerprint"] = fingerprint
        kept["selection_coverage_tags"] = sorted(_coverage_tags(kept))
        representatives.append(kept)
        deduplication.append(
            {
                "challenge_fingerprint": fingerprint,
                "kept_candidate_id": kept["candidate_id"],
                "deduplicated_candidate_ids": [
                    candidate["candidate_id"] for candidate in group[1:]
                ],
            }
        )
    maximum = config.max_selected_targets
    selected: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    if maximum is None or maximum >= len(representatives):
        selected = representatives
        for candidate in representatives:
            trace.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "coverage_gain": candidate["selection_coverage_tags"],
                    "reason": "retained after exact challenge deduplication",
                }
            )
    else:
        remaining = list(representatives)
        covered: set[str] = set()
        while remaining and len(selected) < maximum:
            ranked = sorted(
                remaining,
                key=lambda candidate: (
                    -len(_coverage_tags(candidate).difference(covered)),
                    *(-value for value in _semantic_rank(candidate)),
                    candidate["candidate_id"],
                ),
            )
            chosen = ranked[0]
            gain = sorted(_coverage_tags(chosen).difference(covered))
            selected.append(chosen)
            covered.update(_coverage_tags(chosen))
            remaining.remove(chosen)
            trace.append(
                {
                    "candidate_id": chosen["candidate_id"],
                    "coverage_gain": gain,
                    "reason": "greedy set-cover selection",
                }
            )
    selected.sort(key=lambda item: item["conversation_turn_index"])
    return {
        "schema_version": TARGET_SELECTION_SCHEMA_VERSION,
        "project_id": str(recommended_candidates.get("project_id")),
        "input_fingerprint": deepcopy(recommended_candidates.get("input_fingerprint")),
        "selected_candidates": selected,
        "deduplication": deduplication,
        "selection_trace": trace,
    }


def finalize_ai_selected_targets(
    ai_selection: dict[str, Any],
    candidate_tasks: dict[str, Any],
    evaluations: Iterable[dict[str, Any]],
    config: TargetSelectionConfig,
) -> dict[str, Any]:
    """Finalize every eligible above-threshold AI choice without human review."""
    project_id = str(ai_selection.get("project_id"))
    if project_id != str(candidate_tasks.get("project_id")):
        raise TaskGoldError("AI selection and candidate_tasks have different project IDs")
    if ai_selection.get("selection_mode") != "AI_SCORE_THRESHOLD":
        raise TaskGoldError("AI selection has an invalid selection_mode")
    score_threshold = ai_selection.get("score_threshold")
    _validate_ai_score_threshold(score_threshold)

    candidates: dict[str, dict[str, Any]] = {}
    for raw_candidate in _require_array(
        candidate_tasks.get("candidates"), "candidate_tasks.candidates"
    ):
        candidate = _require_object(raw_candidate, "candidate")
        candidate_id = _require_string(
            candidate.get("candidate_id"), "candidate.candidate_id"
        )
        if candidate_id in candidates:
            raise TaskGoldError(f"duplicate Candidate {candidate_id}")
        candidates[candidate_id] = candidate

    evaluations_by_id: dict[str, dict[str, Any]] = {}
    for raw_evaluation in evaluations:
        evaluation = _require_object(raw_evaluation, "LLM evaluation")
        candidate_id = _require_string(
            evaluation.get("candidate_id"), "evaluation.candidate_id"
        )
        if candidate_id in evaluations_by_id:
            raise TaskGoldError(f"duplicate LLM evaluation for {candidate_id}")
        evaluations_by_id[candidate_id] = evaluation
    if set(evaluations_by_id) != set(candidates):
        missing = sorted(set(candidates).difference(evaluations_by_id))
        unknown = sorted(set(evaluations_by_id).difference(candidates))
        raise TaskGoldError(
            f"Candidate/evaluation IDs do not match; missing={missing}, unknown={unknown}"
        )

    selected_rows = _require_array(
        ai_selection.get("selected_candidates"),
        "AI selection.selected_candidates",
    )
    selected_by_id: dict[str, dict[str, Any]] = {}
    for raw_selected in selected_rows:
        selected = _require_object(raw_selected, "AI-selected Candidate")
        candidate_id = _require_string(
            selected.get("candidate_id"), "AI-selected Candidate.candidate_id"
        )
        if candidate_id in selected_by_id:
            raise TaskGoldError(f"duplicate AI-selected Candidate {candidate_id}")
        selected_by_id[candidate_id] = selected

    expected_rows: list[tuple[dict[str, Any], dict[str, Any], int]] = []
    for candidate_id, candidate in candidates.items():
        payload = _evaluation_payload(evaluations_by_id[candidate_id])
        packet_stub = {
            "candidate_id": candidate_id,
            "candidate_task": {"message_id": candidate.get("message_id")},
        }
        validate_llm_evaluation(payload, packet_stub, config)
        score = calculate_ai_selection_score(payload)
        if (
            payload["valid_task"]
            and payload["history_sensitive"]
            and payload["recommended"]
            and score >= score_threshold
        ):
            expected_rows.append((candidate, payload, score))

    expected_ids = {candidate["candidate_id"] for candidate, _, _ in expected_rows}
    if set(selected_by_id) != expected_ids:
        missing = sorted(expected_ids.difference(selected_by_id))
        extra = sorted(set(selected_by_id).difference(expected_ids))
        raise TaskGoldError(
            "AI score selection must contain every and only eligible Candidate; "
            f"missing={missing}, extra={extra}"
        )
    for candidate, _, score in expected_rows:
        selected = selected_by_id[candidate["candidate_id"]]
        if selected.get("ai_selection_score") != score:
            raise TaskGoldError(
                f"AI-selected Candidate {candidate['candidate_id']} has an invalid score"
            )
        if selected.get("score_threshold") != score_threshold:
            raise TaskGoldError(
                f"AI-selected Candidate {candidate['candidate_id']} has an invalid threshold"
            )

    expected_rows.sort(
        key=lambda item: (
            item[0]["conversation_turn_index"],
            item[0]["candidate_id"],
        )
    )
    selected_targets: list[dict[str, Any]] = []
    for target_number, (candidate, evaluation, score) in enumerate(
        expected_rows, start=1
    ):
        selected_targets.append(
            {
                "target_id": f"{project_id}_T{target_number:03d}",
                "candidate_id": candidate["candidate_id"],
                "message_id": candidate["message_id"],
                "conversation_turn_index": candidate["conversation_turn_index"],
                "history_turn_count": candidate["history_turn_count"],
                "event_ids": deepcopy(candidate["event_ids"]),
                "affected_requirement_ids": deepcopy(candidate["requirement_ids"]),
                "selection_source": "LLM_AUTO_ACCEPT",
                "primary_rq_targets": deepcopy(evaluation["primary_rq_targets"]),
                "ai_selection_score": score,
                "ai_score_threshold": score_threshold,
                "human_review": "SKIPPED",
                "human_review_reason": (
                    "Human review skipped by explicit AI auto-accept mode."
                ),
            }
        )
    return {
        "schema_version": SELECTED_TARGETS_SCHEMA_VERSION,
        "project_id": project_id,
        "input_fingerprint": deepcopy(ai_selection.get("input_fingerprint")),
        "selection_mode": "AI_SCORE_THRESHOLD",
        "score_scale": deepcopy(EVALUATION_LEVEL_RANK),
        "score_threshold": score_threshold,
        "maximum_score": MAX_AI_SELECTION_SCORE,
        "selected_targets": selected_targets,
    }


def finalize_selected_targets(
    selected_candidates_auto: dict[str, Any],
    candidate_tasks: dict[str, Any],
    evaluations: Iterable[dict[str, Any]],
    human_review: dict[str, Any],
    config: TargetSelectionConfig,
) -> dict[str, Any]:
    """Apply complete human decisions and create stable final target IDs."""
    project_id = str(selected_candidates_auto.get("project_id"))
    if project_id != str(candidate_tasks.get("project_id")):
        raise TaskGoldError("auto selection and candidate_tasks have different project IDs")
    review_project = human_review.get("project_id")
    if review_project is not None and str(review_project) != project_id:
        raise TaskGoldError("human review has a different project_id")
    decisions = human_review.get("decisions")
    decisions = _require_array(decisions, "target_time_human_review.decisions")
    decision_by_id: dict[str, dict[str, Any]] = {}
    for raw_decision in decisions:
        decision = _require_object(raw_decision, "human review decision")
        candidate_id = _require_string(
            decision.get("candidate_id"), "human review candidate_id"
        )
        if candidate_id in decision_by_id:
            raise TaskGoldError(f"duplicate human review decision for {candidate_id}")
        if decision.get("decision") not in {"ACCEPT", "REJECT", "ADD_BACK"}:
            raise TaskGoldError(
                f"human review decision for {candidate_id} must be ACCEPT, REJECT, or ADD_BACK"
            )
        reason = decision.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise TaskGoldError(f"human review decision for {candidate_id} needs a reason")
        decision_by_id[candidate_id] = decision
    candidates = {
        row["candidate_id"]: row
        for row in _require_array(candidate_tasks.get("candidates"), "candidate_tasks.candidates")
    }
    evaluations_by_id: dict[str, dict[str, Any]] = {}
    for raw_evaluation in evaluations:
        evaluation_row = _require_object(raw_evaluation, "LLM evaluation")
        candidate_id = _require_string(
            evaluation_row.get("candidate_id"), "evaluation.candidate_id"
        )
        if candidate_id in evaluations_by_id:
            raise TaskGoldError(f"duplicate LLM evaluation for {candidate_id}")
        evaluations_by_id[candidate_id] = evaluation_row
    auto_rows = _require_array(
        selected_candidates_auto.get("selected_candidates"),
        "selected_candidates_auto.selected_candidates",
    )
    auto_ids = {row["candidate_id"] for row in auto_rows}
    for candidate_id in auto_ids:
        decision = decision_by_id.get(candidate_id)
        if decision is None or decision["decision"] not in {"ACCEPT", "REJECT"}:
            raise TaskGoldError(
                f"auto-selected Candidate {candidate_id} needs ACCEPT or REJECT"
            )
    final_rows: list[tuple[dict[str, Any], str]] = []
    for candidate_id, decision in decision_by_id.items():
        action = decision["decision"]
        if action == "ADD_BACK":
            if candidate_id in auto_ids:
                raise TaskGoldError(
                    f"auto-selected Candidate {candidate_id} cannot use ADD_BACK"
                )
            if candidate_id not in candidates or candidate_id not in evaluations_by_id:
                raise TaskGoldError(
                    f"ADD_BACK Candidate {candidate_id} has no Candidate/evaluation artifact"
                )
            payload = _evaluation_payload(evaluations_by_id[candidate_id])
            packet_stub = {
                "candidate_id": candidate_id,
                "candidate_task": {"message_id": candidates[candidate_id]["message_id"]},
            }
            validate_llm_evaluation(payload, packet_stub, config)
            final_rows.append((candidates[candidate_id], "HUMAN_ADD_BACK"))
        elif action == "ACCEPT":
            if candidate_id not in auto_ids:
                raise TaskGoldError(
                    f"non-auto Candidate {candidate_id} must use ADD_BACK, not ACCEPT"
                )
            if candidate_id not in evaluations_by_id:
                raise TaskGoldError(
                    f"ACCEPT Candidate {candidate_id} has no LLM evaluation"
                )
            final_rows.append((candidates[candidate_id], "LLM_PLUS_HUMAN"))
        elif candidate_id not in auto_ids:
            raise TaskGoldError(
                f"REJECT decision references non-auto Candidate {candidate_id}"
            )
    final_rows.sort(key=lambda item: item[0]["conversation_turn_index"])
    selected_targets: list[dict[str, Any]] = []
    for target_number, (candidate, source) in enumerate(final_rows, start=1):
        candidate_id = candidate["candidate_id"]
        evaluation = _evaluation_payload(evaluations_by_id[candidate_id])
        decision = decision_by_id[candidate_id]
        selected_targets.append(
            {
                "target_id": f"{project_id}_T{target_number:03d}",
                "candidate_id": candidate_id,
                "message_id": candidate["message_id"],
                "conversation_turn_index": candidate["conversation_turn_index"],
                "history_turn_count": candidate["history_turn_count"],
                "event_ids": deepcopy(candidate["event_ids"]),
                "affected_requirement_ids": deepcopy(candidate["requirement_ids"]),
                "selection_source": source,
                "primary_rq_targets": deepcopy(evaluation["primary_rq_targets"]),
                "human_review": decision["decision"],
                "human_review_reason": decision["reason"],
            }
        )
    return {
        "schema_version": SELECTED_TARGETS_SCHEMA_VERSION,
        "project_id": project_id,
        "input_fingerprint": deepcopy(selected_candidates_auto.get("input_fingerprint")),
        "selected_targets": selected_targets,
    }


def build_gold_states(
    selected_targets: dict[str, Any],
    normalized_project: dict[str, Any],
    state_graph: dict[str, Any],
) -> dict[str, Any]:
    """Build complete Pre/Post snapshots only for finalized selected targets."""
    messages = _MessageIndex(normalized_project)
    index = _GraphIndex(state_graph, messages.positions)
    if len(
        {
            str(selected_targets.get("project_id")),
            messages.project_id,
            index.project_id,
        }
    ) != 1:
        raise TaskGoldError(
            "selected_targets, normalized_project, and State Graph have different project IDs"
        )
    task_gold_states: list[dict[str, Any]] = []
    seen_target_ids: set[str] = set()
    for raw_target in _require_array(
        selected_targets.get("selected_targets"), "selected_target_times.selected_targets"
    ):
        target = _require_object(raw_target, "selected target")
        target_id = _require_string(target.get("target_id"), "selected target.target_id")
        if target_id in seen_target_ids:
            raise TaskGoldError(f"duplicate target_id: {target_id}")
        seen_target_ids.add(target_id)
        message_id = target.get("message_id")
        position = messages.position(message_id)
        if target.get("conversation_turn_index") != position + 1:
            raise TaskGoldError(f"{target_id} has an invalid conversation_turn_index")
        if target.get("history_turn_count") != position:
            raise TaskGoldError(f"{target_id} has an invalid history_turn_count")
        selection_source = target.get("selection_source")
        if selection_source not in {
            "LLM_PLUS_HUMAN",
            "HUMAN_ADD_BACK",
            "LLM_AUTO_ACCEPT",
        }:
            raise TaskGoldError(f"{target_id} has an invalid selection_source")
        if selection_source == "LLM_AUTO_ACCEPT":
            if target.get("human_review") != "SKIPPED":
                raise TaskGoldError(
                    f"{target_id} must record skipped review in AI auto-accept mode"
                )
            score = target.get("ai_selection_score")
            threshold = target.get("ai_score_threshold")
            _validate_ai_score_threshold(score)
            _validate_ai_score_threshold(threshold)
            if score < threshold:
                raise TaskGoldError(f"{target_id} is below the AI score threshold")
        elif target.get("human_review") not in {"ACCEPT", "ADD_BACK"}:
            raise TaskGoldError(f"{target_id} is not accepted by human review")
        message_key = _id_key(message_id)
        if message_key not in index.edges_by_message:
            raise TaskGoldError(f"{target_id} message has no State Graph Events")
        edge_refs = sorted(
            index.edges_by_message[message_key],
            key=lambda item: (item.graph_position, item.edge_position),
        )
        expected_events = [item.edge["event_id"] for item in edge_refs]
        expected_affected = _stable_unique(item.requirement_id for item in edge_refs)
        if target.get("event_ids") != expected_events:
            raise TaskGoldError(
                f"{target_id}.event_ids must equal all State Graph Events at the target message"
            )
        if target.get("affected_requirement_ids") != expected_affected:
            raise TaskGoldError(
                f"{target_id}.affected_requirement_ids does not match the State Graph"
            )
        pre_snapshot = index.snapshot(message_id, inclusive=False)
        preserved = [
            item["requirement_id"]
            for item in pre_snapshot
            if item["requirement_id"] not in expected_affected
        ]
        task_gold_states.append(
            {
                "task_gold_id": f"{target_id}_GOLD",
                "target_id": target_id,
                "candidate_id": target.get("candidate_id"),
                "conversation_turn_index": position + 1,
                "history_turn_count": position,
                "selection_source": target.get("selection_source"),
                "primary_rq_targets": deepcopy(target.get("primary_rq_targets", [])),
                "ai_selection_score": target.get("ai_selection_score"),
                "ai_score_threshold": target.get("ai_score_threshold"),
                "target_task": messages.source_record(message_id),
                "task_event_ids": expected_events,
                "affected_requirement_ids": expected_affected,
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
        "schema_version": GOLD_SCHEMA_VERSION,
        "project_id": index.project_id,
        "task_gold_states": task_gold_states,
    }
    errors = validate_gold_states(
        result,
        state_graph,
        normalized_project=normalized_project,
        selected_targets=selected_targets,
    )
    if errors:
        raise TaskGoldError("Gold State validation failed: " + "; ".join(errors))
    return result


def validate_gold_states(
    gold_states: dict[str, Any],
    state_graph: dict[str, Any],
    *,
    normalized_project: dict[str, Any] | None = None,
    selected_targets: dict[str, Any] | None = None,
) -> list[str]:
    """Validate state existence, boundaries, completeness, and no leakage."""
    errors: list[str] = []
    try:
        message_index = (
            _MessageIndex(normalized_project)
            if normalized_project is not None
            else None
        )
        index = _GraphIndex(
            state_graph,
            message_index.positions if message_index is not None else None,
        )
        if str(gold_states.get("project_id")) != index.project_id:
            errors.append("project_id does not match the State Graph")
        selected_by_id: dict[str, dict[str, Any]] = {}
        if selected_targets is not None:
            if str(selected_targets.get("project_id")) != index.project_id:
                errors.append("selected_targets.project_id does not match the State Graph")
            for raw_target in _require_array(
                selected_targets.get("selected_targets"),
                "selected_targets.selected_targets",
            ):
                target_row = _require_object(raw_target, "selected target")
                target_id = _require_string(
                    target_row.get("target_id"), "selected target.target_id"
                )
                if target_id in selected_by_id:
                    errors.append(f"duplicate selected target_id: {target_id}")
                selected_by_id[target_id] = target_row
        task_gold_states = _require_array(
            gold_states.get("task_gold_states"), "gold_states.task_gold_states"
        )
        seen_gold_ids: set[str] = set()
        seen_target_ids: set[str] = set()
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
            if message_index is not None:
                normalized_message = message_index.message(message_id)
                for metadata_field in ("speaker", "text"):
                    if target.get(metadata_field) != normalized_message.get(metadata_field):
                        errors.append(
                            f"{context}: target_task.{metadata_field} differs from normalized_project"
                        )
                expected_position = message_index.position(message_id)
                if task_gold.get("conversation_turn_index") != expected_position + 1:
                    errors.append(f"{context}: invalid conversation_turn_index")
                if task_gold.get("history_turn_count") != expected_position:
                    errors.append(f"{context}: invalid history_turn_count")
            if selected_targets is not None:
                target_id = task_gold.get("target_id")
                if not isinstance(target_id, str) or target_id not in selected_by_id:
                    errors.append(f"{context}: Task Gold has no finalized selected target")
                elif target_id in seen_target_ids:
                    errors.append(f"duplicate Task Gold target_id: {target_id}")
                else:
                    seen_target_ids.add(target_id)
                    selected = selected_by_id[target_id]
                    linked_fields = {
                        "candidate_id": "candidate_id",
                        "conversation_turn_index": "conversation_turn_index",
                        "history_turn_count": "history_turn_count",
                        "selection_source": "selection_source",
                        "primary_rq_targets": "primary_rq_targets",
                        "ai_selection_score": "ai_selection_score",
                        "ai_score_threshold": "ai_score_threshold",
                    }
                    for gold_field, selected_field in linked_fields.items():
                        if task_gold.get(gold_field) != selected.get(selected_field):
                            errors.append(
                                f"{context}: {gold_field} differs from selected target"
                            )
                    if _id_key(selected.get("message_id")) != _id_key(message_id):
                        errors.append(f"{context}: message_id differs from selected target")
                    if task_gold.get("task_event_ids") != selected.get("event_ids"):
                        errors.append(f"{context}: Event IDs differ from selected target")
                    if task_gold.get("affected_requirement_ids") != selected.get(
                        "affected_requirement_ids"
                    ):
                        errors.append(
                            f"{context}: affected Requirements differ from selected target"
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

            boundary = index.position(message_id)
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
                        support_position = index.position(
                            index.edge_by_event_id[event_id].edge["source_message_id"]
                        )
                        if support_position > boundary or (
                            not inclusive and support_position == boundary
                        ):
                            errors.append(
                                f"{label} leaks future supporting event {event_id} into {field}"
                            )
        if selected_targets is not None and seen_target_ids != set(selected_by_id):
            missing = sorted(set(selected_by_id).difference(seen_target_ids))
            if missing:
                errors.append(
                    f"selected targets missing Task Gold records: {missing}"
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
