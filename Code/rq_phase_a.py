"""Validation and immutable capture of a ReqMemBench Phase A response."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
import json


PRIVATE_MANIFEST_SCHEMA_VERSION = "rq-private-run-manifest-v1"
FREEZE_RECORD_SCHEMA_VERSION = "rq-phase-a-freeze-v1"
RUN_STATUS_SCHEMA_VERSION = "rq-run-status-v1"
PUBLIC_FILENAMES = (
    "task.json",
    "history.jsonl",
    "instructions.md",
    "response.schema.json",
)
STATE_FIELDS = {
    "attributes",
    "scope",
    "lifecycle_status",
    "ambiguity",
    "execution",
}


class RQPhaseAError(ValueError):
    """Raised when a Phase A response cannot be safely frozen."""


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RQPhaseAError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RQPhaseAError(f"{label} must be a JSON object")
    return value


def _sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise RQPhaseAError(f"cannot hash {path}: {exc}") from exc


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RQPhaseAError(f"{label} must be a non-empty string")
    return value


def _validate_state(value: Any, label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != STATE_FIELDS:
        raise RQPhaseAError(f"{label} must contain exactly {sorted(STATE_FIELDS)}")
    if not isinstance(value.get("attributes"), Mapping):
        raise RQPhaseAError(f"{label}.attributes must be an object")
    if not isinstance(value.get("scope"), Mapping):
        raise RQPhaseAError(f"{label}.scope must be an object")
    lifecycle = value.get("lifecycle_status")
    if lifecycle is not None and not isinstance(lifecycle, str):
        raise RQPhaseAError(f"{label}.lifecycle_status must be string or null")
    ambiguity = value.get("ambiguity")
    if ambiguity is not None and (
        not isinstance(ambiguity, list)
        or any(not isinstance(row, Mapping) for row in ambiguity)
    ):
        raise RQPhaseAError(f"{label}.ambiguity must be null or an object array")
    execution = value.get("execution")
    if execution is not None and not isinstance(execution, Mapping):
        raise RQPhaseAError(f"{label}.execution must be object or null")


def _validate_ref(value: Any, label: str) -> str:
    ref = _text(value, label)
    if ref.casefold().startswith("req_"):
        raise RQPhaseAError(f"{label} must not expose an internal Requirement ID")
    return ref


def validate_unified_response(
    response: Mapping[str, Any],
    *,
    visible_message_ids: set[str],
) -> dict[str, Any]:
    """Validate the public unified response without consulting private Gold."""

    if not isinstance(response, Mapping):
        raise RQPhaseAError("Agent response must be an object")
    top_fields = {"requirements", "decision", "post_task_states", "clarifications"}
    if set(response) != top_fields:
        raise RQPhaseAError(
            "Agent response must contain exactly " f"{sorted(top_fields)}"
        )
    requirements = response.get("requirements")
    if not isinstance(requirements, list):
        raise RQPhaseAError("requirements must be an array")
    refs: set[str] = set()
    requirement_fields = {
        "requirement_ref",
        "requirement_summary",
        "evidence_message_ids",
        "pre_task_state",
    }
    for index, row in enumerate(requirements):
        label = f"requirements[{index}]"
        if not isinstance(row, Mapping) or set(row) != requirement_fields:
            raise RQPhaseAError(
                f"{label} must contain exactly {sorted(requirement_fields)}"
            )
        ref = _validate_ref(row.get("requirement_ref"), f"{label}.requirement_ref")
        if ref in refs:
            raise RQPhaseAError(f"duplicate requirement_ref {ref!r}")
        refs.add(ref)
        _text(row.get("requirement_summary"), f"{label}.requirement_summary")
        evidence = row.get("evidence_message_ids")
        if not isinstance(evidence, list) or any(
            isinstance(value, bool) or not isinstance(value, (str, int))
            for value in evidence
        ):
            raise RQPhaseAError(f"{label}.evidence_message_ids is invalid")
        evidence_keys = [str(value) for value in evidence]
        if len(evidence_keys) != len(set(evidence_keys)):
            raise RQPhaseAError(f"{label}.evidence_message_ids contains duplicates")
        if not set(evidence_keys).issubset(visible_message_ids):
            raise RQPhaseAError(f"{label} cites a message outside visible history")
        _validate_state(row.get("pre_task_state"), f"{label}.pre_task_state")

    decision = response.get("decision")
    post_states = response.get("post_task_states")
    clarifications = response.get("clarifications")
    if decision == "ACT":
        if not isinstance(post_states, list) or not post_states:
            raise RQPhaseAError("ACT requires non-empty post_task_states")
        if clarifications != []:
            raise RQPhaseAError("ACT requires clarifications=[]")
        post_fields = {
            "requirement_ref",
            "requirement_summary",
            "change_type",
            "removed_attribute_keys",
            "state",
        }
        post_refs: set[str] = set()
        for index, row in enumerate(post_states):
            label = f"post_task_states[{index}]"
            if not isinstance(row, Mapping) or set(row) != post_fields:
                raise RQPhaseAError(
                    f"{label} must contain exactly {sorted(post_fields)}"
                )
            ref = _validate_ref(row.get("requirement_ref"), f"{label}.requirement_ref")
            if ref in post_refs:
                raise RQPhaseAError(f"duplicate post-state requirement_ref {ref!r}")
            post_refs.add(ref)
            _text(row.get("requirement_summary"), f"{label}.requirement_summary")
            _text(row.get("change_type"), f"{label}.change_type")
            removed = row.get("removed_attribute_keys")
            if (
                not isinstance(removed, list)
                or any(not isinstance(value, str) or not value for value in removed)
                or len(removed) != len(set(removed))
            ):
                raise RQPhaseAError(
                    f"{label}.removed_attribute_keys must be unique strings"
                )
            _validate_state(row.get("state"), f"{label}.state")
    elif decision == "CLARIFY":
        if post_states is not None:
            raise RQPhaseAError("CLARIFY requires post_task_states=null")
        if not isinstance(clarifications, list) or not clarifications:
            raise RQPhaseAError("CLARIFY requires non-empty clarifications")
        clarification_fields = {
            "requirement_ref",
            "requirement_summary",
            "dimension",
            "field",
            "missing_information",
            "question",
        }
        dimensions = {
            "VALUE",
            "SCOPE",
            "LIFECYCLE",
            "BEHAVIOR",
            "DEPENDENCY",
            "EXECUTION",
        }
        for index, row in enumerate(clarifications):
            label = f"clarifications[{index}]"
            if not isinstance(row, Mapping) or set(row) != clarification_fields:
                raise RQPhaseAError(
                    f"{label} must contain exactly {sorted(clarification_fields)}"
                )
            _validate_ref(row.get("requirement_ref"), f"{label}.requirement_ref")
            _text(row.get("requirement_summary"), f"{label}.requirement_summary")
            if row.get("dimension") not in dimensions:
                raise RQPhaseAError(f"{label}.dimension is invalid")
            if row.get("field") is not None and not isinstance(row.get("field"), str):
                raise RQPhaseAError(f"{label}.field must be string or null")
            _text(row.get("missing_information"), f"{label}.missing_information")
            _text(row.get("question"), f"{label}.question")
    else:
        raise RQPhaseAError("decision must be ACT or CLARIFY")
    return deepcopy(dict(response))


def _validate_public_workspace(
    public_dir: Path,
    manifest: Mapping[str, Any],
) -> set[str]:
    expected_hashes = manifest.get("public_files")
    if not isinstance(expected_hashes, Mapping) or set(expected_hashes) != set(
        PUBLIC_FILENAMES
    ):
        raise RQPhaseAError("private manifest has invalid public file hashes")
    if (public_dir / "repository").exists():
        raise RQPhaseAError("Phase A public workspace must not contain a repository")
    for name in PUBLIC_FILENAMES:
        path = public_dir / name
        if not path.is_file() or _file_sha256(path) != expected_hashes[name]:
            raise RQPhaseAError(f"Phase A public input changed: {name}")
    visible_ids: list[str] = []
    try:
        lines = (public_dir / "history.jsonl").read_text(
            encoding="utf-8-sig"
        ).splitlines()
        for index, line in enumerate(lines):
            row = json.loads(line)
            if not isinstance(row, dict) or isinstance(row.get("message_id"), bool):
                raise RQPhaseAError(f"history.jsonl line {index + 1} is invalid")
            visible_ids.append(str(row.get("message_id")))
    except (OSError, json.JSONDecodeError) as exc:
        raise RQPhaseAError(f"cannot validate history.jsonl: {exc}") from exc
    if len(visible_ids) != len(set(visible_ids)):
        raise RQPhaseAError("history.jsonl contains duplicate message IDs")
    return set(visible_ids)


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def freeze_phase_a_response(
    *,
    private_manifest_path: str | Path,
    public_dir: str | Path,
    response_path: str | Path,
    freeze_root: str | Path,
) -> dict[str, Any]:
    """Validate, content-address, and freeze one Phase A structured response."""

    private_path = Path(private_manifest_path).resolve()
    manifest = _read_object(private_path, "private run manifest")
    if manifest.get("schema_version") != PRIVATE_MANIFEST_SCHEMA_VERSION:
        raise RQPhaseAError("unsupported private run manifest schema")
    gate = manifest.get("phase_gate")
    if not isinstance(gate, dict) or gate.get("phase_a_response_sha256") is not None:
        raise RQPhaseAError("Phase A response is already frozen or gate is malformed")
    visible_ids = _validate_public_workspace(Path(public_dir).resolve(), manifest)
    response = validate_unified_response(
        _read_object(Path(response_path), "Agent response"),
        visible_message_ids=visible_ids,
    )
    frozen_bytes = (
        json.dumps(response, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    response_sha256 = _sha256_bytes(frozen_bytes)
    frozen_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    run_id = _text(manifest.get("run_id"), "private manifest.run_id")
    freeze_dir = Path(freeze_root).resolve() / run_id / "phase_a"
    if freeze_dir.exists():
        raise RQPhaseAError(f"freeze destination already exists: {freeze_dir}")
    freeze_dir.mkdir(parents=True)
    response_target = freeze_dir / "agent_response.json"
    response_target.write_bytes(frozen_bytes)
    (freeze_dir / "agent_response.sha256").write_text(
        response_sha256 + "\n", encoding="ascii"
    )

    rq4 = manifest.get("rq4") if isinstance(manifest.get("rq4"), Mapping) else {}
    rq4_eligible = rq4.get("eligible") is True
    rq4_ready = rq4.get("execution_ready") is True
    phase_b_open = response["decision"] == "ACT" and rq4_eligible and rq4_ready
    if response["decision"] != "ACT":
        phase_b_reason = "AGENT_DECISION_NOT_ACT"
    elif not rq4_eligible:
        phase_b_reason = "RQ4_NOT_ELIGIBLE"
    elif not rq4_ready:
        phase_b_reason = "RQ4_NOT_EXECUTION_READY"
    else:
        phase_b_reason = None

    freeze_record = {
        "schema_version": FREEZE_RECORD_SCHEMA_VERSION,
        "run_id": run_id,
        "target_id": manifest.get("target_id"),
        "condition": manifest.get("condition"),
        "decision": response["decision"],
        "response_sha256": response_sha256,
        "frozen_at": frozen_at,
        "phase_b_gate": "OPEN" if phase_b_open else "CLOSED",
        "phase_b_gate_reason": phase_b_reason,
    }
    _atomic_write_json(freeze_dir / "freeze_record.json", freeze_record)

    manifest["phase_gate"] = {
        **gate,
        "phase_a_response_sha256": response_sha256,
        "phase_a_frozen_at": frozen_at,
        "phase_a_decision": response["decision"],
        "phase_b_gate": freeze_record["phase_b_gate"],
        "phase_b_gate_reason": phase_b_reason,
    }
    _atomic_write_json(private_path, manifest)
    run_status = {
        "schema_version": RUN_STATUS_SCHEMA_VERSION,
        "run_id": run_id,
        "phase_a": "FROZEN",
        "phase_a_response_sha256": response_sha256,
        "phase_b": "READY" if phase_b_open else "NOT_OPENED",
        "phase_b_gate_reason": phase_b_reason,
        "score_status": manifest.get("score_status"),
    }
    _atomic_write_json(freeze_dir.parent / "run_status.json", run_status)
    return {
        "freeze_dir": freeze_dir,
        "freeze_record": freeze_record,
        "run_status": run_status,
    }


__all__ = [
    "RQPhaseAError",
    "freeze_phase_a_response",
    "validate_unified_response",
]
