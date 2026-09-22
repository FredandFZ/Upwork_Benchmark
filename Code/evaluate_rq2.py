#!/usr/bin/env python3
"""Prepare judge requests or score one ReqMemBench RQ2 response."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from evaluation.alignment import AlignmentError
from evaluation.rq2 import (
    RQ2EvaluationError,
    build_alignment_request,
    build_state_semantic_request,
    score_rq2,
)
from evaluation.state import StateEvaluationError


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RQ2EvaluationError(f"{path} must contain a JSON object")
    return value


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--agent-response", type=Path, required=True)
    parser.add_argument("--condition", choices=("C2", "C3"), required=True)
    parser.add_argument("--alignment-response", type=Path)
    parser.add_argument("--semantic-response", type=Path)
    parser.add_argument("--request-out", type=Path)
    parser.add_argument("--score-out", type=Path)
    args = parser.parse_args()
    if args.semantic_response is not None and args.alignment_response is None:
        parser.error("--semantic-response requires --alignment-response")
    if args.score_out is not None and args.semantic_response is None:
        parser.error("--score-out requires both judge responses")
    return args


def main() -> int:
    args = _args()
    try:
        instance = _read(args.instance)
        response = _read(args.agent_response)
        if args.alignment_response is None:
            value = build_alignment_request(instance, response, condition=args.condition)
            label = "RQ2 alignment request"
        elif args.semantic_response is None:
            value = build_state_semantic_request(
                instance,
                response,
                _read(args.alignment_response),
                condition=args.condition,
            )
            label = "RQ2 state semantic request"
        else:
            value = score_rq2(
                instance,
                response,
                _read(args.alignment_response),
                _read(args.semantic_response),
                condition=args.condition,
            )
            label = "RQ2 score"
        output = args.score_out or args.request_out
        if output is None:
            print(json.dumps(value, ensure_ascii=False, indent=2))
        else:
            _write(output, value)
            print(f"{label} written: {output}")
        return 0
    except (
        OSError,
        json.JSONDecodeError,
        RQ2EvaluationError,
        AlignmentError,
        StateEvaluationError,
    ) as exc:
        print(f"RQ2 evaluation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
