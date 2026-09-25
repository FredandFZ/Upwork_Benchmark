"""Leakage-safe Phase A input materialization for ReqMemBench runs."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping
import json
import re


MANIFEST_SCHEMA_VERSION = "rq-instance-manifest-v2"
INDEX_SCHEMA_VERSION = "rq-instance-index-v2"
INSTANCE_SCHEMA_VERSION = "rq-instance-v2"
PRIVATE_MANIFEST_SCHEMA_VERSION = "rq-private-run-manifest-v1"
TASK_SCHEMA_VERSION = "rq-agent-task-v1"
CONDITIONS = ("C1", "C2")
REASONING_RQS = ("RQ1", "RQ2", "RQ3")


class RQMaterializationError(ValueError):
    """Raised when researcher-side inputs cannot form a safe Agent package."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RQMaterializationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RQMaterializationError(f"{path} must contain a JSON object")
    return value


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _id_key(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        raise RQMaterializationError(f"invalid message ID {value!r}")
    return str(value)


def _target_record(manifest: Mapping[str, Any], target_id: str) -> dict[str, Any]:
    rows = manifest.get("targets")
    if not isinstance(rows, list):
        raise RQMaterializationError("project manifest.targets must be an array")
    matches = [row for row in rows if isinstance(row, dict) and row.get("target_id") == target_id]
    if len(matches) != 1:
        raise RQMaterializationError(
            f"project manifest must contain exactly one target {target_id!r}"
        )
    return matches[0]


def _safe_project_path(project_dir: Path, relative: str) -> Path:
    candidate = (project_dir / relative).resolve()
    try:
        candidate.relative_to(project_dir.resolve())
    except ValueError as exc:
        raise RQMaterializationError(
            f"instance path escapes project directory: {relative!r}"
        ) from exc
    return candidate


def load_target_views(
    project_dir: str | Path,
    target_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]], dict[str, Path]]:
    """Load one target only through manifest/index-authoritative references."""

    project_path = Path(project_dir).resolve()
    manifest_path = project_path / "rq_instance_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise RQMaterializationError(
            f"unsupported project manifest schema {manifest.get('schema_version')!r}"
        )
    target = _target_record(manifest, target_id)
    instance_refs = target.get("instances")
    if not isinstance(instance_refs, dict) or not instance_refs:
        raise RQMaterializationError(f"target {target_id!r} has no RQ instances")

    views: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    for rq_id, ref in instance_refs.items():
        if rq_id not in ("RQ1", "RQ2", "RQ3", "RQ4") or not isinstance(ref, dict):
            raise RQMaterializationError(f"target {target_id!r} has invalid RQ reference")
        index_path = project_path / rq_id / "index.json"
        index = _read_json(index_path)
        if index.get("schema_version") != INDEX_SCHEMA_VERSION:
            raise RQMaterializationError(f"{rq_id} index uses an unsupported schema")
        if index.get("input_release") != manifest.get("input_release"):
            raise RQMaterializationError(f"{rq_id} index input_release mismatch")
        relative = ref.get("file")
        if not isinstance(relative, str):
            raise RQMaterializationError(f"target {target_id!r} {rq_id} file is invalid")
        filename = Path(relative).name
        index_rows = index.get("instances")
        if not isinstance(index_rows, list):
            raise RQMaterializationError(f"{rq_id} index.instances must be an array")
        matches = [
            row
            for row in index_rows
            if isinstance(row, dict)
            and row.get("target_id") == target_id
            and row.get("file") == filename
        ]
        if len(matches) != 1:
            raise RQMaterializationError(
                f"{rq_id} index does not authorize {target_id!r}/{filename!r}"
            )
        path = _safe_project_path(project_path, relative)
        instance = _read_json(path)
        if instance.get("schema_version") != INSTANCE_SCHEMA_VERSION:
            raise RQMaterializationError(f"{path} uses an unsupported instance schema")
        if instance.get("rq_id") != rq_id or instance.get("target_id") != target_id:
            raise RQMaterializationError(f"{path} identity does not match its manifest")
        expected_content_hash = ref.get("content_sha256")
        if expected_content_hash != _canonical_sha256(instance):
            raise RQMaterializationError(f"{path} content hash does not match manifest")
        views[rq_id] = instance
        paths[rq_id] = path

    _validate_shared_target(manifest, target, views)
    return manifest, target, views, paths


