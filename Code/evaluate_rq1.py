#!/usr/bin/env python3
"""Prepare or score one automatic ReqMemBench RQ1 evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from evaluation.rq1 import RQ1EvaluationError, build_alignment_request, score_rq1


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise RQ1EvaluationError(f"invalid JSON at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RQ1EvaluationError(f"{path} must contain a JSON object")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the one-call RQ1 Atom-relation request, then optionally "
            "score a complete judge response. This command does not call an LLM."
        )
    )
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--agent-response", type=Path, required=True)
    parser.add_argument(
        "--alignment-request-out",
        type=Path,
        help="Write the all-pairs LLM judge request to this JSON file.",
    )
    parser.add_argument(
        "--judge-response",
        type=Path,
        help="Complete rq1-alignment-response-v1 JSON returned by the judge.",
    )
    parser.add_argument(
        "--score-out",
        type=Path,
        help="Write rq1-evaluation-result-v1 here; requires --judge-response.",
    )
    args = parser.parse_args()
    if args.score_out is not None and args.judge_response is None:
        parser.error("--score-out requires --judge-response")
    return args


def main() -> int:
    args = _arguments()
    try:
        instance = _read_json(args.instance)
        agent_response = _read_json(args.agent_response)
        request = build_alignment_request(instance, agent_response)
        if args.alignment_request_out is not None:
            _write_json(args.alignment_request_out, request)
        if args.judge_response is None:
            if args.alignment_request_out is None:
                print(json.dumps(request, ensure_ascii=False, indent=2))
            else:
                print(f"RQ1 alignment request written: {args.alignment_request_out}")
            return 0

        result = score_rq1(
            instance,
            agent_response,
            _read_json(args.judge_response),
        )
        if args.score_out is not None:
            _write_json(args.score_out, result)
            print(f"RQ1 score written: {args.score_out}")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, RQ1EvaluationError) as exc:
        print(f"RQ1 evaluation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
