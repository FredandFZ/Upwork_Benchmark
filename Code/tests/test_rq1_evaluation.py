from __future__ import annotations

from copy import deepcopy
import unittest

from Code.evaluation.rq1 import (
    ALIGNMENT_RESPONSE_SCHEMA_VERSION,
    RQ1EvaluationError,
    aggregate_rq1_results,
    build_alignment_request,
    score_rq1,
    validate_agent_response,
)
from Code.stage2.rq_instances import build_rq_instances
from Code.tests.test_stage2_rq_instances import _gold, _messages, _state_graph


def _instance() -> dict:
    return build_rq_instances(_gold(), _state_graph(), _messages())["RQ1"][0]


def _agent(*requirements: dict) -> dict:
    return {"requirements": list(requirements)}


def _prediction(ref: str, summary: str, evidence: list[int]) -> dict:
    return {
        "requirement_ref": ref,
        "requirement_summary": summary,
        "evidence_message_ids": evidence,
    }


def _relations(request: dict, values: dict[tuple[str, str], str]) -> dict:
    return {
        "schema_version": ALIGNMENT_RESPONSE_SCHEMA_VERSION,
        "relations": [
            {
                **pair,
                "relation": values.get(
                    (pair["prediction_ref"], pair["gold_ref"]), "UNRELATED"
                ),
            }
            for pair in request["candidate_pairs"]
        ],
    }


