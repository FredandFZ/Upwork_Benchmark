#!/usr/bin/env python3
"""Validate and freeze one ReqMemBench Phase A Agent response."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rq_phase_a import RQPhaseAError, freeze_phase_a_response


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a unified RQ1--RQ3 Agent response, freeze it by hash, "
            "and record whether the RQ4 Phase B gate may open."
        )
    )
    parser.add_argument(
        "--private-manifest",
        type=Path,
        required=True,
        help="Private run_manifest.json created by the input materializer.",
    )
    parser.add_argument(
        "--public-dir",
        type=Path,
        required=True,
        help="The unchanged Phase A public input directory.",
    )
    parser.add_argument(
        "--response",
        type=Path,
        required=True,
        help="Agent's structured Phase A JSON response.",
    )
    parser.add_argument(
        "--freeze-root",
        type=Path,
        default=repo_root() / "outputs" / "rq_runs",
        help="Evaluator-side root for frozen outputs and run status.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = freeze_phase_a_response(
            private_manifest_path=args.private_manifest,
            public_dir=args.public_dir,
            response_path=args.response,
            freeze_root=args.freeze_root,
        )
        record = result["freeze_record"]
        print(
            f"{record['run_id']}: Phase A frozen "
            f"({record['response_sha256']}); Phase B {record['phase_b_gate']}"
        )
        if record["phase_b_gate_reason"]:
            print(f"Phase B gate reason: {record['phase_b_gate_reason']}")
        print(f"Frozen artifacts: {result['freeze_dir']}")
        return 0
    except (OSError, RQPhaseAError) as exc:
        print(f"Phase A freeze failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
