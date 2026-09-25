#!/usr/bin/env python3
"""Independently validate RQ4 observability work items and their provenance."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRIAGE_ROOT = (
    ROOT / "ccfa-workfiles" / "experiments" / "rq4-validation"
)
ALLOWED_STATUSES = {
    "ELIGIBLE_FOR_VALIDATOR_AUTHORING",
    "ENVIRONMENT_REPAIR_REQUIRED",
    "SUBJECTIVE_REVIEW_REQUIRED",
    "NO_DETERMINISTIC_OBSERVABLE",
}


class ValidationError(RuntimeError):
    """A triage release is incomplete, stale, or internally inconsistent."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_workspace(relative: Any) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValidationError(f"invalid workspace path: {relative!r}")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValidationError(f"unsafe workspace path: {relative!r}")
    path = (ROOT / Path(*pure.parts)).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValidationError(f"workspace path escapes root: {relative!r}") from exc
    return path


def _check_source(record: Any, label: str) -> None:
    if not isinstance(record, Mapping):
        raise ValidationError(f"{label} source record is invalid")
    path = _resolve_workspace(record.get("path"))
    if not path.is_file():
        raise ValidationError(f"{label} source is missing: {path}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", ""))):
        raise ValidationError(f"{label} source hash is malformed")
    if _sha256(path) != record["sha256"]:
        raise ValidationError(f"{label} source hash is stale: {path}")


def _check_work_item(path: Path, project_id: str, target_id: str) -> str:
    item = _read_json(path)
    if not isinstance(item, Mapping):
        raise ValidationError(f"{path} must contain an object")
    if item.get("schema_version") != "rq4-validator-work-item-v1":
        raise ValidationError(f"{path} uses an unsupported schema")
    if item.get("project_id") != project_id or item.get("target_id") != target_id:
        raise ValidationError(f"{path} identity mismatch")
    if item.get("visibility") != "RESEARCHER_PRIVATE_NEVER_AGENT_VISIBLE_DURING_BENCHMARK":
        raise ValidationError(f"{path} has an unsafe visibility declaration")
    target_message_id = item.get("target_message_id")
    repository = item.get("code_environment")
    if not isinstance(repository, Mapping):
        raise ValidationError(f"{path} has no repository record")
    archive = _resolve_workspace(repository.get("archive_path"))
    manifest_path = _resolve_workspace(repository.get("manifest_path"))
    if not archive.is_file() or not manifest_path.is_file():
        raise ValidationError(f"{path} repository artifacts are missing")
    if _sha256(archive) != repository.get("archive_sha256"):
        raise ValidationError(f"{path} archive hash is stale")
    if _sha256(manifest_path) != repository.get("manifest_sha256"):
        raise ValidationError(f"{path} manifest hash is stale")
    manifest = _read_json(manifest_path)
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("target_id") != target_id
        or manifest.get("before_message_id") != target_message_id
        or manifest.get("repo_sha256") != repository.get("repository_tree_sha256")
    ):
        raise ValidationError(f"{path} Code Environment identity mismatch")
    rq3 = item.get("rq3_gold")
    if not isinstance(rq3, Mapping):
        raise ValidationError(f"{path} frozen RQ3 record is missing")
    rq3_path = _resolve_workspace(rq3.get("source_path"))
    if not rq3_path.is_file() or _sha256(rq3_path) != rq3.get("file_sha256"):
        raise ValidationError(f"{path} frozen RQ3 source is stale")
    decisions = rq3.get("decision_by_condition")
    if not isinstance(decisions, Mapping) or decisions != {"C1": "ACT", "C2": "ACT"}:
        raise ValidationError(f"{path} is not an RQ3-ACT pair")
    triage = item.get("observability_triage")
    if not isinstance(triage, Mapping) or triage.get("status") not in ALLOWED_STATUSES:
        raise ValidationError(f"{path} has an invalid triage status")
    status = str(triage["status"])
    missing = triage.get("missing_surfaces")
    if not isinstance(missing, list):
        raise ValidationError(f"{path} missing_surfaces must be an array")
    if status == "ENVIRONMENT_REPAIR_REQUIRED" and not missing:
        raise ValidationError(f"{path} repair status has no missing surfaces")
    if status == "NO_DETERMINISTIC_OBSERVABLE" and triage.get(
        "currently_exposed_pre_post_difference"
    ) is not False:
        raise ValidationError(f"{path} no-observable status is inconsistent")
    contract = item.get("authoring_contract")
    if not isinstance(contract, Mapping):
        raise ValidationError(f"{path} authoring contract is missing")
    expected_initial = {
        "acceptance_criteria_status": "NOT_AUTHORED",
        "validator_status": "NOT_AUTHORED",
        "reference_delivery_status": "NOT_AUTHORED",
        "partial_delivery_status": "NOT_AUTHORED",
        "calibration_status": "NOT_RUN",
        "leakage_semantic_audit_status": "NOT_RUN",
        "eligibility_status": "NOT_DECIDED",
    }
    for key, value in expected_initial.items():
        if contract.get(key) != value:
            raise ValidationError(f"{path} prematurely advances {key}")
    if contract.get("agent_may_not_self_certify_calibration_or_eligibility") is not True:
        raise ValidationError(f"{path} weakens the authoring authority boundary")
    sources = item.get("source_artifacts")
    if not isinstance(sources, Mapping):
        raise ValidationError(f"{path} source artifacts are missing")
    for name in ("build_plan", "requirement_state_graph", "normalized_project"):
        _check_source(sources.get(name), f"{path}:{name}")
    return status