def _validate_shared_target(
    manifest: Mapping[str, Any],
    target: Mapping[str, Any],
    views: Mapping[str, Mapping[str, Any]],
) -> None:
    first = next(iter(views.values()))
    shared_fields = (
        "input_release",
        "project_id",
        "target_id",
        "target_message_id",
        "target_task",
        "history_pool",
        "turns",
        "history_turn_count",
        "difficulty",
        "target_fingerprint",
        "fingerprints",
    )
    for rq_id, instance in views.items():
        for field in shared_fields:
            if instance.get(field) != first.get(field):
                raise RQMaterializationError(
                    f"target {target.get('target_id')!r} has inconsistent {field!r} in {rq_id}"
                )
        for condition in CONDITIONS:
            left = instance.get("condition_inputs", {}).get(condition, {})
            right = first.get("condition_inputs", {}).get(condition, {})
            for field in ("history_mode", "history_message_ids", "history_message_count"):
                if left.get(field) != right.get(field):
                    raise RQMaterializationError(
                        f"target {target.get('target_id')!r} has inconsistent {condition}.{field}"
                    )
    if first.get("input_release") != manifest.get("input_release"):
        raise RQMaterializationError("instance and project input_release disagree")
    if first.get("target_fingerprint") != target.get("target_fingerprint"):
        raise RQMaterializationError("instance and target manifest fingerprint disagree")


def _public_history(instance: Mapping[str, Any], condition: str) -> list[dict[str, Any]]:
    if condition not in CONDITIONS:
        raise RQMaterializationError("condition must be C1 or C2")
    condition_record = instance.get("condition_inputs", {}).get(condition)
    if not isinstance(condition_record, dict):
        raise RQMaterializationError(f"missing condition input {condition}")
    ids = condition_record.get("history_message_ids")
    pool = instance.get("history_pool", {}).get("messages")
    if not isinstance(ids, list) or not isinstance(pool, list):
        raise RQMaterializationError("history records are malformed")
    wanted = {_id_key(value) for value in ids}
    if len(wanted) != len(ids):
        raise RQMaterializationError(f"{condition} repeats a history message ID")
    selected = [deepcopy(row) for row in pool if _id_key(row.get("message_id")) in wanted]
    if [_id_key(row.get("message_id")) for row in selected] != [
        _id_key(value) for value in ids
    ]:
        raise RQMaterializationError(
            f"{condition} history IDs are missing or do not preserve history order"
        )
    target_key = _id_key(instance.get("target_message_id"))
    if any(_id_key(row.get("message_id")) == target_key for row in selected):
        raise RQMaterializationError("public history contains the target message")
    return selected


def _assert_no_public_leakage(files: Mapping[str, str]) -> None:
    forbidden_tokens = (
        "construction_gold",
        "selection_basis",
        "source_artifacts",
        "acceptance_criteria",
        "validator_id",
        "reference_delivery",
        "archive_path",
        "pre_repo.zip",
    )
    joined = "\n".join(files.values())
    for token in forbidden_tokens:
        if token in joined:
            raise RQMaterializationError(f"public input leaks forbidden token {token!r}")
    if re.search(r"\bREQ_[A-Z0-9_]+\b", joined):
        raise RQMaterializationError("public input leaks an internal Requirement ID")
    if re.search(r"\b(?:STATE|EVENT)_[A-Z0-9_]+\b", joined):
        raise RQMaterializationError("public input leaks an internal State/Event ID")


