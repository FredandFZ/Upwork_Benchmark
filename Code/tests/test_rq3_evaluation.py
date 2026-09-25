from __future__ import annotations

from copy import deepcopy
import unittest

from Code.evaluation.rq3 import (
    aggregate_rq3_results,
    build_alignment_request,
    build_clarification_semantic_request,
    build_field_alignment_request,
    build_state_semantic_request,
    score_rq3,
    score_rq3_constant_decision_baseline,
)
from Code.stage2.rq3_review import (
    RQ3ReviewError,
    apply_review,
    build_offline_agent_review_template,
    build_review_template,
)
from Code.stage2.rq_instances import build_rq_instances
from Code.tests.test_stage2_rq_instances import (
    _act_state_graph,
    _gold,
    _messages,
    _state_graph,
)


def _alignment_response(request, same_pairs):
    return {
        "schema_version": "requirement-alignment-response-v1",
        "relations": [
            {
                **pair,
                "relation": (
                    "SAME_ATOM"
                    if (pair["prediction_ref"], pair["gold_ref"]) in same_pairs
                    else "UNRELATED"
                ),
            }
            for pair in request["candidate_pairs"]
        ],
    }


def _state_semantic_response(request):
    return {
        "schema_version": "state-semantic-response-v1",
        "relations": [
            {"fact_id": row["fact_id"], "relation": "EQUIVALENT"}
            for row in request["facts"]
        ],
    }


def _field_alignment_response(request):
    return {
        "schema_version": "state-field-alignment-response-v1",
        "relations": [
            {**row, "relation": "DIFFERENT_STATE_VARIABLE"}
            for row in request["candidate_pairs"]
        ],
    }


