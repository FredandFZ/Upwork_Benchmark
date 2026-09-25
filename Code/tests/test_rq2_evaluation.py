from __future__ import annotations

from copy import deepcopy
import unittest

from Code.evaluation.rq2 import (
    build_alignment_request,
    build_field_alignment_request,
    build_state_semantic_request,
    score_rq2,
    score_rq2_constant_state_baseline,
)
from Code.evaluation.state import (
    build_field_alignment_request as build_raw_field_alignment_request,
    build_semantic_fact_request,
    score_state,
)
from Code.stage2.rq2_review import (
    RQ2ReviewError,
    apply_review as apply_rq2_review,
    build_review_template as build_rq2_review_template,
)
from Code.stage2.rq_instances import build_rq_instances
from Code.tests.test_stage2_rq_instances import _gold, _messages, _state_graph


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


def _semantic_response(request):
    return {
        "schema_version": "state-semantic-response-v1",
        "relations": [
            {"fact_id": row["fact_id"], "relation": "EQUIVALENT"}
            for row in request["facts"]
        ],
    }


def _field_alignment_response(request, same_pairs=()):
    return {
        "schema_version": "state-field-alignment-response-v1",
        "relations": [
            {
                **pair,
                "relation": (
                    "SAME_STATE_VARIABLE"
                    if (pair["prediction_field_ref"], pair["gold_field_ref"])
                    in set(same_pairs)
                    else "DIFFERENT_STATE_VARIABLE"
                ),
            }
            for pair in request["candidate_pairs"]
        ],
    }


