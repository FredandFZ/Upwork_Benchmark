#!/usr/bin/env python3
"""Print value-free diagnostics for rejected offline PII repair tasks."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Mapping

try:
    from PII._compat import read_json
    from pii_prepare_offline_text_repairs import _has_unusable_planned_pii
except ModuleNotFoundError:
    from Code.PII._compat import read_json
    from Code.pii_prepare_offline_text_repairs import _has_unusable_planned_pii


def _changed_originals(task: Mapping[str, Any]) -> list[tuple[str, str]]:
    originals: list[tuple[str, str]] = []
    for slot in task.get("must_apply_slots") or []:
        for occurrence in slot.get("literal_replacements") or []:
            old = occurrence.get("original")
            new = occurrence.get("replacement")
            if (
                isinstance(old, str)
                and old
                and isinstance(new, str)
                and old.casefold() != new.casefold()
            ):
                originals.append(("slot", old))
    for entity in task.get("must_apply_entities") or []:
        if entity.get("policy") not in (None, "SYNTHESIZE"):
            continue
        for old in entity.get("original_surface_forms") or []:
            if isinstance(old, str) and old:
                originals.append(("entity", old))
    return originals


def diagnose(project_id: str, work_root: Path) -> None:
    run_dir = work_root / project_id
    package = read_json(run_dir / "agent_tasks" / "index.json")
    result = read_json(run_dir / "agent_repairs" / "repair_result.json")
    rejected = set((result.get("rejected") or {}).keys())
    print(f"[{project_id}] rejected={len(rejected)}")
    for task in package.get("tasks") or []:
        if task.get("task_id") not in rejected:
            continue
        terms = [
            value
            for value in task.get("must_preserve_verbatim") or []
            if isinstance(value, str) and value
        ]
        originals = _changed_originals(task)
        equal = sum(
            1
            for term in terms
            for _kind, old in originals
            if term.casefold() == old.casefold()
        )
        preserve_contains = sum(
            1
            for term in terms
            for _kind, old in originals
            if old.casefold() in term.casefold()
            and term.casefold() != old.casefold()
        )
        original_contains = sum(
            1
            for term in terms
            for _kind, old in originals
            if term.casefold() in old.casefold()
            and term.casefold() != old.casefold()
        )
        failures = (result.get("rejected") or {}).get(task.get("task_id"), [])
        print(
            "  "
            f"ordinal={task.get('ordinal')} bucket={task.get('bucket')} "
            f"preserve={len(terms)} originals={len(originals)} "
            f"conflicts(eq/preserve-contains/original-contains)="
            f"{equal}/{preserve_contains}/{original_contains} "
            f"errors={len(failures)}"
        )


def summarize_blocked(project_id: str, work_root: Path) -> None:
    run_dir = work_root / project_id
    package = read_json(run_dir / "agent_tasks" / "index.json")
    result = read_json(run_dir / "agent_repairs" / "repair_result.json")
    blocked = set((result.get("blocked") or {}).keys())
    categories = {
        "preserve_entity": 0,
        "preserve_slot": 0,
        "planned_pii": 0,
        "other_mapping": 0,
    }
    for task in package.get("tasks") or []:
        if task.get("task_id") not in blocked:
            continue
        terms = {
            value.casefold()
            for value in task.get("must_preserve_verbatim") or []
            if isinstance(value, str) and value
        }
        originals = _changed_originals(task)
        matched = False
        if any(kind == "entity" and value.casefold() in terms for kind, value in originals):
            categories["preserve_entity"] += 1
            matched = True
        if any(kind == "slot" and value.casefold() in terms for kind, value in originals):
            categories["preserve_slot"] += 1
            matched = True
        if _has_unusable_planned_pii(task):
            categories["planned_pii"] += 1
            matched = True
        if not matched:
            categories["other_mapping"] += 1
    print(
        f"[{project_id}] blocked={len(blocked)} "
        + " ".join(f"{key}={value}" for key, value in categories.items())
    )


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", action="append", required=True)
    parser.add_argument("--blocked-summary", action="store_true")
    parser.add_argument("--work-root", type=Path, default=root / "outputs" / "pii_runs")
    args = parser.parse_args()
    for project_id in args.project_id:
        if args.blocked_summary:
            summarize_blocked(project_id, args.work_root)
        else:
            diagnose(project_id, args.work_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
