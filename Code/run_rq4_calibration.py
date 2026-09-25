#!/usr/bin/env python3
"""Mechanically calibrate one frozen RQ4 validator package.

The harness never edits a source archive or a validator package.  Every
delivery is extracted into a fresh temporary directory, the frozen validator
files are copied beside it, and commands are launched without a shell.

Command exit codes have a deliberately narrow meaning:

* 0: the candidate passed that check;
* 1: the candidate failed that check;
* any other exit, launch error, or timeout: harness fault.

An expected target-test failure on the pre-repository or a partial delivery is
therefore calibration evidence, not a harness failure and not an RQ4 score.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence
import zipfile


SPEC_SCHEMA_VERSION = "rq4-calibration-spec-v1"
RESULT_SCHEMA_VERSION = "rq4-calibration-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_ARCHIVE_FILES = 20_000
MAX_ARCHIVE_MEMBER_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 1024 * 1024 * 1024


class RQ4CalibrationError(ValueError):
    """The frozen calibration inputs are missing, unsafe, or inconsistent."""


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RQ4CalibrationError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RQ4CalibrationError(f"{label} must be a JSON object")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RQ4CalibrationError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        (
            (path.relative_to(root).as_posix(), path)
            for path in root.rglob("*")
            if path.is_file()
        ),
        key=lambda item: item[0],
    )
    for relative, path in files:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RQ4CalibrationError(f"{label} must be a non-empty string")
    return value.strip()


def _sha256(value: Any, label: str) -> str:
    digest = _text(value, label)
    if SHA256_RE.fullmatch(digest) is None:
        raise RQ4CalibrationError(f"{label} must be a lowercase SHA-256")
    return digest


def _safe_relative_path(value: Any, label: str) -> PurePosixPath:
    text = _text(value, label).replace("\\", "/")
    pure = PurePosixPath(text)
    if (
        pure.is_absolute()
        or re.match(r"^[A-Za-z]:", text)
        or ".." in pure.parts
        or not pure.parts
    ):
        raise RQ4CalibrationError(f"{label} is not a safe relative path")
    return pure


def _string_array(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if (
        not isinstance(value, list)
        or (not value and not allow_empty)
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise RQ4CalibrationError(f"{label} must be a string array")
    return list(value)


def _validate_archive_record(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RQ4CalibrationError(f"{label} must be an object")
    record = {
        "archive_sha256": _sha256(value.get("archive_sha256"), f"{label}.archive_sha256")
    }
    tree = value.get("tree_sha256")
    if tree is not None:
        record["tree_sha256"] = _sha256(tree, f"{label}.tree_sha256")
    return record


def validate_calibration_spec(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize the frozen, target-specific calibration contract."""

    if value.get("schema_version") != SPEC_SCHEMA_VERSION:
        raise RQ4CalibrationError("unsupported calibration spec schema")
    if value.get("status") != "FROZEN":
        raise RQ4CalibrationError("calibration spec must have status FROZEN")
    project_id = _text(value.get("project_id"), "project_id")
    target_id = _text(value.get("target_id"), "target_id")
    if not target_id.startswith(f"{project_id}_"):
        raise RQ4CalibrationError("target_id does not belong to project_id")
    validator_id = _text(value.get("validator_id"), "validator_id")
    acceptance_sha = _sha256(
        value.get("acceptance_criteria_sha256"), "acceptance_criteria_sha256"
    )

    raw_files = value.get("validator_files")
    if not isinstance(raw_files, list) or not raw_files:
        raise RQ4CalibrationError("validator_files must be a non-empty array")
    validator_files: list[dict[str, str]] = []
    seen_files: set[str] = set()
    seen_files_casefold: set[str] = set()
    for index, raw in enumerate(raw_files):
        if not isinstance(raw, Mapping):
            raise RQ4CalibrationError(f"validator_files[{index}] must be an object")
        relative = _safe_relative_path(
            raw.get("path"), f"validator_files[{index}].path"
        ).as_posix()
        if relative in seen_files or relative.casefold() in seen_files_casefold:
            raise RQ4CalibrationError(f"duplicate validator file {relative!r}")
        seen_files.add(relative)
        seen_files_casefold.add(relative.casefold())
        validator_files.append(
            {
                "path": relative,
                "sha256": _sha256(
                    raw.get("sha256"), f"validator_files[{index}].sha256"
                ),
            }
        )
    if acceptance_sha not in {record["sha256"] for record in validator_files}:
        raise RQ4CalibrationError(
            "acceptance_criteria_sha256 is not bound to a frozen validator file"
        )

    raw_commands = value.get("commands")
    if not isinstance(raw_commands, Mapping) or set(raw_commands) != {
        "build",
        "target_test",
        "regression",
    }:
        raise RQ4CalibrationError(
            "commands must contain exactly build, target_test, and regression"
        )
    commands = {
        name: _string_array(raw_commands.get(name), f"commands.{name}")
        for name in ("build", "target_test", "regression")
    }
    allowed_placeholders = {"{python}", "{repo}", "{validator_root}"}
    for name, command in commands.items():
        for argument in command:
            placeholders = set(re.findall(r"\{[^{}]+\}", argument))
            unknown = placeholders - allowed_placeholders
            if unknown:
                raise RQ4CalibrationError(
                    f"commands.{name} contains unsupported placeholders {sorted(unknown)}"
                )

    timeout = value.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise RQ4CalibrationError("timeout_seconds must be a positive integer")
    if value.get("network_policy") != "DISABLED":
        raise RQ4CalibrationError("network_policy must be DISABLED")
    if value.get("fresh_workspace_required") is not True:
        raise RQ4CalibrationError("fresh_workspace_required must be true")
    environment_allowlist = _string_array(
        value.get("environment_allowlist", []),
        "environment_allowlist",
        allow_empty=True,
    )

    raw_inputs = value.get("calibration_inputs")
    if not isinstance(raw_inputs, Mapping):
        raise RQ4CalibrationError("calibration_inputs must be an object")
    pre_repo = _validate_archive_record(raw_inputs.get("pre_repo"), "pre_repo")
    reference = _validate_archive_record(
        raw_inputs.get("reference_delivery"), "reference_delivery"
    )
    raw_partials = raw_inputs.get("partial_deliveries")
    if not isinstance(raw_partials, list) or not raw_partials:
        raise RQ4CalibrationError("partial_deliveries must be a non-empty array")
    partials: list[dict[str, Any]] = []
    seen_delivery_ids: set[str] = set()
    for index, raw in enumerate(raw_partials):
        if not isinstance(raw, Mapping):
            raise RQ4CalibrationError(f"partial_deliveries[{index}] must be an object")
        delivery_id = _text(
            raw.get("delivery_id"), f"partial_deliveries[{index}].delivery_id"
        )
        if (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", delivery_id) is None
            or delivery_id in {"pre_repo", "reference_delivery"}
        ):
            raise RQ4CalibrationError(
                f"partial_deliveries[{index}].delivery_id is not a safe unique name"
            )
        if delivery_id in seen_delivery_ids:
            raise RQ4CalibrationError(f"duplicate partial delivery {delivery_id!r}")
        seen_delivery_ids.add(delivery_id)
        expected = raw.get("expected_result")
        if expected not in {
            "TARGET_TEST_FAIL",
            "REGRESSION_FAIL",
            "TARGET_OR_REGRESSION_FAIL",
        }:
            raise RQ4CalibrationError(
                f"partial_deliveries[{index}].expected_result is invalid"
            )
        partials.append(
            {
                "delivery_id": delivery_id,
                **_validate_archive_record(raw, f"partial_deliveries[{index}]"),
                "expected_result": expected,
            }
        )

    return {
        "schema_version": SPEC_SCHEMA_VERSION,
        "status": "FROZEN",
        "project_id": project_id,
        "target_id": target_id,
        "validator_id": validator_id,
        "acceptance_criteria_sha256": acceptance_sha,
        "validator_files": validator_files,
        "commands": commands,
        "timeout_seconds": timeout,
        "network_policy": "DISABLED",
        "fresh_workspace_required": True,
        "environment_allowlist": sorted(set(environment_allowlist)),
        "calibration_inputs": {
            "pre_repo": pre_repo,
            "reference_delivery": reference,
            "partial_deliveries": partials,
        },
    }


