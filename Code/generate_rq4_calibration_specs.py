#!/usr/bin/env python3
"""Freeze hash-bound calibration specifications for complete RQ4 targets.

Only targets with valid criteria, validator, reference, and red-team proposals
are emitted.  The generated specification is target-local and contains no
agent-visible material; it is an immutable researcher-side calibration input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any, Mapping
import zipfile

from run_rq4_calibration import validate_calibration_spec
from validate_rq4_authoring_proposal import validate_proposal


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "ccfa-workfiles" / "experiments" / "rq4-validation" / "projects"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CalibrationSpecError(ValueError):
    pass


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationSpecError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CalibrationSpecError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_target_path(target_root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative:
        raise CalibrationSpecError(f"invalid target-relative path {relative!r}")
    pure = PurePosixPath(relative.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or re.match(r"^[A-Za-z]:", relative):
        raise CalibrationSpecError(f"unsafe target-relative path {relative!r}")
    resolved = (target_root / Path(*pure.parts)).resolve()
    try:
        resolved.relative_to(target_root.resolve())
    except ValueError as exc:
        raise CalibrationSpecError(f"path escapes target root: {relative!r}") from exc
    return resolved


def _zip_tree_sha256(path: Path) -> str:
    """Return the same path/content tree digest used by the calibration harness."""

    digest = hashlib.sha256()
    try:
        with zipfile.ZipFile(path) as archive:
            rows: list[tuple[str, zipfile.ZipInfo]] = []
            seen: set[str] = set()
            seen_casefold: set[str] = set()
            for info in archive.infolist():
                if info.is_dir():
                    continue
                normalized = info.filename.replace("\\", "/")
                pure = PurePosixPath(normalized)
                parts = [part for part in pure.parts if part not in ("", ".")]
                if (
                    pure.is_absolute()
                    or re.match(r"^[A-Za-z]:", normalized)
                    or ".." in parts
                    or stat.S_ISLNK(info.external_attr >> 16)
                    or info.flag_bits & 0x1
                ):
                    raise CalibrationSpecError(f"unsafe ZIP member {info.filename!r}")
                relative = PurePosixPath(*parts).as_posix()
                if relative in seen or relative.casefold() in seen_casefold:
                    raise CalibrationSpecError(f"duplicate ZIP member {relative!r}")
                seen.add(relative)
                seen_casefold.add(relative.casefold())
                rows.append((relative, info))
            if not rows:
                raise CalibrationSpecError(f"empty delivery ZIP: {path}")
            for relative, info in sorted(rows, key=lambda row: row[0]):
                digest.update(relative.encode("utf-8"))
                digest.update(b"\0")
                digest.update(archive.read(info))
                digest.update(b"\0")
    except zipfile.BadZipFile as exc:
        raise CalibrationSpecError(f"invalid delivery ZIP {path}: {exc}") from exc
    return digest.hexdigest()


def _validated_proposal(target_root: Path, relative: str) -> dict[str, Any]:
    proposal_path = target_root / relative
    validate_proposal(proposal_path, target_root / "work_item.json", target_root)
    return _json(proposal_path)


def build_spec(target_root: Path, workspace_root: Path = ROOT) -> dict[str, Any]:
    work_item_path = target_root / "work_item.json"
    work_item = _json(work_item_path)
    criteria_path = target_root / "author" / "criteria_proposal.json"
    criteria = _validated_proposal(target_root, "author/criteria_proposal.json")
    validator = _validated_proposal(target_root, "author/validator_proposal.json")
    reference = _validated_proposal(target_root, "reference/reference_proposal.json")
    red_team = _validated_proposal(target_root, "red_team/red_team_proposal.json")

    if criteria.get("payload", {}).get("downstream_disposition") != "PROCEED_TO_VALIDATOR_AUTHORING":
        raise CalibrationSpecError("criteria proposal does not permit validator authoring")
    expected_criteria_hash = validator.get("payload", {}).get("acceptance_criteria_sha256")
    criteria_hash = _sha256(criteria_path)
    if expected_criteria_hash != criteria_hash:
        raise CalibrationSpecError("validator is not bound to the current criteria proposal")

    validator_files = [{"path": "author/criteria_proposal.json", "sha256": criteria_hash}]
    for record in validator.get("produced_files", []):
        relative = record.get("path")
        path = _safe_target_path(target_root, relative)
        validator_files.append({"path": relative, "sha256": _sha256(path)})

    harness = validator.get("payload", {}).get("harness", {})
    commands = {
        "build": harness.get("build_command"),
        "target_test": harness.get("target_test_command"),
        "regression": harness.get("regression_command"),
    }

    code_environment = work_item.get("code_environment", {})
    pre_path = (workspace_root / code_environment.get("archive_path", "")).resolve()
    if not pre_path.is_file() or _sha256(pre_path) != code_environment.get("archive_sha256"):
        raise CalibrationSpecError("pre-repository archive is missing or stale")

    delivery = reference.get("payload", {}).get("delivery", {})
    reference_path = _safe_target_path(target_root, delivery.get("archive_path"))
    if not reference_path.is_file() or _sha256(reference_path) != delivery.get("archive_sha256"):
        raise CalibrationSpecError("reference archive is missing or stale")
    # Freeze the digest of the tree as the calibration harness actually
    # extracts it.  Author-side tooling may have hashed platform-native ZIP
    # member separators; that metadata is advisory, while the archive hash is
    # the proposal's immutable identity.
    reference_tree_hash = _zip_tree_sha256(reference_path)

    partials: list[dict[str, Any]] = []
    for group in ("partial_deliveries", "mutant_deliveries"):
        for record in red_team.get("payload", {}).get(group, []):
            partial_path = _safe_target_path(target_root, record.get("archive_path"))
            actual_hash = _sha256(partial_path)
            if actual_hash != record.get("archive_sha256"):
                raise CalibrationSpecError(f"red-team archive is stale: {partial_path}")
            partials.append(
                {
                    "delivery_id": record.get("delivery_id"),
                    "archive_sha256": actual_hash,
                    "tree_sha256": _zip_tree_sha256(partial_path),
                    "expected_result": record.get("expected_later_result"),
                }
            )
    if not partials:
        raise CalibrationSpecError("red-team proposal has no partial or mutant delivery")

    spec = {
        "schema_version": "rq4-calibration-spec-v1",
        "status": "FROZEN",
        "project_id": work_item.get("project_id"),
        "target_id": work_item.get("target_id"),
        "validator_id": f"{work_item.get('target_id')}-validator-v1",
        "acceptance_criteria_sha256": criteria_hash,
        "validator_files": validator_files,
        "commands": commands,
        "timeout_seconds": harness.get("timeout_seconds"),
        "network_policy": harness.get("network_policy"),
        "fresh_workspace_required": harness.get("fresh_workspace_required"),
        "environment_allowlist": [],
        "calibration_inputs": {
            "pre_repo": {
                "archive_sha256": code_environment.get("archive_sha256"),
                "tree_sha256": code_environment.get("repository_tree_sha256"),
            },
            "reference_delivery": {
                "archive_sha256": delivery.get("archive_sha256"),
                "tree_sha256": reference_tree_hash,
            },
            "partial_deliveries": partials,
        },
    }
    return validate_calibration_spec(spec)


def _write_immutable(path: Path, value: Mapping[str, Any]) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.exists() and path.read_bytes() != payload:
        raise CalibrationSpecError(f"refusing to replace different frozen spec: {path}")
    path.write_bytes(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--workspace-root", type=Path, default=ROOT)
    parser.add_argument("--target-id", action="append", default=[])
    args = parser.parse_args()
    selected = set(args.target_id)
    generated: list[str] = []
    skipped: list[dict[str, str]] = []
    for work_item_path in sorted(args.corpus_root.glob("*/targets/*/work_item.json")):
        target_root = work_item_path.parent
        target_id = target_root.name
        if selected and target_id not in selected:
            continue
        required = [
            target_root / "author" / "criteria_proposal.json",
            target_root / "author" / "validator_proposal.json",
            target_root / "reference" / "reference_proposal.json",
            target_root / "red_team" / "red_team_proposal.json",
        ]
        if not all(path.is_file() for path in required):
            skipped.append({"target_id": target_id, "reason": "INCOMPLETE_AUTHORING_CHAIN"})
            continue
        try:
            spec = build_spec(target_root, args.workspace_root.resolve())
            _write_immutable(target_root / "calibration_spec.json", spec)
            generated.append(target_id)
        except (OSError, CalibrationSpecError, ValueError) as exc:
            print(f"{target_id}: {exc}", file=sys.stderr)
            return 2
    if selected - set(generated) - {row["target_id"] for row in skipped}:
        print("one or more requested target IDs were not found", file=sys.stderr)
        return 2
    print(json.dumps({"generated": generated, "skipped": skipped}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
