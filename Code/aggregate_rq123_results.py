#!/usr/bin/env python3
"""Aggregate scored RQ1--RQ3 runs by Agent, Judge, repetition, and condition."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping
import argparse
import json
import sys

try:  # Package import in tests; script import in CLI.
    from .evaluation.rq1 import aggregate_rq1_results
    from .evaluation.rq2 import aggregate_rq2_results, score_rq2_constant_state_baseline
    from .evaluation.rq3 import aggregate_rq3_results, score_rq3_constant_decision_baseline
    from .rq_run_identity import RUN_MANIFEST_SCHEMA_VERSION, read_json_object
except ImportError:  # pragma: no cover
    from evaluation.rq1 import aggregate_rq1_results
    from evaluation.rq2 import aggregate_rq2_results, score_rq2_constant_state_baseline
    from evaluation.rq3 import aggregate_rq3_results, score_rq3_constant_decision_baseline
    from rq_run_identity import RUN_MANIFEST_SCHEMA_VERSION, read_json_object


class RQAggregationError(ValueError):
    """Raised when scored runs cannot form an unambiguous summary."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _aggregate(rq_id: str, rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    if rq_id == "RQ1":
        return aggregate_rq1_results(rows)
    if rq_id == "RQ2":
        return aggregate_rq2_results(rows)
    if rq_id == "RQ3":
        return aggregate_rq3_results(rows)
    raise RQAggregationError(f"unsupported RQ {rq_id}")


def _numeric_delta(left: Any, right: Any) -> Any:
    """Return C2-C1 for matching numeric leaves while preserving metric shape."""

    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    ):
        return round(float(right) - float(left), 6)
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        output = {
            key: _numeric_delta(left[key], right[key])
            for key in left.keys() & right.keys()
        }
        return {key: value for key, value in output.items() if value is not None}
    return None


def _rq2_baseline(instances: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [score_rq2_constant_state_baseline(instance) for instance in instances]
    if not rows:
        raise RQAggregationError("RQ2 baseline requires instances")

    def avg(path: tuple[str, ...]) -> float | None:
        values: list[float] = []
        for row in rows:
            value: Any = row
            for key in path:
                value = value.get(key) if isinstance(value, Mapping) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))
        return round(mean(values), 6) if values else None

    return {
        "schema_version": "rq2-constant-state-baseline-aggregate-v1",
        "target_count": len(rows),
        "baseline": "ORACLE_ALIGNED_MAJORITY_NULL_STATE",
        "metrics": {
            "attribute_reconstruction_score": avg(
                ("metrics", "attribute_reconstruction_score")
            ),
            "matched_full_state_exact": avg(
                ("metrics", "matched_full_state_exact")
            ),
            "reconstruction_coverage": avg(("metrics", "reconstruction_coverage")),
            "matched_state_score_auxiliary": avg(
                ("metrics", "matched_state_score_auxiliary")
            ),
            "per_dimension_scores": {
                dimension: avg(("metrics", "per_dimension_scores", dimension))
                for dimension in (
                    "attributes",
                    "scope",
                    "lifecycle_status",
                    "ambiguity",
                    "execution",
                )
            },
        },
    }


