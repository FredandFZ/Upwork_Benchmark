"""End-to-end Judge projection and scoring for frozen RQ1--RQ3 runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import json

try:  # Package import in tests; script import in CLIs.
    from .evaluation.rq1 import build_alignment_request as build_rq1_alignment
    from .evaluation.rq1 import score_rq1
    from .evaluation.rq2 import build_alignment_request as build_rq2_alignment
    from .evaluation.rq2 import build_field_alignment_request as build_rq2_field_alignment
    from .evaluation.rq2 import build_state_semantic_request as build_rq2_semantic
    from .evaluation.rq2 import score_rq2
    from .evaluation.rq3 import build_alignment_request as build_rq3_alignment
    from .evaluation.rq3 import build_field_alignment_request as build_rq3_field_alignment
    from .evaluation.rq3 import (
        build_clarification_semantic_request as build_rq3_clarification_semantic,
    )
    from .evaluation.rq3 import build_state_semantic_request as build_rq3_state_semantic
    from .evaluation.rq3 import score_rq3
    from .rq_judge_provider import (
        JudgeProvider,
        deterministic_empty_response,
        response_schema_for_request,
        validate_judge_response,
    )
    from .rq_run_identity import (
        RUN_MANIFEST_SCHEMA_VERSION,
        canonical_sha256,
        file_sha256,
        read_json_object,
    )
except ImportError:  # pragma: no cover
    from evaluation.rq1 import build_alignment_request as build_rq1_alignment
    from evaluation.rq1 import score_rq1
    from evaluation.rq2 import build_alignment_request as build_rq2_alignment
    from evaluation.rq2 import build_field_alignment_request as build_rq2_field_alignment
    from evaluation.rq2 import build_state_semantic_request as build_rq2_semantic
    from evaluation.rq2 import score_rq2
    from evaluation.rq3 import build_alignment_request as build_rq3_alignment
    from evaluation.rq3 import build_field_alignment_request as build_rq3_field_alignment
    from evaluation.rq3 import (
        build_clarification_semantic_request as build_rq3_clarification_semantic,
    )
    from evaluation.rq3 import build_state_semantic_request as build_rq3_state_semantic
    from evaluation.rq3 import score_rq3
    from rq_judge_provider import (
        JudgeProvider,
        deterministic_empty_response,
        response_schema_for_request,
        validate_judge_response,
    )
    from rq_run_identity import (
        RUN_MANIFEST_SCHEMA_VERSION,
        canonical_sha256,
        file_sha256,
        read_json_object,
    )


class RQBatchEvaluationError(RuntimeError):
    """Raised when a frozen Agent run cannot be projected into RQ scores."""


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _verified_agent_response(run_dir: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    freeze_record = read_json_object(run_dir / "phase_a" / "freeze_record.json")
    if freeze_record.get("run_id") != manifest.get("run_id"):
        raise RQBatchEvaluationError("freeze record does not match run manifest")
    response_path = run_dir / "phase_a" / "agent_response.json"
    if file_sha256(response_path) != freeze_record.get("response_sha256"):
        raise RQBatchEvaluationError("frozen Agent response hash mismatch")
    if (
        manifest.get("phase_gate", {}).get("phase_a_response_sha256")
        != freeze_record.get("response_sha256")
    ):
        raise RQBatchEvaluationError("run manifest is not bound to frozen response")
    return read_json_object(response_path)


def _source_instance(
    manifest: Mapping[str, Any], rq_id: str, *, run_dir: Path
) -> dict[str, Any]:
    sources = manifest.get("source_instances")
    record = sources.get(rq_id) if isinstance(sources, Mapping) else None
    if not isinstance(record, Mapping) or not isinstance(record.get("path"), str):
        raise RQBatchEvaluationError(f"run manifest has no {rq_id} source instance")
    path = Path(record["path"])
    if not path.is_absolute():
        path = (run_dir / path).resolve()
        try:
            path.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise RQBatchEvaluationError(
                f"{rq_id} relative source instance escapes run directory"
            ) from exc
    if file_sha256(path) != record.get("file_sha256"):
        raise RQBatchEvaluationError(f"{rq_id} source instance hash mismatch")
    return read_json_object(path)


async def _judge_stage(
    provider: JudgeProvider,
    request: Mapping[str, Any],
    *,
    stage_dir: Path,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    judge_run_id = "judge_" + canonical_sha256(
        {
            "agent_response_sha256": metadata.get("agent_response_sha256"),
            "judge_config_id": provider.config_id,
            "rq_id": metadata.get("rq_id"),
            "judge_stage": metadata.get("judge_stage"),
            "request_sha256": canonical_sha256(request),
        }
    )[:20]
    request_path = stage_dir / "request.json"
    response_path = stage_dir / "response.json"
    _atomic_json(request_path, request)
    if response_path.is_file():
        return validate_judge_response(request, read_json_object(response_path))
    empty = deterministic_empty_response(request)
    if empty is not None:
        _atomic_json(response_path, empty)
        _atomic_json(
            stage_dir / "call_record.json",
            {
                "provider": "LOCAL_DETERMINISTIC_EMPTY",
                "judge_config_id": provider.config_id,
                "judge_run_id": judge_run_id,
                "request_item_count": 0,
            },
        )
        return empty
    result = await provider.call(
        request,
        response_schema=response_schema_for_request(request),
        metadata=metadata,
    )
    _atomic_json(response_path, result.response)
    _atomic_json(
        stage_dir / "call_record.json",
        {
            "judge_config_id": provider.config_id,
            "judge_run_id": judge_run_id,
            **result.record(),
        },
    )
    return result.response


async def evaluate_frozen_run(
    run_dir: str | Path,
    *,
    provider: JudgeProvider,
) -> dict[str, Any]:
    directory = Path(run_dir).resolve()
    manifest = read_json_object(directory / "private" / "run_manifest.json")
    if manifest.get("schema_version") != RUN_MANIFEST_SCHEMA_VERSION:
        raise RQBatchEvaluationError("only isolated v2 Agent runs can be batch scored")
    response = _verified_agent_response(directory, manifest)
    active = manifest.get("reasoning_active_rqs")
    if not isinstance(active, list) or any(
        rq_id not in {"RQ1", "RQ2", "RQ3"} for rq_id in active
    ):
        raise RQBatchEvaluationError("run manifest has invalid reasoning_active_rqs")
    condition = manifest.get("condition")
    if condition not in {"C1", "C2"}:
        raise RQBatchEvaluationError("run manifest has invalid condition")
    judge_root = directory / "judges" / provider.config_id
    score_root = directory / "scores" / provider.config_id
    scores: dict[str, Any] = {}
    base_metadata = {
        "run_id": manifest["run_id"],
        "project_id": manifest.get("project_id"),
        "target_id": manifest.get("target_id"),
        "condition": condition,
        "agent_response_sha256": manifest["phase_gate"][
            "phase_a_response_sha256"
        ],
    }

    if "RQ1" in active:
        instance = _source_instance(manifest, "RQ1", run_dir=directory)
        request = build_rq1_alignment(instance, response)
        alignment = await _judge_stage(
            provider,
            request,
            stage_dir=judge_root / "RQ1" / "alignment",
            metadata={**base_metadata, "rq_id": "RQ1", "judge_stage": "ALIGNMENT"},
        )
        scores["RQ1"] = score_rq1(instance, response, alignment)
        _atomic_json(score_root / "RQ1.json", scores["RQ1"])

    if "RQ2" in active:
        instance = _source_instance(manifest, "RQ2", run_dir=directory)
        alignment_request = build_rq2_alignment(
            instance, response, condition=str(condition)
        )
        alignment = await _judge_stage(
            provider,
            alignment_request,
            stage_dir=judge_root / "RQ2" / "alignment",
            metadata={**base_metadata, "rq_id": "RQ2", "judge_stage": "ALIGNMENT"},
        )
        field_request = build_rq2_field_alignment(
            instance, response, alignment, condition=str(condition)
        )
        field_alignment = await _judge_stage(
            provider,
            field_request,
            stage_dir=judge_root / "RQ2" / "field_alignment",
            metadata={
                **base_metadata,
                "rq_id": "RQ2",
                "judge_stage": "FIELD_ALIGNMENT",
            },
        )
        semantic_request = build_rq2_semantic(
            instance,
            response,
            alignment,
            field_alignment,
            condition=str(condition),
        )
        semantic = await _judge_stage(
            provider,
            semantic_request,
            stage_dir=judge_root / "RQ2" / "state_semantic",
            metadata={
                **base_metadata,
                "rq_id": "RQ2",
                "judge_stage": "STATE_SEMANTIC",
            },
        )
        scores["RQ2"] = score_rq2(
            instance,
            response,
            alignment,
            field_alignment,
            semantic,
            condition=str(condition),
        )
        _atomic_json(score_root / "RQ2.json", scores["RQ2"])

    if "RQ3" in active:
        instance = _source_instance(manifest, "RQ3", run_dir=directory)
        branch = instance.get("construction_gold", {}).get(
            "final_gold_by_condition", {}
        ).get(condition, {})
        gold_decision = branch.get("decision") if isinstance(branch, Mapping) else None
        if response.get("decision") != gold_decision:
            scores["RQ3"] = score_rq3(
                instance, response, condition=str(condition)
            )
        else:
            alignment_request = build_rq3_alignment(
                instance, response, condition=str(condition)
            )
            alignment = await _judge_stage(
                provider,
                alignment_request,
                stage_dir=judge_root / "RQ3" / "alignment",
                metadata={
                    **base_metadata,
                    "rq_id": "RQ3",
                    "judge_stage": "ALIGNMENT",
                },
            )
            if gold_decision == "ACT":
                field_request = build_rq3_field_alignment(
                    instance, response, alignment, condition=str(condition)
                )
                field_alignment = await _judge_stage(
                    provider,
                    field_request,
                    stage_dir=judge_root / "RQ3" / "field_alignment",
                    metadata={
                        **base_metadata,
                        "rq_id": "RQ3",
                        "judge_stage": "FIELD_ALIGNMENT",
                    },
                )
                semantic_request = build_rq3_state_semantic(
                    instance,
                    response,
                    alignment,
                    field_alignment,
                    condition=str(condition),
                )
                stage_name = "state_semantic"
                judge_stage = "STATE_SEMANTIC"
            elif gold_decision == "CLARIFY":
                semantic_request = build_rq3_clarification_semantic(
                    instance, response, alignment, condition=str(condition)
                )
                stage_name = "clarification_semantic"
                judge_stage = "CLARIFICATION_SEMANTIC"
            else:
                raise RQBatchEvaluationError("RQ3 instance has invalid frozen Gold")
            semantic = await _judge_stage(
                provider,
                semantic_request,
                stage_dir=judge_root / "RQ3" / stage_name,
                metadata={
                    **base_metadata,
                    "rq_id": "RQ3",
                    "judge_stage": judge_stage,
                },
            )
            scores["RQ3"] = score_rq3(
                instance,
                response,
                condition=str(condition),
                alignment_response=alignment,
                semantic_response=semantic,
                field_alignment_response=(
                    field_alignment if gold_decision == "ACT" else None
                ),
            )
        _atomic_json(score_root / "RQ3.json", scores["RQ3"])

    summary = {
        "schema_version": "rq123-run-evaluation-summary-v1",
        "run_id": manifest["run_id"],
        "package_id": manifest.get("package_id"),
        "agent_config_id": manifest.get("agent_config_id"),
        "judge_config_id": provider.config_id,
        "project_id": manifest.get("project_id"),
        "target_id": manifest.get("target_id"),
        "condition": condition,
        "scored_rqs": list(scores),
        "status": "SCORED",
    }
    _atomic_json(score_root / "summary.json", summary)
    return summary


def discover_frozen_run_dirs(run_root: str | Path) -> list[Path]:
    root = Path(run_root).resolve()
    return sorted(
        record.parent.parent
        for record in root.rglob("phase_a/freeze_record.json")
        if (record.parent.parent / "private" / "run_manifest.json").is_file()
    )


__all__ = [
    "RQBatchEvaluationError",
    "discover_frozen_run_dirs",
    "evaluate_frozen_run",
]