def materialize_reasoning_input(
    project_dir: str | Path,
    target_id: str,
    condition: str,
    *,
    instructions_path: str | Path,
    response_schema_path: str | Path,
    mode: str = "smoke",
) -> dict[str, Any]:
    """Build one target/condition Phase A public package and private manifest."""

    if mode not in {"smoke", "formal"}:
        raise RQMaterializationError("mode must be smoke or formal")
    manifest, target, views, paths = load_target_views(project_dir, target_id)
    conditions = target.get("conditions")
    condition_record = conditions.get(condition) if isinstance(conditions, dict) else None
    if condition not in CONDITIONS or not isinstance(condition_record, dict):
        raise RQMaterializationError(f"target {target_id!r} has no condition {condition!r}")
    active_rqs = [
        rq_id
        for rq_id in condition_record.get("active_rqs", [])
        if rq_id in REASONING_RQS
    ]
    if not active_rqs:
        raise RQMaterializationError(
            f"target {target_id!r}/{condition} has no active reasoning RQ"
        )
    if mode == "formal":
        blocked = [
            rq_id
            for rq_id in active_rqs
            if views[rq_id].get("readiness", {}).get("formal_reasoning_allowed")
            is not True
        ]
        if blocked:
            raise RQMaterializationError(
                f"formal reasoning is blocked for {target_id}/{condition}: {blocked}"
            )

    first = views[active_rqs[0]]
    history = _public_history(first, condition)
    task = first.get("target_task")
    if not isinstance(task, dict):
        raise RQMaterializationError("target_task must be an object")
    public_task = {
        "schema_version": TASK_SCHEMA_VERSION,
        "task": {
            "message_id": deepcopy(task.get("source_message_id")),
            "speaker": deepcopy(task.get("speaker")),
            "text": deepcopy(task.get("text")),
        },
        "history_file": "history.jsonl",
        "response_schema_file": "response.schema.json",
    }
    instructions = Path(instructions_path).read_text(encoding="utf-8-sig")
    response_schema_text = Path(response_schema_path).read_text(encoding="utf-8-sig")
    try:
        response_schema = json.loads(response_schema_text)
    except json.JSONDecodeError as exc:
        raise RQMaterializationError(f"invalid response schema JSON: {exc}") from exc
    if not isinstance(response_schema, dict) or response_schema.get("$id") != "rq-agent-response-v1":
        raise RQMaterializationError("response schema must use rq-agent-response-v1")
    public_files = {
        "task.json": json.dumps(public_task, ensure_ascii=False, indent=2) + "\n",
        "history.jsonl": "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in history
        ),
        "instructions.md": instructions.rstrip() + "\n",
        "response.schema.json": json.dumps(
            response_schema, ensure_ascii=False, indent=2
        )
        + "\n",
    }
    _assert_no_public_leakage(public_files)
    public_hashes = {
        name: sha256(content.encode("utf-8")).hexdigest()
        for name, content in public_files.items()
    }
    run_id = "run_" + _canonical_sha256(
        {
            "input_release": manifest["input_release"],
            "target_fingerprint": target["target_fingerprint"],
            "condition": condition,
            "public_hashes": public_hashes,
        }
    )[:20]
    rq4_view = views.get("RQ4")
    rq4_gold = rq4_view.get("construction_gold", {}) if rq4_view else {}
    eligibility = rq4_gold.get("eligibility_by_condition", {}).get(condition, {})
    code_environment = rq4_view.get("code_environment", {}) if rq4_view else {}
    repository = None
    if rq4_view is not None:
        repository = {
            "archive_path": code_environment.get("archive_path"),
            "archive_sha256": code_environment.get("archive_sha256"),
            "tree_sha256": code_environment.get("repository_tree_sha256"),
            "manifest_path": code_environment.get("manifest_path"),
            "manifest_sha256": code_environment.get("manifest_sha256"),
            "before_message_id": code_environment.get("before_message_id"),
            "available_to_phase": "B_ONLY",
            "extracted_during_phase_a": False,
            "reconstruction_validation": deepcopy(
                code_environment.get("reconstruction_validation")
            ),
        }
    private_manifest = {
        "schema_version": PRIVATE_MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "input_release": manifest["input_release"],
        "project_id": manifest["project_id"],
        "target_id": target_id,
        "target_fingerprint": target["target_fingerprint"],
        "condition": condition,
        "turns": target["turns"],
        "difficulty": target["difficulty"],
        "reasoning_active_rqs": active_rqs,
        "execution_rq": "RQ4" if rq4_view is not None else None,
        "source_instances": {
            rq_id: {
                "path": str(paths[rq_id]),
                "file_sha256": _file_sha256(paths[rq_id]),
                "content_sha256": _canonical_sha256(views[rq_id]),
            }
            for rq_id in views
        },
        "public_files": public_hashes,
        "phase_gate": {
            "repository_visible_in_phase_a": False,
            "phase_a_response_sha256": None,
            "phase_a_frozen_at": None,
            "phase_b_requires_agent_act": True,
        },
        "repository": repository,
        "rq4": {
            "eligible": eligibility.get("rq4_eligible") is True,
            "eligibility_status": eligibility.get("status"),
            "execution_ready": rq4_gold.get("execution_ready") is True,
            "exclusion_reason": eligibility.get("exclusion_reason"),
            "acceptance_criteria": deepcopy(
                rq4_gold.get("acceptance_criteria", [])
            ),
            "validator_ids": deepcopy(rq4_gold.get("validator_ids", [])),
            "execution_readiness_blockers": deepcopy(
                rq4_gold.get("execution_readiness_blockers", [])
            ),
        },
        "mode": mode.upper(),
        "score_status": "READY" if mode == "formal" else "NOT_SCORED",
    }
    return {
        "run_id": run_id,
        "public_files": public_files,
        "private_manifest": private_manifest,
    }