def _validate_validator_files(
    spec_path: Path, spec: Mapping[str, Any]
) -> list[tuple[PurePosixPath, Path, str]]:
    root = spec_path.parent.resolve()
    output: list[tuple[PurePosixPath, Path, str]] = []
    for record in spec["validator_files"]:
        relative = PurePosixPath(record["path"])
        path = (root / Path(*relative.parts)).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:  # pragma: no cover - guarded by path validation
            raise RQ4CalibrationError(f"validator file escapes package: {relative}") from exc
        if not path.is_file():
            raise RQ4CalibrationError(f"missing frozen validator file: {relative}")
        actual = _sha256_file(path)
        if actual != record["sha256"]:
            raise RQ4CalibrationError(f"frozen validator file hash mismatch: {relative}")
        output.append((relative, path, actual))
    return output


def _inspect_archive(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RQ4CalibrationError(f"delivery archive does not exist: {path}")
    try:
        with zipfile.ZipFile(path) as archive:
            files = [info for info in archive.infolist() if not info.is_dir()]
            if not files:
                raise RQ4CalibrationError(f"delivery archive is empty: {path}")
            if len(files) > MAX_ARCHIVE_FILES:
                raise RQ4CalibrationError(f"delivery archive has too many files: {path}")
            names: set[str] = set()
            casefold_names: set[str] = set()
            total = 0
            for info in archive.infolist():
                normalized = info.filename.replace("\\", "/")
                pure = PurePosixPath(normalized)
                parts = [part for part in pure.parts if part not in ("", ".")]
                if (
                    pure.is_absolute()
                    or re.match(r"^[A-Za-z]:", normalized)
                    or ".." in parts
                ):
                    raise RQ4CalibrationError(
                        f"unsafe path in delivery archive: {info.filename!r}"
                    )
                unix_mode = info.external_attr >> 16
                if stat.S_ISLNK(unix_mode):
                    raise RQ4CalibrationError(
                        f"symlink in delivery archive: {info.filename!r}"
                    )
                if info.flag_bits & 0x1:
                    raise RQ4CalibrationError(
                        f"encrypted delivery archive member: {info.filename!r}"
                    )
                if info.is_dir():
                    continue
                canonical = PurePosixPath(*parts).as_posix()
                if canonical in names or canonical.casefold() in casefold_names:
                    raise RQ4CalibrationError(
                        f"duplicate delivery archive path: {info.filename!r}"
                    )
                names.add(canonical)
                casefold_names.add(canonical.casefold())
                if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                    raise RQ4CalibrationError(
                        f"delivery archive member is too large: {info.filename!r}"
                    )
                total += info.file_size
                if total > MAX_ARCHIVE_TOTAL_BYTES:
                    raise RQ4CalibrationError(
                        f"delivery archive is too large when extracted: {path}"
                    )
            # Run CRC validation only after metadata size and path checks so a
            # declared oversized archive is rejected before decompression.
            bad_member = archive.testzip()
            if bad_member is not None:
                raise RQ4CalibrationError(f"archive CRC failure in {bad_member!r}")
            return {
                "archive_sha256": _sha256_file(path),
                "file_count": len(files),
                "uncompressed_bytes": total,
            }
    except zipfile.BadZipFile as exc:
        raise RQ4CalibrationError(f"invalid delivery ZIP {path}: {exc}") from exc


def _extract_archive(path: Path, destination: Path) -> dict[str, Any]:
    inspection = _inspect_archive(path)
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            parts = [
                part
                for part in PurePosixPath(info.filename.replace("\\", "/")).parts
                if part not in ("", ".")
            ]
            output = destination.joinpath(*parts)
            if info.is_dir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, output.open("wb") as target:
                shutil.copyfileobj(source, target)
    inspection["tree_sha256"] = _tree_sha256(destination)
    return inspection


def _minimal_environment(allowlist: Sequence[str]) -> dict[str, str]:
    required = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in required or key in allowlist
    }
    environment.update(
        {
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "ALL_PROXY": "",
            "NO_PROXY": "*",
            "RQ4_NETWORK_POLICY": "DISABLED",
        }
    )
    return environment


