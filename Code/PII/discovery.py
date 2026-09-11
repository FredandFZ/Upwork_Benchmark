"""Project discovery and ``chat_messages.json`` read/write.

Migrated from v6 (``Code/PII_Clean.py:1255-1292``, ``:2999-3067``) with the same
invariants.  The output contract is unchanged from v6: ``message`` is replaced,
``sender_id`` and ``created_ts`` are removed entirely, every other field is
byte-identical, and every non-chat file is copied verbatim.

Note that the copied files (``job.txt``, ``job_metadata.csv``,
``milestones.json``, ``deliverables/``) are **not** de-identified.  That is the
documented scope of this pipeline, not an oversight.
"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

from ._compat import read_json, sha256_text, write_json
from .config import ProjectFiles
from .errors import PiiError
from .textutil import canonical_sha256

CHAT_FILENAME = "chat_messages.json"
REMOVED_FIELDS = ("sender_id", "created_ts")


def discover_projects(
    source_root: Path, wanted_ids: set[str] | None = None
) -> list[ProjectFiles]:
    if not source_root.is_dir():
        raise PiiError(f"dataset project root does not exist: {source_root}")
    projects: list[ProjectFiles] = []
    for project_dir in sorted(
        (path for path in source_root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    ):
        project_id = project_dir.name
        if wanted_ids is not None and project_id not in wanted_ids:
            continue
        chat_path = project_dir / CHAT_FILENAME
        if not chat_path.is_file():
            continue
        projects.append(ProjectFiles(project_id, project_dir, chat_path))
    if wanted_ids is not None:
        missing = wanted_ids.difference(project.project_id for project in projects)
        if missing:
            raise PiiError(
                "unknown project ID(s) or missing chat_messages.json: "
                f"{', '.join(sorted(missing))}"
            )
    return projects


def load_chat(chat_path: Path) -> list[dict[str, Any]]:
    value = read_json(chat_path)
    if not isinstance(value, list):
        raise PiiError(f"{chat_path}: chat_messages.json must contain a JSON list")
    return value


def adapt_messages(chat: Sequence[Any], project_id: str) -> list[dict[str, Any]]:
    """Validate raw rows and project them onto the internal message shape.

    ``ordinal`` is 1-based list position and doubles as ``message_id``, which is
    why a change to the raw file invalidates every per-message run artifact.
    """

    adapted: list[dict[str, Any]] = []
    for index, row in enumerate(chat, start=1):
        if not isinstance(row, dict):
            raise PiiError(f"{project_id}: chat row {index} must be an object")
        if not isinstance(row.get("message"), str):
            raise PiiError(f"{project_id}: chat row {index} needs a string message field")
        adapted.append(
            {
                "ordinal": index,
                "message_id": index,
                "speaker": row.get("message_user_type"),
                "text": row["message"],
                "sender_id": row.get("sender_id"),
            }
        )
    return adapted


def source_signature_hash(chat: Any) -> str:
    return canonical_sha256(chat)


def sender_id_values(messages: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Distinct non-empty raw sender ids.

    The field is dropped from the output, but the values are still audited: a
    model must not copy one into message text.
    """

    seen: dict[str, None] = {}
    for message in messages:
        value = message.get("sender_id")
        if value is None:
            continue
        text = str(value).strip()
        if text:
            seen.setdefault(text, None)
    return tuple(seen)


def build_cleaned_chat(
    original_chat: Sequence[Any], final_texts: Mapping[int, str]
) -> list[dict[str, Any]]:
    """Apply the final text per row, then drop ``sender_id`` and ``created_ts``."""

    cleaned = copy.deepcopy(list(original_chat))
    for index, row in enumerate(cleaned, start=1):
        if index not in final_texts:
            raise PiiError(f"no accepted text for chat row {index}")
        row["message"] = final_texts[index]
        for field in REMOVED_FIELDS:
            row.pop(field, None)
    return cleaned


def _chat_without_cleaned_fields(chat: Sequence[Any]) -> list[dict[str, Any]]:
    value = copy.deepcopy(list(chat))
    for row in value:
        row.pop("message", None)
        for field in REMOVED_FIELDS:
            row.pop(field, None)
    return value


def chat_field_violations(
    original_chat: Sequence[Any], cleaned_chat: Sequence[Any]
) -> list[str]:
    """Structural differences between source and output, as violation strings."""

    violations: list[str] = []
    if len(original_chat) != len(cleaned_chat):
        violations.append(
            "row count changed: "
            f"{len(original_chat)} -> {len(cleaned_chat)}"
        )
        return violations
    for index, row in enumerate(cleaned_chat, start=1):
        if not isinstance(row, dict):
            violations.append(f"row {index} is not an object")
            continue
        if not isinstance(row.get("message"), str):
            violations.append(f"row {index} has no string message")
        for field in REMOVED_FIELDS:
            if field in row:
                violations.append(f"row {index} retained {field}")
    if _chat_without_cleaned_fields(original_chat) != _chat_without_cleaned_fields(
        cleaned_chat
    ):
        violations.append("a field outside message/sender_id/created_ts changed")
    return violations


def copy_project_except_chat(project: ProjectFiles, project_output: Path) -> None:
    """Copy every project file except the raw chat itself."""

    project_output.mkdir(parents=True, exist_ok=True)
    for source in project.project_dir.iterdir():
        if source.name == CHAT_FILENAME:
            continue
        destination = project_output / source.name
        if source.is_dir():
            shutil.copytree(
                source, destination, dirs_exist_ok=True, copy_function=shutil.copy2
            )
        else:
            shutil.copy2(source, destination)


def output_is_current(
    manifest_path: Path, chat_output: Path, source_sha256: str, engine_version: str
) -> bool:
    """Whether a committed output already matches this source and engine."""

    if not (manifest_path.is_file() and chat_output.is_file()):
        return False
    try:
        manifest = read_json(manifest_path)
    except (OSError, ValueError):
        return False
    if not isinstance(manifest, dict) or manifest.get("status") != "DONE":
        return False
    return (
        manifest.get("source_sha256") == source_sha256
        and manifest.get("engine_version") == engine_version
    )


def write_chat(path: Path, cleaned_chat: Sequence[Any]) -> None:
    write_json(path, list(cleaned_chat))


def text_hash(value: str) -> str:
    return sha256_text(value)