def write_materialized_input(
    materialized: Mapping[str, Any],
    output_root: str | Path,
) -> tuple[Path, Path]:
    """Write public/private artifacts while keeping the private file outside public/."""

    private_manifest = materialized["private_manifest"]
    base = (
        Path(output_root)
        / private_manifest["input_release"]
        / private_manifest["project_id"]
        / private_manifest["target_id"]
        / private_manifest["condition"]
    )
    public_dir = base / "public"
    private_path = base / "private" / "run_manifest.json"
    public_dir.mkdir(parents=True, exist_ok=True)
    private_path.parent.mkdir(parents=True, exist_ok=True)
    for name, content in materialized["public_files"].items():
        path = public_dir / name
        temporary = path.with_name(f".{path.name}.tmp")
        # Bytes avoid platform newline conversion so the recorded public hash
        # is identical on Windows and POSIX runners.
        temporary.write_bytes(content.encode("utf-8"))
        temporary.replace(path)
    temporary = private_path.with_name(f".{private_path.name}.tmp")
    temporary.write_bytes(
        (json.dumps(private_manifest, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        )
    )
    temporary.replace(private_path)
    return public_dir, private_path


def stage_phase_a_workspace(
    materialized: Mapping[str, Any],
    workspace_root: str | Path,
) -> Path:
    """Create a fresh opaque Agent-visible workspace with public files only."""

    run_id = materialized.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"run_[0-9a-f]{20}", run_id):
        raise RQMaterializationError("materialized package has an invalid run_id")
    public_files = materialized.get("public_files")
    if not isinstance(public_files, Mapping) or set(public_files) != {
        "task.json",
        "history.jsonl",
        "instructions.md",
        "response.schema.json",
    }:
        raise RQMaterializationError("materialized package has invalid public files")
    destination = Path(workspace_root).resolve() / run_id
    if destination.exists():
        raise RQMaterializationError(
            f"Phase A workspace already exists and will not be reused: {destination}"
        )
    destination.mkdir(parents=True)
    for name, content in public_files.items():
        if not isinstance(content, str):
            raise RQMaterializationError(f"public file {name!r} must be text")
        (destination / name).write_bytes(content.encode("utf-8"))
    return destination


__all__ = [
    "CONDITIONS",
    "RQMaterializationError",
    "load_target_views",
    "materialize_reasoning_input",
    "stage_phase_a_workspace",
    "write_materialized_input",
]
