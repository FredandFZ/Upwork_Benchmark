#!/usr/bin/env python3
"""Build the frozen 40-target registry for the universal RQ4 Agent Judge."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

try:  # Package import in tests; script import in CLIs.
    from .validate_rq4_authoring_proposal import validate_proposal
except ImportError:  # pragma: no cover
    from validate_rq4_authoring_proposal import validate_proposal


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK_ROOT = ROOT / "ccfa-workfiles" / "experiments" / "rq4-validation" / "projects"
DEFAULT_STAGE2_ROOT = ROOT / "outputs_new" / "stage2"
DEFAULT_OUTPUT = ROOT / "ccfa-workfiles" / "experiments" / "rq4-validation" / "rq4_agent_judge_registry.json"
DEFAULT_PROMPT = ROOT / "prompt" / "rq4_agent_judge.md"
DEFAULT_RESPONSE_SCHEMA = ROOT / "schema" / "rq4_agent_judge_result.schema.json"
CONDITIONS = ("C1", "C2")


class RQ4RegistryError(ValueError):
    pass


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RQ4RegistryError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RQ4RegistryError(f"{path} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise RQ4RegistryError(f"path is outside repository root: {path}") from exc


def _criteria_for_judge(proposal: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = proposal.get("payload", {}).get("acceptance_criteria")
    if not isinstance(rows, list) or not rows:
        raise RQ4RegistryError("included target has no acceptance criteria")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise RQ4RegistryError("acceptance criterion must be an object")
        criterion_id = row.get("criterion_id")
        if (
            not isinstance(criterion_id, str)
            or re.fullmatch(r"AC[0-9]{3}", criterion_id) is None
            or criterion_id in seen
        ):
            raise RQ4RegistryError(f"invalid or duplicate criterion ID {criterion_id!r}")
        seen.add(criterion_id)
        # Internal Requirement/State IDs are provenance, not Judge input.
        output.append(
            {
                key: deepcopy(row[key])
                for key in ("criterion_id", "scope", "statement", "observables", "negative_cases")
                if key in row
            }
        )
    return output


def _condition_eligibility(rq3: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    gold = rq3.get("construction_gold")
    if not isinstance(gold, Mapping) or gold.get("status") != "FINAL_UPDATE_OR_CLARIFY_GOLD":
        raise RQ4RegistryError("RQ3 Gold is not frozen")
    final = gold.get("final_gold_by_condition")
    if not isinstance(final, Mapping):
        raise RQ4RegistryError("RQ3 has no condition-specific final Gold")
    output: dict[str, dict[str, Any]] = {}
    for condition in CONDITIONS:
        record = final.get(condition)
        if not isinstance(record, Mapping) or record.get("decision") not in {"ACT", "CLARIFY"}:
            raise RQ4RegistryError(f"RQ3 {condition} decision is invalid")
        eligible = record.get("decision") == "ACT"
        output[condition] = {
            "rq3_gold_decision": record.get("decision"),
            "rq4_eligible": eligible,
            "status": "ELIGIBLE" if eligible else "EXCLUDED",
            "exclusion_reason": None if eligible else "RQ3_NOT_ACT",
        }
    return output


def build_registry(
    *,
    work_root: Path = DEFAULT_WORK_ROOT,
    stage2_root: Path = DEFAULT_STAGE2_ROOT,
    prompt_path: Path = DEFAULT_PROMPT,
    response_schema_path: Path = DEFAULT_RESPONSE_SCHEMA,
    repository_root: Path = ROOT,
    expected_count: int | None = 40,
) -> dict[str, Any]:
    prompt_path = prompt_path.resolve()
    response_schema_path = response_schema_path.resolve()
    schema = _json(response_schema_path)
    if schema.get("$id") != "rq4-agent-judge-result-v1":
        raise RQ4RegistryError("unexpected RQ4 Judge response schema")
    work_items = sorted(work_root.glob("*/targets/*/work_item.json"))
    if not work_items:
        raise RQ4RegistryError(f"no RQ4 work items below {work_root}")
    targets: list[dict[str, Any]] = []
    for work_item_path in work_items:
        target_root = work_item_path.parent
        criteria_path = target_root / "author" / "criteria_proposal.json"
        if not criteria_path.is_file():
            raise RQ4RegistryError(f"missing criteria proposal: {criteria_path}")
        proposal = _json(criteria_path)
        if proposal.get("payload", {}).get("downstream_disposition") != "PROCEED_TO_VALIDATOR_AUTHORING":
            continue
        validate_proposal(criteria_path, work_item_path, target_root)
        work_item = _json(work_item_path)
        project_id = str(work_item.get("project_id"))
        target_id = str(work_item.get("target_id"))
        rq3_path = stage2_root / project_id / "RQ3" / f"{target_id}_RQ3.json"
        rq3 = _json(rq3_path)
        if rq3.get("target_id") != target_id or rq3.get("target_message_id") != work_item.get("target_message_id"):
            raise RQ4RegistryError(f"RQ3/work-item identity mismatch for {target_id}")
        if rq3.get("target_fingerprint") != work_item.get("target_fingerprint"):
            raise RQ4RegistryError(f"RQ3/work-item fingerprint mismatch for {target_id}")
        rq3_gold = work_item.get("rq3_gold", {})
        if rq3_gold.get("file_sha256") != _sha256(rq3_path):
            raise RQ4RegistryError(f"RQ3 file hash is stale for {target_id}")
        code_environment = work_item.get("code_environment")
        if not isinstance(code_environment, Mapping):
            raise RQ4RegistryError(f"work item has no Code Environment for {target_id}")
        archive_path = repository_root / str(code_environment.get("archive_path", ""))
        manifest_path = repository_root / str(code_environment.get("manifest_path", ""))
        if not archive_path.is_file() or _sha256(archive_path) != code_environment.get("archive_sha256"):
            raise RQ4RegistryError(f"pre-repository is missing or stale for {target_id}")
        if not manifest_path.is_file() or _sha256(manifest_path) != code_environment.get("manifest_sha256"):
            raise RQ4RegistryError(f"Code Environment manifest is missing or stale for {target_id}")
        tree_hash = code_environment.get("repository_tree_sha256")
        if not isinstance(tree_hash, str) or re.fullmatch(r"[0-9a-f]{64}", tree_hash) is None:
            raise RQ4RegistryError(f"Code Environment tree hash is invalid for {target_id}")
        targets.append(
            {
                "project_id": project_id,
                "target_id": target_id,
                "target_message_id": work_item.get("target_message_id"),
                "target_fingerprint": work_item.get("target_fingerprint"),
                "status": "READY_FOR_PHASE_A_LINK",
                "condition_eligibility": _condition_eligibility(rq3),
                "acceptance_criteria": _criteria_for_judge(proposal),
                "evaluation_commands": {
                    "build": ["{python}", "scripts/build.py"],
                    "regression": ["{python}", "scripts/check.py"],
                },
                "code_environment": {
                    "archive_path": _repo_relative(archive_path, repository_root),
                    "archive_sha256": code_environment.get("archive_sha256"),
                    "tree_sha256": tree_hash,
                    "manifest_path": _repo_relative(manifest_path, repository_root),
                    "manifest_sha256": code_environment.get("manifest_sha256"),
                    "before_message_id": code_environment.get("before_message_id"),
                },
                "source_identity": {
                    "work_item_path": _repo_relative(work_item_path, repository_root),
                    "work_item_sha256": _sha256(work_item_path),
                    "criteria_proposal_path": _repo_relative(criteria_path, repository_root),
                    "criteria_proposal_sha256": _sha256(criteria_path),
                    "rq3_instance_path": _repo_relative(rq3_path, repository_root),
                    "rq3_instance_sha256": _sha256(rq3_path),
                },
            }
        )
    targets.sort(key=lambda row: (row["project_id"], row["target_id"]))
    if expected_count is not None and len(targets) != expected_count:
        raise RQ4RegistryError(
            f"expected {expected_count} Agent-Judge targets, found {len(targets)}"
        )
    return {
        "schema_version": "rq4-agent-judge-registry-v1",
        "selection": {
            "raw_target_count": len(work_items),
            "included_target_count": len(targets),
            "rule": "CRITERIA_DISPOSITION_PROCEED_TO_VALIDATOR_AUTHORING",
        },
        "judge_contract": {
            "prompt_path": _repo_relative(prompt_path, repository_root),
            "prompt_sha256": _sha256(prompt_path),
            "response_schema_path": _repo_relative(response_schema_path, repository_root),
            "response_schema_sha256": _sha256(response_schema_path),
            "finalizer_version": "rq4-agent-judge-finalizer-v1",
        },
        "targets": targets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--stage2-root", type=Path, default=DEFAULT_STAGE2_ROOT)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--response-schema", type=Path, default=DEFAULT_RESPONSE_SCHEMA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--expected-count", type=int, default=40)
    args = parser.parse_args()
    try:
        registry = build_registry(
            work_root=args.work_root.resolve(),
            stage2_root=args.stage2_root.resolve(),
            prompt_path=args.prompt.resolve(),
            response_schema_path=args.response_schema.resolve(),
            expected_count=args.expected_count,
        )
        payload = (json.dumps(registry, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(f".{args.output.name}.tmp")
        temporary.write_bytes(payload)
        temporary.replace(args.output)
        print(json.dumps(registry["selection"], ensure_ascii=False, indent=2))
        return 0
    except (OSError, RQ4RegistryError, ValueError) as exc:
        print(f"RQ4 Agent Judge registry failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
