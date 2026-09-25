#!/usr/bin/env python3
"""Validate one or all project-scoped RQ4 Code Environment Build Plans."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
from typing import Any, Mapping


SCHEMA_VERSION = "rq4-code-environment-project-build-plan-v1"


class PlanValidationError(ValueError):
    """An RQ4 project Build Plan is inconsistent or stale."""


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise PlanValidationError(f"{path} must contain an object")
    return value


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _resolve(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative:
        raise PlanValidationError(f"invalid relative path {relative!r}")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise PlanValidationError(f"unsafe plan path {relative!r}")
    path = (root / Path(*pure.parts)).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise PlanValidationError(f"plan path escapes repository: {relative!r}") from exc
    return path


def _validate_plan(
    *,
    plan_path: Path,
    root: Path,
    allowlist_path: Path,
    allowlist_source_hash: str,
    allowed_project_ids: set[str],
) -> dict[str, Any]:
    plan = _read(plan_path)
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise PlanValidationError(f"{plan_path}: unsupported Build Plan schema")
    if plan.get("construction_policy") != "FROM_SCRATCH_NEW_RELEASE_ONLY":
        raise PlanValidationError(f"{plan_path}: plan does not require a clean rebuild")

    project_id = str(plan.get("project_id", ""))
    if not project_id or project_id not in allowed_project_ids:
        raise PlanValidationError(
            f"{plan_path}: project {project_id!r} is not in the approved allowlist"
        )
    if plan_path.name != "rq4_build_plan.json" or plan_path.parent.name != project_id:
        raise PlanValidationError(
            f"{project_id}: plan must be stored at "
            f"projects/{project_id}/rq4_build_plan.json"
        )

    applicability = plan.get("project_applicability")
    if not isinstance(applicability, Mapping):
        raise PlanValidationError(f"{project_id}: project_applicability is missing")
    if applicability.get("selection_source") != "USER_CURATED_PROJECT_ALLOWLIST":
        raise PlanValidationError(f"{project_id}: applicability is not user-curated")
    if applicability.get("included_project_id") != project_id:
        raise PlanValidationError(f"{project_id}: applicability project mismatch")
    allowlist_source = applicability.get("source_artifact")
    if not isinstance(allowlist_source, Mapping):
        raise PlanValidationError(f"{project_id}: allowlist source is missing")
    if _resolve(root, allowlist_source.get("path")) != allowlist_path.resolve():
        raise PlanValidationError(f"{project_id}: allowlist source path is invalid")
    if allowlist_source.get("file_sha256") != allowlist_source_hash:
        raise PlanValidationError(f"{project_id}: allowlist source hash is stale")
    profile = plan.get("repository_profile")
    if not isinstance(profile, Mapping) or profile.get("renderer") not in {
        "web",
        "mobile",
        "kicad",
        "docx",
        "report",
    }:
        raise PlanValidationError(f"{project_id}: repository profile is invalid")

    rows = plan.get("targets")
    if not isinstance(rows, list) or not rows:
        raise PlanValidationError(f"{project_id}: targets must be a non-empty array")
    message_ids = [int(row["target_message_id"]) for row in rows]
    if message_ids != sorted(message_ids):
        raise PlanValidationError(f"{project_id}: targets are not chronological")

    statuses: Counter[str] = Counter()
    decisions: Counter[str] = Counter()
    target_ids: set[str] = set()
    output_dirs: set[str] = set()
    source_files_checked = 0
    expected_sequence = 0
    for row in rows:
        if not isinstance(row, Mapping):
            raise PlanValidationError(f"{project_id}: target record must be an object")
        target_id = str(row["target_id"])
        if not target_id.startswith(f"{project_id}_"):
            raise PlanValidationError(f"{target_id}: target belongs to another project")
        if target_id in target_ids:
            raise PlanValidationError(f"{project_id}: duplicate target {target_id}")
        target_ids.add(target_id)

        status = str(row["plan_status"])
        decision = str(row["rq3_gold_decision"])
        statuses[status] += 1
        decisions[decision] += 1
        if status == "READY_FOR_CODE_ENV_RECONSTRUCTION":
            if decision != "ACT" or row.get("exclusion_reason") is not None:
                raise PlanValidationError(f"{target_id}: invalid build gate")
            expected_sequence += 1
            if row.get("build_sequence") != expected_sequence:
                raise PlanValidationError(f"{target_id}: invalid build sequence")
            output = row.get("output_contract")
            if not isinstance(output, Mapping):
                raise PlanValidationError(f"{target_id}: output contract is missing")
            target_dir = str(output.get("target_directory"))
            expected_prefix = f"Code Environment/{project_id}/targets/"
            if not target_dir.startswith(expected_prefix):
                raise PlanValidationError(f"{target_id}: output escapes project scope")
            if target_dir in output_dirs:
                raise PlanValidationError(f"{target_id}: duplicate output directory")
            output_dirs.add(target_dir)
            if output.get("before_message_id") != row.get("target_message_id"):
                raise PlanValidationError(f"{target_id}: output boundary mismatch")
        elif status == "EXCLUDED_RQ3_NOT_ACT":
            if decision != "CLARIFY" or row.get("exclusion_reason") != "RQ3_NOT_ACT":
                raise PlanValidationError(f"{target_id}: invalid exclusion")
            if row.get("build_sequence") is not None or row.get("output_contract") is not None:
                raise PlanValidationError(f"{target_id}: excluded target has build output")
        else:
            raise PlanValidationError(f"{target_id}: unknown plan status")

        rq3_source = row.get("source_artifacts", {}).get("rq3_instance", {})
        rq3_path = _resolve(root, rq3_source.get("path"))
        if _file_sha256(rq3_path) != rq3_source.get("file_sha256"):
            raise PlanValidationError(f"{target_id}: RQ3 source hash is stale")
        rq3 = _read(rq3_path)
        if _canonical_sha256(rq3) != rq3_source.get("content_sha256"):
            raise PlanValidationError(f"{target_id}: RQ3 content hash is stale")
        frozen = rq3["construction_gold"]["final_gold_by_condition"]
        if frozen["C1"] != frozen["C2"] or frozen["C1"]["decision"] != decision:
            raise PlanValidationError(f"{target_id}: no longer matches frozen RQ3")
        source_files_checked += 1

    project_sources = plan.get("project_sources")
    if not isinstance(project_sources, Mapping):
        raise PlanValidationError(f"{project_id}: project_sources is missing")
    for source in project_sources.values():
        if not isinstance(source, Mapping):
            raise PlanValidationError(f"{project_id}: invalid project source")
        path = _resolve(root, source.get("path"))
        if _file_sha256(path) != source.get("file_sha256"):
            raise PlanValidationError(f"{project_id}: project source hash is stale")
        source_files_checked += 1
    required_sources = {
        "rq_instance_manifest",
        "gold_states",
        "requirement_state_graph",
        "normalized_project",
        "stage1_annotation",
        "gold_state_validation",
        "repository_profiles",
    }
    if set(project_sources) != required_sources:
        raise PlanValidationError(f"{project_id}: project source set is incomplete")

    summary = plan.get("summary", {})
    actual = {
        "selected_target_count": len(target_ids),
        "build_target_count": statuses["READY_FOR_CODE_ENV_RECONSTRUCTION"],
        "excluded_rq3_not_act_count": statuses["EXCLUDED_RQ3_NOT_ACT"],
        "rq3_decision_distribution": dict(decisions),
    }
    for key, value in actual.items():
        if summary.get(key) != value:
            raise PlanValidationError(f"{project_id}: summary mismatch for {key}")

    return {
        "project_id": project_id,
        **actual,
        "source_files_checked": source_files_checked,
        "unique_output_directory_count": len(output_dirs),
        "status": "PASS",
    }


def _args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    default_root = (
        root
        / "ccfa-workfiles"
        / "experiments"
        / "rq4-code-environment"
        / "projects"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--plan",
        type=Path,
        help="Validate one project-scoped rq4_build_plan.json.",
    )
    group.add_argument(
        "--plans-root",
        type=Path,
        default=default_root,
        help="Validate every projects/<project_id>/rq4_build_plan.json.",
    )
    return parser.parse_args()


def main() -> int:
    args = _args()
    root = Path(__file__).resolve().parents[1]
    try:
        allowlist_path = root / "Code" / "config" / "rq4_project_allowlist.json"
        allowlist = _read(allowlist_path)
        project_ids = allowlist.get("project_ids")
        if (
            allowlist.get("schema_version") != "rq4-project-allowlist-v1"
            or not isinstance(project_ids, list)
            or not all(isinstance(value, str) and value for value in project_ids)
        ):
            raise PlanValidationError("invalid RQ4 project allowlist")
        allowed_project_ids = set(project_ids)
        if len(allowed_project_ids) != len(project_ids):
            raise PlanValidationError("RQ4 project allowlist contains duplicates")

        batch_mode = args.plan is None
        if batch_mode:
            plan_paths = sorted(args.plans_root.glob("*/rq4_build_plan.json"))
            discovered = {path.parent.name for path in plan_paths}
            if discovered != allowed_project_ids:
                missing = sorted(allowed_project_ids - discovered)
                extra = sorted(discovered - allowed_project_ids)
                raise PlanValidationError(
                    f"project plan set differs from allowlist; missing={missing}, extra={extra}"
                )
        else:
            plan_paths = [args.plan]

        allowlist_hash = _file_sha256(allowlist_path)
        results = [
            _validate_plan(
                plan_path=path,
                root=root,
                allowlist_path=allowlist_path,
                allowlist_source_hash=allowlist_hash,
                allowed_project_ids=allowed_project_ids,
            )
            for path in plan_paths
        ]
        if batch_mode:
            output: dict[str, Any] = {
                "project_count": len(results),
                "selected_target_count": sum(
                    row["selected_target_count"] for row in results
                ),
                "build_target_count": sum(row["build_target_count"] for row in results),
                "excluded_rq3_not_act_count": sum(
                    row["excluded_rq3_not_act_count"] for row in results
                ),
                "projects": results,
                "status": "PASS",
            }
        else:
            output = results[0]
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (
        OSError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"RQ4 Build Plan validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
