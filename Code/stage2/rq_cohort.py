"""Explicit cohort filtering for researcher-side RQ construction."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping
import json

from .rq_instances import RQInstanceError


EXCLUSION_SCHEMA_VERSION = "rq-target-exclusions-v1"
EXCLUSION_SCOPE = "MAIN_RQ123_PHASE_A_COHORT"


def load_target_exclusions(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RQInstanceError(f"cannot read RQ target exclusions {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise RQInstanceError("RQ target exclusions must be a JSON object")
    if value.get("schema_version") != EXCLUSION_SCHEMA_VERSION:
        raise RQInstanceError("unsupported RQ target exclusion schema")
    if value.get("scope") != EXCLUSION_SCOPE:
        raise RQInstanceError("RQ target exclusions use an unsupported scope")
    rows = value.get("exclusions")
    if not isinstance(rows, list):
        raise RQInstanceError("RQ target exclusions.exclusions must be an array")
    seen: set[tuple[str, str]] = set()
    normalized: list[dict[str, str]] = []
    for position, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise RQInstanceError(f"RQ target exclusion {position} must be an object")
        normalized_row: dict[str, str] = {}
        for field in ("project_id", "target_id", "reason", "detail"):
            item = row.get(field)
            if not isinstance(item, str) or not item.strip():
                raise RQInstanceError(
                    f"RQ target exclusion {position}.{field} must be non-empty text"
                )
            normalized_row[field] = item.strip()
        key = (normalized_row["project_id"], normalized_row["target_id"])
        if key in seen:
            raise RQInstanceError(f"duplicate RQ target exclusion {key!r}")
        seen.add(key)
        normalized.append(normalized_row)
    return {
        "schema_version": EXCLUSION_SCHEMA_VERSION,
        "scope": EXCLUSION_SCOPE,
        "exclusions": normalized,
    }


def apply_target_exclusions(
    gold_states: Mapping[str, Any],
    exclusion_config: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return a filtered copy while preserving the source Stage 2 Gold file."""

    project_id = gold_states.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise RQInstanceError("gold_states.project_id must be non-empty text")
    targets = gold_states.get("task_gold_states")
    if not isinstance(targets, list):
        raise RQInstanceError("gold_states.task_gold_states must be an array")
    project_exclusions = [
        deepcopy(dict(row))
        for row in exclusion_config.get("exclusions", [])
        if isinstance(row, Mapping) and row.get("project_id") == project_id
    ]
    excluded_ids = {row["target_id"] for row in project_exclusions}
    target_ids = {
        row.get("target_id")
        for row in targets
        if isinstance(row, Mapping) and isinstance(row.get("target_id"), str)
    }
    missing = sorted(excluded_ids.difference(target_ids))
    if missing:
        raise RQInstanceError(
            f"RQ cohort exclusions reference missing {project_id} targets: {missing}"
        )
    filtered = deepcopy(dict(gold_states))
    filtered["task_gold_states"] = [
        deepcopy(row)
        for row in targets
        if not isinstance(row, Mapping) or row.get("target_id") not in excluded_ids
    ]
    return filtered, project_exclusions


__all__ = [
    "EXCLUSION_SCHEMA_VERSION",
    "EXCLUSION_SCOPE",
    "apply_target_exclusions",
    "load_target_exclusions",
]