def _expanded_command(
    template: Sequence[str], *, repository: Path, validator_root: Path
) -> list[str]:
    replacements = {
        "{python}": sys.executable,
        "{repo}": str(repository),
        "{validator_root}": str(validator_root),
    }
    output: list[str] = []
    for argument in template:
        expanded = argument
        for token, replacement in replacements.items():
            expanded = expanded.replace(token, replacement)
        output.append(expanded)
    return output


def _normalize_process_text(value: str, repository: Path, validator_root: Path) -> str:
    normalized = value.replace(str(repository), "<repo>")
    normalized = normalized.replace(str(validator_root), "<validator_root>")
    return normalized[-8000:]


def _run_check(
    name: str,
    template: Sequence[str],
    *,
    repository: Path,
    validator_root: Path,
    timeout_seconds: int,
    environment: Mapping[str, str],
) -> dict[str, Any]:
    command = _expanded_command(
        template, repository=repository, validator_root=validator_root
    )
    cwd = validator_root if name == "target_test" else repository
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=dict(environment),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (
            exc.stdout.decode("utf-8", "replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode("utf-8", "replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        return {
            "check": name,
            "command_template": list(template),
            "outcome": "HARNESS_FAULT",
            "exit_code": None,
            "fault_kind": "TIMEOUT",
            "stdout_tail": _normalize_process_text(stdout, repository, validator_root),
            "stderr_tail": _normalize_process_text(stderr, repository, validator_root),
        }
    except OSError as exc:
        return {
            "check": name,
            "command_template": list(template),
            "outcome": "HARNESS_FAULT",
            "exit_code": None,
            "fault_kind": "PROCESS_LAUNCH_ERROR",
            "stdout_tail": "",
            "stderr_tail": f"{type(exc).__name__}: {exc}",
        }
    if result.returncode == 0:
        outcome, fault_kind = "PASS", None
    elif result.returncode == 1:
        outcome, fault_kind = "CANDIDATE_FAIL", None
    else:
        outcome, fault_kind = "HARNESS_FAULT", "UNSUPPORTED_EXIT_CODE"
    return {
        "check": name,
        "command_template": list(template),
        "outcome": outcome,
        "exit_code": result.returncode,
        "fault_kind": fault_kind,
        "stdout_tail": _normalize_process_text(
            result.stdout, repository, validator_root
        ),
        "stderr_tail": _normalize_process_text(
            result.stderr, repository, validator_root
        ),
    }


def _copy_validator_files(
    files: Sequence[tuple[PurePosixPath, Path, str]], destination: Path
) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for relative, source, _ in files:
        output = destination.joinpath(*relative.parts)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, output)


def _run_delivery(
    *,
    delivery_id: str,
    role: str,
    archive_path: Path,
    expected_archive: Mapping[str, Any],
    spec: Mapping[str, Any],
    validator_files: Sequence[tuple[PurePosixPath, Path, str]],
    temporary_root: Path,
) -> dict[str, Any]:
    archive_inspection = _inspect_archive(archive_path)
    if archive_inspection["archive_sha256"] != expected_archive["archive_sha256"]:
        raise RQ4CalibrationError(f"{delivery_id} archive SHA-256 mismatch")
    delivery_root = temporary_root / delivery_id
    repository = delivery_root / "repository"
    validator_root = delivery_root / "validator"
    extracted = _extract_archive(archive_path, repository)
    expected_tree = expected_archive.get("tree_sha256")
    if expected_tree is not None and extracted["tree_sha256"] != expected_tree:
        raise RQ4CalibrationError(f"{delivery_id} repository tree SHA-256 mismatch")
    _copy_validator_files(validator_files, validator_root)
    environment = _minimal_environment(spec["environment_allowlist"])
    checks = {
        name: _run_check(
            name,
            spec["commands"][name],
            repository=repository,
            validator_root=validator_root,
            timeout_seconds=spec["timeout_seconds"],
            environment=environment,
        )
        for name in ("build", "target_test", "regression")
    }
    return {
        "delivery_id": delivery_id,
        "role": role,
        "archive_sha256": extracted["archive_sha256"],
        "tree_sha256": extracted["tree_sha256"],
        "archive_file_count": extracted["file_count"],
        "archive_uncompressed_bytes": extracted["uncompressed_bytes"],
        "checks": checks,
    }


def _expectation(delivery: Mapping[str, Any], expected: str) -> dict[str, Any]:
    checks = delivery["checks"]
    actual = {name: record["outcome"] for name, record in checks.items()}
    if any(outcome == "HARNESS_FAULT" for outcome in actual.values()):
        return {
            "expected": expected,
            "actual": actual,
            "status": "HARNESS_ERROR",
        }
    expected_outcomes = {
        "PRE_REPO": {
            "build": "PASS",
            "target_test": "CANDIDATE_FAIL",
            "regression": "PASS",
        },
        "REFERENCE_PASS": {
            "build": "PASS",
            "target_test": "PASS",
            "regression": "PASS",
        },
        "TARGET_TEST_FAIL": {
            "build": "PASS",
            "target_test": "CANDIDATE_FAIL",
            "regression": "PASS",
        },
        "REGRESSION_FAIL": {
            "build": "PASS",
            "target_test": "PASS",
            "regression": "CANDIDATE_FAIL",
        },
    }
    if expected == "TARGET_OR_REGRESSION_FAIL":
        passed = (
            actual["build"] == "PASS"
            and "CANDIDATE_FAIL"
            in {actual["target_test"], actual["regression"]}
        )
    else:
        passed = actual == expected_outcomes[expected]
    return {
        "expected": expected,
        "actual": actual,
        "status": "PASS" if passed else "FAIL",
    }


def _parse_partial_arguments(values: Sequence[str]) -> dict[str, Path]:
    output: dict[str, Path] = {}
    for value in values:
        delivery_id, separator, raw_path = value.partition("=")
        if not separator or not delivery_id or not raw_path:
            raise RQ4CalibrationError(
                "--partial-delivery must use DELIVERY_ID=ARCHIVE_PATH"
            )
        if delivery_id in output:
            raise RQ4CalibrationError(f"duplicate partial delivery argument {delivery_id!r}")
        output[delivery_id] = Path(raw_path).resolve()
    return output


def run_calibration(
    *,
    spec_path: str | Path,
    pre_repo_path: str | Path,
    reference_delivery_path: str | Path,
    partial_delivery_paths: Mapping[str, str | Path] | None = None,
    temporary_parent: str | Path | None = None,
) -> dict[str, Any]:
    """Run calibration and return a deterministic, hash-bound result record."""

    spec_source = Path(spec_path).resolve()
    spec = validate_calibration_spec(_read_object(spec_source, "calibration spec"))
    validator_files = _validate_validator_files(spec_source, spec)
    partial_paths = {
        key: Path(value).resolve()
        for key, value in (partial_delivery_paths or {}).items()
    }
    expected_partial_ids = {
        row["delivery_id"]
        for row in spec["calibration_inputs"]["partial_deliveries"]
    }
    if set(partial_paths) != expected_partial_ids:
        raise RQ4CalibrationError(
            "partial delivery arguments do not exactly match the frozen spec"
        )
    parent = Path(temporary_parent).resolve() if temporary_parent is not None else None
    if parent is not None:
        parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as directory:
        temp_root = Path(directory)
        deliveries: list[dict[str, Any]] = []
        pre_repo = _run_delivery(
            delivery_id="pre_repo",
            role="PRE_REPO",
            archive_path=Path(pre_repo_path).resolve(),
            expected_archive=spec["calibration_inputs"]["pre_repo"],
            spec=spec,
            validator_files=validator_files,
            temporary_root=temp_root,
        )
        pre_repo["expectation"] = _expectation(pre_repo, "PRE_REPO")
        deliveries.append(pre_repo)
        reference = _run_delivery(
            delivery_id="reference_delivery",
            role="REFERENCE_DELIVERY",
            archive_path=Path(reference_delivery_path).resolve(),
            expected_archive=spec["calibration_inputs"]["reference_delivery"],
            spec=spec,
            validator_files=validator_files,
            temporary_root=temp_root,
        )
        reference["expectation"] = _expectation(reference, "REFERENCE_PASS")
        deliveries.append(reference)
        for row in spec["calibration_inputs"]["partial_deliveries"]:
            delivery_id = row["delivery_id"]
            partial = _run_delivery(
                delivery_id=delivery_id,
                role="PARTIAL_OR_MUTANT",
                archive_path=partial_paths[delivery_id],
                expected_archive=row,
                spec=spec,
                validator_files=validator_files,
                temporary_root=temp_root,
            )
            partial["expectation"] = _expectation(
                partial, row["expected_result"]
            )
            deliveries.append(partial)

    expectation_statuses = [row["expectation"]["status"] for row in deliveries]
    if "HARNESS_ERROR" in expectation_statuses:
        overall = "HARNESS_ERROR"
    elif "FAIL" in expectation_statuses:
        overall = "FAIL"
    else:
        overall = "PASS"
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "project_id": spec["project_id"],
        "target_id": spec["target_id"],
        "validator_id": spec["validator_id"],
        "overall": overall,
        "calibration_complete": overall != "HARNESS_ERROR",
        "eligible_for_freezing": overall == "PASS",
        "identity": {
            "calibration_spec_sha256": _sha256_file(spec_source),
            "acceptance_criteria_sha256": spec["acceptance_criteria_sha256"],
            "validator_files": [
                {"path": relative.as_posix(), "sha256": digest}
                for relative, _, digest in validator_files
            ],
        },
        "execution_contract": {
            "exit_code_0": "PASS",
            "exit_code_1": "CANDIDATE_FAIL",
            "other_exit_or_timeout": "HARNESS_FAULT",
            "network_policy": spec["network_policy"],
            "network_isolation_enforcement": "REQUIRED_FROM_OUTER_RUNNER",
            "fresh_workspace_per_delivery": True,
        },
        "deliveries": deliveries,
    }


def _write_immutable_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise RQ4CalibrationError(f"refusing to replace different calibration: {path}")
        return
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--pre-repo", type=Path, required=True)
    parser.add_argument("--reference-delivery", type=Path, required=True)
    parser.add_argument(
        "--partial-delivery",
        action="append",
        default=[],
        metavar="DELIVERY_ID=ARCHIVE_PATH",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--temporary-parent", type=Path)
    args = parser.parse_args()
    try:
        result = run_calibration(
            spec_path=args.spec,
            pre_repo_path=args.pre_repo,
            reference_delivery_path=args.reference_delivery,
            partial_delivery_paths=_parse_partial_arguments(args.partial_delivery),
            temporary_parent=args.temporary_parent,
        )
        _write_immutable_json(args.output.resolve(), result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return {"PASS": 0, "FAIL": 1, "HARNESS_ERROR": 2}[result["overall"]]
    except (OSError, RQ4CalibrationError) as exc:
        print(f"RQ4 calibration failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
