#!/usr/bin/env python3
"""Run materialized RQ1--RQ3 packages in fresh, memory-isolated processes."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from rq_agent_runtime import (
    RQAgentRuntimeError,
    discover_package_manifests,
    run_isolated_agent_case,
)
from rq_run_identity import (
    EXPERIMENT_CONFIG_SCHEMA_VERSION,
    RQRunConfigError,
    read_json_object,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_config(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RQRunConfigError("experiment config must be a JSON object")
    if value.get("schema_version") != EXPERIMENT_CONFIG_SCHEMA_VERSION:
        raise RQRunConfigError("unsupported experiment config schema")
    if not isinstance(value.get("agent"), dict):
        raise RQRunConfigError("experiment config requires an agent object")
    experiment_id = value.get("experiment_id")
    if not isinstance(experiment_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+", experiment_id
    ):
        raise RQRunConfigError(
            "experiment_id must use only letters, digits, dot, underscore, or dash"
        )
    repetitions = value.get("repetitions", 1)
    if (
        isinstance(repetitions, bool)
        or not isinstance(repetitions, int)
        or repetitions < 1
    ):
        raise RQRunConfigError("repetitions must be a positive integer")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--package-root",
        type=Path,
        default=root / "outputs_new" / "rq_agent_inputs",
    )
    parser.add_argument(
        "--run-root", type=Path, default=root / "outputs_new" / "rq_runs"
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=Path(tempfile.gettempdir()) / "reqmembench_agent_workspaces",
    )
    parser.add_argument(
        "--run-prompt",
        type=Path,
        default=root / "prompt" / "rq_agent_run_prompt.md",
    )
    parser.add_argument(
        "--case",
        action="append",
        metavar="PROJECT_ID:TARGET_ID",
        help=(
            "Run both C1 and C2 packages for the named target. May be repeated."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit package count after case filtering (not target count).",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _parse_cases(values: list[str] | None) -> set[tuple[str, str]]:
    cases: set[tuple[str, str]] = set()
    for value in values or []:
        project_id, separator, target_id = value.partition(":")
        if not separator or not project_id or not target_id:
            raise RQRunConfigError("--case must use PROJECT_ID:TARGET_ID")
        cases.add((project_id, target_id))
    return cases


def _filter_manifests_by_case(
    manifests: list[Path], cases: set[tuple[str, str]]
) -> list[Path]:
    if not cases:
        return manifests
    selected: list[Path] = []
    found: set[tuple[str, str]] = set()
    for manifest_path in manifests:
        package = read_json_object(manifest_path)
        case = (package.get("project_id"), package.get("target_id"))
        if case in cases:
            selected.append(manifest_path)
            found.add(case)
    missing = sorted(cases.difference(found))
    if missing:
        raise RQRunConfigError(f"no materialized packages for target cases: {missing}")
    condition_counts: dict[tuple[str, str], set[str]] = {}
    for manifest_path in selected:
        package = read_json_object(manifest_path)
        case = (package["project_id"], package["target_id"])
        condition_counts.setdefault(case, set()).add(package.get("condition"))
    incomplete = sorted(
        case for case, conditions in condition_counts.items()
        if conditions != {"C1", "C2"}
    )
    if incomplete:
        raise RQRunConfigError(
            f"target cases do not have exactly both C1 and C2 packages: {incomplete}"
        )
    return selected


def main() -> int:
    args = _args()
    try:
        config = _read_config(args.config)
        manifests = discover_package_manifests(args.package_root)
        manifests = _filter_manifests_by_case(manifests, _parse_cases(args.case))
        if args.limit is not None:
            if args.limit < 1:
                raise RQRunConfigError("--limit must be positive")
            manifests = manifests[: args.limit]
        if not manifests:
            raise RQRunConfigError(
                f"no package_manifest.json files found below {args.package_root}"
            )
        total = len(manifests) * int(config.get("repetitions", 1))
        if args.dry_run:
            print(f"Would launch {total} isolated Agent run(s) from {len(manifests)} package(s)")
            return 0
        failures: list[dict[str, str]] = []
        run_rows: list[dict[str, Any]] = []
        completed = 0
        skipped = 0
        for package_manifest in manifests:
            for repetition in range(1, int(config.get("repetitions", 1)) + 1):
                try:
                    result = run_isolated_agent_case(
                        package_manifest_path=package_manifest,
                        agent_config=config["agent"],
                        repetition=repetition,
                        run_prompt_path=args.run_prompt,
                        run_root=args.run_root,
                        workspace_root=args.workspace_root,
                    )
                    if result["status"] == "SKIPPED_FROZEN":
                        skipped += 1
                    else:
                        completed += 1
                    run_rows.append(
                        {
                            "run_id": result["run_id"],
                            "agent_config_id": result["agent_config_id"],
                            "package_manifest": str(package_manifest.resolve()),
                            "repetition": repetition,
                            "status": result["status"],
                        }
                    )
                    print(f"{result['run_id']}: {result['status']}")
                except Exception as exc:
                    failures.append(
                        {
                            "package_manifest": str(package_manifest),
                            "repetition": str(repetition),
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    print(
                        f"FAILED {package_manifest} repetition {repetition}: {exc}",
                        file=sys.stderr,
                    )
        ledger_path = (
            args.run_root
            / "experiments"
            / config["experiment_id"]
            / "agent_runs.json"
        )
        _write_json(
            ledger_path,
            {
                "schema_version": "rq123-experiment-agent-ledger-v1",
                "experiment_id": config["experiment_id"],
                "experiment_config": str(args.config.resolve()),
                "runs": run_rows,
                "failures": failures,
            },
        )
        print(
            json.dumps(
                {
                    "requested": total,
                    "completed": completed,
                    "skipped_frozen": skipped,
                    "failed": len(failures),
                    "failures": failures,
                    "experiment_ledger": str(ledger_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2 if failures else 0
    except (OSError, json.JSONDecodeError, RQRunConfigError, RQAgentRuntimeError) as exc:
        print(f"RQ Agent batch failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
