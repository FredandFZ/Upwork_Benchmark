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


INSTANCE_SCHEMA_VERSION = "rq-instance-v1"
INDEX_SCHEMA_VERSION = "rq-instance-index-v1"
MANIFEST_SCHEMA_VERSION = "rq-instance-manifest-v1"

RQ_IDS = ("RQ1", "RQ2", "RQ3", "RQ4")
CONDITIONS = ("C1", "C2", "C3")

RQ_DEFINITIONS: dict[str, dict[str, Any]] = {
    "RQ1": {
        "name": "Relevant Requirement Selection",
        "question": (
            "Using the full pre-task conversation, identify the historical "
            "requirements and message evidence that are relevant to the current "
            "client task. Exclude unrelated history and do not treat the current "
            "task itself as historical evidence."
        ),
        "supported_conditions": ["C2"],
    },
    "RQ2": {
        "name": "Current Requirement State Reconstruction",
        "question": (
            "Reconstruct the currently valid state of every historical "
            "requirement needed to understand the current client task, resolving "
            "superseded values and preserving still-active constraints."
        ),
        "supported_conditions": ["C1", "C2", "C3"],
    },
    "RQ3": {
        "name": "Memory-or-Clarify Decision",
        "question": (
            "Given only the evidence available in this condition, decide whether "
            "it is safe to act on the current client task or whether a concrete "
            "clarification is required."
        ),
        "supported_conditions": ["C1", "C2", "C3"],
    },
    "RQ4": {
        "name": "Requirement-to-Code Execution",
        "question": (
            "Translate the current client task and the valid requirement state "
            "into the appropriate development action in the supplied pre-task "
            "repository. Clarify instead of making a speculative change when "
            "the available evidence is insufficient."
        ),
        "supported_conditions": ["C1", "C2", "C3"],
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

    for requirement_id in direct_historical:
        state = pre_state[requirement_id]
        current_support_event_ids = deepcopy(state["supporting_event_ids"])
        trajectory = graph.trajectory_before(
            requirement_id, target_position, messages
        )
        trajectory_event_ids = [edge["event_id"] for edge in trajectory]
        core_message_ids = _ordered_message_ids(
            [edge["source_message_id"] for edge in trajectory],
            messages,
            target_position,
        )
        current_support_message_ids = _ordered_message_ids(
            [
                graph.event_by_id[_id_key(event_id)][1]["source_message_id"]
                for event_id in current_support_event_ids
            ],
            messages,
            target_position,
        )
        evidence[requirement_id] = {
            "current_support_event_ids": current_support_event_ids,
            "current_support_message_ids": current_support_message_ids,
            "trajectory_event_ids": trajectory_event_ids,
            "core_message_ids": core_message_ids,
            "context_message_ids": [],
            "context_review_status": "PENDING_CONTEXT_MESSAGE_REVIEW",
        }
        oracle_message_ids.extend(core_message_ids)

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
        "review_status": "PENDING_INHERITED_CONSTRAINT_AND_CONTEXT_REVIEW",
        "review_note": (
            "Direct historical Requirements and Event trajectories are "
            "deterministic. Applicable preserved constraints and contextual "
            "messages require the causal-necessity review defined by the design."
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
            mode = "NO_HISTORY"
            ids: list[Any] = []
            review_status = "NOT_APPLICABLE"
        elif condition == "C2":
            mode = "FULL_HISTORY"
            ids = deepcopy(full_history_ids)
            review_status = "DETERMINISTIC"
        else:
            mode = "ORACLE_RELEVANT_HISTORY"
            ids = deepcopy(oracle_history_ids)
            review_status = "PENDING_CONTEXT_AND_INHERITED_CONSTRAINT_REVIEW"
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
            "schema_version": "rq1-agent-response-v1",
            "required_fields": [
                "selected_history_message_ids",
                "requirements",
            ],
            "requirement_item_fields": [
                "requirement_ref",
                "requirement_summary",
                "evidence_message_ids",
            ],
        }
    if rq_id == "RQ2":
        return {
            "schema_version": "rq2-agent-response-v1",
            "required_fields": ["requirements"],
            "requirement_item_fields": [
                "requirement_ref",
                "requirement_summary",
                "evidence_message_ids",
                "current_state",
            ],
            "current_state_fields": [
                "attributes",
                "scope",
                "lifecycle_status",
                "ambiguity",
                "execution",
            ],
        }
    if rq_id == "RQ3":
        return {
            "schema_version": "rq3-agent-response-v1",
            "required_fields": ["decision", "clarification"],
            "decision_values": ["ACT", "CLARIFY"],
        }
    return {
        "schema_version": "rq4-agent-response-v1",
        "required_fields": ["decision", "planned_actions"],
        "decision_values": ["ACT", "CLARIFY"],
        "action_values": ["IMPLEMENT", "MODIFY", "REMOVE", "PRESERVE"],
        "repository_result": (
            "When decision=ACT, the evaluation runner will separately capture "
            "the patch, changed files, command logs, and repository hash."
        ),
    }


def _semantic_state(state: dict[str, Any] | None) -> dict[str, Any] | None:
    if state is None:
        return None
    return {
        key: deepcopy(state.get(key))
        for key in (
            "attributes",
            "scope",
            "lifecycle_status",
            "ambiguity",
            "execution",
        )
    }


def _state_delta(
    before: dict[str, Any] | None, after: dict[str, Any] | None
) -> dict[str, Any]:
    if before is None:
        return {"change_type": "INTRODUCED", "changed_fields": ["existence"]}
    if after is None:
        return {"change_type": "REMOVED_FROM_SNAPSHOT", "changed_fields": ["existence"]}
    fields = [
        key
        for key in (
            "attributes",
            "scope",
            "lifecycle_status",
            "ambiguity",
            "execution",
        )
        if before.get(key) != after.get(key)
    ]
    return {
        "change_type": "MODIFIED" if fields else "UNCHANGED",
        "changed_fields": fields,
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
                    "description": deepcopy(ambiguity.get("description")),
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
    project_id: str,
    project_title: Any,
    gold: dict[str, Any],
    target_id: str,
    target_message_id: Any,
    history: list[dict[str, Any]],
    messages: _MessageIndex,
    relevance: dict[str, Any],
    sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    turns = len(history)
    full_history_ids = [message["message_id"] for message in history]
    return {
        "schema_version": INSTANCE_SCHEMA_VERSION,
        "instance_id": f"{target_id}_{rq_id}",
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
        "selection_basis": {
            "source": "task_gold.primary_rq_targets",
            "final_rq_eligibility": "PENDING_RQ_SPECIFIC_REVIEW",
        },
        "question": RQ_DEFINITIONS[rq_id]["question"],
        "target_task": deepcopy(gold["target_task"]),
        "history_pool": {
            "boundary": "STRICTLY_BEFORE_TARGET_MESSAGE",
            "contains_target_message": False,
            "message_count": turns,
            "messages": [messages.public_message(message) for message in history],
        },
        "condition_inputs": _condition_inputs(
            rq_id,
            full_history_ids,
            relevance["oracle_history_message_ids"],
        ),
        "response_contract": _response_contract(rq_id),
        "visibility": {
            "record_kind": "RESEARCHER_SIDE_CONSTRUCTION_INSTANCE",
            "runner_must_hide": [
                "construction_gold",
                "source_artifacts",
                "selection_basis",
            ],
            "runner_materialization_status": "NOT_IMPLEMENTED_IN_THIS_STAGE",
        },
        "source_artifacts": deepcopy(sources),
    }


def _build_rq1_gold(relevance: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "PROVISIONAL_REQUIRES_RELEVANCE_REVIEW",
        "relevant_requirement_ids": deepcopy(relevance["relevant_requirement_ids"]),
        "directly_affected_historical_requirement_ids": deepcopy(
            relevance["directly_affected_historical_requirement_ids"]
        ),
        "inherited_constraint_requirement_ids": [],
        "new_requirement_ids": deepcopy(relevance["new_requirement_ids"]),
        "evidence": deepcopy(relevance["evidence"]),
        "derivation_scope": relevance["derivation_scope"],
        "review_status": relevance["review_status"],
    }


def _build_rq2_gold(
    relevance: dict[str, Any], pre_state: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    requirement_ids = relevance["relevant_requirement_ids"]
    return {
        "status": "PROVISIONAL_REQUIRES_RELEVANCE_REVIEW",
        "gold_requirement_ids": deepcopy(requirement_ids),
        "new_requirement_ids": deepcopy(relevance["new_requirement_ids"]),
        "states": {
            requirement_id: deepcopy(pre_state[requirement_id])
            for requirement_id in requirement_ids
        },
        "state_dimensions": [
            "selection",
            "attributes",
            "lifecycle",
            "scope",
            "ambiguity",
            "execution",
        ],
        "review_status": relevance["review_status"],
    }


def _build_rq3_gold(
    relevance: dict[str, Any], ambiguity_candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    project_candidate = "CLARIFY" if ambiguity_candidates else "ACT"
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
                "value": None,
                "status": "PENDING_EVIDENCE_SUFFICIENCY_REVIEW",
            },
            "C2": {
                "value": project_candidate,
                "status": "PENDING_BLOCKING_AMBIGUITY_REVIEW",
            },
            "C3": {
                "value": project_candidate,
                "status": "PENDING_BLOCKING_AMBIGUITY_REVIEW",
            },
        },
        "blocking_ambiguity_candidates": deepcopy(ambiguity_candidates),
        "safe_subactions": [],
        "safe_subactions_review_status": "PENDING_MULTI_REQUIREMENT_REVIEW",
        "relevance_review_status": relevance["review_status"],
        "review_note": (
            "An OPEN ambiguity is only a candidate. It becomes blocking Gold "
            "after materiality, task relevance, alternative implementation, and "
            "available-evidence checks. C1 must be audited independently."
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
    transitions: dict[str, dict[str, Any]] = {}
    for requirement_id in affected:
        before = pre_state.get(requirement_id)
        after = post_state.get(requirement_id)
        events = event_refs.get(requirement_id, [])
        if not events:
            raise RQInstanceError(
                f"affected Requirement {requirement_id!r} has no target Event"
            )
        actions[requirement_id] = _requirement_action_candidate(
            requirement_id, events, before, after
        )
        transitions[requirement_id] = {
            "before": deepcopy(before),
            "after": deepcopy(after),
            "delta": _state_delta(before, after),
        }

    project_candidate = "CLARIFY" if ambiguity_candidates else "APPLY_CHANGES"
    return {
        "status": "PROVISIONAL_NOT_EXECUTION_READY",
        "task_action_candidates_by_condition": {
            "C1": {
                "value": None,
                "status": "PENDING_EVIDENCE_SUFFICIENCY_REVIEW",
            },
            "C2": {
                "value": project_candidate,
                "status": "PENDING_BLOCKING_AMBIGUITY_REVIEW",
            },
            "C3": {
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
        "execution_ready": False,
        "execution_readiness_blockers": [
            "FINAL_BLOCKING_AMBIGUITY_DECISION_REQUIRED",
            "INHERITED_CONSTRAINT_REVIEW_REQUIRED",
            "ACCEPTANCE_CRITERIA_REQUIRED",
            "HIDDEN_VALIDATORS_REQUIRED",
        ],
    }


def build_rq_instances(
    gold_states: dict[str, Any],
    state_graph: dict[str, Any],
    normalized_project: dict[str, Any],
    *,
    code_environment_dir: str | Path | None = None,
    source_paths: Mapping[str, str | Path] | None = None,
    workspace_root: str | Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Build all provisionally selected RQ instances for one project.

    A target is materialized under an RQ when that RQ occurs in the finalized
    Task Gold ``primary_rq_targets``.  The tag is treated as a construction
    inclusion signal, not as final RQ-specific eligibility.
    """

    gold_states = _require_object(gold_states, "gold_states")
    state_graph = _require_object(state_graph, "state_graph")
    normalized_project = _require_object(normalized_project, "normalized_project")
    messages = _MessageIndex(normalized_project)
    graph = _GraphIndex(state_graph, messages)
    project_id = _validate_project_ids(gold_states, graph, messages)
    root = Path(workspace_root).resolve() if workspace_root is not None else None
    code_env = _CodeEnvironmentIndex(
        Path(code_environment_dir) if code_environment_dir is not None else None,
        project_id=project_id,
        workspace_root=root,
    )
    normalized_sources = {
        name: Path(path) for name, path in (source_paths or {}).items()
    }
    sources = _source_record(normalized_sources, root)

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

        rq_targets = _require_array(
            gold.get("primary_rq_targets"), f"{target_id}.primary_rq_targets"
        )
        if not rq_targets:
            raise RQInstanceError(f"{target_id}.primary_rq_targets cannot be empty")
        if len({_id_key(value) for value in rq_targets}) != len(rq_targets):
            raise RQInstanceError(f"{target_id}.primary_rq_targets has duplicates")
        unknown = [value for value in rq_targets if value not in RQ_IDS]
        if unknown:
            raise RQInstanceError(
                f"{target_id}.primary_rq_targets contains unsupported values: {unknown}"
            )

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

        for rq_id in RQ_IDS:
            if rq_id not in rq_targets:
                continue
            instance = _common_instance(
                rq_id=rq_id,
                project_id=project_id,
                project_title=messages.project_title,
                gold=gold,
                target_id=target_id,
                target_message_id=target_message_id,
                history=history,
                messages=messages,
                relevance=relevance,
                sources=sources,
            )
            if rq_id == "RQ1":
                instance["construction_gold"] = _build_rq1_gold(relevance)
            elif rq_id == "RQ2":
                instance["construction_gold"] = _build_rq2_gold(
                    relevance, pre_state
                )
            elif rq_id == "RQ3":
                instance["construction_gold"] = _build_rq3_gold(
                    relevance, ambiguity_candidates
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


def validate_rq_instance(instance: dict[str, Any]) -> list[str]:
    """Return structural errors for one constructed instance."""

    errors: list[str] = []
    if not isinstance(instance, dict):
        return ["instance must be an object"]
    if instance.get("schema_version") != INSTANCE_SCHEMA_VERSION:
        errors.append("invalid schema_version")
    rq_id = instance.get("rq_id")
    if rq_id not in RQ_IDS:
        errors.append("invalid rq_id")
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
        errors.append("condition_inputs must contain exactly C1, C2, and C3")
    else:
        c1_ids = condition_inputs["C1"].get("history_message_ids")
        c2_ids = condition_inputs["C2"].get("history_message_ids")
        c3_ids = condition_inputs["C3"].get("history_message_ids")
        if c1_ids != []:
            errors.append("C1 history must be empty")
        if c2_ids != history_ids:
            errors.append("C2 history IDs must equal the full history pool")
        if not isinstance(c3_ids, list) or not {
            _id_key(value) for value in c3_ids
        }.issubset({_id_key(value) for value in history_ids}):
            errors.append("C3 history must be a subset of C2")
        for condition in CONDITIONS:
            record = condition_inputs[condition]
            ids = record.get("history_message_ids")
            if isinstance(ids, list) and record.get("history_message_count") != len(ids):
                errors.append(f"{condition} history_message_count is inconsistent")
    if rq_id == "RQ1" and condition_inputs and (
        condition_inputs["C1"].get("available") is not False
        or condition_inputs["C2"].get("available") is not True
        or condition_inputs["C3"].get("available") is not False
    ):
        errors.append("RQ1 must be available only in C2")
    if rq_id in ("RQ2", "RQ3", "RQ4") and condition_inputs:
        if not all(condition_inputs[c].get("available") is True for c in CONDITIONS):
            errors.append(f"{rq_id} must expose C1, C2, and C3")
    if rq_id == "RQ4":
        code_environment = instance.get("code_environment")
        if not isinstance(code_environment, dict) or not code_environment.get("available"):
            errors.append("RQ4 requires a Code Environment reference")
        elif code_environment.get("extracted_during_instance_construction") is not False:
            errors.append("RQ4 archive must not be extracted during construction")
    if "construction_gold" not in instance:
        errors.append("construction_gold is required")
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
                    "target_id": instance["target_id"],
                    "target_message_id": instance["target_message_id"],
                    "turns": instance["turns"],
                    "difficulty": instance["difficulty"],
                    "file": f"{instance['instance_id']}.json",
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
    source_paths: Mapping[str, str | Path] | None = None,
    workspace_root: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root).resolve() if workspace_root is not None else None
    source_records = _source_record(
        {name: Path(path) for name, path in (source_paths or {}).items()}, root
    )
    for rq_id in RQ_IDS:
        if rq_id not in indexes:
            raise RQInstanceError(f"missing index for {rq_id}")
        if len(collections.get(rq_id, [])) != indexes[rq_id].get("instance_count"):
            raise RQInstanceError(f"{rq_id} index count does not match its collection")
    project_directory = (
        _portable_path(Path(output_dir), root)
        if output_dir is not None
        else f"outputs/stage2/{project_id}"
    )
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "project_id": project_id,
        "construction_scope": "RQ_INSTANCES_ONLY_NO_EVALUATION",
        "layout": {
            "project_directory": project_directory,
            "rq_directories": list(RQ_IDS),
            "one_json_file_per_target_rq_pair": True,
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
            "Create a target/RQ pair when the finalized Task Gold lists the RQ "
            "in primary_rq_targets; final RQ-specific eligibility remains pending."
        ),
        "rq_counts": {
            rq_id: indexes[rq_id]["instance_count"] for rq_id in RQ_IDS
        },
        "total_instance_count": sum(
            indexes[rq_id]["instance_count"] for rq_id in RQ_IDS
        ),
        "source_artifacts": source_records,
        "construction_boundaries": {
            "evaluation_implemented": False,
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
