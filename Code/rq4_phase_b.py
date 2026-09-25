"""Safe Phase B staging and immutable capture for RQ4 coding runs."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
from typing import Any, Mapping
import zipfile


RUN_MANIFEST_SCHEMA_VERSION = "rq-private-run-manifest-v2"
PHASE_B_FREEZE_SCHEMA_VERSION = "rq4-phase-b-freeze-v1"
RUN_STATUS_SCHEMA_VERSION = "rq-run-status-v1"
PUBLIC_PHASE_A_FILES = ("task.json", "history.jsonl")


class RQ4PhaseBError(ValueError):
    pass


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RQ4PhaseBError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RQ4PhaseBError(f"{path} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _safe_run_workspace(workspace_root: Path, run_id: str) -> Path:
    if re.fullmatch(r"run_[0-9a-f]{20}", run_id) is None:
        raise RQ4PhaseBError("invalid run_id")
    root = workspace_root.resolve()
    destination = (root / run_id).resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise RQ4PhaseBError("Phase B workspace escapes workspace root") from exc
    return destination


def _safe_archive_member(info: zipfile.ZipInfo) -> tuple[str, ...]:
    normalized = info.filename.replace("\\", "/")
    pure = PurePosixPath(normalized)
    parts = tuple(part for part in pure.parts if part not in ("", "."))
    if (
        pure.is_absolute()
        or re.match(r"^[A-Za-z]:", normalized)
        or ".." in parts
        or stat.S_ISLNK(info.external_attr >> 16)
        or info.flag_bits & 0x1
    ):
        raise RQ4PhaseBError(f"unsafe repository archive member {info.filename!r}")
    return parts


def _extract_repository(archive_path: Path, destination: Path) -> str:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            files = [row for row in archive.infolist() if not row.is_dir()]
            if not files:
                raise RQ4PhaseBError("pre-repository archive is empty")
            seen: set[str] = set()
            seen_casefold: set[str] = set()
            for info in archive.infolist():
                parts = _safe_archive_member(info)
                if not parts:
                    continue
                relative = PurePosixPath(*parts).as_posix()
                if not info.is_dir():
                    if relative in seen or relative.casefold() in seen_casefold:
                        raise RQ4PhaseBError(f"duplicate repository path {relative!r}")
                    seen.add(relative)
                    seen_casefold.add(relative.casefold())
                output = destination.joinpath(*parts)
                if info.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                else:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, output.open("wb") as target:
                        shutil.copyfileobj(source, target)
            bad = archive.testzip()
            if bad is not None:
                raise RQ4PhaseBError(f"repository archive CRC failure: {bad}")
    except zipfile.BadZipFile as exc:
        raise RQ4PhaseBError(f"invalid repository archive: {exc}") from exc
    return _tree_sha256(destination)


def _resolve_repository_path(repository_root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative:
        raise RQ4PhaseBError("run manifest has no repository archive path")
    pure = PurePosixPath(relative.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or re.match(r"^[A-Za-z]:", relative):
        raise RQ4PhaseBError("repository archive path is not repository-relative")
    result = (repository_root.resolve() / Path(*pure.parts)).resolve()
    try:
        result.relative_to(repository_root.resolve())
    except ValueError as exc:
        raise RQ4PhaseBError("repository archive escapes repository root") from exc
    return result


def stage_phase_b_workspace(
    *,
    run_dir: str | Path,
    workspace_root: str | Path,
    repository_root: str | Path,
    instructions_path: str | Path,
) -> Path:
    """Open Phase B only after the frozen Phase A gate says OPEN."""

    run_path = Path(run_dir).resolve()
    manifest_path = run_path / "private" / "run_manifest.json"
    manifest = _json(manifest_path)
    if manifest.get("schema_version") != RUN_MANIFEST_SCHEMA_VERSION:
        raise RQ4PhaseBError("unsupported run manifest schema")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or run_path.name != run_id:
        raise RQ4PhaseBError("run directory identity mismatch")
    rq4 = manifest.get("rq4")
    gate = manifest.get("phase_gate")
    if not isinstance(rq4, Mapping) or not isinstance(gate, Mapping):
        raise RQ4PhaseBError("run manifest has no RQ4 Phase B contract")
    if rq4.get("eligible") is not True or rq4.get("execution_ready") is not True:
        raise RQ4PhaseBError("RQ4 target is not execution-ready")
    if gate.get("phase_b_gate") != "OPEN" or gate.get("phase_a_decision") != "ACT":
        raise RQ4PhaseBError("Phase A gate is not OPEN")
    frozen_response = run_path / "phase_a" / "agent_response.json"
    expected_response_hash = gate.get("phase_a_response_sha256")
    if not frozen_response.is_file() or _sha256(frozen_response) != expected_response_hash:
        raise RQ4PhaseBError("frozen Phase A response is missing or stale")

    repository = manifest.get("repository")
    if not isinstance(repository, Mapping):
        raise RQ4PhaseBError("run manifest has no repository binding")
    archive = _resolve_repository_path(Path(repository_root), repository.get("archive_path"))
    if not archive.is_file() or _sha256(archive) != repository.get("archive_sha256"):
        raise RQ4PhaseBError("pre-repository archive is missing or stale")
    destination = _safe_run_workspace(Path(workspace_root), run_id)
    if destination.exists():
        raise RQ4PhaseBError(f"Phase B workspace already exists: {destination}")
    destination.mkdir(parents=True)
    private_inputs = manifest.get("phase_a_input_files")
    if not isinstance(private_inputs, Mapping):
        raise RQ4PhaseBError("run has no retained Phase A inputs")
    for name in PUBLIC_PHASE_A_FILES:
        record = private_inputs.get(name)
        if not isinstance(record, Mapping):
            raise RQ4PhaseBError(f"missing retained Phase A input {name}")
        source = run_path / str(record.get("path"))
        if not source.is_file() or _sha256(source) != record.get("sha256"):
            raise RQ4PhaseBError(f"retained Phase A input is stale: {name}")
        shutil.copyfile(source, destination / name)
    frozen_dir = destination / "frozen"
    frozen_dir.mkdir()
    copied_response = frozen_dir / "agent_response.json"
    shutil.copyfile(frozen_response, copied_response)
    copied_response.chmod(stat.S_IREAD)
    instructions = Path(instructions_path).read_bytes()
    (destination / "execution_instructions.md").write_bytes(instructions)
    repository_dir = destination / "repository"
    repository_dir.mkdir()
    actual_tree = _extract_repository(archive, repository_dir)
    expected_tree = repository.get("tree_sha256")
    if isinstance(expected_tree, str) and actual_tree != expected_tree:
        shutil.rmtree(destination)
        raise RQ4PhaseBError("pre-repository tree hash mismatch")
    return destination


def _write_deterministic_zip(source: Path, destination: Path) -> tuple[str, str, int]:
    ignored_parts = {"__pycache__", ".git", ".rq4-results"}
    files = [
        path for path in source.rglob("*")
        if path.is_file()
        and not any(part in ignored_parts for part in path.relative_to(source).parts)
        and path.suffix != ".pyc"
    ]
    for path in source.rglob("*"):
        if path.is_symlink():
            raise RQ4PhaseBError(f"final repository contains symlink: {path}")
    temporary = destination.with_name(f".{destination.name}.tmp")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files, key=lambda p: p.relative_to(source).as_posix()):
            relative = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    temporary.replace(destination)
    tree_digest = hashlib.sha256()
    for path in sorted(files, key=lambda p: p.relative_to(source).as_posix()):
        relative = path.relative_to(source).as_posix()
        tree_digest.update(relative.encode("utf-8"))
        tree_digest.update(b"\0")
        tree_digest.update(path.read_bytes())
        tree_digest.update(b"\0")
    return _sha256(destination), tree_digest.hexdigest(), len(files)


def freeze_phase_b_repository(*, run_dir: str | Path, workspace: str | Path) -> dict[str, Any]:
    """Freeze the candidate repository and recheck the immutable Phase A response."""

    run_path = Path(run_dir).resolve()
    workspace_path = Path(workspace).resolve()
    manifest = _json(run_path / "private" / "run_manifest.json")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or workspace_path.name != run_id:
        raise RQ4PhaseBError("Phase B workspace/run identity mismatch")
    expected_response_hash = manifest.get("phase_gate", {}).get("phase_a_response_sha256")
    workspace_response = workspace_path / "frozen" / "agent_response.json"
    canonical_response = run_path / "phase_a" / "agent_response.json"
    if (
        not workspace_response.is_file()
        or not canonical_response.is_file()
        or _sha256(workspace_response) != expected_response_hash
        or _sha256(canonical_response) != expected_response_hash
    ):
        raise RQ4PhaseBError("Phase A response changed during Phase B")
    repository = workspace_path / "repository"
    if not repository.is_dir():
        raise RQ4PhaseBError("Phase B workspace has no final repository")
    output_dir = run_path / "phase_b"
    freeze_path = output_dir / "freeze_record.json"
    if freeze_path.exists():
        raise RQ4PhaseBError(f"Phase B repository is already frozen: {freeze_path}")
    archive_path = output_dir / "final_repository.zip"
    archive_sha, tree_sha, file_count = _write_deterministic_zip(repository, archive_path)
    record = {
        "schema_version": PHASE_B_FREEZE_SCHEMA_VERSION,
        "run_id": run_id,
        "project_id": manifest.get("project_id"),
        "target_id": manifest.get("target_id"),
        "condition": manifest.get("condition"),
        "phase_a_response_sha256": expected_response_hash,
        "final_repository_archive": "phase_b/final_repository.zip",
        "final_repository_archive_sha256": archive_sha,
        "final_repository_tree_sha256": tree_sha,
        "final_repository_file_count": file_count,
        "frozen_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "evaluation_status": "PENDING_AGENT_JUDGE",
    }
    freeze_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status_path = run_path / "run_status.json"
    status = _json(status_path)
    status.update({"phase_b": "FROZEN", "rq4_evaluation": "PENDING_AGENT_JUDGE"})
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


__all__ = [
    "RQ4PhaseBError",
    "freeze_phase_b_repository",
    "stage_phase_b_workspace",
]