def validate_release(root: Path = DEFAULT_TRIAGE_ROOT) -> dict[str, Any]:
    report_path = root / "observability_triage.json"
    report = _read_json(report_path)
    if not isinstance(report, Mapping) or report.get("schema_version") != "rq4-observability-triage-v1":
        raise ValidationError("unsupported or missing observability triage report")
    projects = report.get("projects")
    if not isinstance(projects, list) or not projects:
        raise ValidationError("triage report has no projects")
    seen_projects: set[str] = set()
    status_counts: Counter[str] = Counter()
    target_count = 0
    for project in projects:
        if not isinstance(project, Mapping):
            raise ValidationError("invalid project record")
        project_id = str(project.get("project_id", ""))
        if not project_id or project_id in seen_projects:
            raise ValidationError(f"invalid or duplicate project {project_id!r}")
        seen_projects.add(project_id)
        summary_path = root / Path(*PurePosixPath(str(project.get("summary", ""))).parts)
        summary = _read_json(summary_path)
        if not isinstance(summary, Mapping) or summary.get("project_id") != project_id:
            raise ValidationError(f"{project_id} summary identity mismatch")
        rows = summary.get("targets")
        if not isinstance(rows, list):
            raise ValidationError(f"{project_id} summary targets are missing")
        seen_targets: set[str] = set()
        project_counts: Counter[str] = Counter()
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValidationError(f"{project_id} target row is invalid")
            target_id = str(row.get("target_id", ""))
            if not target_id.startswith(f"{project_id}_") or target_id in seen_targets:
                raise ValidationError(f"{project_id} invalid target {target_id!r}")
            seen_targets.add(target_id)
            item_path = root / Path(*PurePosixPath(str(row.get("work_item", ""))).parts)
            status = _check_work_item(item_path, project_id, target_id)
            if row.get("status") != status:
                raise ValidationError(f"{target_id} summary status mismatch")
            project_counts[status] += 1
        if dict(sorted(project_counts.items())) != summary.get("status_counts"):
            raise ValidationError(f"{project_id} status counts disagree")
        if len(rows) != summary.get("target_count"):
            raise ValidationError(f"{project_id} target count disagrees")
        if summary.get("status_counts") != project.get("status_counts"):
            raise ValidationError(f"{project_id} report summary disagrees")
        status_counts.update(project_counts)
        target_count += len(rows)
    if target_count != report.get("target_count"):
        raise ValidationError("release target count disagrees")
    if len(seen_projects) != report.get("project_count"):
        raise ValidationError("release project count disagrees")
    if dict(sorted(status_counts.items())) != report.get("status_counts"):
        raise ValidationError("release status counts disagree")
    return {
        "schema_version": "rq4-observability-validation-v1",
        "overall": "PASS",
        "project_count": len(seen_projects),
        "target_count": target_count,
        "status_counts": dict(sorted(status_counts.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_TRIAGE_ROOT)
    args = parser.parse_args()
    try:
        result = validate_release(args.root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValidationError) as exc:
        print(f"RQ4 observability validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