class RQ2EvaluationTests(unittest.TestCase):
    @staticmethod
    def _adjudicated_field_review(instance):
        review = build_rq2_review_template(instance)
        review["reviewers"] = ["offline-reviewer-a", "offline-reviewer-b"]
        review["adjudicator"] = "offline-adjudicator"
        review["adjudication_status"] = "ADJUDICATED"
        review["verdict"] = "FINALIZE"
        review["boundary_review"] = {
            "pre_task_boundary_correct": True,
            "historical_requirement_scope_correct": True,
            "internal_ids_excluded": True,
        }

        def mark(value):
            if not isinstance(value, dict):
                return
            if "comparator" in value:
                value["review_status"] = "OFFLINE_AGENT_REVIEWED"
            for child in value.values():
                if isinstance(child, dict):
                    mark(child)

        mark(review["final_field_scoring_specs"])
        return review

    def test_rq2_offline_review_freezes_typed_gold(self):
        instance = build_rq_instances(_gold(), _state_graph(), _messages())["RQ2"][0]
        frozen = apply_rq2_review(
            instance, self._adjudicated_field_review(instance)
        )
        self.assertEqual(
            frozen["construction_gold"]["status"], "FINAL_TYPED_STATE_GOLD"
        )
        self.assertEqual(
            frozen["construction_gold"]["review_status"],
            "OFFLINE_AGENT_REVIEWED_AND_ADJUDICATED",
        )
        self.assertTrue(frozen["readiness"]["formal_reasoning_allowed"])

    def test_rq2_offline_review_requires_distinct_adjudicator(self):
        instance = build_rq_instances(_gold(), _state_graph(), _messages())["RQ2"][0]
        review = self._adjudicated_field_review(instance)
        review["adjudicator"] = "offline-reviewer-a"
        with self.assertRaises(RQ2ReviewError):
            apply_rq2_review(instance, review)

    def setUp(self):
        self.instance = build_rq_instances(
            _gold(), _state_graph(), _messages()
        )["RQ2"][0]
        state = deepcopy(
            self.instance["construction_gold"]["states"]["REQ_BUTTON"]
        )
        self.response = {
            "requirements": [
                {
                    "requirement_ref": "agent-local-1",
                    "requirement_summary": "Button colour",
                    "evidence_message_ids": [10],
                    "pre_task_state": state,
                }
            ]
        }

    def test_correct_state_scores_exact_but_remains_provisional(self):
        alignment_request = build_alignment_request(
            self.instance, self.response, condition="C2"
        )
        alignment = _alignment_response(
            alignment_request, {("agent-local-1", "G001")}
        )
        field_request = build_field_alignment_request(
            self.instance, self.response, alignment, condition="C2"
        )
        field_alignment = _field_alignment_response(field_request)
        semantic_request = build_state_semantic_request(
            self.instance, self.response, alignment, field_alignment, condition="C2"
        )
        result = score_rq2(
            self.instance,
            self.response,
            alignment,
            field_alignment,
            _semantic_response(semantic_request),
            condition="C2",
        )
        self.assertEqual(result["official_metrics"]["attribute_reconstruction_score"], 1.0)
        self.assertEqual(result["official_metrics"]["matched_full_state_exact"], 1)
        self.assertEqual(result["official_metrics"]["reconstruction_coverage"], 1.0)
        self.assertFalse(result["reporting_eligible"])

    def test_closed_world_extra_attribute_is_penalized(self):
        response = deepcopy(self.response)
        response["requirements"][0]["pre_task_state"]["attributes"]["stale"] = "old"
        alignment_request = build_alignment_request(
            self.instance, response, condition="C2"
        )
        alignment = _alignment_response(
            alignment_request, {("agent-local-1", "G001")}
        )
        field_request = build_field_alignment_request(
            self.instance, response, alignment, condition="C2"
        )
        field_alignment = _field_alignment_response(field_request)
        semantic_request = build_state_semantic_request(
            self.instance, response, alignment, field_alignment, condition="C2"
        )
        result = score_rq2(
            self.instance,
            response,
            alignment,
            field_alignment,
            _semantic_response(semantic_request),
            condition="C2",
        )
        self.assertLess(
            result["official_metrics"]["attribute_reconstruction_score"], 1.0
        )
        self.assertEqual(result["official_metrics"]["matched_full_state_exact"], 0)

    def test_semantically_equivalent_attribute_name_is_aligned_before_value_scoring(self):
        response = deepcopy(self.response)
        attributes = response["requirements"][0]["pre_task_state"]["attributes"]
        attributes["button_color"] = attributes.pop("colour")
        alignment_request = build_alignment_request(
            self.instance, response, condition="C2"
        )
        alignment = _alignment_response(
            alignment_request, {("agent-local-1", "G001")}
        )
        field_request = build_field_alignment_request(
            self.instance, response, alignment, condition="C2"
        )
        renamed_pair = next(
            (
                row["prediction_field_ref"],
                row["gold_field_ref"],
            )
            for row in field_request["candidate_pairs"]
            if "button_color" in row["prediction_field_ref"]
            and "colour" in row["gold_field_ref"]
        )
        field_alignment = _field_alignment_response(
            field_request, {renamed_pair}
        )
        semantic_request = build_state_semantic_request(
            self.instance,
            response,
            alignment,
            field_alignment,
            condition="C2",
        )
        result = score_rq2(
            self.instance,
            response,
            alignment,
            field_alignment,
            _semantic_response(semantic_request),
            condition="C2",
        )
        self.assertEqual(
            result["official_metrics"]["attribute_reconstruction_score"], 1.0
        )
        details = result["matched_requirement_states"][0]["dimension_details"][
            "attributes"
        ]["diagnostics"]
        self.assertEqual(len(details["matched_fields"]), 1)
        self.assertEqual(details["unmatched_prediction_paths"], [])
        self.assertEqual(details["unmatched_gold_paths"], [])

    def test_user_example_three_renamed_fields_receives_full_attribute_credit(self):
        base = deepcopy(self.instance["construction_gold"]["states"]["REQ_BUTTON"])
        specs = deepcopy(
            self.instance["construction_gold"]["field_scoring_specs"]["REQ_BUTTON"]
        )
        base["attributes"] = {
            "winner_count": 8,
            "prize_amount_per_winner_usd": 900,
            "winner_eligibility": "weighted ticket holders",
        }
        specs["attributes"] = {
            "comparator": "RECURSIVE_FIELDS",
            "score": True,
            "closed_world": True,
            "fields": {
                "winner_count": {"comparator": "NUMBER_EXACT", "score": True},
                "prize_amount_per_winner_usd": {
                    "comparator": "NUMBER_EXACT",
                    "score": True,
                },
                "winner_eligibility": {
                    "comparator": "SEMANTIC_FACT",
                    "score": True,
                },
            },
        }
        predicted = deepcopy(base)
        predicted["attributes"] = {
            "prize_count": 8,
            "prize_amount_usd": 900,
            "winner_selection": "weighted ticket holders",
        }
        pair = {
            "pair_id": "user-example",
            "gold_state": base,
            "predicted_state": predicted,
            "scoring_specs": specs,
        }
        field_request = build_raw_field_alignment_request(
            target_id="example",
            purpose="TEST",
            state_pairs=[pair],
        )
        predicted_by_name = {
            row["field_name"]: row["field_ref"]
            for row in field_request["predicted_fields"]
        }
        gold_by_name = {
            row["field_name"]: row["field_ref"]
            for row in field_request["gold_fields"]
        }
        same = {
            (predicted_by_name["prize_count"], gold_by_name["winner_count"]),
            (
                predicted_by_name["prize_amount_usd"],
                gold_by_name["prize_amount_per_winner_usd"],
            ),
            (
                predicted_by_name["winner_selection"],
                gold_by_name["winner_eligibility"],
            ),
        }
        field_alignment = _field_alignment_response(field_request, same)
        semantic_request = build_semantic_fact_request(
            target_id="example",
            purpose="TEST_VALUES",
            state_pairs=[pair],
            field_alignment_response=field_alignment,
        )
        semantic_relations = {
            row["fact_id"]: "EQUIVALENT" for row in semantic_request["facts"]
        }
        result = score_state(
            pair_id="user-example",
            gold_state=base,
            predicted_state=predicted,
            scoring_specs=specs,
            semantic_relations=semantic_relations,
            field_alignment_request=field_request,
            field_alignment_response=field_alignment,
        )
        self.assertEqual(result["dimension_scores"]["attributes"], 1.0)
        self.assertEqual(result["dimension_details"]["attributes"]["correct_units"], 3.0)

        # Field identity is independent of value correctness: the same field
        # alignment remains valid, but NUMBER_EXACT removes value credit.
        wrong_value = deepcopy(predicted)
        wrong_value["attributes"]["prize_count"] = 7
        wrong_result = score_state(
            pair_id="user-example",
            gold_state=base,
            predicted_state=wrong_value,
            scoring_specs=specs,
            semantic_relations=semantic_relations,
            field_alignment_request=field_request,
            field_alignment_response=field_alignment,
        )
        self.assertAlmostEqual(
            wrong_result["dimension_scores"]["attributes"], 2 / 3, places=6
        )

    def test_constant_state_baseline_is_explicit_and_not_full_exact(self):
        result = score_rq2_constant_state_baseline(self.instance)
        self.assertTrue(result["conditional_on_gold_requirement_set"])
        self.assertEqual(result["metrics"]["attribute_reconstruction_score"], 0.0)
        self.assertEqual(result["metrics"]["matched_full_state_exact"], 0)

    def test_ambiguity_records_require_dimension_and_description_match(self):
        state = deepcopy(self.instance["construction_gold"]["states"]["REQ_BUTTON"])
        state["ambiguity"] = [
            {
                "status": "OPEN",
                "dimension": "VALUE",
                "description": "The final colour is unresolved.",
            }
        ]
        specs = deepcopy(
            self.instance["construction_gold"]["field_scoring_specs"]["REQ_BUTTON"]
        )
        specs["ambiguity"] = {
            "comparator": "UNORDERED_RECORD_F1",
            "score": True,
            "matching_key_fields": ["dimension", "description"],
            "item_fields": {
                "status": {"comparator": "NORMALIZED_EXACT", "score": True},
                "dimension": {"comparator": "NORMALIZED_EXACT", "score": True},
                "description": {"comparator": "SEMANTIC_FACT", "score": True},
            },
        }
        predicted = deepcopy(state)
        predicted["ambiguity"][0]["dimension"] = "SCOPE"
        relations = {
            "ambiguity-test::attributes.colour": "EQUIVALENT",
            "ambiguity-test::ambiguity.gold[0].predicted[0].description": "EQUIVALENT"
        }
        result = score_state(
            pair_id="ambiguity-test",
            gold_state=state,
            predicted_state=predicted,
            scoring_specs=specs,
            semantic_relations=relations,
        )
        self.assertEqual(result["dimension_scores"]["ambiguity"], 0.0)

    def test_ordered_list_is_order_sensitive_with_partial_credit(self):
        state = deepcopy(self.instance["construction_gold"]["states"]["REQ_BUTTON"])
        state["attributes"] = {"workflow": ["first", "second", "third"]}
        specs = deepcopy(
            self.instance["construction_gold"]["field_scoring_specs"]["REQ_BUTTON"]
        )
        specs["attributes"] = {
            "comparator": "RECURSIVE_FIELDS",
            "score": True,
            "closed_world": True,
            "fields": {
                "workflow": {"comparator": "ORDERED_LIST", "score": True}
            },
        }
        predicted = deepcopy(state)
        predicted["attributes"]["workflow"] = ["second", "first", "third"]
        result = score_state(
            pair_id="ordered-list-test",
            gold_state=state,
            predicted_state=predicted,
            scoring_specs=specs,
        )
        self.assertEqual(result["full_state_exact"], 0)
        self.assertAlmostEqual(
            result["dimension_scores"]["attributes"], 2 / 3, places=6
        )


if __name__ == "__main__":
    unittest.main()
