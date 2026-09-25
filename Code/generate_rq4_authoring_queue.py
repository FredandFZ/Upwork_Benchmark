#!/usr/bin/env python3
"""Build the researcher-side RQ4 Agent work queue.

The queue points every role at one universal authoring prompt.  It does not
duplicate or specialize prompts per project, and it never marks an Agent
proposal as calibrated, frozen, or eligible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK_ROOT = ROOT / "ccfa-workfiles" / "experiments" / "rq4-validation"
DEFAULT_PROMPT = ROOT / "prompt" / "rq4_validator_authoring.md"


class QueueError(RuntimeError):
    pass


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QueueError(f"cannot read {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _portable(path: Path) -> str:
    try:
        relative = path.resolve().relative_to(ROOT.resolve())
    except ValueError as exc:
        raise QueueError(f"path escapes workspace: {path}") from exc
    return PurePosixPath(relative).as_posix()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _jobs_for(work_item_path: Path, item: dict[str, Any]) -> list[dict[str, Any]]:
    status = item.get("observability_triage", {}).get("status")
    base = {
        "project_id": item.get("project_id"),
        "target_id": item.get("target_id"),
        "work_item": _portable(work_item_path),
        "work_item_sha256": _sha256(work_item_path),
    }
    jobs = [
        {
            **base,
            "role": "CRITERIA_AUTHOR",
            "queue_state": "READY",
            "depends_on": [],
            "purpose": (
                "AUTHOR_CRITERIA"
                if status == "ELIGIBLE_FOR_VALIDATOR_AUTHORING"
                else "RESOLVE_TRIAGE_OR_RECORD_EXCLUSION"
            ),
        }
    ]
    if status != "ELIGIBLE_FOR_VALIDATOR_AUTHORING":
        return jobs
    jobs.extend(
        [
            {
                **base,
                "role": "REFERENCE_AUTHOR",
                "queue_state": "READY",
                "depends_on": [],
                "purpose": "INDEPENDENT_REFERENCE_FROM_TASK_AND_PRE_REPO",
            },
            {
                **base,
                "role": "VALIDATOR_AUTHOR",
                "queue_state": "BLOCKED_ON_UPSTREAM",
                "depends_on": ["CRITERIA_AUTHOR"],
                "purpose": "IMPLEMENT_HIDDEN_DETERMINISTIC_VALIDATOR",
            },
            {
                **base,
                "role": "RED_TEAM_LEAKAGE_AUDITOR",
                "queue_state": "BLOCKED_ON_UPSTREAM",
                "depends_on": ["CRITERIA_AUTHOR", "VALIDATOR_AUTHOR"],
                "purpose": "AUTHOR_PARTIALS_AND_AUDIT_LEAKAGE",
            },
            {
                **base,
                "role": "INDEPENDENT_REVIEWER",
                "queue_state": "BLOCKED_ON_UPSTREAM",
                "depends_on": [
                    "CRITERIA_AUTHOR",
                    "VALIDATOR_AUTHOR",
                    "REFERENCE_AUTHOR",
                    "RED_TEAM_LEAKAGE_AUDITOR",
                ],
                "purpose": "REVIEW_PROPOSALS_BEFORE_CALIBRATION",
            },
        ]
    )
    return jobs


def build_queue(work_root: Path, prompt_path: Path) -> dict[str, Any]:
    if not prompt_path.is_file():
        raise QueueError(f"universal authoring prompt is missing: {prompt_path}")
    work_items = sorted(work_root.glob("projects/*/targets/*/work_item.json"))
    if not work_items:
        raise QueueError(f"no RQ4 work items found under {work_root}")
    projects: dict[str, list[dict[str, Any]]] = {}
    all_jobs: list[dict[str, Any]] = []
    for path in work_items:
        item = _read_json(path)
        if not isinstance(item, dict):
            raise QueueError(f"work item is not an object: {path}")
        project_id = str(item.get("project_id") or "")
        if not project_id:
            raise QueueError(f"work item has no project_id: {path}")
        jobs = _jobs_for(path, item)
        projects.setdefault(project_id, []).extend(jobs)
        all_jobs.extend(jobs)

    prompt = {"path": _portable(prompt_path), "sha256": _sha256(prompt_path)}
    project_records = []
    for project_id, jobs in sorted(projects.items()):
        project_queue = {
            "schema_version": "rq4-agent-authoring-queue-v1",
            "project_id": project_id,
            "universal_prompt": prompt,
            "jobs": jobs,
        }
        path = work_root / "projects" / project_id / "authoring_queue.json"
        _write_json(path, project_queue)
        project_records.append(
            {
                "project_id": project_id,
                "path": _portable(path),
                "sha256": _sha256(path),
                "job_count": len(jobs),
            }
        )
    queue = {
        "schema_version": "rq4-agent-authoring-queue-v1",
        "scope": "RESEARCHER_PRIVATE_NEVER_AGENT_VISIBLE_DURING_BENCHMARK",
        "universal_prompt": prompt,
        "project_count": len(project_records),
        "target_count": len(work_items),
        "job_count": len(all_jobs),
        "jobs_by_role": {
            role: sum(job["role"] == role for job in all_jobs)
            for role in (
                "CRITERIA_AUTHOR",
                "VALIDATOR_AUTHOR",
                "REFERENCE_AUTHOR",
                "RED_TEAM_LEAKAGE_AUDITOR",
                "INDEPENDENT_REVIEWER",
            )
        },
        "projects": project_records,
        "authority": {
            "agent_outputs_are_proposals": True,
            "calibration_is_deterministic": True,
            "eligibility_is_deterministic": True,
            "runtime_llm_judge": False,
        },
    }
    _write_json(work_root / "authoring_queue.json", queue)
    return queue


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    args = parser.parse_args()
    try:
        result = build_queue(args.work_root, args.prompt)
    except QueueError as exc:
        print(f"RQ4 authoring queue failed: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
