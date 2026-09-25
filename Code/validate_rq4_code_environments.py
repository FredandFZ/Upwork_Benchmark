#!/usr/bin/env python3
"""Independently validate the released RQ4 Code Environment packages."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Mapping
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLANS_ROOT = (
    ROOT / "ccfa-workfiles" / "experiments" / "rq4-code-environment" / "projects"
)
DEFAULT_ENV_ROOT = ROOT / "Code Environment"
BUILD_STATUS = "READY_FOR_CODE_ENV_RECONSTRUCTION"


class ValidationError(ValueError):
    """A released project differs from its frozen plan or manifest."""


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive_tree_hash(archive: zipfile.ZipFile) -> str:
    digest = hashlib.sha256()
    names = sorted(info.filename for info in archive.infolist() if not info.is_dir())
    for name in names:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(archive.read(name))
        digest.update(b"\0")
    return digest.hexdigest()


def _audit_archive(path: Path) -> tuple[int, str]:
    forbidden = [
        re.compile(r"\bREQ_[A-Z0-9_]+\b"),
        re.compile(r"\b[A-Z][A-Z0-9_]+_[SE]\d{3}\b"),
        re.compile(
            r"acceptance_criteria|hidden[_ -]?validator|reference[_ -]?delivery|build plan",
            re.IGNORECASE,
        ),
        re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
        re.compile(r"AKIA[0-9A-Z]{16}"),
    ]
    text_suffixes = {
        ".py",
        ".md",
        ".html",
        ".json",
        ".txt",
        ".toml",
        ".yml",
        ".yaml",
        ".css",
        ".js",
        ".mjs",
        "",
    }
    try:
        with zipfile.ZipFile(path) as archive:
            bad_crc = archive.testzip()
            if bad_crc is not None:
                raise ValidationError(f"{path}: CRC failure in {bad_crc}")
            files = [info for info in archive.infolist() if not info.is_dir()]
            if not files:
                raise ValidationError(f"{path}: archive is empty")
            for info in files:
                pure = PurePosixPath(info.filename)
                if pure.is_absolute() or ".." in pure.parts or ".git" in pure.parts:
                    raise ValidationError(f"{path}: unsafe member {info.filename}")
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValidationError(f"{path}: symlink member {info.filename}")
                if pure.suffix.lower() in text_suffixes:
                    text = archive.read(info).decode("utf-8", errors="ignore")
                    for pattern in forbidden:
                        match = pattern.search(text)
                        if match:
                            raise ValidationError(
                                f"{path}: leakage {match.group(0)!r} in {info.filename}"
                            )
            return len(files), _archive_tree_hash(archive)
    except zipfile.BadZipFile as exc:
        raise ValidationError(f"{path}: invalid ZIP: {exc}") from exc


def _validate_project(
    project_id: str, plan_path: Path, environment_root: Path
) -> dict[str, Any]:
    plan = _read(plan_path)
    if not isinstance(plan, Mapping) or str(plan.get("project_id")) != project_id:
        raise ValidationError(f"{project_id}: invalid project plan")
    expected_targets = [
        target
        for target in plan.get("targets", [])
        if target.get("plan_status") == BUILD_STATUS
    ]
    project_root = environment_root / project_id
    reports = project_root / "reports"
    validation = _read(reports / "validation_report.json")
    if validation.get("overall") != "PASS":
        raise ValidationError(f"{project_id}: validation report is not PASS")
    if validation.get("construction_policy") != "FROM_SCRATCH_NEW_RELEASE_ONLY":
        raise ValidationError(f"{project_id}: release is not marked as a clean rebuild")

    index = _read(reports / "target_index.json")
    if not isinstance(index, list):
        raise ValidationError(f"{project_id}: target index must be an array")
    expected_ids = [str(target["target_id"]) for target in expected_targets]
    actual_ids = [str(row["target_id"]) for row in index]
    if actual_ids != expected_ids:
        raise ValidationError(f"{project_id}: target index differs from plan")

    target_dirs = sorted(
        path for path in (project_root / "targets").iterdir() if path.is_dir()
    )
    if len(target_dirs) != len(expected_targets):
        raise ValidationError(f"{project_id}: target directory count differs from plan")
    index_by_id = {str(row["target_id"]): row for row in index}
    archive_file_count = 0
    for target in expected_targets:
        target_id = str(target["target_id"])
        expected_name = PurePosixPath(
            target["output_contract"]["target_directory"]
        ).name
        target_root = project_root / "targets" / expected_name
        manifest_path = target_root / "manifest.json"
        archive_path = target_root / "pre_repo.zip"
        manifest = _read(manifest_path)
        if manifest != index_by_id[target_id]:
            raise ValidationError(f"{target_id}: manifest and target index differ")
        if manifest.get("before_message_id") != target.get("target_message_id"):
            raise ValidationError(f"{target_id}: boundary differs from plan")
        if not manifest.get("pre_state_verified_against_gold") or not manifest.get(
            "post_state_verified_against_gold"
        ):
            raise ValidationError(f"{target_id}: Gold replay verification is missing")
        if manifest.get("archive_sha256") != _sha256(archive_path):
            raise ValidationError(f"{target_id}: archive hash mismatch")
        member_count, tree_hash = _audit_archive(archive_path)
        archive_file_count += member_count
        if manifest.get("repo_sha256") != tree_hash:
            raise ValidationError(f"{target_id}: repository tree hash mismatch")

    baseline_archive = project_root / "C_env" / f"{project_id}_C_env_complete.zip"
    baseline_count, baseline_tree_hash = _audit_archive(baseline_archive)
    baseline_report = validation.get("baseline")
    if not isinstance(baseline_report, Mapping):
        raise ValidationError(f"{project_id}: baseline validation is missing")
    if baseline_report.get("archive_sha256") != _sha256(baseline_archive):
        raise ValidationError(f"{project_id}: baseline archive hash mismatch")
    if baseline_report.get("repo_sha256") != baseline_tree_hash:
        raise ValidationError(f"{project_id}: baseline tree hash mismatch")

    source_report = _read(reports / "source_checksums.json")
    if source_report.get("plan_sha256") != _sha256(plan_path):
        raise ValidationError(f"{project_id}: source report plan hash mismatch")
    if source_report.get("sources") != plan.get("project_sources"):
        raise ValidationError(f"{project_id}: source report differs from plan")

    return {
        "project_id": project_id,
        "target_count": len(expected_targets),
        "target_archive_file_count": archive_file_count,
        "baseline_archive_file_count": baseline_count,
        "status": "PASS",
    }


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans-root", type=Path, default=DEFAULT_PLANS_ROOT)
    parser.add_argument("--environment-root", type=Path, default=DEFAULT_ENV_ROOT)
    return parser.parse_args()


def main() -> int:
    args = _args()
    try:
        allowlist = _read(ROOT / "Code" / "config" / "rq4_project_allowlist.json")
        project_ids = list(allowlist["project_ids"])
        actual_dirs = {
            path.name
            for path in args.environment_root.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        }
        if actual_dirs != set(project_ids):
            raise ValidationError(
                f"canonical project set differs from allowlist: {sorted(actual_dirs)}"
            )
        staging = args.environment_root / ".staging"
        if staging.exists() and any(staging.iterdir()):
            raise ValidationError("non-empty build staging remains")
        results = [
            _validate_project(
                project_id,
                args.plans_root / project_id / "rq4_build_plan.json",
                args.environment_root,
            )
            for project_id in project_ids
        ]
        output = {
            "project_count": len(results),
            "target_count": sum(row["target_count"] for row in results),
            "projects": results,
            "status": "PASS",
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (OSError, KeyError, TypeError, ValueError, ValidationError) as exc:
        print(f"RQ4 Code Environment validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
