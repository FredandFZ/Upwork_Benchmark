#!/usr/bin/env python3
"""Judge and score every frozen RQ1--RQ3 Agent run."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from rq_batch_evaluation import (
    RQBatchEvaluationError,
    discover_frozen_run_dirs,
    evaluate_frozen_run,
)
from rq_judge_provider import RQJudgeError, create_judge_provider
from rq_run_identity import EXPERIMENT_CONFIG_SCHEMA_VERSION, RQRunConfigError


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _config(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict) or value.get("schema_version") != EXPERIMENT_CONFIG_SCHEMA_VERSION:
        raise RQRunConfigError("unsupported experiment config")
    if not isinstance(value.get("judge"), dict):
        raise RQRunConfigError("experiment config requires a judge object")
    experiment_id = value.get("experiment_id")
    if not isinstance(experiment_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+", experiment_id
    ):
        raise RQRunConfigError("experiment config has an invalid experiment_id")
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
        "--run-root", type=Path, default=root / "outputs_new" / "rq_runs"
    )
    parser.add_argument(
        "--judge-prompt",
        type=Path,
        default=root / "prompt" / "rq_llm_judge_prompt.md",
    )
    parser.add_argument(
        "--log-dir", type=Path, default=root / "outputs_new" / "rq_judge_logs"
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--insecure", action="store_true")
    return parser.parse_args()


async def _main_async(args: argparse.Namespace) -> int:
    config = _config(args.config)
    agent_ledger_path = (
        args.run_root
        / "experiments"
        / config["experiment_id"]
        / "agent_runs.json"
    )
    if not agent_ledger_path.is_file():
        raise RQBatchEvaluationError(
            f"experiment Agent ledger does not exist: {agent_ledger_path}"
        )
    agent_ledger = json.loads(agent_ledger_path.read_text(encoding="utf-8-sig"))
    if not isinstance(agent_ledger, dict) or agent_ledger.get("experiment_id") != config["experiment_id"]:
        raise RQBatchEvaluationError("experiment Agent ledger is invalid")
    registered = {
        row.get("run_id")
        for row in agent_ledger.get("runs", [])
        if isinstance(row, dict) and isinstance(row.get("run_id"), str)
    }
    runs = [path for path in discover_frozen_run_dirs(args.run_root) if path.name in registered]
    if args.limit is not None:
        if args.limit < 1:
            raise RQRunConfigError("--limit must be positive")
        runs = runs[: args.limit]
    if not runs:
        raise RQBatchEvaluationError(f"no frozen v2 runs found below {args.run_root}")
    provider = create_judge_provider(
        config["judge"],
        judge_prompt_path=args.judge_prompt,
        log_dir=args.log_dir,
        upwork_api_key=os.environ.get("UPWORK_API_KEY"),
        upwork_budget_id=os.environ.get("UPWORK_BUDGET_ID"),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        insecure=args.insecure,
    )
    failures: list[dict[str, str]] = []
    completed = 0
    semaphore = asyncio.Semaphore(
        int(config["judge"].get("max_concurrent_requests", 1))
    )

    async def evaluate_one(run_dir: Path) -> None:
        nonlocal completed
        async with semaphore:
            try:
                result = await evaluate_frozen_run(run_dir, provider=provider)
                completed += 1
                print(f"{result['run_id']}: SCORED {','.join(result['scored_rqs'])}")
            except Exception as exc:
                failures.append(
                    {
                        "run_dir": str(run_dir),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                print(f"FAILED {run_dir}: {exc}", file=sys.stderr)

    try:
        await asyncio.gather(*(evaluate_one(run_dir) for run_dir in runs))
    finally:
        await provider.aclose()
    judge_ledger_path = (
        args.run_root
        / "experiments"
        / config["experiment_id"]
        / f"judge_{provider.config_id}.json"
    )
    _write_json(
        judge_ledger_path,
        {
            "schema_version": "rq123-experiment-judge-ledger-v1",
            "experiment_id": config["experiment_id"],
            "judge_config_id": provider.config_id,
            "completed_run_count": completed,
            "failures": failures,
        },
    )
    print(
        json.dumps(
            {
                "requested": len(runs),
                "completed": completed,
                "failed": len(failures),
                "failures": failures,
                "experiment_ledger": str(judge_ledger_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 2 if failures else 0


def main() -> int:
    args = _args()
    try:
        return asyncio.run(_main_async(args))
    except (
        OSError,
        json.JSONDecodeError,
        RQRunConfigError,
        RQJudgeError,
        RQBatchEvaluationError,
    ) as exc:
        print(f"RQ Judge batch failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
