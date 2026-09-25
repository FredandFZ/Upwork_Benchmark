#!/usr/bin/env python3
"""Materialize Phase A packages for the frozen 40-target RQ4 Judge registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

try:  # Package import in tests; script import in CLI use.
    from .rq_agent_input import (
        CONDITIONS,
        RQMaterializationError,
        load_rq4_agent_judge_registry,
        materialize_reasoning_input,
        write_materialized_input,
    )
except ImportError:  # pragma: no cover
    from rq_agent_input import (
        CONDITIONS,
        RQMaterializationError,
        load_rq4_agent_judge_registry,
        materialize_reasoning_input,
        write_materialized_input,
    )


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=ROOT / "ccfa-workfiles" / "experiments" / "rq4-validation" / "rq4_agent_judge_registry.json",
    )
    parser.add_argument("--stage2-root", type=Path, default=ROOT / "outputs_new" / "stage2")
    parser.add_argument(
        "--output-root", type=Path, default=ROOT / "outputs_new" / "rq4_agent_inputs"
    )
    parser.add_argument("--instructions", type=Path, default=ROOT / "prompt" / "rq_agent_instructions.md")
    parser.add_argument("--response-schema", type=Path, default=ROOT / "schema" / "rq_agent_response.schema.json")
    parser.add_argument("--condition", action="append", choices=CONDITIONS)
    parser.add_argument("--mode", choices=("smoke", "formal"), default="formal")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--target-id", action="append", default=[])
    args = parser.parse_args()
    try:
        registry, indexed = load_rq4_agent_judge_registry(args.registry)
        selected = set(args.target_id)
        unknown = selected - {target_id for _, target_id in indexed}
        if unknown:
            raise RQMaterializationError(f"unknown RQ4 target IDs: {sorted(unknown)}")
        rows = [
            row for (_, target_id), row in sorted(indexed.items())
            if not selected or target_id in selected
        ]
        completed: list[dict[str, str]] = []
        for row in rows:
            for condition in tuple(dict.fromkeys(args.condition or CONDITIONS)):
                eligibility = row["condition_eligibility"][condition]
                if eligibility.get("rq4_eligible") is not True:
                    continue
                package = materialize_reasoning_input(
                    args.stage2_root / row["project_id"],
                    row["target_id"],
                    condition,
                    instructions_path=args.instructions,
                    response_schema_path=args.response_schema,
                    mode=args.mode,
                    rq4_evaluation_record=row,
                    rq4_judge_contract=registry["judge_contract"],
                    rq4_registry_sha256=registry["registry_sha256"],
                )
                if not args.validate_only:
                    write_materialized_input(package, args.output_root)
                completed.append(
                    {
                        "project_id": row["project_id"],
                        "target_id": row["target_id"],
                        "condition": condition,
                        "package_id": package["package_id"],
                    }
                )
        print(
            json.dumps(
                {
                    "mode": args.mode.upper(),
                    "target_count": len({row["target_id"] for row in completed}),
                    "package_count": len(completed),
                    "written": not args.validate_only,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (OSError, RQMaterializationError, KeyError, TypeError) as exc:
        print(f"RQ4 Phase A materialization failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