class RQ3EvaluationTests(unittest.TestCase):
    def _review(self, instance, decision):
        review = build_review_template(instance)
        review["reviewers"] = ["reviewer-a", "reviewer-b"]
        review["adjudication_status"] = "ADJUDICATED"
        for condition in ("C1", "C2"):
            branch = review["conditions"][condition]
            branch["decision"] = decision
            branch["decision_rationale"] = "Synthetic adjudicated fixture."
            if decision == "ACT":
                branch["post_task_state_source"] = "CONSTRUCTION_TRANSITIONS_AFTER"
            else:
                branch["post_task_state_source"] = None
                branch["blocking_clarifications"] = [
                    {
                        "requirement_id": "REQ_BUTTON",
                        "dimension": "VALUE",
                        "field": "colour",
                        "missing_information": "The final button colour is not fixed.",
                        "acceptable_question_facts": [
                            "ask the client to choose the final button colour"
                        ],
                    }
                ]
        return review

    def test_review_requires_two_reviewers(self):
        instance = build_rq_instances(
            _gold(), _state_graph(), _messages()
        )["RQ3"][0]
        review = self._review(instance, "CLARIFY")
        review["reviewers"] = ["reviewer-a"]
        with self.assertRaises(RQ3ReviewError):
            apply_review(instance, review)

    def test_offline_agent_review_has_explicit_provenance(self):
        instance = build_rq_instances(
            _gold(), _act_state_graph(), _messages()
        )["RQ3"][0]
        review = build_offline_agent_review_template(instance)
        review["reviewers"] = ["offline-reviewer-a", "offline-reviewer-b"]
        review["adjudicator"] = "offline-adjudicator"
        review["adjudication_status"] = "ADJUDICATED"
        for condition in ("C1", "C2"):
            branch = review["conditions"][condition]
            branch["decision"] = "ACT"
            branch["decision_rationale"] = "Reviewed unique post-task state."
            branch["post_task_state_source"] = "CONSTRUCTION_TRANSITIONS_AFTER"
        frozen = apply_review(instance, review)
        self.assertEqual(
            frozen["construction_gold"]["review_status"],
            "OFFLINE_AGENT_REVIEWED_AND_ADJUDICATED",
        )
        self.assertEqual(
            frozen["construction_gold"]["review_metadata"]["adjudicator"],
            "offline-adjudicator",
        )
        self.assertTrue(frozen["readiness"]["formal_reasoning_allowed"])

    def test_act_branch_scores_complete_post_state(self):
        provisional = build_rq_instances(
            _gold(), _act_state_graph(), _messages()
        )["RQ3"][0]
        instance = apply_review(provisional, self._review(provisional, "ACT"))
        states = instance["construction_gold"]["post_task_states"]
        response = {
            "decision": "ACT",
            "post_task_states": [
                {
                    "requirement_ref": f"agent-{index}",
                    "requirement_summary": (
                        "Button colour" if rid == "REQ_BUTTON" else "Report"
                    ),
                    "change_type": "MODIFIED" if rid == "REQ_BUTTON" else "INTRODUCED",
                    "removed_attribute_keys": [],
                    "state": deepcopy(state),
                }
                for index, (rid, state) in enumerate(states.items(), 1)
            ],
            "clarifications": [],
        }
        request = build_alignment_request(instance, response, condition="C2")
        alignment = _alignment_response(
            request, {("P001", "G001"), ("P002", "G002")}
        )
        field_request = build_field_alignment_request(
            instance, response, alignment, condition="C2"
        )
        field_alignment = _field_alignment_response(field_request)
        semantic_request = build_state_semantic_request(
            instance, response, alignment, field_alignment, condition="C2"
        )
        result = score_rq3(
            instance,
            response,
            condition="C2",
            alignment_response=alignment,
            field_alignment_response=field_alignment,
            semantic_response=_state_semantic_response(semantic_request),
        )
        self.assertEqual(result["official_metrics"]["post_state_exact"], 1)
        self.assertEqual(result["official_metrics"]["act_end_to_end_success"], 1)

    def test_act_branch_rejects_incorrect_removed_attribute_declaration(self):
        provisional = build_rq_instances(
            _gold(), _act_state_graph(), _messages()
        )["RQ3"][0]
        instance = apply_review(provisional, self._review(provisional, "ACT"))
        states = instance["construction_gold"]["post_task_states"]
        response = {
            "decision": "ACT",
            "post_task_states": [
                {
                    "requirement_ref": f"agent-{index}",
                    "requirement_summary": (
                        "Button colour" if rid == "REQ_BUTTON" else "Report"
                    ),
                    "change_type": "MODIFIED" if rid == "REQ_BUTTON" else "INTRODUCED",
                    "removed_attribute_keys": (
                        ["not_actually_removed"] if rid == "REQ_BUTTON" else []
                    ),
                    "state": deepcopy(state),
                }
                for index, (rid, state) in enumerate(states.items(), 1)
            ],
            "clarifications": [],
        }
        request = build_alignment_request(instance, response, condition="C2")
        alignment = _alignment_response(
            request, {("P001", "G001"), ("P002", "G002")}
        )
        field_request = build_field_alignment_request(
            instance, response, alignment, condition="C2"
        )
        field_alignment = _field_alignment_response(field_request)
        semantic_request = build_state_semantic_request(
            instance, response, alignment, field_alignment, condition="C2"
        )
        result = score_rq3(
            instance,
            response,
            condition="C2",
            alignment_response=alignment,
            field_alignment_response=field_alignment,
            semantic_response=_state_semantic_response(semantic_request),
        )
        self.assertEqual(result["official_metrics"]["post_state_exact"], 0)

    def test_clarify_branch_scores_issue_and_question(self):
        provisional = build_rq_instances(
            _gold(), _state_graph(), _messages()
        )["RQ3"][0]
        instance = apply_review(provisional, self._review(provisional, "CLARIFY"))
        response = {
            "decision": "CLARIFY",
            "post_task_states": None,
            "clarifications": [
                {
                    "requirement_ref": "agent-button",
                    "requirement_summary": "Button colour",
                    "dimension": "VALUE",
                    "field": "colour",
                    "missing_information": "The requested final colour is unclear.",
                    "question": "Which final colour should the button use?",
                }
            ],
        }
        request = build_alignment_request(instance, response, condition="C1")
        alignment = _alignment_response(request, {("P001", "G001")})
        semantic_request = build_clarification_semantic_request(
            instance, response, alignment, condition="C1"
        )
        semantic = {
            "schema_version": "rq3-clarification-semantic-response-v1",
            "relations": [
                {
                    "candidate_id": row["candidate_id"],
                    "issue_relation": "EQUIVALENT",
                    "question_validity": "VALID",
                }
                for row in semantic_request["candidates"]
            ],
        }
        result = score_rq3(
            instance,
            response,
            condition="C1",
            alignment_response=alignment,
            semantic_response=semantic,
        )
        self.assertEqual(result["official_metrics"]["blocking_issue_f1"], 1.0)
        self.assertEqual(result["official_metrics"]["clarification_success"], 1)

    def test_wrong_branch_needs_no_judge(self):
        provisional = build_rq_instances(
            _gold(), _state_graph(), _messages()
        )["RQ3"][0]
        instance = apply_review(provisional, self._review(provisional, "CLARIFY"))
        first_state = next(iter(instance["construction_gold"]["post_task_states"].values()))
        response = {
            "decision": "ACT",
            "post_task_states": [
                {
                    "requirement_ref": "agent-button",
                    "requirement_summary": "Button colour",
                    "change_type": "MODIFIED",
                    "removed_attribute_keys": [],
                    "state": deepcopy(first_state),
                }
            ],
            "clarifications": [],
        }
        result = score_rq3(instance, response, condition="C1")
        self.assertEqual(result["official_metrics"]["unsupported_autonomy"], 1)
        self.assertEqual(result["official_metrics"]["clarification_success"], 0)

    def test_constant_decision_baseline_reports_class_imbalance(self):
        provisional = build_rq_instances(
            _gold(), _state_graph(), _messages()
        )["RQ3"][0]
        act_instance = apply_review(
            provisional, self._review(provisional, "ACT")
        )
        clarify_instance = apply_review(
            provisional, self._review(provisional, "CLARIFY")
        )
        result = score_rq3_constant_decision_baseline(
            [act_instance, clarify_instance], condition="C2", decision="ACT"
        )
        self.assertEqual(result["metrics"]["decision_accuracy"], 0.5)
        self.assertEqual(result["metrics"]["balanced_accuracy"], 0.5)
        self.assertEqual(
            result["metric_counts"]["unsupported_autonomy_rate"],
            {"numerator": 1, "denominator": 1},
        )

    def test_aggregate_uses_class_conditional_errors_and_exact_intervals(self):
        rows = [
            {
                "rq_id": "RQ3",
                "gold_decision": "ACT",
                "official_metrics": {
                    "decision_correct": 1,
                    "unsupported_autonomy": 0,
                    "unnecessary_clarification": 0,
                },
            },
            {
                "rq_id": "RQ3",
                "gold_decision": "CLARIFY",
                "official_metrics": {
                    "decision_correct": 0,
                    "unsupported_autonomy": 1,
                    "unnecessary_clarification": 0,
                },
            },
        ]
        result = aggregate_rq3_results(rows)
        self.assertEqual(
            result["official_metrics"]["unsupported_autonomy_rate"], 1.0
        )
        self.assertEqual(
            result["metric_counts"]["unsupported_autonomy_rate"],
            {"numerator": 1, "denominator": 1},
        )
        self.assertEqual(
            result["exact_binomial_confidence_intervals_95"][
                "unsupported_autonomy_rate"
            ],
            [0.025, 1.0],
        )


if __name__ == "__main__":
    unittest.main()
