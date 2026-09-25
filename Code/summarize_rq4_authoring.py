#!/usr/bin/env python3
"""Validate and summarize the private RQ4 Agent-authoring corpus."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

try:
    from .validate_rq4_authoring_proposal import validate_proposal
except ImportError:
    from validate_rq4_authoring_proposal import validate_proposal


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK_ROOT = ROOT / "ccfa-workfiles" / "experiments" / "rq4-validation"


def summarize(work_root: Path) -> dict[str, Any]:
    targets = sorted(work_root.glob("projects/*/targets/*/work_item.json"))
    role_counts: Counter[str] = Counter()
    disposition_counts: Counter[str] = Counter()
    project_counts: dict[str, Counter[str]] = defaultdict(Counter)
    invalid: list[dict[str, str]] = []
    acceptance_criteria_count = 0
    for work_item in targets:
        target_root = work_item.parent
        project_id = target_root.parents[1].name
        proposals = sorted(target_root.glob("**/*_proposal.json"))
        for proposal_path in proposals:
            try:
                result = validate_proposal(
                    proposal_path, work_item, target_root
                )
                role = result["author_role"]
                role_counts[role] += 1
                project_counts[project_id][role] += 1
                proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
                if role == "CRITERIA_AUTHOR":
                    payload = proposal["payload"]
                    disposition_counts[payload["downstream_disposition"]] += 1
                    acceptance_criteria_count += len(payload["acceptance_criteria"])
            except Exception as exc:
                invalid.append(
                    {
                        "path": proposal_path.relative_to(work_root).as_posix(),
                        "error": str(exc),
                    }
                )
    return {
        "schema_version": "rq4-authoring-corpus-summary-v1",
        "target_count": len(targets),
        "valid_proposal_count": sum(role_counts.values()),
        "invalid_proposal_count": len(invalid),
        "proposals_by_role": dict(sorted(role_counts.items())),
        "criteria_dispositions": dict(sorted(disposition_counts.items())),
        "acceptance_criteria_count": acceptance_criteria_count,
        "projects": [
            {"project_id": project_id, "proposals_by_role": dict(sorted(counts.items()))}
            for project_id, counts in sorted(project_counts.items())
        ],
        "invalid_proposals": invalid,
        "formal_eligibility_decided": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = summarize(args.work_root)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    output = args.output or (args.work_root / "authoring_status.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0 if not report["invalid_proposal_count"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
