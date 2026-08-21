from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .schemas import EVENT_TYPES
from .storage import read_json


def annotation_statistics(project_id: str, annotation: dict[str, Any]) -> tuple[list[dict[str, Any]], int, int]:
    requirements = annotation.get("requirements", [])
    if not isinstance(requirements, list):
        raise ValueError("Annotation field 'requirements' must be an array")
    rows: list[dict[str, Any]] = []
    project_event_count = 0
    for requirement in requirements:
        if not isinstance(requirement, dict) or not isinstance(requirement.get("events"), list):
            raise ValueError("Every Requirement must be an object with an events array")
        events = requirement["events"]
        counts = {event_type: 0 for event_type in EVENT_TYPES}
        for event in events:
            if isinstance(event, dict) and event.get("event_type") in counts:
                counts[event["event_type"]] += 1
        project_event_count += len(events)
        rows.append(
            {
                "project_id": project_id,
                "requirement_id": requirement.get("requirement_id", ""),
                "requirement_title": requirement.get("title", ""),
                "family_id": requirement.get("family_id", ""),
                "event_count": len(events),
                **{f"{event_type.lower()}_count": counts[event_type] for event_type in sorted(EVENT_TYPES)},
            }
        )
    return rows, len(requirements), project_event_count


def write_statistics(stats_path: Path, output_dir: Path) -> tuple[int, int, int]:
    rows: list[dict[str, Any]] = []
    projects = 0
    for annotation_path in sorted(output_dir.glob("*_stage1_annotation.json")):
        try:
            annotation = read_json(annotation_path)
            project = annotation.get("project", {})
            project_id = project.get("project_id") if isinstance(project, dict) else None
            project_id = project_id or annotation_path.name.removesuffix("_stage1_annotation.json")
            project_rows, _, _ = annotation_statistics(str(project_id), annotation)
        except (OSError, ValueError) as exc:
            print(f"[statistics skipped] {annotation_path.name}: {exc}", flush=True)
            continue
        rows.extend(project_rows)
        projects += 1
    event_columns = [f"{event_type.lower()}_count" for event_type in sorted(EVENT_TYPES)]
    fieldnames = [
        "project_id",
        "requirement_id",
        "requirement_title",
        "family_id",
        "event_count",
        *event_columns,
    ]
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = stats_path.with_suffix(stats_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(stats_path)
    return projects, len(rows), sum(int(row["event_count"]) for row in rows)
