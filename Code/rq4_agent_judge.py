"""Validation and deterministic finalization for universal RQ4 Agent Judge output."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping, Sequence


JUDGE_RESULT_SCHEMA_VERSION = "rq4-agent-judge-result-v1"
FINAL_RESULT_SCHEMA_VERSION = "rq4-evaluation-result-v1"
FINALIZER_VERSION = "rq4-agent-judge-finalizer-v1"


class RQ4JudgeValidationError(ValueError):
    pass


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RQ4JudgeValidationError(f"{label} must be a non-empty string")
    return value.strip()


def _artifact_path(value: Any, workspace: Path, label: str) -> str | None:
    if value is None:
        return None
    relative = _text(value, label).replace("\\", "/")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or re.match(r"^[A-Za-z]:", relative):
        raise RQ4JudgeValidationError(f"{label} is not a safe relative path")
    path = workspace.joinpath(*pure.parts).resolve()
    try:
        path.relative_to(workspace.resolve())
    except ValueError as exc:
        raise RQ4JudgeValidationError(f"{label} escapes the Judge workspace") from exc
    if not path.is_file():
        raise RQ4JudgeValidationError(f"{label} does not exist: {relative}")
    return pure.as_posix()


def validate_agent_judge_result(
    value: Mapping[str, Any],
    *,
    target_id: str,
    criterion_ids: Sequence[str],
    workspace: str | Path,
) -> dict[str, Any]:
    """Validate exact criterion coverage and concrete evidence references."""

    if set(value) != {"schema_version", "target_id", "criteria", "judge_summary"}:
        raise RQ4JudgeValidationError("Judge result has invalid top-level fields")
    if value.get("schema_version") != JUDGE_RESULT_SCHEMA_VERSION:
        raise RQ4JudgeValidationError("unsupported Judge result schema")
    if value.get("target_id") != target_id:
        raise RQ4JudgeValidationError("Judge result target_id mismatch")
    expected = list(criterion_ids)
    if not expected or len(expected) != len(set(expected)):
        raise RQ4JudgeValidationError("expected criterion IDs are empty or duplicated")
    rows = value.get("criteria")
    if not isinstance(rows, list):
        raise RQ4JudgeValidationError("Judge criteria must be an array")
    by_id: dict[str, dict[str, Any]] = {}
    workspace_path = Path(workspace).resolve()
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping) or set(raw) != {"criterion_id", "verdict", "evidence"}:
            raise RQ4JudgeValidationError(f"criteria[{index}] has invalid fields")
        criterion_id = raw.get("criterion_id")
        if criterion_id not in expected or criterion_id in by_id:
            raise RQ4JudgeValidationError(f"invalid or repeated criterion {criterion_id!r}")
        verdict = raw.get("verdict")
        if verdict not in {"PASS", "FAIL", "UNSURE"}:
            raise RQ4JudgeValidationError(f"invalid verdict for {criterion_id}")
        evidence = raw.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise RQ4JudgeValidationError(f"{criterion_id} has no execution evidence")
        normalized_evidence: list[dict[str, Any]] = []
        for evidence_index, item in enumerate(evidence):
            if not isinstance(item, Mapping) or not set(item).issubset({"operation", "observation", "artifact"}):
                raise RQ4JudgeValidationError(
                    f"{criterion_id}.evidence[{evidence_index}] has invalid fields"
                )
            if not {"operation", "observation"}.issubset(item):
                raise RQ4JudgeValidationError(
                    f"{criterion_id}.evidence[{evidence_index}] is incomplete"
                )
            normalized_evidence.append(
                {
                    "operation": _text(item.get("operation"), "evidence.operation"),
                    "observation": _text(item.get("observation"), "evidence.observation"),
                    "artifact": _artifact_path(
                        item.get("artifact"), workspace_path, "evidence.artifact"
                    ),
                }
            )
        by_id[str(criterion_id)] = {
            "criterion_id": criterion_id,
            "verdict": verdict,
            "evidence": normalized_evidence,
        }
    if set(by_id) != set(expected):
        raise RQ4JudgeValidationError(
            f"Judge criterion coverage mismatch; missing={sorted(set(expected) - set(by_id))}"
        )
    return {
        "schema_version": JUDGE_RESULT_SCHEMA_VERSION,
        "target_id": target_id,
        "criteria": [by_id[criterion_id] for criterion_id in expected],
        "judge_summary": _text(value.get("judge_summary"), "judge_summary"),
    }


def finalize_rq4_result(
    *,
    run_identity: Mapping[str, Any],
    build: Mapping[str, Any],
    regression: Mapping[str, Any],
    judge_result: Mapping[str, Any] | None,
    judge_config_id: str | None,
) -> dict[str, Any]:
    """Mechanically derive the formal result; never trust a Judge overall field."""

    components = {"build": deepcopy(dict(build)), "regression": deepcopy(dict(regression))}
    statuses = {name: component.get("status") for name, component in components.items()}
    if any(status not in {"PASS", "FAIL", "HARNESS_ERROR"} for status in statuses.values()):
        raise RQ4JudgeValidationError("build/regression status is invalid")
    formal_result: str | None
    if "HARNESS_ERROR" in statuses.values():
        score_status = "JUDGE_ERROR"
        formal_result = None
        reason = "BUILD_OR_REGRESSION_HARNESS_ERROR"
    elif "FAIL" in statuses.values():
        score_status = "SCORED"
        formal_result = "FAIL"
        reason = "BUILD_OR_REGRESSION_FAIL"
    elif judge_result is None:
        score_status = "JUDGE_ERROR"
        formal_result = None
        reason = "MISSING_AGENT_JUDGE_RESULT"
    else:
        verdicts = [row.get("verdict") for row in judge_result.get("criteria", [])]
        if not verdicts:
            raise RQ4JudgeValidationError("Judge result has no criteria")
        if "UNSURE" in verdicts:
            score_status = "REVIEW_REQUIRED"
            formal_result = None
            reason = "JUDGE_UNSURE"
        elif "FAIL" in verdicts:
            score_status = "SCORED"
            formal_result = "FAIL"
            reason = "ACCEPTANCE_CRITERION_FAIL"
        elif all(verdict == "PASS" for verdict in verdicts):
            score_status = "SCORED"
            formal_result = "PASS"
            reason = "ALL_GATES_PASS"
        else:
            raise RQ4JudgeValidationError("Judge verdict set is invalid")
    return {
        "schema_version": FINAL_RESULT_SCHEMA_VERSION,
        "finalizer_version": FINALIZER_VERSION,
        "run_id": run_identity.get("run_id"),
        "project_id": run_identity.get("project_id"),
        "target_id": run_identity.get("target_id"),
        "condition": run_identity.get("condition"),
        "agent_config_id": run_identity.get("agent_config_id"),
        "repetition": run_identity.get("repetition"),
        "judge_config_id": judge_config_id,
        "components": components,
        "judge_result": deepcopy(dict(judge_result)) if judge_result is not None else None,
        "score_status": score_status,
        "result": formal_result,
        "decision_reason": reason,
    }


__all__ = [
    "FINALIZER_VERSION",
    "RQ4JudgeValidationError",
    "finalize_rq4_result",
    "validate_agent_judge_result",
]
