from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ProjectSource
from .storage import id_key


def parse_timestamp(value: Any) -> float:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except (ValueError, OverflowError):
            pass
    return float("inf")


def discover_projects(
    dataset_root: Path,
    output_dir: Path,
    run_root: Path,
    wanted_ids: set[str] | None = None,
) -> list[ProjectSource]:
    if not dataset_root.is_dir():
        raise FileNotFoundError(f"Dataset directory does not exist: {dataset_root}")
    projects: list[ProjectSource] = []
    seen: set[str] = set()
    for chat_path in sorted(dataset_root.rglob("chat_messages.json")):
        metadata = _load_metadata(chat_path.parent)
        project_id = str(metadata.get("contract_id") or chat_path.parent.name)
        if wanted_ids and project_id not in wanted_ids:
            continue
        if project_id in seen:
            raise ValueError(f"Duplicate project directory ID: {project_id}")
        seen.add(project_id)
        projects.append(
            ProjectSource(
                project_id=project_id,
                project_dir=chat_path.parent,
                chat_path=chat_path,
                output_path=output_dir / f"{project_id}_stage1_annotation.json",
                run_dir=run_root / project_id,
            )
        )
    return projects


def _speaker(value: Any) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "buyer": "client",
        "customer": "client",
        "client": "client",
        "freelancer": "freelancer",
        "contractor": "freelancer",
        "talent": "freelancer",
    }
    return aliases.get(raw, raw or "unknown")


def _load_metadata(project_dir: Path) -> dict[str, Any]:
    path = project_dir / "job_metadata.csv"
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        row = next(reader, None)
    return dict(row) if row else {}


def preprocess_project(project: ProjectSource) -> dict[str, Any]:
    try:
        raw_messages = json.loads(project.chat_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {project.chat_path}: {exc}") from exc
    if not isinstance(raw_messages, list) or any(not isinstance(item, dict) for item in raw_messages):
        raise ValueError(f"Expected an array of message objects in {project.chat_path}")

    ordered = sorted(
        enumerate(raw_messages),
        key=lambda pair: (parse_timestamp(pair[1].get("created_ts")), pair[0]),
    )
    existing_ids = [item.get("message_id") for _, item in ordered if item.get("message_id") is not None]
    existing_keys = [id_key(value) for value in existing_ids]
    if len(existing_keys) != len(set(existing_keys)):
        raise ValueError(f"Duplicate existing message_id in {project.chat_path}")
    reserved = set(existing_keys)
    next_fallback = 1
    messages: list[dict[str, Any]] = []
    for original_index, item in ordered:
        message_id = item.get("message_id")
        if message_id is None:
            while id_key(next_fallback) in reserved:
                next_fallback += 1
            message_id = next_fallback
            reserved.add(id_key(message_id))
            next_fallback += 1
        text = item.get("message", item.get("text", ""))
        if not isinstance(text, str):
            raise ValueError(f"Message {message_id!r} text is not a string")
        messages.append(
            {
                "message_id": message_id,
                "created_ts": item.get("created_ts"),
                "speaker": _speaker(item.get("message_user_type", item.get("speaker"))),
                "text": text,
                "milestone": item.get("milestone", item.get("milestone_id")),
                "original_index": original_index,
                "sender_id": item.get("sender_id"),
            }
        )

    metadata = _load_metadata(project.project_dir)
    milestones_path = project.project_dir / "milestones.json"
    if milestones_path.is_file():
        try:
            milestones = json.loads(milestones_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {milestones_path}: {exc}") from exc
        metadata = {**metadata, "milestones": milestones}
    title = metadata.get("job_title") or metadata.get("project_title") or metadata.get("title") or project.project_id
    return {
        "project_id": project.project_id,
        "project_title": title,
        "project_metadata": metadata,
        "source_chat_path": str(project.chat_path),
        "messages": messages,
    }


def message_index(normalized: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    by_id: dict[str, dict[str, Any]] = {}
    order: dict[str, int] = {}
    for position, message in enumerate(normalized["messages"]):
        key = id_key(message["message_id"])
        by_id[key] = message
        order[key] = position
    return by_id, order