class RQ1EvaluationTests(unittest.TestCase):
    def test_unified_response_is_projected_to_rq1_fields(self):
        instance = _instance()
        response = {
            "requirements": [
                {
                    **_prediction("agent-local-1", "Button colour", [10]),
                    "pre_task_state": {
                        "attributes": {"colour": "blue"},
                        "scope": {},
                        "lifecycle_status": "ACTIVE",
                        "ambiguity": None,
                        "execution": None,
                    },
                }
            ],
            "decision": "CLARIFY",
            "post_task_states": None,
            "clarifications": [
                {
                    "requirement_ref": "agent-local-1",
                    "question": "Which colour?",
                }
            ],
        }

        projected = validate_agent_response(instance, response)

        self.assertEqual(projected, [_prediction("agent-local-1", "Button colour", [10])])

    def test_unified_response_still_rejects_unknown_fields(self):
        instance = _instance()
        with self.assertRaisesRegex(RQ1EvaluationError, "unsupported field"):
            validate_agent_response(
                instance,
                {"requirements": [], "undeclared_rq_field": True},
            )
        with self.assertRaisesRegex(RQ1EvaluationError, "unsupported field"):
            validate_agent_response(
                instance,
                {
                    "requirements": [
                        {
                            **_prediction("p1", "Button colour", [10]),
                            "undeclared_item_field": True,
                        }
                    ]
                },
            )

    def test_declared_future_rq_fields_do_not_break_rq1_projection(self):
        instance = _instance()
        instance["response_contract"]["allowed_top_level_fields"].append(
            "future_rq_output"
        )
        instance["response_contract"][
            "allowed_requirement_item_fields"
        ].append("future_item_output")
        response = {
            "requirements": [
                {
                    **_prediction("p1", "Button colour", [10]),
                    "future_item_output": {"value": True},
                }
            ],
            "future_rq_output": {"value": True},
        }

        self.assertEqual(
            validate_agent_response(instance, response),
            [_prediction("p1", "Button colour", [10])],
        )

    def test_same_atom_scores_requirement_and_required_evidence(self):
        instance = _instance()
        response = _agent(
            _prediction("agent-local-1", "Button colour", [10])
        )
        request = build_alignment_request(instance, response)
        judge = _relations(
            request,
            {("agent-local-1", "gold-local-001"): "SAME_ATOM"},
        )
        result = score_rq1(instance, response, judge)

        self.assertEqual(result["official_metrics"]["requirement"]["f1"], 1.0)
        self.assertEqual(result["official_metrics"]["evidence"]["f1"], 1.0)
        self.assertEqual(
            result["official_metrics"]["exact_requirement_set_accuracy"], 1
        )

    def test_missing_requirement_makes_required_evidence_a_false_negative(self):
        instance = _instance()
        response = _agent()
        request = build_alignment_request(instance, response)
        result = score_rq1(instance, response, _relations(request, {}))

        self.assertEqual(result["official_metrics"]["requirement"]["fn"], 1)
        self.assertEqual(result["official_metrics"]["evidence"]["fn"], 1)
        self.assertEqual(result["official_metrics"]["evidence"]["f1"], 0.0)

    def test_wrong_evidence_does_not_cancel_correct_requirement_match(self):
        instance = _instance()
        response = _agent(
            _prediction("agent-local-1", "Button colour", [20])
        )
        request = build_alignment_request(instance, response)
        judge = _relations(
            request,
            {("agent-local-1", "gold-local-001"): "SAME_ATOM"},
        )
        result = score_rq1(instance, response, judge)

        self.assertEqual(result["official_metrics"]["requirement"]["f1"], 1.0)
        self.assertEqual(result["official_metrics"]["evidence"]["tp"], 0)
        self.assertEqual(result["official_metrics"]["evidence"]["fp"], 1)
        self.assertEqual(result["official_metrics"]["evidence"]["fn"], 1)

    def test_neutral_context_neither_helps_nor_hurts(self):
        instance = _instance()
        atom = instance["construction_gold"]["gold_requirement_atoms"]["REQ_BUTTON"]
        atom["neutral_context_message_ids"] = [20]
        atom["trajectory_message_ids"] = [10, 20]
        response = _agent(
            _prediction("agent-local-1", "Button colour", [10, 20])
        )
        request = build_alignment_request(instance, response)
        judge = _relations(
            request,
            {("agent-local-1", "gold-local-001"): "SAME_ATOM"},
        )
        result = score_rq1(instance, response, judge)

        self.assertEqual(result["official_metrics"]["evidence"]["tp"], 1)
        self.assertEqual(result["official_metrics"]["evidence"]["fp"], 0)

    def test_merged_atom_is_not_matched_but_correct_evidence_is_credited(self):
        instance = _instance()
        response = _agent(
            _prediction("agent-local-1", "All interface rules", [10])
        )
        request = build_alignment_request(instance, response)
        judge = _relations(
            request,
            {("agent-local-1", "gold-local-001"): "MERGED_ATOMS"},
        )
        result = score_rq1(instance, response, judge)

        self.assertEqual(result["official_metrics"]["requirement"]["fp"], 1)
        self.assertEqual(result["official_metrics"]["requirement"]["fn"], 1)
        self.assertEqual(result["official_metrics"]["evidence"]["tp"], 1)
        self.assertEqual(result["official_metrics"]["evidence"]["fp"], 0)
        self.assertEqual(result["official_metrics"]["evidence"]["fn"], 0)
        self.assertEqual(result["official_metrics"]["evidence"]["f1"], 1.0)

    def test_one_merged_prediction_can_cover_evidence_for_two_gold_atoms(self):
        instance = _instance()
        instance["construction_gold"]["relevant_requirement_ids"].append(
            "REQ_SECOND"
        )
        instance["construction_gold"]["gold_requirement_atoms"]["REQ_SECOND"] = {
            "canonical_summary": "Button label",
            "requirement_title": "Button label",
            "family_id": "UI",
            "required_evidence_groups": [
                {
                    "group_id": "REQ_SECOND_EG001",
                    "acceptable_message_ids": [20],
                }
            ],
            "neutral_context_message_ids": [],
            "trajectory_message_ids": [20],
        }
        response = _agent(
            _prediction("agent-local-1", "All button rules", [10, 20])
        )
        request = build_alignment_request(instance, response)
        relations = _relations(
            request,
            {
                ("agent-local-1", "gold-local-001"): "MERGED_ATOMS",
                ("agent-local-1", "gold-local-002"): "MERGED_ATOMS",
            },
        )

        result = score_rq1(instance, response, relations)

        self.assertEqual(result["official_metrics"]["requirement"]["tp"], 0)
        self.assertEqual(result["official_metrics"]["requirement"]["fp"], 1)
        self.assertEqual(result["official_metrics"]["requirement"]["fn"], 2)
        self.assertEqual(result["official_metrics"]["evidence"]["tp"], 2)
        self.assertEqual(result["official_metrics"]["evidence"]["fp"], 0)
        self.assertEqual(result["official_metrics"]["evidence"]["fn"], 0)
        self.assertEqual(result["official_metrics"]["evidence"]["f1"], 1.0)

    def test_over_split_subparts_are_all_false_positives(self):
        instance = _instance()
        response = _agent(
            _prediction("p1", "Button colour value", [10]),
            _prediction("p2", "Button component scope", [10]),
            _prediction("p3", "Button lifecycle", [10]),
        )
        request = build_alignment_request(instance, response)
        judge = _relations(
            request,
            {
                (pair["prediction_ref"], pair["gold_ref"]): "SUBPART_OF_ATOM"
                for pair in request["candidate_pairs"]
            },
        )
        result = score_rq1(instance, response, judge)

        self.assertEqual(result["official_metrics"]["requirement"]["tp"], 0)
        self.assertEqual(result["official_metrics"]["requirement"]["fp"], 3)
        self.assertEqual(result["official_metrics"]["requirement"]["fn"], 1)
        self.assertEqual(result["official_metrics"]["evidence"]["tp"], 1)
        self.assertEqual(result["official_metrics"]["evidence"]["fp"], 0)
        self.assertEqual(result["official_metrics"]["evidence"]["fn"], 0)
        self.assertEqual(
            len(
                result["evidence_alignment"][
                    "ignored_gold_or_neutral_claims"
                ]
            ),
            2,
        )

    def test_matching_maximizes_cardinality_before_weight(self):
        instance = _instance()
        gold = instance["construction_gold"]
        second = deepcopy(gold["gold_requirement_atoms"]["REQ_BUTTON"])
        second["canonical_summary"] = "Report generation"
        second["requirement_title"] = "Report generation"
        second["required_evidence_groups"] = [
            {
                "group_id": "REQ_SECOND_EG001",
                "acceptable_message_ids": [20],
            }
        ]
        second["neutral_context_message_ids"] = []
        second["trajectory_message_ids"] = [20]
        gold["relevant_requirement_ids"].append("REQ_SECOND")
        gold["gold_requirement_atoms"]["REQ_SECOND"] = second
        response = _agent(
            _prediction("p1", "Report generation", [20]),
            _prediction("p2", "Uninformative wording", [20]),
        )
        request = build_alignment_request(instance, response)
        judge = _relations(
            request,
            {
                ("p1", "gold-local-001"): "SAME_ATOM",
                ("p1", "gold-local-002"): "SAME_ATOM",
                ("p2", "gold-local-002"): "SAME_ATOM",
            },
        )
        result = score_rq1(instance, response, judge)

        self.assertEqual(result["official_metrics"]["requirement"]["tp"], 2)
        pairs = {
            (row["prediction_ref"], row["gold_requirement_id"])
            for row in result["alignment"]["matched_pairs"]
        }
        self.assertEqual(pairs, {("p1", "REQ_BUTTON"), ("p2", "REQ_SECOND")})

    def test_uncertain_is_no_match_without_human_review(self):
        instance = _instance()
        response = _agent(_prediction("p1", "Button maybe", [10]))
        request = build_alignment_request(instance, response)
        judge = _relations(
            request, {("p1", "gold-local-001"): "UNCERTAIN"}
        )
        result = score_rq1(instance, response, judge)
        self.assertEqual(result["official_metrics"]["requirement"]["tp"], 0)
        self.assertEqual(result["diagnostics"]["relation_counts"]["UNCERTAIN"], 1)

    def test_incomplete_judge_response_is_an_evaluation_error(self):
        instance = _instance()
        response = _agent(_prediction("p1", "Button colour", [10]))
        with self.assertRaisesRegex(RQ1EvaluationError, "does not classify every"):
            score_rq1(
                instance,
                response,
                {
                    "schema_version": ALIGNMENT_RESPONSE_SCHEMA_VERSION,
                    "relations": [],
                },
            )

    def test_aggregate_uses_target_level_macro_average(self):
        instance = _instance()
        correct_response = _agent(
            _prediction("p1", "Button colour", [10])
        )
        correct_request = build_alignment_request(instance, correct_response)
        correct = score_rq1(
            instance,
            correct_response,
            _relations(
                correct_request,
                {("p1", "gold-local-001"): "SAME_ATOM"},
            ),
        )
        missed_instance = deepcopy(instance)
        missed_instance["instance_id"] = "P1_T002_RQ1"
        missed_instance["target_id"] = "P1_T002"
        missed_response = _agent()
        missed_request = build_alignment_request(missed_instance, missed_response)
        missed = score_rq1(
            missed_instance,
            missed_response,
            _relations(missed_request, {}),
        )

        aggregate = aggregate_rq1_results([correct, missed])
        self.assertEqual(aggregate["aggregation"], "TARGET_LEVEL_MACRO_AVERAGE")
        self.assertEqual(aggregate["official_metrics"]["requirement"]["f1"], 0.5)
        self.assertEqual(aggregate["official_metrics"]["evidence"]["f1"], 0.5)
        self.assertEqual(aggregate["official_metrics"]["exact_requirement_set_accuracy"], 0.5)


if __name__ == "__main__":
    unittest.main()
