#!/usr/bin/env python3
"""Aggregate formal RQ4 results, including Phase A no-code-submission failures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


class RQ4AggregationError(ValueError):
    pass


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RQ4AggregationError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RQ4AggregationError(f"{path} must contain a JSON object")
    return value


def aggregate(run_root: Path) -> dict[str, Any]:
    manifests = sorted(run_root.rglob("private/run_manifest.json"))
    if not manifests:
        raise RQ4AggregationError(f"no RQ4 runs below {run_root}")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for manifest_path in manifests:
        run_dir = manifest_path.parent.parent
        manifest = _json(manifest_path)
        rq4 = manifest.get("rq4")
        if not isinstance(rq4, dict) or rq4.get("eligible") is not True:
            continue
        key = (
            manifest.get("project_id"),
            manifest.get("target_id"),
            manifest.get("condition"),
            manifest.get("agent_config_id"),
            manifest.get("repetition"),
        )
        if key in seen:
            raise RQ4AggregationError(f"duplicate RQ4 run identity {key}")
        seen.add(key)
        gate = manifest.get("phase_gate", {})
        result_path = run_dir / "rq4_evaluation" / "result.json"
        if result_path.is_file():
            result = _json(result_path)
            score_status = result.get("score_status")
            formal_result = result.get("result")
            reason = result.get("decision_reason")
        elif gate.get("phase_b_gate") == "CLOSED" and gate.get("phase_b_gate_reason") == "AGENT_DECISION_NOT_ACT":
            score_status, formal_result, reason = "SCORED", "FAIL", "NO_CODE_SUBMISSION"
        else:
            status_path = run_dir / "run_status.json"
            status = _json(status_path) if status_path.is_file() else {}
            if status.get("rq4_result") == "FAIL" and status.get("phase_b") == "FAILED":
                score_status, formal_result, reason = "SCORED", "FAIL", "PHASE_B_AGENT_FAILURE"
            else:
                score_status, formal_result, reason = "PENDING", None, "INCOMPLETE_PIPELINE"
        rows.append(
            {
                "run_id": manifest.get("run_id"),
                "project_id": manifest.get("project_id"),
                "target_id": manifest.get("target_id"),
                "condition": manifest.get("condition"),
                "agent_config_id": manifest.get("agent_config_id"),
                "repetition": manifest.get("repetition"),
                "score_status": score_status,
                "result": formal_result,
                "reason": reason,
            }
        )
    scored = [row for row in rows if row["score_status"] == "SCORED"]
    passed = sum(row["result"] == "PASS" for row in scored)
    failed = sum(row["result"] == "FAIL" for row in scored)
    pair_groups: dict[tuple[Any, ...], dict[str, dict[str, Any]]] = {}
    for row in rows:
        pair_key = (
            row["project_id"],
            row["target_id"],
            row["agent_config_id"],
            row["repetition"],
        )
        pair_groups.setdefault(pair_key, {})[row["condition"]] = row
    eligible_pairs = [
        group
        for group in pair_groups.values()
        if set(group) == {"C1", "C2"}
    ]
    scored_pairs = [
        group
        for group in eligible_pairs
        if all(group[condition]["score_status"] == "SCORED" for condition in ("C1", "C2"))
    ]
    paired_pass_counts = {
        condition: sum(group[condition]["result"] == "PASS" for group in scored_pairs)
        for condition in ("C1", "C2")
    }
    paired_rates = {
        condition: (
            paired_pass_counts[condition] / len(scored_pairs)
            if scored_pairs
            else None
        )
        for condition in ("C1", "C2")
    }
    project_ids = sorted({row["project_id"] for row in rows})
    by_project: dict[str, dict[str, Any]] = {}
    for project_id in project_ids:
        project_rows = [row for row in rows if row["project_id"] == project_id]
        project_scored = [row for row in project_rows if row["score_status"] == "SCORED"]
        project_passed = sum(row["result"] == "PASS" for row in project_scored)
        by_project[project_id] = {
            "eligible": len(project_rows),
            "scored": len(project_scored),
            "pass": project_passed,
            "fail": sum(row["result"] == "FAIL" for row in project_scored),
            "success_rate": (
                project_passed / len(project_scored) if project_scored else None
            ),
            "execution_coverage": (
                len(project_scored) / len(project_rows) if project_rows else None
            ),
        }
    project_rates = [
        metrics["success_rate"]
        for metrics in by_project.values()
        if metrics["success_rate"] is not None
    ]
    paired_project_rates: dict[str, list[float]] = {"C1": [], "C2": []}
    for project_id in project_ids:
        project_pairs = [
            group
            for group in scored_pairs
            if group["C1"]["project_id"] == project_id
        ]
        if not project_pairs:
            continue
        for condition in ("C1", "C2"):
            paired_project_rates[condition].append(
                sum(group[condition]["result"] == "PASS" for group in project_pairs)
                / len(project_pairs)
            )
    paired_project_macro = {
        condition: (
            sum(paired_project_rates[condition]) / len(paired_project_rates[condition])
            if paired_project_rates[condition]
            else None
        )
        for condition in ("C1", "C2")
    }
    return {
        "schema_version": "rq4-aggregate-v1",
        "eligible_run_count": len(rows),
        "scored_run_count": len(scored),
        "pending_or_review_count": len(rows) - len(scored),
        "pass_count": passed,
        "fail_count": failed,
        "success_rate": passed / len(scored) if scored else None,
        "project_macro_success_rate": (
            sum(project_rates) / len(project_rates) if project_rates else None
        ),
        "project_macro_project_count": len(project_rates),
        "execution_coverage": len(scored) / len(rows) if rows else None,
        "by_condition": {
            condition: {
                "eligible": sum(row["condition"] == condition for row in rows),
                "scored": sum(row["condition"] == condition for row in scored),
                "pass": sum(row["condition"] == condition and row["result"] == "PASS" for row in scored),
                "fail": sum(row["condition"] == condition and row["result"] == "FAIL" for row in scored),
            }
            for condition in ("C1", "C2")
        },
        "by_project": by_project,
        "paired_comparison": {
            "unit": "same project_id, target_id, agent_config_id, and repetition",
            "eligible_pair_count": len(eligible_pairs),
            "scored_pair_count": len(scored_pairs),
            "execution_coverage": (
                len(scored_pairs) / len(eligible_pairs) if eligible_pairs else None
            ),
            "pass_count": paired_pass_counts,
            "success_rate": paired_rates,
            "success_rate_delta_c2_minus_c1": (
                paired_rates["C2"] - paired_rates["C1"]
                if scored_pairs
                else None
            ),
            "project_macro_success_rate": paired_project_macro,
            "project_macro_success_rate_delta_c2_minus_c1": (
                paired_project_macro["C2"] - paired_project_macro["C1"]
                if paired_project_macro["C1"] is not None
                and paired_project_macro["C2"] is not None
                else None
            ),
            "discordant_pairs": {
                "c1_pass_c2_fail": sum(
                    group["C1"]["result"] == "PASS"
                    and group["C2"]["result"] == "FAIL"
                    for group in scored_pairs
                ),
                "c1_fail_c2_pass": sum(
                    group["C1"]["result"] == "FAIL"
                    and group["C2"]["result"] == "PASS"
                    for group in scored_pairs
                ),
            },
        },
        "runs": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=ROOT / "outputs_new" / "rq4_runs")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs_new" / "rq_results" / "rq4_summary.json")
    args = parser.parse_args()
    try:
        result = aggregate(args.run_root.resolve())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary_keys = (
            "eligible_run_count",
            "scored_run_count",
            "pending_or_review_count",
            "pass_count",
            "fail_count",
            "success_rate",
            "project_macro_success_rate",
            "execution_coverage",
            "paired_comparison",
        )
        print(
            json.dumps(
                {key: result[key] for key in summary_keys},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (OSError, RQ4AggregationError) as exc:
        print(f"RQ4 aggregation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
