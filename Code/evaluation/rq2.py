"""RQ2 pre-task Requirement-state reconstruction evaluation."""

from __future__ import annotations

from copy import deepcopy
from statistics import mean
from typing import Any, Iterable, Mapping

from .alignment import (
    AlignmentError,
    build_requirement_alignment_request,
    match_same_atoms,
    validate_alignment_response,
)
from .state import (
    STATE_DIMENSIONS,
    StateEvaluationError,
    build_field_alignment_request as build_state_field_alignment_request,
    build_semantic_fact_request,
    score_state,
    validate_semantic_fact_response,
)


AGENT_RESPONSE_SCHEMA_VERSION = "rq2-agent-response-v3"
EVALUATION_RESULT_SCHEMA_VERSION = "rq2-evaluation-result-v2"
AGGREGATE_RESULT_SCHEMA_VERSION = "rq2-aggregate-result-v1"


class RQ2EvaluationError(ValueError):
    """The RQ2 instance, response, or judge result cannot be scored safely."""


def _gold(instance: Mapping[str, Any]) -> tuple[list[str], Mapping[str, Any]]:
    if instance.get("rq_id") != "RQ2":
        raise RQ2EvaluationError("instance.rq_id must be RQ2")
    gold = instance.get("construction_gold")
    if not isinstance(gold, Mapping):
        raise RQ2EvaluationError("construction_gold must be an object")
    requirement_ids = gold.get("gold_requirement_ids")
    states = gold.get("states")
    specs = gold.get("field_scoring_specs")
    summaries = gold.get("requirement_summaries")
    if not isinstance(requirement_ids, list) or not requirement_ids:
        raise RQ2EvaluationError("RQ2 Gold requires gold_requirement_ids")
    if not isinstance(states, Mapping) or set(states) != set(requirement_ids):
        raise RQ2EvaluationError("RQ2 states must equal gold_requirement_ids")
    if not isinstance(specs, Mapping) or set(specs) != set(requirement_ids):
        raise RQ2EvaluationError("RQ2 scoring specs must equal gold_requirement_ids")
    if not isinstance(summaries, Mapping) or set(summaries) != set(requirement_ids):
        raise RQ2EvaluationError("RQ2 requirement_summaries must equal Gold IDs")
    return [str(value) for value in requirement_ids], gold


def validate_agent_response(
    instance: Mapping[str, Any], response: Mapping[str, Any], *, condition: str
) -> list[dict[str, Any]]:
    _gold(instance)
    if condition not in ("C1", "C2"):
        raise RQ2EvaluationError("RQ2 condition must be C1 or C2")
    condition_inputs = instance.get("condition_inputs")
    if not isinstance(condition_inputs, Mapping) or not condition_inputs.get(
        condition, {}
    ).get("available"):
        raise RQ2EvaluationError(f"RQ2 condition {condition} is unavailable")
    contract = instance.get("response_contract")
    if not isinstance(contract, Mapping) or contract.get(
        "schema_version"
    ) != AGENT_RESPONSE_SCHEMA_VERSION:
        raise RQ2EvaluationError(
            f"RQ2 response_contract must use {AGENT_RESPONSE_SCHEMA_VERSION}"
        )
    if not isinstance(response, Mapping):
        raise RQ2EvaluationError("agent response must be an object")
    allowed_top = set(contract.get("allowed_top_level_fields", []))
    if "requirements" not in response:
        raise RQ2EvaluationError("agent response is missing requirements")
    unsupported_top = set(response).difference(allowed_top)
    if unsupported_top:
        raise RQ2EvaluationError(
            f"agent response contains unsupported fields {sorted(unsupported_top)}"
        )
    rows = response.get("requirements")
    if not isinstance(rows, list):
        raise RQ2EvaluationError("agent response.requirements must be an array")
    required = set(contract.get("required_requirement_item_fields", []))
    allowed = set(contract.get("allowed_requirement_item_fields", []))
    visible_ids = {
        str(value)
        for value in condition_inputs[condition].get("history_message_ids", [])
    }
    output: list[dict[str, Any]] = []
    refs: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise RQ2EvaluationError(f"requirements[{index}] must be an object")
        missing = required.difference(raw)
        unsupported = set(raw).difference(allowed)
        if missing or unsupported:
            raise RQ2EvaluationError(
                f"requirements[{index}] fields invalid; missing={sorted(missing)}, "
                f"unsupported={sorted(unsupported)}"
            )
        ref = raw.get("requirement_ref")
        summary = raw.get("requirement_summary")
        if not isinstance(ref, str) or not ref.strip() or ref.casefold().startswith("req_"):
            raise RQ2EvaluationError(f"requirements[{index}] has invalid requirement_ref")
        if ref in refs:
            raise RQ2EvaluationError(f"duplicate requirement_ref {ref!r}")
        refs.add(ref)
        if not isinstance(summary, str) or not summary.strip():
            raise RQ2EvaluationError(f"requirements[{index}] has invalid summary")
        evidence = raw.get("evidence_message_ids")
        if not isinstance(evidence, list) or len({str(v) for v in evidence}) != len(evidence):
            raise RQ2EvaluationError(f"requirements[{index}] has invalid evidence IDs")
        if not {str(value) for value in evidence}.issubset(visible_ids):
            raise RQ2EvaluationError(
                f"requirements[{index}] cites evidence outside {condition}"
            )
        state = raw.get("pre_task_state")
        if not isinstance(state, Mapping) or set(state) != set(STATE_DIMENSIONS):
            raise RQ2EvaluationError(
                f"requirements[{index}].pre_task_state must contain exactly "
                f"{list(STATE_DIMENSIONS)}"
            )
        if state.get("ambiguity") is not None and not isinstance(
            state.get("ambiguity"), list
        ):
            raise RQ2EvaluationError(
                f"requirements[{index}].pre_task_state.ambiguity must be null or an array"
            )
        output.append(deepcopy(dict(raw)))
    return output


