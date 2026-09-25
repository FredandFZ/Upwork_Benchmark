#!/usr/bin/env python3
"""Validate one researcher-side RQ4 Agent authoring proposal.

The repository intentionally has no third-party JSON Schema dependency.  This
module implements the draft-2020-12 subset used by the frozen proposal schema,
then applies provenance and authority checks that JSON Schema alone cannot
express.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schema" / "rq4_validator_authoring_proposal.schema.json"


class ProposalValidationError(RuntimeError):
    """The proposal is invalid, stale, unsafe, or exceeds its role authority."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProposalValidationError(f"cannot read {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _resolve_ref(root: Mapping[str, Any], reference: str) -> Mapping[str, Any]:
    if not reference.startswith("#/"):
        raise ProposalValidationError(f"unsupported external schema ref {reference!r}")
    value: Any = root
    for token in reference[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, Mapping) or token not in value:
            raise ProposalValidationError(f"broken schema ref {reference!r}")
        value = value[token]
    if not isinstance(value, Mapping):
        raise ProposalValidationError(f"schema ref is not an object: {reference!r}")
    return value


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise ProposalValidationError(f"unsupported schema type {expected!r}")


def _is_valid(value: Any, schema: Mapping[str, Any], root: Mapping[str, Any]) -> bool:
    try:
        _validate_schema(value, schema, root, "$")
        return True
    except ProposalValidationError:
        return False


def _validate_schema(
    value: Any,
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    location: str,
) -> None:
    if "$ref" in schema:
        _validate_schema(value, _resolve_ref(root, str(schema["$ref"])), root, location)
    expected_type = schema.get("type")
    if expected_type is not None:
        types = [expected_type] if isinstance(expected_type, str) else expected_type
        if not isinstance(types, list) or not any(
            isinstance(kind, str) and _matches_type(value, kind) for kind in types
        ):
            raise ProposalValidationError(f"{location}: type mismatch, expected {types}")
    if "const" in schema and value != schema["const"]:
        raise ProposalValidationError(f"{location}: expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ProposalValidationError(f"{location}: value is outside enum")
    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            raise ProposalValidationError(f"{location}: string is too short")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            raise ProposalValidationError(f"{location}: string does not match pattern")
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            raise ProposalValidationError(f"{location}: array is too short")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise ProposalValidationError(f"{location}: array is too long")
        if schema.get("uniqueItems") is True:
            serialized = [_canonical(item) for item in value]
            if len(serialized) != len(set(serialized)):
                raise ProposalValidationError(f"{location}: array items are not unique")
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, item in enumerate(value):
                _validate_schema(item, items, root, f"{location}[{index}]")
        contains = schema.get("contains")
        if isinstance(contains, Mapping) and not any(
            _is_valid(item, contains, root) for item in value
        ):
            raise ProposalValidationError(f"{location}: contains constraint failed")
    if isinstance(value, Mapping):
        required = schema.get("required", [])
        if isinstance(required, list):
            missing = [key for key in required if key not in value]
            if missing:
                raise ProposalValidationError(f"{location}: missing keys {missing}")
        properties = schema.get("properties", {})
        if isinstance(properties, Mapping):
            for key, child_schema in properties.items():
                if key in value and isinstance(child_schema, Mapping):
                    _validate_schema(value[key], child_schema, root, f"{location}.{key}")
            if schema.get("additionalProperties") is False:
                extra = sorted(set(value) - set(properties))
                if extra:
                    raise ProposalValidationError(f"{location}: unexpected keys {extra}")
    for child in schema.get("allOf", []):
        if isinstance(child, Mapping):
            _validate_schema(value, child, root, location)
    if "anyOf" in schema:
        choices = schema["anyOf"]
        if not isinstance(choices, list) or not any(
            isinstance(choice, Mapping) and _is_valid(value, choice, root)
            for choice in choices
        ):
            raise ProposalValidationError(f"{location}: anyOf constraint failed")
    if "oneOf" in schema:
        choices = schema["oneOf"]
        matches = sum(
            isinstance(choice, Mapping) and _is_valid(value, choice, root)
            for choice in choices
        ) if isinstance(choices, list) else 0
        if matches != 1:
            raise ProposalValidationError(f"{location}: oneOf matched {matches} choices")
    condition = schema.get("if")
    if isinstance(condition, Mapping):
        branch = schema.get("then") if _is_valid(value, condition, root) else schema.get("else")
        if isinstance(branch, Mapping):
            _validate_schema(value, branch, root, location)


def _safe_artifact_path(artifact_root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ProposalValidationError(f"invalid produced file path {relative!r}")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise ProposalValidationError(f"unsafe produced file path {relative!r}")
    path = (artifact_root / Path(*pure.parts)).resolve()
    try:
        path.relative_to(artifact_root.resolve())
    except ValueError as exc:
        raise ProposalValidationError(f"produced file escapes artifact root: {relative!r}") from exc
    return path


def validate_proposal(
    proposal_path: Path,
    work_item_path: Path,
    artifact_root: Path,
    schema_path: Path = DEFAULT_SCHEMA,
) -> dict[str, Any]:
    schema = _read_json(schema_path)
    proposal = _read_json(proposal_path)
    work_item = _read_json(work_item_path)
    if not isinstance(schema, Mapping) or not isinstance(proposal, Mapping):
        raise ProposalValidationError("schema and proposal must be objects")
    if not isinstance(work_item, Mapping):
        raise ProposalValidationError("work item must be an object")
    _validate_schema(proposal, schema, schema, "$")
    for field in ("project_id", "target_id"):
        if proposal.get(field) != work_item.get(field):
            raise ProposalValidationError(f"proposal/work-item {field} mismatch")
    if proposal.get("before_message_id") != work_item.get("target_message_id"):
        raise ProposalValidationError("proposal/work-item message boundary mismatch")
    source_identity = proposal["source_identity"]
    if source_identity.get("work_item_sha256") != _sha256(work_item_path):
        raise ProposalValidationError("work item hash is stale")
    repository = work_item.get("code_environment", {})
    if source_identity.get("pre_repo_sha256") != repository.get("archive_sha256"):
        raise ProposalValidationError("pre-repo hash disagrees with work item")
    if source_identity.get("target_manifest_sha256") != repository.get("manifest_sha256"):
        raise ProposalValidationError("target manifest hash disagrees with work item")
    for record in source_identity.get("upstream_proposals", []):
        relative = record.get("path")
        path = _safe_artifact_path(artifact_root, relative)
        if not path.is_file() or _sha256(path) != record.get("sha256"):
            raise ProposalValidationError(
                f"upstream proposal is missing or stale: {relative}"
            )
    seen_paths: set[str] = set()
    for record in proposal.get("produced_files", []):
        relative = record.get("path")
        if relative in seen_paths:
            raise ProposalValidationError(f"duplicate produced file {relative!r}")
        seen_paths.add(relative)
        if record.get("researcher_only") is not True:
            raise ProposalValidationError(f"produced file is not researcher-only: {relative}")
        path = _safe_artifact_path(artifact_root, relative)
        if not path.is_file() or _sha256(path) != record.get("sha256"):
            raise ProposalValidationError(f"produced file is missing or stale: {relative}")
    role = proposal["author_role"]
    payload = proposal["payload"]
    if role == "CRITERIA_AUTHOR":
        triage = payload["observability_triage"]["determination"]
        disposition = payload["downstream_disposition"]
        criteria = payload["acceptance_criteria"]
        expected = {
            "DETERMINISTIC_OBSERVABLE": "PROCEED_TO_VALIDATOR_AUTHORING",
            "ENVIRONMENT_REPAIR_REQUIRED": "BLOCK_FOR_ENVIRONMENT_REPAIR",
            "NO_DETERMINISTIC_OBSERVABLE": "EXCLUDE_NO_DETERMINISTIC_OBSERVABLE",
        }
        if disposition != expected[triage]:
            raise ProposalValidationError("criteria triage and disposition disagree")
        if triage == "DETERMINISTIC_OBSERVABLE" and not criteria:
            raise ProposalValidationError("deterministic target has no acceptance criteria")
        if triage != "DETERMINISTIC_OBSERVABLE" and criteria:
            raise ProposalValidationError("blocked/excluded target must not author criteria")
    if role in {"VALIDATOR_AUTHOR", "REFERENCE_AUTHOR", "RED_TEAM_LEAKAGE_AUDITOR"}:
        status = work_item.get("observability_triage", {}).get("status")
        if status != "ELIGIBLE_FOR_VALIDATOR_AUTHORING":
            raise ProposalValidationError(
                f"{role} cannot run while work item status is {status}"
            )
    return {
        "schema_version": "rq4-authoring-proposal-validation-v1",
        "overall": "PASS",
        "project_id": proposal["project_id"],
        "target_id": proposal["target_id"],
        "author_role": role,
        "produced_file_count": len(proposal.get("produced_files", [])),
        "proposal_sha256": _sha256(proposal_path),
        "schema_sha256": _sha256(schema_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--work-item", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    args = parser.parse_args()
    try:
        result = validate_proposal(
            args.proposal, args.work_item, args.artifact_root, args.schema
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ProposalValidationError) as exc:
        print(f"RQ4 proposal validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