def aggregate_run_tree(
    run_root: str | Path,
    *,
    registered_run_ids: set[str] | None = None,
    experiment_id: str | None = None,
) -> dict[str, Any]:
    root = Path(run_root).resolve()
    groups: dict[tuple[str, str, int, str, str], list[dict[str, Any]]] = defaultdict(list)
    projects: dict[
        tuple[str, str, int, str, str, str], list[dict[str, Any]]
    ] = defaultdict(list)
    configs: dict[str, dict[str, Any]] = {}
    source_instances: dict[tuple[str, str], dict[str, Any]] = {}
    seen_scores: set[tuple[str, str, str]] = set()
    for summary_path in sorted(root.rglob("scores/*/summary.json")):
        run_dir = summary_path.parents[2]
        manifest = read_json_object(run_dir / "private" / "run_manifest.json")
        if manifest.get("schema_version") != RUN_MANIFEST_SCHEMA_VERSION:
            continue
        if (
            registered_run_ids is not None
            and manifest.get("run_id") not in registered_run_ids
        ):
            continue
        summary = read_json_object(summary_path)
        judge_config = summary_path.parent.name
        if summary.get("judge_config_id") != judge_config:
            raise RQAggregationError(f"judge config mismatch at {summary_path}")
        agent_config = str(manifest.get("agent_config_id"))
        repetition = manifest.get("repetition")
        condition = str(manifest.get("condition"))
        project_id = str(manifest.get("project_id"))
        if not isinstance(repetition, int):
            raise RQAggregationError(f"invalid repetition at {summary_path}")
        configs.setdefault(agent_config, dict(manifest.get("agent_config", {})))
        for rq_id in summary.get("scored_rqs", []):
            score_path = summary_path.parent / f"{rq_id}.json"
            score = read_json_object(score_path)
            identity = (str(manifest.get("run_id")), judge_config, rq_id)
            if identity in seen_scores:
                raise RQAggregationError(f"duplicate score {identity}")
            seen_scores.add(identity)
            key = (agent_config, judge_config, repetition, rq_id, condition)
            groups[key].append(score)
            projects[(*key, project_id)].append(score)
            source = manifest.get("source_instances", {}).get(rq_id, {})
            if isinstance(source, Mapping) and isinstance(source.get("path"), str):
                source_instances.setdefault(
                    (rq_id, str(manifest.get("target_id"))),
                    read_json_object(source["path"]),
                )
    if not groups:
        raise RQAggregationError(f"no scored v2 runs found below {root}")

    aggregate_rows: list[dict[str, Any]] = []
    by_pair: dict[tuple[str, str, int, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for key, rows in sorted(groups.items()):
        agent_config, judge_config, repetition, rq_id, condition = key
        aggregate = _aggregate(rq_id, rows)
        entry = {
            "agent_config_id": agent_config,
            "judge_config_id": judge_config,
            "repetition": repetition,
            "rq_id": rq_id,
            "condition": condition,
            "aggregate": aggregate,
        }
        aggregate_rows.append(entry)
        by_pair[(agent_config, judge_config, repetition, rq_id)][condition] = aggregate

    deltas: list[dict[str, Any]] = []
    for key, conditions in sorted(by_pair.items()):
        agent_config, judge_config, repetition, rq_id = key
        if rq_id not in {"RQ2", "RQ3"} or not {"C1", "C2"}.issubset(conditions):
            continue
        metric_key = "macro_metrics" if rq_id == "RQ2" else "official_metrics"
        deltas.append(
            {
                "agent_config_id": agent_config,
                "judge_config_id": judge_config,
                "repetition": repetition,
                "rq_id": rq_id,
                "comparison": "C2_MINUS_C1",
                "metrics": _numeric_delta(
                    conditions["C1"].get(metric_key, {}),
                    conditions["C2"].get(metric_key, {}),
                ),
            }
        )

    project_rows = [
        {
            "agent_config_id": key[0],
            "judge_config_id": key[1],
            "repetition": key[2],
            "rq_id": key[3],
            "condition": key[4],
            "project_id": key[5],
            "aggregate": _aggregate(key[3], rows),
        }
        for key, rows in sorted(projects.items())
    ]
    rq2_instances = [
        instance
        for (rq_id, _), instance in sorted(source_instances.items())
        if rq_id == "RQ2"
    ]
    rq3_instances = [
        instance
        for (rq_id, _), instance in sorted(source_instances.items())
        if rq_id == "RQ3"
    ]
    baselines: dict[str, Any] = {}
    if rq2_instances:
        baselines["RQ2"] = _rq2_baseline(rq2_instances)
    if rq3_instances:
        baselines["RQ3"] = {
            condition: {
                decision: score_rq3_constant_decision_baseline(
                    rq3_instances, condition=condition, decision=decision
                )
                for decision in ("ACT", "CLARIFY")
            }
            for condition in ("C1", "C2")
        }
    return {
        "schema_version": "rq123-benchmark-summary-v1",
        "experiment_id": experiment_id,
        "scored_record_count": len(seen_scores),
        "agent_configs": configs,
        "benchmark_aggregates": aggregate_rows,
        "project_aggregates": project_rows,
        "paired_condition_deltas": deltas,
        "baselines": baselines,
    }


def _args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root", type=Path, default=root / "outputs_new" / "rq_runs"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "outputs_new" / "rq_results" / "rq123_summary.json",
    )
    parser.add_argument(
        "--experiment-id",
        help="Restrict aggregation to run IDs in this experiment's Agent ledger.",
    )
    return parser.parse_args()


def main() -> int:
    args = _args()
    try:
        registered = None
        if args.experiment_id is not None:
            ledger_path = (
                args.run_root
                / "experiments"
                / args.experiment_id
                / "agent_runs.json"
            )
            ledger = read_json_object(ledger_path)
            if ledger.get("experiment_id") != args.experiment_id:
                raise RQAggregationError("experiment Agent ledger identity mismatch")
            registered = {
                row["run_id"]
                for row in ledger.get("runs", [])
                if isinstance(row, Mapping) and isinstance(row.get("run_id"), str)
            }
        summary = aggregate_run_tree(
            args.run_root,
            registered_run_ids=registered,
            experiment_id=args.experiment_id,
        )
        _atomic_json(args.output, summary)
        print(
            f"RQ1--RQ3 summary written: {args.output} "
            f"({summary['scored_record_count']} score records)"
        )
        return 0
    except (OSError, json.JSONDecodeError, RQAggregationError, ValueError) as exc:
        print(f"RQ1--RQ3 aggregation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
