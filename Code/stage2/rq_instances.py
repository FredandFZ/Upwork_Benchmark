"""Deterministic construction of ReqMemBench RQ1--RQ4 instances.

The builder joins finalized Task Gold, the Requirement State Graph, the
normalized (PII-clean) conversation, and the pre-task Code Environment.  It
constructs researcher-side instance records only; it intentionally does not
run agents or score responses.

Some RQ facts are deterministic (for example, pre-task states and Event
trajectories).  Judgements that need annotation -- inherited constraints,
blocking ambiguity, condition-specific evidence sufficiency, acceptance
criteria, and validators -- are emitted as explicit review candidates rather
than silently promoted to final Gold.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256
from pathlib import Path, PurePosixPath
from statistics import median
from typing import Any, Iterable, Mapping
import json
import re
import stat
import zipfile


INSTANCE_SCHEMA_VERSION = "rq-instance-v2"
INDEX_SCHEMA_VERSION = "rq-instance-index-v2"
MANIFEST_SCHEMA_VERSION = "rq-instance-manifest-v2"

RQ_IDS = ("RQ1", "RQ2", "RQ3", "RQ4")
CONDITIONS = ("C1", "C2")

RQ_DEFINITIONS: dict[str, dict[str, Any]] = {
    "RQ1": {
        "name": "Relevant Requirement Selection",
        "question": (
            "Using the full pre-task conversation, identify the historical "
            "requirements and message evidence that are relevant to the current "
            "client task. Exclude unrelated history and do not treat the current "
            "task itself as historical evidence."
        ),
        "supported_conditions": ["C1"],
    },
    "RQ2": {
        "name": "Pre-task State Reconstruction",
        "question": (
            "For the historical requirements relevant to the current client "
            "task, reconstruct their last valid state immediately before the "
            "current task. Do not apply the current task to that state."
        ),
        "supported_conditions": ["C1", "C2"],
    },
    "RQ3": {
        "name": "Requirement Update or Clarify",
        "question": (
            "Combine the pre-task requirement state with the current client task. "
            "If the task determines a unique post-task state, choose ACT and "
            "construct that state; otherwise choose CLARIFY and identify the "
            "blocking requirement field and the question that must be answered."
        ),
        "supported_conditions": ["C1", "C2"],
    },
    "RQ4": {
        "name": "Requirement-to-Code Execution",
        "question": (
            "Translate the current client task and the valid requirement state "
            "into the appropriate development action in the supplied pre-task "
            "repository. Clarify instead of making a speculative change when "
            "the available evidence is insufficient."
        ),
        "supported_conditions": ["C1", "C2"],
    },
}


class RQInstanceError(ValueError):
    """Raised when source artifacts cannot form leakage-safe RQ instances."""


def difficulty_from_turns(turns: int) -> str:
    """Map the preserved pre-task turn count to the paper's difficulty bins."""

    if isinstance(turns, bool) or not isinstance(turns, int) or turns < 0:
        raise RQInstanceError("turns must be a non-negative integer")
    if turns <= 25:
        return "SHORT"
    if turns <= 50:
        return "MEDIUM"
    return "LONG"


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RQInstanceError(f"{label} must be an object")
    return value


def _require_array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise RQInstanceError(f"{label} must be an array")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RQInstanceError(f"{label} must be a non-empty string")
    return value


def _id_key(value: Any) -> str:
    if value is None or isinstance(value, (dict, list, bool)):
        raise RQInstanceError(f"invalid stable ID value: {value!r}")
    text = str(value).strip()
    if not text:
        raise RQInstanceError("stable ID cannot be empty")
    return text