def _history_index(instance: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    pool = instance.get("history_pool")
    rows = pool.get("messages") if isinstance(pool, Mapping) else None
    if not isinstance(rows, list):
        raise RQ2EvaluationError("history_pool.messages must be an array")
    return {str(row.get("message_id")): dict(row) for row in rows if isinstance(row, Mapping)}


def _gold_ref_map(requirement_ids: list[str]) -> dict[str, str]:
    return {f"G{index:03d}": requirement_id for index, requirement_id in enumerate(requirement_ids, 1)}


def build_alignment_request(
    instance: Mapping[str, Any], response: Mapping[str, Any], *, condition: str
) -> dict[str, Any]:
    predictions = validate_agent_response(instance, response, condition=condition)
    requirement_ids, gold = _gold(instance)
    history = _history_index(instance)
    ref_map = _gold_ref_map(requirement_ids)
    evidence_by_requirement = gold.get("alignment_evidence_message_ids", {})
    return build_requirement_alignment_request(
        target_id=instance.get("target_id"),
        task=instance.get("target_task", {}),
        purpose=f"RQ2_PRE_TASK_REQUIREMENT_ALIGNMENT_{condition}",
        predictions=[
            {
                "prediction_ref": row["requirement_ref"],
                "requirement_summary": row["requirement_summary"],
                "historical_evidence": [
                    history[str(message_id)]
                    for message_id in row["evidence_message_ids"]
                    if str(message_id) in history
                ],
            }
            for row in predictions
        ],
        gold_requirements=[
            {
                "gold_ref": gold_ref,
                "canonical_summary": gold["requirement_summaries"][requirement_id],
                "historical_evidence": [
                    history[str(message_id)]
                    for message_id in evidence_by_requirement.get(requirement_id, [])
                    if str(message_id) in history
                ],
            }
            for gold_ref, requirement_id in ref_map.items()
        ],
    )


def _matched_state_pairs(
    instance: Mapping[str, Any],
    response: Mapping[str, Any],
    alignment_response: Mapping[str, Any],
    *,
    condition: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    predictions = validate_agent_response(instance, response, condition=condition)
    by_ref = {row["requirement_ref"]: row for row in predictions}
    requirement_ids, gold = _gold(instance)
    ref_map = _gold_ref_map(requirement_ids)
    request = build_alignment_request(instance, response, condition=condition)
    relations = validate_alignment_response(request, alignment_response)
    alignment = match_same_atoms(request, relations)
    pairs = []
    for row in alignment["matched_pairs"]:
        prediction = by_ref[row["prediction_ref"]]
        requirement_id = ref_map[row["gold_ref"]]
        pairs.append(
            {
                "pair_id": _pair_id(row["prediction_ref"], row["gold_ref"]),
                "prediction_ref": row["prediction_ref"],
                "gold_ref": row["gold_ref"],
                "gold_requirement_id": requirement_id,
                "predicted_requirement_summary": prediction["requirement_summary"],
                "gold_requirement_summary": gold["requirement_summaries"][requirement_id],
                "gold_state": gold["states"][requirement_id],
                "predicted_state": prediction["pre_task_state"],
                "scoring_specs": gold["field_scoring_specs"][requirement_id],
            }
        )
    return pairs, alignment


def _pair_id(prediction_ref: str, gold_ref: str) -> str:
    return f"rq2-{prediction_ref}-{gold_ref}"


def build_state_semantic_request(
    instance: Mapping[str, Any],
    response: Mapping[str, Any],
    alignment_response: Mapping[str, Any],
    field_alignment_response: Mapping[str, Any],
    *,
    condition: str,
) -> dict[str, Any]:
    pairs, _ = _matched_state_pairs(
        instance, response, alignment_response, condition=condition
    )
    return build_semantic_fact_request(
        target_id=instance.get("target_id"),
        purpose=f"RQ2_STATE_FACT_EQUIVALENCE_{condition}",
        state_pairs=pairs,
        field_alignment_response=field_alignment_response,
    )


def build_field_alignment_request(
    instance: Mapping[str, Any],
    response: Mapping[str, Any],
    alignment_response: Mapping[str, Any],
    *,
    condition: str,
) -> dict[str, Any]:
    pairs, _ = _matched_state_pairs(
        instance, response, alignment_response, condition=condition
    )
    return build_state_field_alignment_request(
        target_id=instance.get("target_id"),
        purpose=f"RQ2_ATTRIBUTE_FIELD_ALIGNMENT_{condition}",
        state_pairs=pairs,
    )


def score_rq2(
    instance: Mapping[str, Any],
    response: Mapping[str, Any],
    alignment_response: Mapping[str, Any],
    field_alignment_response: Mapping[str, Any],
    semantic_response: Mapping[str, Any],
    *,
    condition: str,
) -> dict[str, Any]:
    requirement_ids, gold = _gold(instance)
    pairs, alignment = _matched_state_pairs(
        instance, response, alignment_response, condition=condition
    )
    field_request = build_state_field_alignment_request(
        target_id=instance.get("target_id"),
        purpose=f"RQ2_ATTRIBUTE_FIELD_ALIGNMENT_{condition}",
        state_pairs=pairs,
    )
    semantic_request = build_semantic_fact_request(
        target_id=instance.get("target_id"),
        purpose=f"RQ2_STATE_FACT_EQUIVALENCE_{condition}",
        state_pairs=pairs,
        field_alignment_response=field_alignment_response,
    )
    semantic_relations = validate_semantic_fact_response(
        semantic_request, semantic_response
    )
    scored = [
        {
            "prediction_ref": pair["prediction_ref"],
            "gold_requirement_id": pair["gold_requirement_id"],
            **score_state(
                pair_id=pair["pair_id"],
                gold_state=pair["gold_state"],
                predicted_state=pair["predicted_state"],
                scoring_specs=pair["scoring_specs"],
                semantic_relations=semantic_relations,
                field_alignment_request=field_request,
                field_alignment_response=field_alignment_response,
            ),
        }
        for pair in pairs
    ]

    def macro(values: Iterable[float | None]) -> float | None:
        usable = [value for value in values if value is not None]
        return round(mean(usable), 6) if usable else None

    per_dimension = {
        dimension: macro(
            row["dimension_scores"][dimension] for row in scored
        )
        for dimension in STATE_DIMENSIONS
    }
    matched_state_score = macro(row["state_score"] for row in scored)
    full_state_exact = (
        int(bool(scored) and all(row["full_state_exact"] == 1 for row in scored))
        if scored
        else None
    )
    coverage = round(len(scored) / len(requirement_ids), 6)
    formal = gold.get("status") == "FINAL_TYPED_STATE_GOLD"
    return {
        "schema_version": EVALUATION_RESULT_SCHEMA_VERSION,
        "instance_id": deepcopy(instance.get("instance_id")),
        "target_id": deepcopy(instance.get("target_id")),
        "rq_id": "RQ2",
        "condition": condition,
        "status": "SCORED" if formal else "PROVISIONAL_SCORE_NOT_FOR_REPORTING",
        "reporting_eligible": formal,
        "official_metrics": {
            "attribute_reconstruction_score": per_dimension["attributes"],
            "per_dimension_scores": per_dimension,
            "matched_full_state_exact": full_state_exact,
            "reconstruction_coverage": coverage,
        },
        "auxiliary_metrics": {"matched_state_score": matched_state_score},
        "alignment": alignment,
        "matched_requirement_states": scored,
        "diagnostics": {
            "gold_status": gold.get("status"),
            "semantic_fact_count": len(semantic_request["facts"]),
            "field_alignment_candidate_count": len(field_request["candidate_pairs"]),
        },
    }


def aggregate_rq2_results(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(results)
    if not rows:
        raise RQ2EvaluationError("cannot aggregate an empty RQ2 result set")
    if any(row.get("rq_id") != "RQ2" for row in rows):
        raise RQ2EvaluationError("aggregate contains a non-RQ2 result")

    def macro(path: tuple[str, ...]) -> float | None:
        values: list[float] = []
        for row in rows:
            value: Any = row
            for key in path:
                value = value.get(key) if isinstance(value, Mapping) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))
        return round(mean(values), 6) if values else None

    return {
        "schema_version": AGGREGATE_RESULT_SCHEMA_VERSION,
        "rq_id": "RQ2",
        "result_count": len(rows),
        "all_reporting_eligible": all(
            row.get("reporting_eligible") is True for row in rows
        ),
        "macro_metrics": {
            "attribute_reconstruction_score": macro(
                ("official_metrics", "attribute_reconstruction_score")
            ),
            "matched_full_state_exact": macro(
                ("official_metrics", "matched_full_state_exact")
            ),
            "reconstruction_coverage": macro(
                ("official_metrics", "reconstruction_coverage")
            ),
            "matched_state_score_auxiliary": macro(
                ("auxiliary_metrics", "matched_state_score")
            ),
            "per_dimension_scores": {
                dimension: macro(
                    ("official_metrics", "per_dimension_scores", dimension)
                )
                for dimension in STATE_DIMENSIONS
            },
        },
    }


def score_rq2_constant_state_baseline(instance: Mapping[str, Any]) -> dict[str, Any]:
    """Score the fixed majority/null state with oracle Requirement alignment.

    This is a conditional state-reconstruction sanity baseline.  It deliberately
    receives the Gold Requirement set, so it must be reported beside, not instead
    of, Reconstruction Coverage and RQ1 selection metrics.
    """

    requirement_ids, gold = _gold(instance)
    constant_state = {
        "attributes": {},
        "scope": {
            "persistence": "PROJECT_PERSISTENT",
            "components": [],
            "contexts": [],
        },
        "lifecycle_status": "ACTIVE",
        "ambiguity": None,
        "execution": None,
    }
    scored = [
        score_state(
            pair_id=f"rq2-constant-G{index:03d}",
            gold_state=gold["states"][requirement_id],
            predicted_state=constant_state,
            scoring_specs=gold["field_scoring_specs"][requirement_id],
            semantic_relations={},
        )
        for index, requirement_id in enumerate(requirement_ids, 1)
    ]

    def macro(values: Iterable[float | None]) -> float | None:
        usable = [value for value in values if value is not None]
        return round(mean(usable), 6) if usable else None

    return {
        "schema_version": "rq2-constant-state-baseline-v1",
        "target_id": deepcopy(instance.get("target_id")),
        "baseline": "ORACLE_ALIGNED_MAJORITY_NULL_STATE",
        "conditional_on_gold_requirement_set": True,
        "metrics": {
            "attribute_reconstruction_score": macro(
                row["dimension_scores"]["attributes"] for row in scored
            ),
            "per_dimension_scores": {
                dimension: macro(
                    row["dimension_scores"][dimension] for row in scored
                )
                for dimension in STATE_DIMENSIONS
            },
            "matched_state_score_auxiliary": macro(
                row["state_score"] for row in scored
            ),
            "matched_full_state_exact": int(
                bool(scored)
                and all(row["full_state_exact"] == 1 for row in scored)
            ),
            "reconstruction_coverage": 1.0,
        },
    }


__all__ = [
    "RQ2EvaluationError",
    "aggregate_rq2_results",
    "build_alignment_request",
    "build_field_alignment_request",
    "build_state_semantic_request",
    "score_rq2",
    "score_rq2_constant_state_baseline",
    "validate_agent_response",
]