def _stable_unique(values: Iterable[Any]) -> list[Any]:
    output: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = _id_key(value)
        if key not in seen:
            seen.add(key)
            output.append(value)
    return output


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    """Hash a JSON-compatible value using one canonical serialization."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _portable_path(path: Path, workspace_root: Path | None) -> str:
    resolved = path.resolve()
    if workspace_root is not None:
        try:
            return resolved.relative_to(workspace_root.resolve()).as_posix()
        except ValueError:
            pass
    return resolved.as_posix()


class _MessageIndex:
    def __init__(self, normalized_project: dict[str, Any]) -> None:
        self.project_id = _require_string(
            normalized_project.get("project_id"), "normalized_project.project_id"
        )
        self.project_title = normalized_project.get("project_title")
        messages = _require_array(
            normalized_project.get("messages"), "normalized_project.messages"
        )
        self.messages: list[dict[str, Any]] = []
        self.by_id: dict[str, dict[str, Any]] = {}
        self.position_by_id: dict[str, int] = {}
        for position, raw in enumerate(messages):
            message = _require_object(raw, f"messages[{position}]")
            key = _id_key(message.get("message_id"))
            if key in self.by_id:
                raise RQInstanceError(f"duplicate message_id {key!r}")
            _require_string(message.get("speaker"), f"message {key}.speaker")
            if not isinstance(message.get("text"), str):
                raise RQInstanceError(f"message {key}.text must be a string")
            self.messages.append(message)
            self.by_id[key] = message
            self.position_by_id[key] = position

    def position(self, message_id: Any) -> int:
        key = _id_key(message_id)
        if key not in self.position_by_id:
            raise RQInstanceError(f"unknown message_id {key!r}")
        return self.position_by_id[key]

    def message(self, message_id: Any) -> dict[str, Any]:
        key = _id_key(message_id)
        if key not in self.by_id:
            raise RQInstanceError(f"unknown message_id {key!r}")
        return self.by_id[key]

    def public_message(self, message: Mapping[str, Any]) -> dict[str, Any]:
        """Return only PII-clean conversation fields needed by an RQ runner."""

        return {
            "message_id": deepcopy(message.get("message_id")),
            "created_ts": deepcopy(message.get("created_ts")),
            "speaker": deepcopy(message.get("speaker")),
            "text": deepcopy(message.get("text")),
            "milestone": deepcopy(message.get("milestone")),
        }


class _GraphIndex:
    def __init__(self, state_graph: dict[str, Any], messages: _MessageIndex) -> None:
        self.project_id = _require_string(
            state_graph.get("project_id"), "state_graph.project_id"
        )
        self.graph_by_requirement: dict[str, dict[str, Any]] = {}
        self.node_by_state: dict[str, tuple[str, dict[str, Any]]] = {}
        self.event_by_id: dict[str, tuple[str, dict[str, Any]]] = {}

        graphs = _require_array(
            state_graph.get("requirement_graphs"),
            "state_graph.requirement_graphs",
        )
        for graph_position, raw_graph in enumerate(graphs):
            graph = _require_object(raw_graph, f"requirement_graphs[{graph_position}]")
            requirement_id = _require_string(
                graph.get("requirement_id"),
                f"requirement_graphs[{graph_position}].requirement_id",
            )
            if requirement_id in self.graph_by_requirement:
                raise RQInstanceError(f"duplicate requirement_id {requirement_id!r}")
            self.graph_by_requirement[requirement_id] = graph

            for node_position, raw_node in enumerate(
                _require_array(graph.get("nodes"), f"{requirement_id}.nodes")
            ):
                node = _require_object(
                    raw_node, f"{requirement_id}.nodes[{node_position}]"
                )
                state_id = _require_string(
                    node.get("state_id"),
                    f"{requirement_id}.nodes[{node_position}].state_id",
                )
                if state_id in self.node_by_state:
                    raise RQInstanceError(f"duplicate state_id {state_id!r}")
                _require_array(
                    node.get("supporting_event_ids"),
                    f"{state_id}.supporting_event_ids",
                )
                self.node_by_state[state_id] = (requirement_id, node)

            previous_position = -1
            for edge_position, raw_edge in enumerate(
                _require_array(graph.get("edges"), f"{requirement_id}.edges")
            ):
                edge = _require_object(
                    raw_edge, f"{requirement_id}.edges[{edge_position}]"
                )
                event_id = _require_string(
                    edge.get("event_id"),
                    f"{requirement_id}.edges[{edge_position}].event_id",
                )
                if event_id in self.event_by_id:
                    raise RQInstanceError(f"duplicate event_id {event_id!r}")
                message_position = messages.position(edge.get("source_message_id"))
                supporting_message_ids = edge.get("supporting_message_ids", [])
                _require_array(
                    supporting_message_ids,
                    f"{requirement_id}.edges[{edge_position}].supporting_message_ids",
                )
                supporting_keys: set[str] = set()
                source_key = _id_key(edge.get("source_message_id"))
                for message_id in supporting_message_ids:
                    support_key = _id_key(message_id)
                    messages.position(message_id)
                    if support_key == source_key or support_key in supporting_keys:
                        raise RQInstanceError(
                            f"{event_id}.supporting_message_ids repeats a message"
                        )
                    supporting_keys.add(support_key)
                edge.setdefault("supporting_message_ids", [])
                if message_position < previous_position:
                    raise RQInstanceError(
                        f"{requirement_id}.edges are not in conversation order"
                    )
                previous_position = message_position
                self.event_by_id[event_id] = (requirement_id, edge)

        for state_id, (requirement_id, node) in self.node_by_state.items():
            for event_id in node["supporting_event_ids"]:
                ref = self.event_by_id.get(_id_key(event_id))
                if ref is None or ref[0] != requirement_id:
                    raise RQInstanceError(
                        f"{state_id} references unknown or cross-Requirement "
                        f"supporting Event {event_id!r}"
                    )

    def expand_state(self, requirement_id: str, state_id: str) -> dict[str, Any]:
        ref = self.node_by_state.get(state_id)
        if ref is None:
            raise RQInstanceError(f"unknown state_id {state_id!r}")
        node_requirement_id, node = ref
        if node_requirement_id != requirement_id:
            raise RQInstanceError(
                f"state {state_id!r} belongs to {node_requirement_id!r}, not "
                f"{requirement_id!r}"
            )
        graph = self.graph_by_requirement[requirement_id]
        return {
            "requirement_id": requirement_id,
            "requirement_title": deepcopy(graph.get("title")),
            "family_id": deepcopy(graph.get("family_id")),
            "state_id": state_id,
            "attributes": deepcopy(node.get("attributes")),
            "scope": deepcopy(node.get("scope")),
            "lifecycle_status": deepcopy(node.get("lifecycle_status")),
            "ambiguity": deepcopy(node.get("ambiguity")),
            "execution": deepcopy(node.get("execution")),
            "supporting_event_ids": deepcopy(node.get("supporting_event_ids")),
        }

    def expand_snapshot(self, snapshot: Any, label: str) -> dict[str, dict[str, Any]]:
        value = _require_object(snapshot, label)
        rows = _require_array(value.get("requirement_states"), f"{label}.requirement_states")
        expanded: dict[str, dict[str, Any]] = {}
        for position, raw_row in enumerate(rows):
            row = _require_object(raw_row, f"{label}.requirement_states[{position}]")
            requirement_id = _require_string(
                row.get("requirement_id"),
                f"{label}.requirement_states[{position}].requirement_id",
            )
            state_id = _require_string(
                row.get("state_id"),
                f"{label}.requirement_states[{position}].state_id",
            )
            if requirement_id in expanded:
                raise RQInstanceError(
                    f"{label} contains duplicate Requirement {requirement_id!r}"
                )
            expanded[requirement_id] = self.expand_state(requirement_id, state_id)
        return expanded

    def trajectory_before(
        self,
        requirement_id: str,
        target_position: int,
        messages: _MessageIndex,
    ) -> list[dict[str, Any]]:
        graph = self.graph_by_requirement.get(requirement_id)
        if graph is None:
            raise RQInstanceError(f"unknown requirement_id {requirement_id!r}")
        return [
            edge
            for edge in graph["edges"]
            if messages.position(edge["source_message_id"]) < target_position
        ]


def _validate_project_ids(
    gold_states: dict[str, Any],
    graph: _GraphIndex,
    messages: _MessageIndex,
) -> str:
    project_id = _require_string(gold_states.get("project_id"), "gold_states.project_id")
    if project_id != graph.project_id or project_id != messages.project_id:
        raise RQInstanceError(
            "project_id mismatch across Gold State, State Graph, and normalized history"
        )
    schema = gold_states.get("schema_version")
    if schema != "task-gold-v2":
        raise RQInstanceError(
            f"unsupported Gold State schema {schema!r}; expected 'task-gold-v2'"
        )
    return project_id


def _validate_target(
    gold: dict[str, Any], messages: _MessageIndex
) -> tuple[str, Any, int, list[dict[str, Any]]]:
    target_id = _require_string(gold.get("target_id"), "task_gold.target_id")
    task = _require_object(gold.get("target_task"), f"{target_id}.target_task")
    target_message_id = task.get("source_message_id")
    target_position = messages.position(target_message_id)
    source_message = messages.message(target_message_id)
    if task.get("speaker") != source_message.get("speaker"):
        raise RQInstanceError(f"{target_id} target speaker does not match message catalog")
    if task.get("text") != source_message.get("text"):
        raise RQInstanceError(f"{target_id} target text does not match message catalog")

    history = messages.messages[:target_position]
    declared_turns = gold.get("history_turn_count")
    if isinstance(declared_turns, bool) or not isinstance(declared_turns, int):
        raise RQInstanceError(f"{target_id}.history_turn_count must be an integer")
    if declared_turns != len(history):
        raise RQInstanceError(
            f"{target_id}.history_turn_count={declared_turns} but normalized "
            f"history contains {len(history)} pre-task messages"
        )
    conversation_turn_index = gold.get("conversation_turn_index")
    if conversation_turn_index != target_position + 1:
        raise RQInstanceError(
            f"{target_id}.conversation_turn_index does not match normalized order"
        )
    return target_id, target_message_id, target_position, history


def _ordered_message_ids(
    message_ids: Iterable[Any], messages: _MessageIndex, target_position: int
) -> list[Any]:
    unique: dict[str, Any] = {}
    for message_id in message_ids:
        position = messages.position(message_id)
        if position >= target_position:
            raise RQInstanceError(
                f"oracle history contains target/future message {message_id!r}"
            )
        unique.setdefault(_id_key(message_id), message_id)
    return sorted(unique.values(), key=messages.position)


def _derive_relevance(
    gold: dict[str, Any],
    pre_state: dict[str, dict[str, Any]],
    graph: _GraphIndex,
    messages: _MessageIndex,
    target_position: int,
) -> dict[str, Any]:
    affected = [
        _require_string(value, "affected_requirement_ids[]")
        for value in _require_array(
            gold.get("affected_requirement_ids"), "affected_requirement_ids"
        )
    ]
    if len(set(affected)) != len(affected):
        raise RQInstanceError("affected_requirement_ids contains duplicates")
    direct_historical = [rid for rid in affected if rid in pre_state]
    new_requirements = [rid for rid in affected if rid not in pre_state]
    evidence: dict[str, dict[str, Any]] = {}
    oracle_message_ids: list[Any] = []

    def visible_edge_message_ids(edge: dict[str, Any]) -> list[Any]:
        return [
            message_id
            for message_id in [
                edge["source_message_id"],
                *edge.get("supporting_message_ids", []),
            ]
            if messages.position(message_id) < target_position
        ]

    trajectory_cache: dict[str, dict[str, Any]] = {}
    for requirement_id in pre_state:
        trajectory = graph.trajectory_before(
            requirement_id, target_position, messages
        )
        trajectory_cache[requirement_id] = {
            "event_ids": [edge["event_id"] for edge in trajectory],
            "message_ids": _ordered_message_ids(
                [
                    message_id
                    for edge in trajectory
                    for message_id in visible_edge_message_ids(edge)
                ],
                messages,
                target_position,
            ),
        }

    for requirement_id in direct_historical:
        state = pre_state[requirement_id]
        current_support_event_ids = deepcopy(state["supporting_event_ids"])
        trajectory_event_ids = trajectory_cache[requirement_id]["event_ids"]
        trajectory_message_ids = trajectory_cache[requirement_id]["message_ids"]

        candidate_groups: list[list[Any]] = []
        for event_id in current_support_event_ids:
            edge = graph.event_by_id[_id_key(event_id)][1]
            candidate_ids = _ordered_message_ids(
                visible_edge_message_ids(edge),
                messages,
                target_position,
            )
            overlapping = [
                index
                for index, group_ids in enumerate(candidate_groups)
                if {_id_key(value) for value in group_ids}.intersection(
                    {_id_key(value) for value in candidate_ids}
                )
            ]
            if not overlapping:
                candidate_groups.append(candidate_ids)
                continue
            keep = overlapping[0]
            merged_ids = list(candidate_groups[keep]) + candidate_ids
            for index in reversed(overlapping[1:]):
                merged_ids.extend(candidate_groups.pop(index))
            candidate_groups[keep] = _ordered_message_ids(
                merged_ids, messages, target_position
            )

        current_support_message_ids = _ordered_message_ids(
            [message_id for group_ids in candidate_groups for message_id in group_ids],
            messages,
            target_position,
        )
        current_support_keys = {
            _id_key(message_id) for message_id in current_support_message_ids
        }

        family_id = state.get("family_id")
        family_trajectory_message_ids = list(trajectory_message_ids)
        if family_id is not None:
            family_trajectory_message_ids = _ordered_message_ids(
                [
                    message_id
                    for sibling_id, sibling_state in pre_state.items()
                    if sibling_state.get("family_id") == family_id
                    for message_id in trajectory_cache[sibling_id]["message_ids"]
                ],
                messages,
                target_position,
            )
        neutral_context_message_ids = [
            message_id
            for message_id in family_trajectory_message_ids
            if _id_key(message_id) not in current_support_keys
        ]
        required_evidence_groups = [
            {
                "group_id": f"{requirement_id}_EG{index:03d}",
                "acceptable_message_ids": deepcopy(group_ids),
            }
            for index, group_ids in enumerate(candidate_groups, start=1)
        ]
        evidence[requirement_id] = {
            "current_support_event_ids": current_support_event_ids,
            "current_support_message_ids": current_support_message_ids,
            "trajectory_event_ids": trajectory_event_ids,
            "trajectory_message_ids": trajectory_message_ids,
            "core_message_ids": deepcopy(current_support_message_ids),
            "required_evidence_groups": required_evidence_groups,
            "context_message_ids": neutral_context_message_ids,
            "neutral_context_message_ids": deepcopy(
                neutral_context_message_ids
            ),
            "family_trajectory_message_ids": deepcopy(
                family_trajectory_message_ids
            ),
            "context_review_status": "DETERMINISTIC_FAMILY_TRAJECTORY_CONTEXT",
        }
        oracle_message_ids.extend(trajectory_message_ids)

    return {
        "relevant_requirement_ids": deepcopy(direct_historical),
        "directly_affected_historical_requirement_ids": deepcopy(
            direct_historical
        ),
        "inherited_constraint_requirement_ids": [],
        "new_requirement_ids": deepcopy(new_requirements),
        "evidence": evidence,
        "oracle_history_message_ids": _ordered_message_ids(
            oracle_message_ids, messages, target_position
        ),
        "derivation_scope": "DIRECT_AFFECTED_ONLY",
        "review_status": "DETERMINISTIC_DIRECT_AFFECTED_ONLY",
        "review_note": (
            "RQ1 relevance is operationally defined as directly affected "
            "Requirements that already exist in the pre-task snapshot. Preserved "
            "or inherited Requirements are outside RQ1 Gold."
        ),
    }


def _condition_inputs(
    rq_id: str,
    full_history_ids: list[Any],
    oracle_history_ids: list[Any],
) -> dict[str, dict[str, Any]]:
    inputs: dict[str, dict[str, Any]] = {}
    for condition in CONDITIONS:
        available = condition in RQ_DEFINITIONS[rq_id]["supported_conditions"]
        if condition == "C1":
            mode = "FULL_HISTORY"
            ids: list[Any] = deepcopy(full_history_ids)
            review_status = "DETERMINISTIC"
        else:
            mode = "ORACLE_RELEVANT_HISTORY"
            ids = deepcopy(oracle_history_ids)
            review_status = "DETERMINISTIC_DIRECT_TRAJECTORY_ONLY"
        inputs[condition] = {
            "available": available,
            "history_mode": mode,
            "history_message_ids": ids,
            "history_message_count": len(ids),
            "review_status": review_status,
        }
    return inputs


def _response_contract(rq_id: str) -> dict[str, Any]:
    if rq_id == "RQ1":
        return {
            "schema_version": "rq1-agent-response-v3",
            "required_fields": ["requirements"],
            "allowed_top_level_fields": [
                "requirements",
                "decision",
                "post_task_states",
                "clarifications",
            ],
            "required_requirement_item_fields": [
                "requirement_ref",
                "requirement_summary",
                "evidence_message_ids",
            ],
            "allowed_requirement_item_fields": [
                "requirement_ref",
                "requirement_summary",
                "evidence_message_ids",
                "pre_task_state",
            ],
            "rq1_projection": {
                "top_level_fields": ["requirements"],
                "requirement_item_fields": [
                    "requirement_ref",
                    "requirement_summary",
                    "evidence_message_ids",
                ],
            },
            "requirement_refs_must_be_unique": True,
            "evidence_message_ids_must_reference_c1_history": True,
            "internal_ids_forbidden": True,
        }
    if rq_id == "RQ2":
        return {
            "schema_version": "rq2-agent-response-v3",
            "required_fields": ["requirements"],
            "allowed_top_level_fields": [
                "requirements",
                "decision",
                "post_task_states",
                "clarifications",
            ],
            "required_requirement_item_fields": [
                "requirement_ref",
                "requirement_summary",
                "evidence_message_ids",
                "pre_task_state",
            ],
            "allowed_requirement_item_fields": [
                "requirement_ref",
                "requirement_summary",
                "evidence_message_ids",
                "pre_task_state",
            ],
            "pre_task_state_fields": [
                "attributes",
                "scope",
                "lifecycle_status",
                "ambiguity",
                "execution",
            ],
            "ambiguity_representation": "NULL_OR_ARRAY_OF_RECORDS",
            "complete_state_closed_world": True,
            "unexpected_state_fields_are_false_positives": True,
            "internal_ids_forbidden": True,
        }
    if rq_id == "RQ3":
        return {
            "schema_version": "rq3-agent-response-v3",
            "required_fields": [
                "decision",
                "post_task_states",
                "clarifications",
            ],
            "allowed_top_level_fields": [
                "requirements",
                "decision",
                "post_task_states",
                "clarifications",
            ],
            "decision_values": ["ACT", "CLARIFY"],
            "branch_constraints": {
                "ACT": {
                    "post_task_states": "NON_EMPTY_ARRAY",
                    "clarifications": "EMPTY_ARRAY",
                },
                "CLARIFY": {
                    "post_task_states": "NULL",
                    "clarifications": "NON_EMPTY_ARRAY",
                },
            },
            "clarification_item_fields": [
                "requirement_ref",
                "requirement_summary",
                "dimension",
                "field",
                "missing_information",
                "question",
            ],
            "post_task_state_item_fields": [
                "requirement_ref",
                "requirement_summary",
                "change_type",
                "removed_attribute_keys",
                "state",
            ],
            "state_fields": [
                "attributes",
                "scope",
                "lifecycle_status",
                "ambiguity",
                "execution",
            ],
            "ambiguity_representation": "NULL_OR_ARRAY_OF_RECORDS",
            "complete_state_closed_world": True,
            "unexpected_state_fields_are_false_positives": True,
            "internal_ids_forbidden": True,
        }
    return {
        "schema_version": "rq4-repository-result-v2",
        "scored_artifact": "FINAL_REPOSITORY",
        "structured_agent_response_required": False,
        "planned_actions_scored": False,
        "result_values": ["PASS", "FAIL"],
    }


def _semantic_state(state: dict[str, Any] | None) -> dict[str, Any] | None:
    if state is None:
        return None
    ambiguity = state.get("ambiguity")
    if isinstance(ambiguity, dict):
        ambiguity = [
            {
                str(key): deepcopy(value)
                for key, value in raw.items()
                if key not in {"source_event_id", "ambiguity_event_id"}
            }
            for _, raw in sorted(ambiguity.items(), key=lambda item: str(item[0]))
            if isinstance(raw, dict)
        ]
    execution = state.get("execution")
    if isinstance(execution, dict):
        execution = {
            str(key): deepcopy(value)
            for key, value in execution.items()
            if key != "source_event_id"
        }
    return {
        "attributes": deepcopy(state.get("attributes")),
        "scope": deepcopy(state.get("scope")),
        "lifecycle_status": deepcopy(state.get("lifecycle_status")),
        "ambiguity": deepcopy(ambiguity),
        "execution": deepcopy(execution),
    }


def _state_delta(
    before: dict[str, Any] | None, after: dict[str, Any] | None
) -> dict[str, Any]:
    if before is None:
        return {
            "change_type": "INTRODUCED",
            "changed_fields": ["existence"],
            "changed_paths": ["existence"],
            "removed_paths": [],
        }
    if after is None:
        return {
            "change_type": "REMOVED_FROM_SNAPSHOT",
            "changed_fields": ["existence"],
            "changed_paths": ["existence"],
            "removed_paths": ["existence"],
        }
    before_semantic = _semantic_state(before) or {}
    after_semantic = _semantic_state(after) or {}
    fields = [
        key
        for key in (
            "attributes",
            "scope",
            "lifecycle_status",
            "ambiguity",
            "execution",
        )
        if before_semantic.get(key) != after_semantic.get(key)
    ]

    changed_paths: list[str] = []
    removed_paths: list[str] = []

    def visit(path: str, old: Any, new: Any) -> None:
        if old == new:
            return
        if isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(set(old) | set(new)):
                child_path = f"{path}.{key}" if path else str(key)
                if key not in new:
                    changed_paths.append(child_path)
                    removed_paths.append(child_path)
                elif key not in old:
                    changed_paths.append(child_path)
                else:
                    visit(child_path, old[key], new[key])
            return
        changed_paths.append(path)

    for field in fields:
        visit(field, before_semantic.get(field), after_semantic.get(field))
    return {
        "change_type": "MODIFIED" if fields else "UNCHANGED",
        "changed_fields": fields,
        "changed_paths": changed_paths,
        "removed_paths": removed_paths,
    }


def _open_ambiguity_candidates(
    affected_requirement_ids: list[str],
    post_state: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for requirement_id in affected_requirement_ids:
        state = post_state.get(requirement_id)
        if state is None:
            continue
        ambiguities = state.get("ambiguity")
        if not isinstance(ambiguities, dict):
            continue
        for ambiguity_event_id, raw in ambiguities.items():
            ambiguity = raw if isinstance(raw, dict) else {}
            if ambiguity.get("status") != "OPEN":
                continue
            output.append(
                {
                    "requirement_id": requirement_id,
                    "ambiguity_event_id": ambiguity_event_id,
                    "dimension": deepcopy(ambiguity.get("dimension")),
                    "field": deepcopy(ambiguity.get("field")),
                    "description": deepcopy(ambiguity.get("description")),
                    "missing_information": deepcopy(
                        ambiguity.get("missing_information")
                        or ambiguity.get("description")
                    ),
                    "clarification_question": deepcopy(
                        ambiguity.get("clarification_question")
                    ),
                    "source_event_id": deepcopy(ambiguity.get("source_event_id")),
                    "blocking_status": "PENDING_MATERIALITY_REVIEW",
                }
            )
    return output


def _target_event_refs(
    gold: dict[str, Any], graph: _GraphIndex
) -> dict[str, list[dict[str, Any]]]:
    refs: dict[str, list[dict[str, Any]]] = {}
    target_message_key = _id_key(gold["target_task"]["source_message_id"])
    seen_events: set[str] = set()
    for event_id in _require_array(gold.get("task_event_ids"), "task_event_ids"):
        event_key = _id_key(event_id)
        if event_key in seen_events:
            raise RQInstanceError(f"target repeats Event {event_id!r}")
        seen_events.add(event_key)
        ref = graph.event_by_id.get(event_key)
        if ref is None:
            raise RQInstanceError(f"target references unknown Event {event_id!r}")
        requirement_id, edge = ref
        if _id_key(edge.get("source_message_id")) != target_message_key:
            raise RQInstanceError(
                f"target Event {event_id!r} does not originate from the target message"
            )
        refs.setdefault(requirement_id, []).append(edge)
    affected = {
        _require_string(value, "affected_requirement_ids[]")
        for value in _require_array(
            gold.get("affected_requirement_ids"), "affected_requirement_ids"
        )
    }
    if set(refs) != affected:
        raise RQInstanceError(
            "target Event Requirements do not exactly match affected_requirement_ids"
        )
    return refs


def _requirement_action_candidate(
    requirement_id: str,
    events: list[dict[str, Any]],
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> dict[str, Any]:
    event_types = [edge.get("event_type") for edge in events]
    delta = _state_delta(before, after)
    open_ambiguity = bool(
        isinstance(after, dict)
        and isinstance(after.get("ambiguity"), dict)
        and after["ambiguity"]
    )

    if "REMOVE" in event_types or (
        after is not None and after.get("lifecycle_status") == "REMOVED"
    ):
        action, operation = "REMOVE", "REMOVE"
    elif "RUNTIME_FAILURE" in event_types:
        action, operation = "MODIFY", "REPAIR"
    elif "DEFER" in event_types:
        action, operation = "MODIFY", "DEFER"
    elif "RESUME" in event_types:
        action, operation = "MODIFY", "RESUME"
    elif before is None:
        action, operation = "IMPLEMENT", "IMPLEMENT"
    elif delta["change_type"] == "MODIFIED":
        action, operation = "MODIFY", "APPLY_STATE_TRANSITION"
    else:
        action, operation = "PRESERVE", "VERIFY_OR_NO_CODE_CHANGE"

    return {
        "requirement_id": requirement_id,
        "action_candidate": action,
        "operation_candidate": operation,
        "event_types": event_types,
        "before_state_id": before.get("state_id") if before else None,
        "after_state_id": after.get("state_id") if after else None,
        "state_delta": delta,
        "open_ambiguity_present": open_ambiguity,
        "review_status": (
            "PENDING_BLOCKING_AMBIGUITY_REVIEW"
            if open_ambiguity
            else "DETERMINISTIC_TRANSITION_CANDIDATE"
        ),
    }


def _inspect_repository_archive(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RQInstanceError(f"missing Code Environment archive: {path}")
    file_count = 0
    directory_count = 0
    uncompressed_bytes = 0
    compressed_bytes = 0
    try:
        with zipfile.ZipFile(path) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise RQInstanceError(
                    f"Code Environment archive has a bad CRC member: {bad_member}"
                )
            for info in archive.infolist():
                normalized = info.filename.replace("\\", "/")
                pure = PurePosixPath(normalized)
                parts = [part for part in pure.parts if part not in ("", ".")]
                if (
                    pure.is_absolute()
                    or re.match(r"^[A-Za-z]:", normalized)
                    or ".." in parts
                ):
                    raise RQInstanceError(
                        f"unsafe path in Code Environment archive: {info.filename!r}"
                    )
                if any(part.casefold() == ".git" for part in parts):
                    raise RQInstanceError(
                        f"Code Environment archive contains forbidden .git data: "
                        f"{info.filename!r}"
                    )
                unix_mode = info.external_attr >> 16
                if stat.S_ISLNK(unix_mode):
                    raise RQInstanceError(
                        f"Code Environment archive contains a symlink: {info.filename!r}"
                    )
                compressed_bytes += info.compress_size
                uncompressed_bytes += info.file_size
                if info.is_dir():
                    directory_count += 1
                else:
                    file_count += 1
    except zipfile.BadZipFile as exc:
        raise RQInstanceError(f"invalid Code Environment archive {path}: {exc}") from exc
    return {
        "archive_sha256": _sha256_file(path),
        "archive_validation": "PASSED",
        "member_path_validation": "PASSED",
        "crc_validation": "PASSED",
        "contains_git_metadata": False,
        "contains_symlinks": False,
        "file_count": file_count,
        "directory_count": directory_count,
        "compressed_member_bytes": compressed_bytes,
        "uncompressed_member_bytes": uncompressed_bytes,
    }


class _CodeEnvironmentIndex:
    def __init__(
        self,
        root: Path | None,
        *,
        project_id: str,
        workspace_root: Path | None,
    ) -> None:
        self.root = root
        self.project_id = project_id
        self.workspace_root = workspace_root
        self.by_target: dict[str, tuple[Path, dict[str, Any]]] = {}
        self.target_index_by_target: dict[str, dict[str, Any]] = {}
        self.validation_summary: dict[str, Any] | None = None
        self._inspection_cache: dict[str, dict[str, Any]] = {}
        if root is None:
            return
        if not root.is_dir():
            raise RQInstanceError(f"Code Environment directory does not exist: {root}")
        for manifest_path in sorted(root.glob("targets/*/manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RQInstanceError(f"cannot read {manifest_path}: {exc}") from exc
            manifest = _require_object(manifest, str(manifest_path))
            target_id = _require_string(
                manifest.get("target_id"), f"{manifest_path}.target_id"
            )
            if target_id in self.by_target:
                raise RQInstanceError(
                    f"duplicate Code Environment manifest for {target_id!r}"
                )
            if not target_id.startswith(f"{project_id}_"):
                raise RQInstanceError(
                    f"Code Environment target {target_id!r} does not belong to "
                    f"project {project_id!r}"
                )
            self.by_target[target_id] = (manifest_path, manifest)

        reports_dir = root / "reports"
        validation_path = reports_dir / "validation_report.json"
        target_index_path = reports_dir / "target_index.json"
        try:
            validation_report = json.loads(
                validation_path.read_text(encoding="utf-8-sig")
            )
            target_index = json.loads(
                target_index_path.read_text(encoding="utf-8-sig")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise RQInstanceError(
                f"cannot read Code Environment validation reports under "
                f"{reports_dir}: {exc}"
            ) from exc
        validation_report = _require_object(
            validation_report, str(validation_path)
        )
        if str(validation_report.get("overall", "")).casefold() != "pass":
            raise RQInstanceError(
                "Code Environment reconstruction validation did not pass"
            )
        for position, raw_row in enumerate(
            _require_array(target_index, str(target_index_path))
        ):
            row = _require_object(raw_row, f"target_index[{position}]")
            target_id = _require_string(
                row.get("target_id"), f"target_index[{position}].target_id"
            )
            if target_id in self.target_index_by_target:
                raise RQInstanceError(
                    f"target_index contains duplicate target {target_id!r}"
                )
            self.target_index_by_target[target_id] = row
        if set(self.target_index_by_target) != set(self.by_target):
            raise RQInstanceError(
                "Code Environment target_index and target manifests disagree"
            )
        self.validation_summary = {
            "overall": "pass",
            "validation_report_path": _portable_path(
                validation_path, self.workspace_root
            ),
            "validation_report_sha256": _sha256_file(validation_path),
            "target_index_path": _portable_path(
                target_index_path, self.workspace_root
            ),
            "target_index_sha256": _sha256_file(target_index_path),
        }

    def has_target(self, target_id: str) -> bool:
        """Return whether this project has a reconstructed environment for target."""

        return target_id in self.by_target

    def describe(
        self,
        target_id: str,
        gold: dict[str, Any],
        expected_event_types: list[Any],
    ) -> dict[str, Any]:
        ref = self.by_target.get(target_id)
        if ref is None:
            raise RQInstanceError(
                f"RQ4 target {target_id!r} has no Code Environment manifest"
            )
        manifest_path, manifest = ref
        indexed_manifest = self.target_index_by_target[target_id]
        for field in (
            "before_message_id",
            "target_event_ids",
            "target_event_types",
            "repo_sha256",
        ):
            if indexed_manifest.get(field) != manifest.get(field):
                raise RQInstanceError(
                    f"{target_id} manifest field {field!r} disagrees with target_index"
                )
        archive_path = manifest_path.parent / "pre_repo.zip"
        target_message_id = gold["target_task"]["source_message_id"]
        if _id_key(manifest.get("before_message_id")) != _id_key(target_message_id):
            raise RQInstanceError(
                f"{target_id} Code Environment boundary does not match target message"
            )
        if manifest.get("pre_state_verified_against_gold") is not True:
            raise RQInstanceError(f"{target_id} pre-state is not verified against Gold")
        if manifest.get("post_state_verified_against_gold") is not True:
            raise RQInstanceError(f"{target_id} post-state is not verified against Gold")
        if manifest.get("target_event_ids") != gold.get("task_event_ids"):
            raise RQInstanceError(
                f"{target_id} Code Environment target Events do not match Task Gold"
            )
        if manifest.get("target_event_types") != expected_event_types:
            raise RQInstanceError(
                f"{target_id} Code Environment Event types do not match State Graph"
            )
        cache_key = str(archive_path.resolve())
        if cache_key not in self._inspection_cache:
            self._inspection_cache[cache_key] = _inspect_repository_archive(archive_path)
        inspection = self._inspection_cache[cache_key]
        tree_sha = _require_string(
            manifest.get("repo_sha256"), f"{target_id}.manifest.repo_sha256"
        )
        if not re.fullmatch(r"[0-9a-fA-F]{64}", tree_sha):
            raise RQInstanceError(f"{target_id} has an invalid repository tree SHA-256")
        return {
            "available": True,
            "archive_path": _portable_path(archive_path, self.workspace_root),
            "manifest_path": _portable_path(manifest_path, self.workspace_root),
            "manifest_sha256": _sha256_file(manifest_path),
            "archive_sha256": inspection["archive_sha256"],
            "repository_tree_sha256": tree_sha.lower(),
            "before_message_id": deepcopy(manifest.get("before_message_id")),
            "repository_classification": deepcopy(
                manifest.get("repository_classification")
            ),
            "contract_layer": deepcopy(manifest.get("contract_layer")),
            "web_api_layer": deepcopy(manifest.get("web_api_layer")),
            "active_code_feature_count": deepcopy(
                manifest.get("active_code_feature_count")
            ),
            "tracked_requirement_count": deepcopy(
                manifest.get("tracked_requirement_count")
            ),
            "requirements_to_code": deepcopy(manifest.get("requirements_to_code")),
            "temporal_fixture": deepcopy(manifest.get("temporal_fixture")),
            "archive_inspection": deepcopy(inspection),
            "reconstruction_validation": deepcopy(self.validation_summary),
            "workspace_policy": "EXTRACT_TO_FRESH_ISOLATED_WORKSPACE_PER_RUN",
            "extracted_during_instance_construction": False,
        }


def _source_record(
    source_paths: Mapping[str, Path] | None,
    workspace_root: Path | None,
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for name, path in (source_paths or {}).items():
        value = Path(path)
        record: dict[str, Any] = {"path": _portable_path(value, workspace_root)}
        if value.is_file():
            record["sha256"] = _sha256_file(value)
        output[name] = record
    return output


def _common_instance(
    *,
    rq_id: str,
    input_release: str,
    target_fingerprint: str,
    project_id: str,
    project_title: Any,
    gold: dict[str, Any],
    target_id: str,
    target_message_id: Any,
    history: list[dict[str, Any]],
    messages: _MessageIndex,
    relevance: dict[str, Any],
    applicable_rqs: list[str],
    sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    turns = len(history)
    full_history_ids = [message["message_id"] for message in history]
    public_history = [messages.public_message(message) for message in history]
    condition_inputs = _condition_inputs(
        rq_id,
        full_history_ids,
        relevance["oracle_history_message_ids"],
    )
    return {
        "schema_version": INSTANCE_SCHEMA_VERSION,
        "instance_id": f"{target_id}_{rq_id}",
        "input_release": input_release,
        "target_fingerprint": target_fingerprint,
        "project_id": project_id,
        "project_title": deepcopy(project_title),
        "rq_id": rq_id,
        "rq_name": RQ_DEFINITIONS[rq_id]["name"],
        "target_id": target_id,
        "task_gold_id": deepcopy(gold.get("task_gold_id")),
        "target_message_id": deepcopy(target_message_id),
        "turns": turns,
        "history_turn_count": turns,
        "difficulty": difficulty_from_turns(turns),
        "applicable_rqs": deepcopy(applicable_rqs),
        "question": RQ_DEFINITIONS[rq_id]["question"],
        "target_task": deepcopy(gold["target_task"]),
        "history_pool": {
            "boundary": "STRICTLY_BEFORE_TARGET_MESSAGE",
            "contains_target_message": False,
            "message_count": turns,
            "messages": public_history,
        },
        "condition_inputs": condition_inputs,
        "fingerprints": {
            "target": target_fingerprint,
            "history_pool": _sha256_json(public_history),
            "condition_history": {
                condition: _sha256_json(
                    condition_inputs[condition]["history_message_ids"]
                )
                for condition in CONDITIONS
            },
        },
        "response_contract": _response_contract(rq_id),
        "visibility": {
            "record_kind": "RESEARCHER_SIDE_CONSTRUCTION_INSTANCE",
            "runner_must_hide": [
                "construction_gold",
                "source_artifacts",
            ],
            "runner_materialization_status": "NOT_IMPLEMENTED_IN_THIS_STAGE",
        },
        "source_artifacts": deepcopy(sources),
    }


def _build_rq1_gold(
    relevance: dict[str, Any], pre_state: Mapping[str, dict[str, Any]]
) -> dict[str, Any]:
    atoms: dict[str, dict[str, Any]] = {}
    for requirement_id in relevance["relevant_requirement_ids"]:
        state = pre_state[requirement_id]
        evidence = relevance["evidence"][requirement_id]
        required_groups = deepcopy(evidence["required_evidence_groups"])
        if not required_groups:
            raise RQInstanceError(
                f"RQ1 Gold Requirement {requirement_id!r} has no current-support "
                "evidence group"
            )
        atoms[requirement_id] = {
            "canonical_summary": deepcopy(state["requirement_title"]),
            "requirement_title": deepcopy(state["requirement_title"]),
            "family_id": deepcopy(state.get("family_id")),
            "required_evidence_groups": required_groups,
            "neutral_context_message_ids": deepcopy(
                evidence["neutral_context_message_ids"]
            ),
            "family_trajectory_message_ids": deepcopy(
                evidence["family_trajectory_message_ids"]
            ),
            "trajectory_message_ids": deepcopy(
                evidence["trajectory_message_ids"]
            ),
        }
    return {
        "status": "DETERMINISTIC_RQ1_GOLD",
        "gold_unit": "INDEPENDENT_REQUIREMENT_ATOM",
        "atomization_rule": "ONE_REQUIREMENT_GRAPH_EQUALS_ONE_GOLD_ATOM",
        "relevant_requirement_ids": deepcopy(relevance["relevant_requirement_ids"]),
        "gold_requirement_atoms": atoms,
        "directly_affected_historical_requirement_ids": deepcopy(
            relevance["directly_affected_historical_requirement_ids"]
        ),
        "inherited_constraint_requirement_ids": [],
        "new_requirement_ids": deepcopy(relevance["new_requirement_ids"]),
        "evidence": deepcopy(relevance["evidence"]),
        "derivation_scope": relevance["derivation_scope"],
        "review_status": relevance["review_status"],
    }


_NORMALIZED_EXACT_PATHS = {
    ("scope", "persistence"),
    ("lifecycle_status",),
    ("ambiguity", "[]", "status"),
    ("ambiguity", "[]", "dimension"),
    ("ambiguity", "[]", "field"),
    ("execution", "status"),
}

_UNKNOWN_NULL_PATHS = {
    ("lifecycle_status",),
    ("scope", "persistence"),
    ("scope", "components"),
    ("scope", "contexts"),
}


def _typed_scoring_spec(
    value: Any, path: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Create a path-aware comparator for an agent-expressible Gold field."""

    if value is None:
        if path in _UNKNOWN_NULL_PATHS:
            return {
                "comparator": "SKIP",
                "score": False,
                "null_semantics": "UNKNOWN_UNANNOTATED",
                "review_status": "REQUIRES_FIELD_REVIEW",
            }
        return {
            "comparator": "NULL_EXACT",
            "score": True,
            "null_semantics": "EXPLICIT_ABSENT",
            "review_status": "DETERMINISTIC_EXPLICIT_ABSENCE",
        }
    if isinstance(value, bool):
        return {
            "comparator": "BOOLEAN_EXACT",
            "score": True,
            "review_status": "DETERMINISTIC",
        }
    if isinstance(value, (int, float)):
        return {
            "comparator": "NUMBER_EXACT",
            "score": True,
            "review_status": "DETERMINISTIC",
        }
    if isinstance(value, str):
        if path in _NORMALIZED_EXACT_PATHS:
            return {
                "comparator": "NORMALIZED_EXACT",
                "score": True,
                "review_status": "DETERMINISTIC_ENUM_OR_IDENTIFIER",
            }
        return {
            "comparator": "SEMANTIC_FACT",
            "score": True,
            "review_status": "REQUIRES_FROZEN_SEMANTIC_JUDGE",
        }
    if isinstance(value, list):
        if any(isinstance(child, dict) for child in value):
            item_fields = sorted(
                {
                    str(key)
                    for child in value
                    if isinstance(child, dict)
                    for key in child
                }
            )
            result = {
                "comparator": "UNORDERED_RECORD_F1",
                "score": True,
                "item_fields": {
                    field: _typed_scoring_spec(
                        next(
                            (
                                child.get(field)
                                for child in value
                                if isinstance(child, dict) and field in child
                            ),
                            None,
                        ),
                        path + ("[]", field),
                    )
                    for field in item_fields
                },
                "matching_policy": "MAX_WEIGHT_ONE_TO_ONE",
                "review_status": "DETERMINISTIC_STRUCTURE_SEMANTIC_LEAVES",
            }
            if path == ("ambiguity",):
                result["matching_key_fields"] = ["dimension", "description"]
            return result
        return {
            "comparator": "SET_F1",
            "score": True,
            "review_status": "DETERMINISTIC_UNORDERED_SET",
        }
    if isinstance(value, dict):
        return {
            "comparator": "RECURSIVE_FIELDS",
            "score": True,
            "closed_world": True,
            "fields": {
                str(key): _typed_scoring_spec(child, path + (str(key),))
                for key, child in value.items()
            },
            "review_status": "DETERMINISTIC_STRUCTURE_SEMANTIC_LEAVES",
        }
    return {
        "comparator": "NORMALIZED_EXACT",
        "score": True,
        "review_status": "PENDING_COMPARATOR_REVIEW",
    }


def _state_scoring_specs(
    states: Mapping[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        requirement_id: {
            field: _typed_scoring_spec(state.get(field), (field,))
            for field in (
                "attributes",
                "scope",
                "lifecycle_status",
                "ambiguity",
                "execution",
            )
        }
        for requirement_id, state in states.items()
    }


def _affected_requirement_transitions(
    gold: dict[str, Any],
    event_refs: dict[str, list[dict[str, Any]]],
    pre_state: dict[str, dict[str, Any]],
    post_state: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    transitions: dict[str, dict[str, Any]] = {}
    for requirement_id in [str(value) for value in gold["affected_requirement_ids"]]:
        events = event_refs.get(requirement_id, [])
        if not events:
            raise RQInstanceError(
                f"affected Requirement {requirement_id!r} has no target Event"
            )
        raw_before = pre_state.get(requirement_id)
        raw_after = post_state.get(requirement_id)
        before = _semantic_state(raw_before)
        after = _semantic_state(raw_after)
        transitions[requirement_id] = {
            "event_ids": [deepcopy(event.get("event_id")) for event in events],
            "event_types": [deepcopy(event.get("event_type")) for event in events],
            "before": before,
            "after": after,
            "state_provenance": {
                "before_state_id": deepcopy(
                    raw_before.get("state_id") if raw_before else None
                ),
                "after_state_id": deepcopy(
                    raw_after.get("state_id") if raw_after else None
                ),
                "before_supporting_event_ids": deepcopy(
                    raw_before.get("supporting_event_ids", []) if raw_before else []
                ),
                "after_supporting_event_ids": deepcopy(
                    raw_after.get("supporting_event_ids", []) if raw_after else []
                ),
            },
            "delta": _state_delta(raw_before, raw_after),
        }
    return transitions


def _build_rq2_gold(
    relevance: dict[str, Any], pre_state: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    requirement_ids = relevance["relevant_requirement_ids"]
    states = {
        requirement_id: _semantic_state(pre_state[requirement_id])
        for requirement_id in requirement_ids
    }
    requirement_summaries = {
        requirement_id: deepcopy(pre_state[requirement_id].get("requirement_title"))
        for requirement_id in requirement_ids
    }
    alignment_evidence_message_ids = {
        requirement_id: deepcopy(
            relevance["evidence"][requirement_id]["trajectory_message_ids"]
        )
        for requirement_id in requirement_ids
    }
    state_provenance = {
        requirement_id: {
            "state_id": deepcopy(pre_state[requirement_id].get("state_id")),
            "supporting_event_ids": deepcopy(
                pre_state[requirement_id].get("supporting_event_ids", [])
            ),
        }
        for requirement_id in requirement_ids
    }
    return {
        "status": "PROVISIONAL_REQUIRES_FIELD_REVIEW",
        "gold_requirement_ids": deepcopy(requirement_ids),
        "requirement_summaries": requirement_summaries,
        "alignment_evidence_message_ids": alignment_evidence_message_ids,
        "state_provenance": state_provenance,
        "new_requirement_ids": deepcopy(relevance["new_requirement_ids"]),
        "states": states,
        "state_dimensions": [
            "attributes",
            "scope",
            "lifecycle_status",
            "ambiguity",
            "execution",
        ],
        "scoring_scope": {
            "selection_scored_here": False,
            "matched_requirements_only": True,
            "report_reconstruction_coverage_separately": True,
            "no_matched_requirement_result": "N/A",
        },
        "field_scoring_specs": _state_scoring_specs(states),
        "scoring_policy": {
            "closed_world_objects": True,
            "unexpected_fields": "FALSE_POSITIVE_AND_EXACT_FAILURE",
            "semantic_judge_outputs_final_scores": False,
            "primary_metrics": [
                "ATTRIBUTE_RECONSTRUCTION_SCORE",
                "MATCHED_FULL_STATE_EXACT",
                "RECONSTRUCTION_COVERAGE",
                "PER_DIMENSION_SCORES",
            ],
            "auxiliary_metrics": ["MATCHED_STATE_SCORE"],
        },
        "review_status": relevance["review_status"],
    }


def _build_rq3_gold(
    *,
    gold: dict[str, Any],
    event_refs: dict[str, list[dict[str, Any]]],
    pre_state: dict[str, dict[str, Any]],
    post_state: dict[str, dict[str, Any]],
    relevance: dict[str, Any],
    ambiguity_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    project_candidate = "CLARIFY" if ambiguity_candidates else "ACT"
    transitions = _affected_requirement_transitions(
        gold, event_refs, pre_state, post_state
    )
    affected_post_states = {
        requirement_id: deepcopy(transition["after"])
        for requirement_id, transition in transitions.items()
        if transition["after"] is not None
    }
    alignment_gold = {
        requirement_id: {
            "canonical_summary": deepcopy(
                (
                    post_state.get(requirement_id)
                    or pre_state.get(requirement_id)
                    or {}
                ).get("requirement_title")
            ),
            "introduced": requirement_id not in pre_state,
        }
        for requirement_id in transitions
    }
    return {
        "status": "PENDING_HUMAN_DECISION_REVIEW",
        "project_decision_candidate": {
            "value": project_candidate,
            "is_final_gold": False,
            "basis": (
                "OPEN ambiguity exists on a directly affected Requirement"
                if ambiguity_candidates
                else "No OPEN ambiguity exists on a directly affected Requirement"
            ),
        },
        "decision_candidates_by_condition": {
            "C1": {
                "value": project_candidate,
                "status": "PENDING_BLOCKING_AMBIGUITY_REVIEW",
            },
            "C2": {
                "value": project_candidate,
                "status": "PENDING_BLOCKING_AMBIGUITY_REVIEW",
            },
        },
        "final_gold_by_condition": {condition: None for condition in CONDITIONS},
        "affected_requirement_ids": [
            str(value) for value in gold["affected_requirement_ids"]
        ],
        "affected_requirement_alignment_gold": alignment_gold,
        "affected_requirement_transitions": transitions,
        "post_task_states": affected_post_states,
        "post_state_scoring_specs": _state_scoring_specs(affected_post_states),
        "blocking_ambiguity_candidates": deepcopy(ambiguity_candidates),
        "safe_subactions": [],
        "safe_subactions_review_status": "PENDING_MULTI_REQUIREMENT_REVIEW",
        "relevance_review_status": relevance["review_status"],
        "review_note": (
            "An OPEN ambiguity is only a candidate. It becomes blocking Gold "
            "after materiality, task relevance, alternative implementation, and "
            "available-evidence checks. C1 and C2 must freeze the same semantic "
            "Gold; a disagreement indicates an Oracle-history or review defect."
        ),
    }


def _build_rq4_gold(
    *,
    gold: dict[str, Any],
    event_refs: dict[str, list[dict[str, Any]]],
    pre_state: dict[str, dict[str, Any]],
    post_state: dict[str, dict[str, Any]],
    ambiguity_candidates: list[dict[str, Any]],
    relevance: dict[str, Any],
) -> dict[str, Any]:
    affected = [str(value) for value in gold["affected_requirement_ids"]]
    actions: dict[str, dict[str, Any]] = {}
    transitions = _affected_requirement_transitions(
        gold, event_refs, pre_state, post_state
    )
    for requirement_id in affected:
        before = pre_state.get(requirement_id)
        after = post_state.get(requirement_id)
        events = event_refs.get(requirement_id, [])
        actions[requirement_id] = _requirement_action_candidate(
            requirement_id, events, before, after
        )

    project_candidate = "CLARIFY" if ambiguity_candidates else "APPLY_CHANGES"
    return {
        "status": "PROVISIONAL_NOT_EXECUTION_READY",
        "task_action_candidates_by_condition": {
            "C1": {
                "value": project_candidate,
                "status": "PENDING_BLOCKING_AMBIGUITY_REVIEW",
            },
            "C2": {
                "value": project_candidate,
                "status": "PENDING_BLOCKING_AMBIGUITY_REVIEW",
            },
        },
        "requirement_action_candidates": actions,
        "affected_requirement_transitions": transitions,
        "inherited_constraint_actions": {},
        "inherited_constraint_review_status": relevance["review_status"],
        "acceptance_criteria": [],
        "validator_ids": [],
        "eligibility_by_condition": {
            condition: {
                "rq4_eligible": False,
                "status": "PENDING_RQ3_GOLD_AND_EXECUTION_REVIEW",
                "exclusion_reason": "RQ3_GOLD_OR_EXECUTION_ASSETS_NOT_FROZEN",
            }
            for condition in CONDITIONS
        },
        "execution_ready": False,
        "execution_readiness_blockers": [
            "FINAL_BLOCKING_AMBIGUITY_DECISION_REQUIRED",
            "INHERITED_CONSTRAINT_REVIEW_REQUIRED",
            "ACCEPTANCE_CRITERIA_REQUIRED",
            "HIDDEN_VALIDATORS_REQUIRED",
        ],
    }


def _instance_readiness(instance: Mapping[str, Any]) -> dict[str, Any]:
    """Describe construction and scoring readiness without changing Gold."""

    rq_id = str(instance.get("rq_id"))
    gold = instance.get("construction_gold")
    status = gold.get("status") if isinstance(gold, Mapping) else None
    blockers: list[str] = []
    formal_reasoning = False
    formal_execution = False
    if rq_id == "RQ1":
        formal_reasoning = status == "DETERMINISTIC_RQ1_GOLD"
        if not formal_reasoning:
            blockers.append("DETERMINISTIC_RQ1_GOLD_REQUIRED")
    elif rq_id == "RQ2":
        formal_reasoning = status == "FINAL_TYPED_STATE_GOLD"
        if not formal_reasoning:
            blockers.append("FIELD_COMPARATOR_REVIEW_REQUIRED")
    elif rq_id == "RQ3":
        formal_reasoning = status == "FINAL_UPDATE_OR_CLARIFY_GOLD"
        if not formal_reasoning:
            blockers.append("HUMAN_DECISION_REVIEW_REQUIRED")
    elif rq_id == "RQ4":
        formal_execution = bool(
            isinstance(gold, Mapping) and gold.get("execution_ready") is True
        )
        if not formal_execution:
            raw_blockers = gold.get("execution_readiness_blockers", []) if isinstance(gold, Mapping) else []
            blockers.extend(str(value) for value in raw_blockers)
    return {
        "construction": "COMPLETE",
        "smoke_allowed": True,
        "formal_reasoning_allowed": formal_reasoning,
        "formal_execution_allowed": formal_execution,
        "blockers": blockers,
    }


def _derive_applicable_rqs(
    *,
    relevance: dict[str, Any],
    target_event_refs: dict[str, list[dict[str, Any]]],
    code_environment_available: bool,
) -> list[str]:
    """Apply the benchmark's deterministic target/RQ materialization rules."""

    applicable: list[str] = []
    if relevance["relevant_requirement_ids"]:
        applicable.extend(["RQ1", "RQ2"])
    if target_event_refs:
        applicable.append("RQ3")
    if target_event_refs and code_environment_available:
        applicable.append("RQ4")
    return applicable


def build_rq_instances(
    gold_states: dict[str, Any],
    state_graph: dict[str, Any],
    normalized_project: dict[str, Any],
    *,
    rq_ids: Iterable[str] | None = None,
    input_release: str | None = None,
    code_environment_dir: str | Path | None = None,
    source_paths: Mapping[str, str | Path] | None = None,
    workspace_root: str | Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Build RQ instances selected by deterministic RQ-specific rules.

    Legacy ``primary_rq_targets`` values in Task Gold are intentionally ignored.
    Each emitted instance records the complete derived ``applicable_rqs`` list.
    """

    gold_states = _require_object(gold_states, "gold_states")
    state_graph = _require_object(state_graph, "state_graph")
    normalized_project = _require_object(normalized_project, "normalized_project")
    messages = _MessageIndex(normalized_project)
    graph = _GraphIndex(state_graph, messages)
    project_id = _validate_project_ids(gold_states, graph, messages)
    selected_rqs = tuple(rq_ids) if rq_ids is not None else RQ_IDS
    if (
        not selected_rqs
        or len(set(selected_rqs)) != len(selected_rqs)
        or any(rq_id not in RQ_IDS for rq_id in selected_rqs)
    ):
        raise RQInstanceError("rq_ids must be a non-empty unique subset of RQ1--RQ4")
    release = input_release or (
        f"{project_id}-"
        f"{_sha256_json([gold_states, state_graph, normalized_project])[:16]}"
    )
    root = Path(workspace_root).resolve() if workspace_root is not None else None
    code_env = _CodeEnvironmentIndex(
        (
            Path(code_environment_dir)
            if "RQ4" in selected_rqs and code_environment_dir is not None
            else None
        ),
        project_id=project_id,
        workspace_root=root,
    )
    normalized_sources = {
        name: Path(path) for name, path in (source_paths or {}).items()
    }
    reasoning_sources = _source_record(
        {
            name: path
            for name, path in normalized_sources.items()
            if name != "code_environment"
        },
        root,
    )
    execution_sources = _source_record(normalized_sources, root)

    collections: dict[str, list[dict[str, Any]]] = {rq_id: [] for rq_id in RQ_IDS}
    seen_targets: set[str] = set()
    rows = _require_array(
        gold_states.get("task_gold_states"), "gold_states.task_gold_states"
    )
    for position, raw_gold in enumerate(rows):
        gold = _require_object(raw_gold, f"task_gold_states[{position}]")
        target_id, target_message_id, target_position, history = _validate_target(
            gold, messages
        )
        if target_id in seen_targets:
            raise RQInstanceError(f"duplicate target_id {target_id!r}")
        seen_targets.add(target_id)

        pre_state = graph.expand_snapshot(
            gold.get("pre_task_gold_state"), f"{target_id}.pre_task_gold_state"
        )
        post_state = graph.expand_snapshot(
            gold.get("post_task_gold_state"), f"{target_id}.post_task_gold_state"
        )
        target_event_refs = _target_event_refs(gold, graph)
        before_boundary = gold["pre_task_gold_state"].get("boundary", {}).get(
            "before_message_id"
        )
        through_boundary = gold["post_task_gold_state"].get("boundary", {}).get(
            "through_message_id"
        )
        if _id_key(before_boundary) != _id_key(target_message_id):
            raise RQInstanceError(f"{target_id} Pre-task boundary mismatch")
        if _id_key(through_boundary) != _id_key(target_message_id):
            raise RQInstanceError(f"{target_id} Post-task boundary mismatch")

        relevance = _derive_relevance(
            gold, pre_state, graph, messages, target_position
        )
        ambiguity_candidates = _open_ambiguity_candidates(
            gold["affected_requirement_ids"], post_state
        )
        applicable_rqs = _derive_applicable_rqs(
            relevance=relevance,
            target_event_refs=target_event_refs,
            code_environment_available=code_env.has_target(target_id),
        )
        applicable_rqs = [
            rq_id for rq_id in applicable_rqs if rq_id in selected_rqs
        ]
        public_history = [messages.public_message(message) for message in history]
        target_fingerprint = _sha256_json(
            {
                "input_release": release,
                "project_id": project_id,
                "target_id": target_id,
                "target_message_id": target_message_id,
                "target_task": gold.get("target_task"),
                "history": public_history,
                "task_event_ids": gold.get("task_event_ids"),
                "affected_requirement_ids": gold.get("affected_requirement_ids"),
                "pre_task_gold_state": gold.get("pre_task_gold_state"),
                "post_task_gold_state": gold.get("post_task_gold_state"),
            }
        )

        for rq_id in selected_rqs:
            if rq_id not in applicable_rqs:
                continue
            instance = _common_instance(
                rq_id=rq_id,
                input_release=release,
                target_fingerprint=target_fingerprint,
                project_id=project_id,
                project_title=messages.project_title,
                gold=gold,
                target_id=target_id,
                target_message_id=target_message_id,
                history=history,
                messages=messages,
                relevance=relevance,
                applicable_rqs=applicable_rqs,
                sources=(
                    execution_sources if rq_id == "RQ4" else reasoning_sources
                ),
            )
            if rq_id == "RQ1":
                instance["construction_gold"] = _build_rq1_gold(
                    relevance, pre_state
                )
            elif rq_id == "RQ2":
                instance["construction_gold"] = _build_rq2_gold(
                    relevance, pre_state
                )
            elif rq_id == "RQ3":
                instance["construction_gold"] = _build_rq3_gold(
                    gold=gold,
                    event_refs=target_event_refs,
                    pre_state=pre_state,
                    post_state=post_state,
                    relevance=relevance,
                    ambiguity_candidates=ambiguity_candidates,
                )
            else:
                expected_event_types = [
                    graph.event_by_id[_id_key(event_id)][1]["event_type"]
                    for event_id in gold["task_event_ids"]
                ]
                instance["code_environment"] = code_env.describe(
                    target_id, gold, expected_event_types
                )
                instance["construction_gold"] = _build_rq4_gold(
                    gold=gold,
                    event_refs=target_event_refs,
                    pre_state=pre_state,
                    post_state=post_state,
                    ambiguity_candidates=ambiguity_candidates,
                    relevance=relevance,
                )
            instance["readiness"] = _instance_readiness(instance)
            errors = validate_rq_instance(instance)
            if errors:
                raise RQInstanceError(
                    f"constructed {instance['instance_id']} is invalid: "
                    + "; ".join(errors)
                )
            collections[rq_id].append(instance)

    for rq_id in RQ_IDS:
        collections[rq_id].sort(
            key=lambda row: messages.position(row["target_message_id"])
        )
    return collections


def _scoring_spec_issues(specs: Any, path: tuple[str, ...] = ()) -> list[str]:
    issues: list[str] = []
    if not isinstance(specs, dict):
        return [f"{'.'.join(path) or 'spec'} must be an object"]
    comparator = specs.get("comparator")
    if path and path[-1] in {
        "source_event_id",
        "ambiguity_event_id",
        "state_id",
        "requirement_id",
        "supporting_event_ids",
    } and specs.get("score") is not False:
        issues.append(f"internal provenance field {'.'.join(path)} is scoreable")
    if path in {
        ("scope", "persistence"),
        ("lifecycle_status",),
        ("execution", "status"),
    } and comparator not in {"NORMALIZED_EXACT", "SKIP"}:
        issues.append(f"enum field {'.'.join(path)} must use NORMALIZED_EXACT")
    for key, child in specs.get("fields", {}).items():
        issues.extend(_scoring_spec_issues(child, path + (str(key),)))
    for key, child in specs.get("item_fields", {}).items():
        issues.extend(_scoring_spec_issues(child, path + ("[]", str(key))))
    return issues


def _state_shape_issues(state: Any, label: str) -> list[str]:
    if not isinstance(state, dict):
        return [f"{label} must be an object"]
    issues: list[str] = []
    expected = {"attributes", "scope", "lifecycle_status", "ambiguity", "execution"}
    if set(state) != expected:
        issues.append(f"{label} must contain exactly the five semantic dimensions")
    ambiguity = state.get("ambiguity")
    if ambiguity is not None and not isinstance(ambiguity, list):
        issues.append(f"{label}.ambiguity must be null or an array")
    serialized = json.dumps(state, ensure_ascii=False)
    for forbidden in (
        "source_event_id",
        "ambiguity_event_id",
        "state_id",
        "supporting_event_ids",
    ):
        if f'"{forbidden}"' in serialized:
            issues.append(f"{label} contains internal provenance field {forbidden}")
    return issues


def validate_rq_instance(instance: dict[str, Any]) -> list[str]:
    """Return structural errors for one constructed instance."""

    errors: list[str] = []
    if not isinstance(instance, dict):
        return ["instance must be an object"]
    if instance.get("schema_version") != INSTANCE_SCHEMA_VERSION:
        errors.append("invalid schema_version")
    if not isinstance(instance.get("input_release"), str) or not instance.get(
        "input_release"
    ):
        errors.append("input_release must be a non-empty string")
    target_fingerprint = instance.get("target_fingerprint")
    if not isinstance(target_fingerprint, str) or not re.fullmatch(
        r"[0-9a-f]{64}", target_fingerprint
    ):
        errors.append("target_fingerprint must be a lowercase SHA-256")
    fingerprints = instance.get("fingerprints")
    if not isinstance(fingerprints, dict) or fingerprints.get(
        "target"
    ) != target_fingerprint:
        errors.append("fingerprints.target must equal target_fingerprint")
    rq_id = instance.get("rq_id")
    if rq_id not in RQ_IDS:
        errors.append("invalid rq_id")
    applicable_rqs = instance.get("applicable_rqs")
    if not isinstance(applicable_rqs, list):
        errors.append("applicable_rqs must be an array")
    else:
        if len(applicable_rqs) != len(set(applicable_rqs)):
            errors.append("applicable_rqs must not contain duplicates")
        if any(value not in RQ_IDS for value in applicable_rqs):
            errors.append("applicable_rqs contains an invalid rq_id")
        if rq_id in RQ_IDS and rq_id not in applicable_rqs:
            errors.append("applicable_rqs must contain this instance's rq_id")
    turns = instance.get("turns")
    if isinstance(turns, bool) or not isinstance(turns, int) or turns < 0:
        errors.append("turns must be a non-negative integer")
    else:
        if instance.get("history_turn_count") != turns:
            errors.append("history_turn_count must equal turns")
        if instance.get("difficulty") != difficulty_from_turns(turns):
            errors.append("difficulty does not match turns")
    history_pool = instance.get("history_pool")
    if not isinstance(history_pool, dict) or not isinstance(
        history_pool.get("messages"), list
    ):
        errors.append("history_pool.messages must be an array")
        history_messages: list[Any] = []
    else:
        history_messages = history_pool["messages"]
        if isinstance(turns, int) and len(history_messages) != turns:
            errors.append("history_pool message count does not equal turns")
        if history_pool.get("message_count") != len(history_messages):
            errors.append("history_pool.message_count is inconsistent")
    history_ids = [
        row.get("message_id") for row in history_messages if isinstance(row, dict)
    ]
    if len(history_ids) != len({_id_key(value) for value in history_ids}):
        errors.append("history_pool contains duplicate message IDs")
    if any(
        _id_key(value) == _id_key(instance.get("target_message_id"))
        for value in history_ids
    ):
        errors.append("history_pool contains the target message")

    condition_inputs = instance.get("condition_inputs")
    if not isinstance(condition_inputs, dict) or set(condition_inputs) != set(CONDITIONS):
        errors.append("condition_inputs must contain exactly C1 and C2")
    else:
        c1_ids = condition_inputs["C1"].get("history_message_ids")
        c2_ids = condition_inputs["C2"].get("history_message_ids")
        if c1_ids != history_ids:
            errors.append("C1 history IDs must equal the full history pool")
        c2_is_subset = isinstance(c2_ids, list) and {
            _id_key(value) for value in c2_ids
        }.issubset({_id_key(value) for value in history_ids})
        if not c2_is_subset:
            errors.append("C2 history must be a subset of C1")
        if c2_is_subset:
            positions = {
                _id_key(message_id): position
                for position, message_id in enumerate(history_ids)
            }
            c2_positions = [positions[_id_key(value)] for value in c2_ids]
            if c2_positions != sorted(c2_positions):
                errors.append("C2 history must preserve C1 order")
        for condition in CONDITIONS:
            record = condition_inputs[condition]
            ids = record.get("history_message_ids")
            if isinstance(ids, list) and record.get("history_message_count") != len(ids):
                errors.append(f"{condition} history_message_count is inconsistent")
    if rq_id == "RQ1" and condition_inputs and (
        condition_inputs["C1"].get("available") is not True
        or condition_inputs["C2"].get("available") is not False
    ):
        errors.append("RQ1 must be available only in C1")
    if rq_id in ("RQ2", "RQ3", "RQ4") and condition_inputs:
        if not all(condition_inputs[c].get("available") is True for c in CONDITIONS):
            errors.append(f"{rq_id} must expose C1 and C2")
    if rq_id == "RQ4":
        code_environment = instance.get("code_environment")
        if not isinstance(code_environment, dict) or not code_environment.get("available"):
            errors.append("RQ4 requires a Code Environment reference")
        elif code_environment.get("extracted_during_instance_construction") is not False:
            errors.append("RQ4 archive must not be extracted during construction")
        construction_gold = instance.get("construction_gold")
        eligibility = (
            construction_gold.get("eligibility_by_condition")
            if isinstance(construction_gold, dict)
            else None
        )
        if not isinstance(eligibility, dict) or set(eligibility) != set(CONDITIONS):
            errors.append("RQ4 eligibility must contain exactly C1 and C2")
        elif any(
            not isinstance(eligibility[condition], dict)
            or not isinstance(
                eligibility[condition].get("rq4_eligible"), bool
            )
            for condition in CONDITIONS
        ):
            errors.append("RQ4 condition eligibility records are invalid")
    if "construction_gold" not in instance:
        errors.append("construction_gold is required")
    elif rq_id == "RQ1":
        construction_gold = instance["construction_gold"]
        if not isinstance(construction_gold, dict):
            errors.append("RQ1 construction_gold must be an object")
        else:
            if construction_gold.get("status") != "DETERMINISTIC_RQ1_GOLD":
                errors.append("RQ1 Gold must have deterministic status")
            requirement_ids = construction_gold.get("relevant_requirement_ids")
            atoms = construction_gold.get("gold_requirement_atoms")
            if not isinstance(requirement_ids, list) or not requirement_ids:
                errors.append("RQ1 relevant_requirement_ids must be non-empty")
            elif not isinstance(atoms, dict) or set(atoms) != set(requirement_ids):
                errors.append(
                    "RQ1 gold_requirement_atoms must equal relevant_requirement_ids"
                )
            else:
                history_key_set = {_id_key(value) for value in history_ids}
                for requirement_id in requirement_ids:
                    atom = atoms[requirement_id]
                    groups = atom.get("required_evidence_groups") if isinstance(atom, dict) else None
                    if not isinstance(groups, list) or not groups:
                        errors.append(
                            f"RQ1 atom {requirement_id} requires evidence groups"
                        )
                        continue
                    group_ids: set[str] = set()
                    evidence_keys: set[str] = set()
                    for group in groups:
                        if not isinstance(group, dict):
                            errors.append(
                                f"RQ1 atom {requirement_id} has invalid evidence group"
                            )
                            continue
                        group_id = group.get("group_id")
                        acceptable = group.get("acceptable_message_ids")
                        if not isinstance(group_id, str) or not group_id:
                            errors.append(
                                f"RQ1 atom {requirement_id} has invalid group_id"
                            )
                        elif group_id in group_ids:
                            errors.append(
                                f"RQ1 atom {requirement_id} repeats group_id"
                            )
                        else:
                            group_ids.add(group_id)
                        if not isinstance(acceptable, list) or not acceptable:
                            errors.append(
                                f"RQ1 atom {requirement_id} has empty evidence group"
                            )
                            continue
                        acceptable_keys = {_id_key(value) for value in acceptable}
                        if not acceptable_keys.issubset(history_key_set):
                            errors.append(
                                f"RQ1 atom {requirement_id} evidence leaves history"
                            )
                        if evidence_keys.intersection(acceptable_keys):
                            errors.append(
                                f"RQ1 atom {requirement_id} evidence groups overlap"
                            )
                        evidence_keys.update(acceptable_keys)
                    neutral = atom.get("neutral_context_message_ids")
                    if not isinstance(neutral, list):
                        errors.append(
                            f"RQ1 atom {requirement_id} neutral context must be an array"
                        )
                    else:
                        neutral_keys = {_id_key(value) for value in neutral}
                        if not neutral_keys.issubset(history_key_set):
                            errors.append(
                                f"RQ1 atom {requirement_id} context leaves history"
                            )
                        if neutral_keys.intersection(evidence_keys):
                            errors.append(
                                f"RQ1 atom {requirement_id} required/context overlap"
                            )
    elif rq_id == "RQ2":
        construction_gold = instance["construction_gold"]
        contract = instance.get("response_contract", {})
        if contract.get("schema_version") != "rq2-agent-response-v3":
            errors.append("RQ2 response contract must use v3")
        states = construction_gold.get("states")
        specs = construction_gold.get("field_scoring_specs")
        requirement_ids = construction_gold.get("gold_requirement_ids")
        if not isinstance(requirement_ids, list) or not requirement_ids:
            errors.append("RQ2 gold_requirement_ids must be non-empty")
        elif not isinstance(states, dict) or set(states) != set(requirement_ids):
            errors.append("RQ2 states must equal gold_requirement_ids")
        elif not isinstance(specs, dict) or set(specs) != set(requirement_ids):
            errors.append("RQ2 scoring specs must equal gold_requirement_ids")
        else:
            for requirement_id in requirement_ids:
                errors.extend(
                    _state_shape_issues(
                        states[requirement_id], f"RQ2 states.{requirement_id}"
                    )
                )
                for dimension, spec in specs[requirement_id].items():
                    errors.extend(_scoring_spec_issues(spec, (dimension,)))
    elif rq_id == "RQ3":
        construction_gold = instance["construction_gold"]
        contract = instance.get("response_contract", {})
        if contract.get("schema_version") != "rq3-agent-response-v3":
            errors.append("RQ3 response contract must use v3")
        post_states = construction_gold.get("post_task_states")
        specs = construction_gold.get("post_state_scoring_specs")
        if not isinstance(post_states, dict) or not isinstance(specs, dict):
            errors.append("RQ3 post states and scoring specs must be objects")
        elif set(post_states) != set(specs):
            errors.append("RQ3 post states and scoring specs must have identical keys")
        else:
            for requirement_id, state in post_states.items():
                errors.extend(
                    _state_shape_issues(
                        state, f"RQ3 post_task_states.{requirement_id}"
                    )
                )
                for dimension, spec in specs[requirement_id].items():
                    errors.extend(_scoring_spec_issues(spec, (dimension,)))
        final = construction_gold.get("final_gold_by_condition")
        if construction_gold.get("status") == "FINAL_UPDATE_OR_CLARIFY_GOLD":
            if not isinstance(final, dict) or set(final) != set(CONDITIONS):
                errors.append("final RQ3 Gold must contain C1 and C2")
            elif any(not isinstance(final[condition], dict) for condition in CONDITIONS):
                errors.append("final RQ3 Gold cannot contain null branches")
            elif final["C1"] != final["C2"]:
                errors.append("final RQ3 Gold must be identical for C1 and C2")
    readiness = instance.get("readiness")
    if not isinstance(readiness, dict) or readiness.get("construction") != "COMPLETE":
        errors.append("readiness must describe a complete construction record")
    return errors


def build_rq_indexes(
    collections: Mapping[str, list[dict[str, Any]]]
) -> dict[str, dict[str, Any]]:
    """Build one deterministic index document per RQ folder."""

    indexes: dict[str, dict[str, Any]] = {}
    all_project_ids = {
        instance.get("project_id")
        for rq_id in RQ_IDS
        for instance in collections.get(rq_id, [])
    }
    if len(all_project_ids) > 1:
        raise RQInstanceError("RQ collections span multiple projects")
    collection_project_id = next(iter(all_project_ids), None)
    all_releases = {
        instance.get("input_release")
        for rq_id in RQ_IDS
        for instance in collections.get(rq_id, [])
    }
    if len(all_releases) > 1:
        raise RQInstanceError("RQ collections span multiple input releases")
    collection_release = next(iter(all_releases), None)
    for rq_id in RQ_IDS:
        instances = list(collections.get(rq_id, []))
        if any(instance.get("rq_id") != rq_id for instance in instances):
            raise RQInstanceError(f"{rq_id} collection contains a foreign instance")
        project_ids = {instance.get("project_id") for instance in instances}
        if len(project_ids) > 1:
            raise RQInstanceError(f"{rq_id} collection spans multiple projects")
        turns = [instance["turns"] for instance in instances]
        difficulties = Counter(instance["difficulty"] for instance in instances)
        indexes[rq_id] = {
            "schema_version": INDEX_SCHEMA_VERSION,
            "input_release": collection_release,
            "project_id": next(iter(project_ids), collection_project_id),
            "rq_id": rq_id,
            "rq_name": RQ_DEFINITIONS[rq_id]["name"],
            "instance_count": len(instances),
            "difficulty_distribution": {
                label: difficulties.get(label, 0)
                for label in ("SHORT", "MEDIUM", "LONG")
            },
            "turn_statistics": {
                "minimum": min(turns) if turns else None,
                "maximum": max(turns) if turns else None,
                "median": median(turns) if turns else None,
            },
            "instances": [
                {
                    "instance_id": instance["instance_id"],
                    "target_fingerprint": instance["target_fingerprint"],
                    "target_id": instance["target_id"],
                    "target_message_id": instance["target_message_id"],
                    "turns": instance["turns"],
                    "difficulty": instance["difficulty"],
                    "file": f"{instance['instance_id']}.json",
                    "content_sha256": _sha256_json(instance),
                }
                for instance in instances
            ],
        }
    return indexes


def build_project_manifest(
    collections: Mapping[str, list[dict[str, Any]]],
    indexes: Mapping[str, dict[str, Any]],
    *,
    project_id: str,
    rq_ids: Iterable[str] | None = None,
    input_release: str | None = None,
    source_paths: Mapping[str, str | Path] | None = None,
    workspace_root: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root).resolve() if workspace_root is not None else None
    source_records = _source_record(
        {name: Path(path) for name, path in (source_paths or {}).items()}, root
    )
    selected_rqs = tuple(rq_ids) if rq_ids is not None else RQ_IDS
    if (
        not selected_rqs
        or len(set(selected_rqs)) != len(selected_rqs)
        or any(rq_id not in RQ_IDS for rq_id in selected_rqs)
    ):
        raise RQInstanceError("rq_ids must be a non-empty unique subset of RQ1--RQ4")
    for rq_id in selected_rqs:
        if rq_id not in indexes:
            raise RQInstanceError(f"missing index for {rq_id}")
        if len(collections.get(rq_id, [])) != indexes[rq_id].get("instance_count"):
            raise RQInstanceError(f"{rq_id} index count does not match its collection")
    project_directory = (
        _portable_path(Path(output_dir), root)
        if output_dir is not None
        else f"outputs/stage2/{project_id}"
    )
    releases = {
        instance.get("input_release")
        for rq_id in selected_rqs
        for instance in collections.get(rq_id, [])
    }
    if input_release is not None:
        releases.add(input_release)
    releases.discard(None)
    if len(releases) != 1:
        raise RQInstanceError("project manifest requires exactly one input_release")
    release = next(iter(releases))

    targets: dict[str, dict[str, Any]] = {}
    for rq_id in selected_rqs:
        for instance in collections.get(rq_id, []):
            target_id = str(instance["target_id"])
            target = targets.setdefault(
                target_id,
                {
                    "target_id": target_id,
                    "target_message_id": deepcopy(instance["target_message_id"]),
                    "target_fingerprint": instance["target_fingerprint"],
                    "turns": instance["turns"],
                    "difficulty": instance["difficulty"],
                    "instances": {},
                    "conditions": {
                        condition: {
                            "history_mode": instance["condition_inputs"][condition][
                                "history_mode"
                            ],
                            "history_sha256": instance["fingerprints"][
                                "condition_history"
                            ][condition],
                            "active_rqs": [],
                        }
                        for condition in CONDITIONS
                    },
                },
            )
            for field in (
                "target_message_id",
                "target_fingerprint",
                "turns",
                "difficulty",
            ):
                if target[field] != instance[field]:
                    raise RQInstanceError(
                        f"target {target_id!r} has inconsistent shared field {field!r}"
                    )
            target["instances"][rq_id] = {
                "file": f"{rq_id}/{instance['instance_id']}.json",
                "content_sha256": _sha256_json(instance),
                "readiness": deepcopy(instance["readiness"]),
            }
            for condition in CONDITIONS:
                record = instance["condition_inputs"][condition]
                condition_record = target["conditions"][condition]
                if (
                    condition_record["history_mode"] != record["history_mode"]
                    or condition_record["history_sha256"]
                    != instance["fingerprints"]["condition_history"][condition]
                ):
                    raise RQInstanceError(
                        f"target {target_id!r} has inconsistent {condition} history"
                    )
                is_active = record.get("available") is True
                if rq_id == "RQ4":
                    gold = instance.get("construction_gold", {})
                    eligibility = gold.get("eligibility_by_condition", {}).get(
                        condition, {}
                    )
                    is_active = bool(
                        is_active
                        and eligibility.get("rq4_eligible") is True
                        and gold.get("execution_ready") is True
                    )
                if is_active:
                    condition_record["active_rqs"].append(rq_id)

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "input_release": release,
        "project_id": project_id,
        "construction_scope": "RQ_INSTANCES_ONLY_NO_EVALUATION",
        "layout": {
            "project_directory": project_directory,
            "rq_directories": list(selected_rqs),
            "one_json_file_per_target_rq_pair": True,
        },
        "condition_protocol": {
            "C1": "FULL_HISTORY",
            "C2": "ORACLE_RELEVANT_HISTORY",
            "no_history_is_formal_condition": False,
        },
        "turns_policy": {
            "definition": "number of normalized messages strictly before target_message_id",
            "difficulty_bins": {
                "SHORT": "0-25",
                "MEDIUM": "26-50",
                "LONG": ">50",
            },
        },
        "inclusion_policy": (
            "Derive applicable_rqs deterministically: RQ1 and RQ2 require a "
            "relevant historical Requirement; RQ3 requires an affected target "
            "transition; an RQ4 candidate requires an affected transition and a "
            "matching target Code Environment."
        ),
        "applicability_policy": {
            "RQ1": "HAS_RELEVANT_HISTORICAL_REQUIREMENT",
            "RQ2": "HAS_RELEVANT_HISTORICAL_REQUIREMENT",
            "RQ3": "HAS_AFFECTED_TARGET_TRANSITION",
            "RQ4": "AFFECTED_TRANSITION_AND_MATCHING_CODE_ENVIRONMENT",
        },
        "rq_counts": {
            rq_id: indexes[rq_id]["instance_count"] for rq_id in selected_rqs
        },
        "total_instance_count": sum(
            indexes[rq_id]["instance_count"] for rq_id in selected_rqs
        ),
        "targets": [targets[target_id] for target_id in sorted(targets)],
        "source_artifacts": source_records,
        "construction_boundaries": {
            "evaluation_implemented": {
                "RQ1": True,
                "RQ2": True,
                "RQ3": True,
                "RQ4": False,
            },
            "rq2_formal_scores_require_final_field_review": True,
            "rq3_formal_scores_require_frozen_condition_gold": True,
            "rq4_archives_extracted": False,
            "human_review_required": True,
        },
    }


__all__ = [
    "CONDITIONS",
    "INDEX_SCHEMA_VERSION",
    "INSTANCE_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "RQ_DEFINITIONS",
    "RQ_IDS",
    "RQInstanceError",
    "build_project_manifest",
    "build_rq_indexes",
    "build_rq_instances",
    "difficulty_from_turns",
    "validate_rq_instance",
]
