from __future__ import annotations

import json
import unittest

from Code.stage2.gold_state import (
    TargetSelectionConfig,
    TaskGoldError,
    apply_coverage_and_deduplication,
    audit_event_provenance,
    build_candidate_contexts,
    build_candidate_packets,
    build_gold_states,
    build_threshold_selection_statistics,
    calculate_ai_selection_score,
    evaluate_candidate_packets,
    finalize_ai_selected_targets,
    finalize_selected_targets,
    generate_candidate_tasks,
    render_threshold_selection_markdown,
    select_ai_candidates_by_score,
    select_recommended_candidates,
    validate_gold_states,
    validate_llm_evaluation,
)
from Code.stage2.state_graph import build_requirement_state_graph


def message(message_id, *, speaker="client", text=None, original_index=0):
    return {
        "message_id": message_id,
        "created_ts": f"2026-01-01 00:00:{original_index:02d}",
        "speaker": speaker,
        "text": text if text is not None else f"message {message_id}",
        "milestone": None,
        "original_index": original_index,
    }


def normalized(*messages):
    return {
        "project_id": "P1",
        "project_title": "Project",
        "messages": list(messages),
    }


def event(
    requirement_id: str,
    number: int,
    message_id,
    event_type: str,
    *,
    value_updates=None,
    value_removals=None,
    scope_updates=None,
    ambiguity=None,
    execution=None,
    resolves_ambiguity_event_ids=None,
    supporting_message_ids=None,
    speaker: str = "client",
):
    return {
        "event_id": f"{requirement_id}_E{number:03d}",
        "source_message": {
            "message_id": message_id,
            "speaker": speaker,
            "text": f"message {message_id}",
        },
        "supporting_message_ids": supporting_message_ids or [],
        "event_type": event_type,
        "value_updates": value_updates,
        "value_removals": value_removals,
        "scope_updates": scope_updates,
        "ambiguity": ambiguity,
        "execution": execution,
        "resolves_ambiguity_event_ids": resolves_ambiguity_event_ids,
    }


def requirement(requirement_id: str, events):
    return {
        "requirement_id": requirement_id,
        "title": requirement_id,
        "family_id": None,
        "events": events,
    }


def annotation(*requirements):
    return {
        "benchmark": "ReqMemBench",
        "annotation_version": "v0.6",
        "project": {"project_id": "P1", "project_title": "Project"},
        "requirement_families": [],
        "requirements": list(requirements),
    }


def evaluation(candidate, *, recommended=True, rq_targets=None, **overrides):
    row = {
        "candidate_id": candidate["candidate_id"],
        "message_id": candidate["message_id"],
        "valid_task": True,
        "historical_dependency": "HIGH",
        "requirement_evolution": "HIGH",
        "reconstruction_risk": "HIGH",
        "ambiguity_decision_value": "LOW",
        "multi_requirement_value": "HIGH"
        if len(candidate["requirement_ids"]) > 1
        else "LOW",
        "history_sensitive": recommended,
        "recommended": recommended,
        "primary_rq_targets": rq_targets or ["RQ1", "RQ2"],
        "reason": "Correct action depends on reconstructing earlier Requirement state.",
    }
    row.update(overrides)
    return row


def selected_targets_for(graph, messages, *message_ids):
    positions = {
        json.dumps(row["message_id"], ensure_ascii=False, sort_keys=True): position
        for position, row in enumerate(messages["messages"])
    }
    targets = []
    for number, message_id in enumerate(message_ids, start=1):
        key = json.dumps(message_id, ensure_ascii=False, sort_keys=True)
        events = []
        requirements = []
        for requirement_graph in graph["requirement_graphs"]:
            for edge in requirement_graph["edges"]:
                if json.dumps(
                    edge["source_message_id"], ensure_ascii=False, sort_keys=True
                ) == key:
                    events.append(edge["event_id"])
                    if requirement_graph["requirement_id"] not in requirements:
                        requirements.append(requirement_graph["requirement_id"])
        position = positions[key]
        targets.append(
            {
                "target_id": f"P1_T{number:03d}",
                "candidate_id": f"P1_CANDIDATE_MSG_{message_id}",
                "message_id": message_id,
                "conversation_turn_index": position + 1,
                "history_turn_count": position,
                "event_ids": events,
                "affected_requirement_ids": requirements,
                "selection_source": "LLM_PLUS_HUMAN",
                "primary_rq_targets": ["RQ1", "RQ2"],
                "human_review": "ACCEPT",
                "human_review_reason": "Representative history-dependent task.",
            }
        )
    return {
        "schema_version": "selected-target-times-v1",
        "project_id": "P1",
        "selected_targets": targets,
    }


def task(gold, message_id):
    return next(
        item
        for item in gold["task_gold_states"]
        if item["target_task"]["source_message_id"] == message_id
    )


def snapshot_map(task_gold, field: str):
    return {
        item["requirement_id"]: item["state_id"]
        for item in task_gold[field]["requirement_states"]
    }


class FakeApi:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def call(self, *, messages, validator=None, **kwargs):
        packet = json.loads(messages[-1]["content"])
        self.calls.append(packet["candidate_id"])
        response = self.responses[packet["candidate_id"]]
        if validator is not None:
            validator(response)
        return response


class TargetSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = TargetSelectionConfig.from_mapping({})

    def test_legacy_sampler_config_is_rejected(self) -> None:
        with self.assertRaisesRegex(TaskGoldError, "legacy Task sampler"):
            TargetSelectionConfig.from_mapping({"random_seed": 42})
        self.assertEqual(
            TargetSelectionConfig.from_mapping({}).allowed_rq_targets,
            ("RQ1", "RQ2", "RQ3", "RQ4"),
        )
        with self.assertRaisesRegex(TaskGoldError, "RQ1-RQ4"):
            TargetSelectionConfig.from_mapping(
                {"allowed_rq_targets": ["RQ1", "RQ5"]}
            )

    def test_candidate_groups_all_same_message_events_and_counts_history(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1}),
                    event("REQ_A", 2, 3, "MODIFY", value_updates={"a": 2}),
                ],
            ),
            requirement(
                "REQ_B",
                [
                    event("REQ_B", 1, 1, "INTRODUCE", value_updates={"b": 1}),
                    event("REQ_B", 2, 3, "REMOVE"),
                ],
            ),
        )
        messages = normalized(
            message(1, original_index=0),
            message(2, speaker="freelancer", original_index=1),
            message(3, original_index=2),
        )
        graph = build_requirement_state_graph(stage1)
        result = generate_candidate_tasks(stage1, messages, graph, self.config)
        self.assertEqual(len(result["candidates"]), 2)
        candidate = next(
            row for row in result["candidates"] if row["message_id"] == 3
        )
        self.assertEqual(candidate["message_id"], 3)
        self.assertEqual(candidate["conversation_turn_index"], 3)
        self.assertEqual(candidate["history_turn_count"], 2)
        self.assertEqual(candidate["event_ids"], ["REQ_A_E002", "REQ_B_E002"])
        self.assertEqual(candidate["requirement_ids"], ["REQ_A", "REQ_B"])
        self.assertIn("MULTI_REQUIREMENT", candidate["coverage_tags"])

    def test_late_pure_introduce_is_high_recall_candidate(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [event("REQ_A", 1, "m1", "INTRODUCE", value_updates={"a": 1})],
            ),
            requirement(
                "REQ_B",
                [event("REQ_B", 1, "m3", "INTRODUCE", value_updates={"b": 1})],
            ),
        )
        messages = normalized(
            message("m1", original_index=10),
            message("m2", speaker="freelancer", original_index=20),
            message("m3", original_index=30),
        )
        graph = build_requirement_state_graph(stage1)
        result = generate_candidate_tasks(stage1, messages, graph, self.config)
        self.assertEqual([row["message_id"] for row in result["candidates"]], ["m3"])
        self.assertTrue(result["candidates"][0]["introduce_only"])

    def test_execution_only_is_excluded_by_default(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1}),
                    event(
                        "REQ_A",
                        2,
                        2,
                        "RUNTIME_FAILURE",
                        execution={"status": "FAILED", "observed_behavior": "failed"},
                        speaker="freelancer",
                    ),
                ],
            )
        )
        messages = normalized(
            message(1, original_index=0),
            message(2, speaker="freelancer", original_index=1),
        )
        graph = build_requirement_state_graph(stage1)
        result = generate_candidate_tasks(stage1, messages, graph, self.config)
        self.assertEqual(result["candidates"], [])

    def test_context_is_pre_task_and_marks_resolution(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1}),
                    event(
                        "REQ_A",
                        2,
                        2,
                        "AMBIGUOUS",
                        ambiguity={"dimension": "VALUE", "description": "unclear"},
                    ),
                    event(
                        "REQ_A",
                        3,
                        3,
                        "MODIFY",
                        value_updates={"a": 2},
                        resolves_ambiguity_event_ids=["REQ_A_E002"],
                    ),
                    event("REQ_A", 4, 4, "MODIFY", value_updates={"a": 3}),
                ],
            )
        )
        messages = normalized(
            *[message(value, original_index=value - 1) for value in range(1, 5)]
        )
        graph = build_requirement_state_graph(stage1)
        candidates = generate_candidate_tasks(stage1, messages, graph, self.config)
        candidate = next(row for row in candidates["candidates"] if row["message_id"] == 3)
        self.assertIn("AMBIGUITY_RESOLUTION", candidate["coverage_tags"])
        contexts = build_candidate_contexts(candidates, stage1, messages, graph)
        context = next(
            row for row in contexts["contexts"] if row["candidate_id"] == candidate["candidate_id"]
        )
        history_ids = [
            row["event_id"] for row in context["requirement_history"][0]["events"]
        ]
        self.assertEqual(history_ids, ["REQ_A_E001", "REQ_A_E002"])
        self.assertEqual(
            [row["message_id"] for row in context["historical_evidence_messages"]],
            [1, 2],
        )
        pre_state = context["pre_task_requirement_states"][0]["state"]
        self.assertIn("REQ_A_E002", pre_state["ambiguity"])

    def test_provenance_mismatch_stops_selection(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1})],
            )
        )
        messages = normalized(message(1, original_index=0))
        graph = build_requirement_state_graph(stage1)
        graph["requirement_graphs"][0]["edges"][0]["event_type"] = "MODIFY"
        self.assertEqual(len(audit_event_provenance(stage1, graph, messages)), 1)
        with self.assertRaisesRegex(TaskGoldError, "provenance audit failed"):
            generate_candidate_tasks(stage1, messages, graph, self.config)

    def test_llm_response_schema_is_strict(self) -> None:
        packet = {
            "candidate_id": "P1_C1",
            "candidate_task": {"message_id": 2},
        }
        candidate = {
            "candidate_id": "P1_C1",
            "message_id": 2,
            "requirement_ids": ["REQ_A"],
        }
        valid = evaluation(candidate)
        validate_llm_evaluation(valid, packet, self.config)
        invalid = dict(valid, extra="not allowed")
        with self.assertRaisesRegex(TaskGoldError, "fields do not match"):
            validate_llm_evaluation(invalid, packet, self.config)
        invalid = dict(valid, recommended=True, history_sensitive=False)
        with self.assertRaisesRegex(TaskGoldError, "recommended=true"):
            validate_llm_evaluation(invalid, packet, self.config)
        invalid = dict(valid, primary_rq_targets=["RQ5"])
        with self.assertRaisesRegex(TaskGoldError, "configured RQ IDs"):
            validate_llm_evaluation(invalid, packet, self.config)
        invalid = dict(valid, primary_rq_targets=[])
        with self.assertRaisesRegex(TaskGoldError, "primary_rq_target"):
            validate_llm_evaluation(invalid, packet, self.config)

    def test_coverage_deduplicates_exact_challenge(self) -> None:
        candidates = {
            "project_id": "P1",
            "candidates": [
                {
                    "candidate_id": "C1",
                    "message_id": 2,
                    "conversation_turn_index": 2,
                    "history_turn_count": 1,
                    "speaker": "client",
                    "text": "first",
                    "event_ids": ["REQ_A_E002"],
                    "requirement_ids": ["REQ_A"],
                    "event_types": ["MODIFY"],
                    "coverage_tags": ["MODIFY", "SINGLE_REQUIREMENT"],
                    "introduce_only": False,
                },
                {
                    "candidate_id": "C2",
                    "message_id": 3,
                    "conversation_turn_index": 3,
                    "history_turn_count": 2,
                    "speaker": "client",
                    "text": "second",
                    "event_ids": ["REQ_A_E003"],
                    "requirement_ids": ["REQ_A"],
                    "event_types": ["MODIFY"],
                    "coverage_tags": ["MODIFY", "SINGLE_REQUIREMENT"],
                    "introduce_only": False,
                },
            ],
        }
        evaluations = [
            evaluation(candidates["candidates"][0], rq_targets=["RQ1"]),
            evaluation(candidates["candidates"][1], rq_targets=["RQ1", "RQ2"]),
        ]
        recommended = select_recommended_candidates(candidates, evaluations, self.config)
        same_state = {
            "state_id": "REQ_A_S001",
            "lifecycle_status": "ACTIVE",
            "ambiguity": None,
        }
        contexts = {
            "project_id": "P1",
            "contexts": [
                {
                    "candidate_id": candidate_id,
                    "pre_task_requirement_states": [
                        {"requirement_id": "REQ_A", "state": same_state}
                    ],
                }
                for candidate_id in ("C1", "C2")
            ],
        }
        selected = apply_coverage_and_deduplication(
            recommended, contexts, self.config
        )
        self.assertEqual(
            [row["candidate_id"] for row in selected["selected_candidates"]],
            ["C2"],
        )
        self.assertEqual(
            selected["deduplication"][0]["deduplicated_candidate_ids"], ["C1"]
        )

    def test_ai_score_threshold_selects_every_eligible_candidate(self) -> None:
        rows = [
            {
                "candidate_id": candidate_id,
                "message_id": position,
                "conversation_turn_index": position,
                "history_turn_count": position - 1,
                "speaker": "client",
                "text": candidate_id,
                "event_ids": [f"REQ_{candidate_id}_E001"],
                "requirement_ids": [f"REQ_{candidate_id}"],
                "event_types": ["MODIFY"],
                "coverage_tags": ["MODIFY", "SINGLE_REQUIREMENT"],
                "introduce_only": False,
            }
            for position, candidate_id in enumerate(("C1", "C2", "C3"), start=2)
        ]
        candidates = {"project_id": "P1", "candidates": rows}
        evaluations = [
            evaluation(rows[0], ambiguity_decision_value="HIGH"),
            evaluation(rows[1], ambiguity_decision_value="MEDIUM"),
            evaluation(
                rows[2],
                recommended=False,
                historical_dependency="HIGH",
                requirement_evolution="HIGH",
                reconstruction_risk="HIGH",
                ambiguity_decision_value="HIGH",
                multi_requirement_value="HIGH",
            ),
        ]

        self.assertEqual(calculate_ai_selection_score(evaluations[0]), 8)
        selected = select_ai_candidates_by_score(
            candidates, evaluations, self.config, score_threshold=7
        )
        self.assertEqual(
            [row["candidate_id"] for row in selected["selected_candidates"]],
            ["C1", "C2"],
        )
        self.assertEqual(
            [row["ai_selection_score"] for row in selected["selected_candidates"]],
            [8, 7],
        )

        finalized = finalize_ai_selected_targets(
            selected, candidates, evaluations, self.config
        )
        self.assertEqual(
            [row["selection_source"] for row in finalized["selected_targets"]],
            ["LLM_AUTO_ACCEPT", "LLM_AUTO_ACCEPT"],
        )
        self.assertEqual(
            [row["human_review"] for row in finalized["selected_targets"]],
            ["SKIPPED", "SKIPPED"],
        )
        self.assertEqual(finalized["score_threshold"], 7)

        with self.assertRaisesRegex(TaskGoldError, "score threshold"):
            select_ai_candidates_by_score(
                candidates, evaluations, self.config, score_threshold=11
            )

    def test_threshold_statistics_split_history_boundaries(self) -> None:
        history_lengths = (49, 50, 99, 100)
        rows = [
            {
                "candidate_id": f"C{number}",
                "message_id": number,
                "conversation_turn_index": history_length + 1,
                "history_turn_count": history_length,
                "speaker": "client",
                "text": f"candidate {number}",
                "event_ids": [f"REQ_{number}_E001"],
                "requirement_ids": [f"REQ_{number}"],
                "event_types": ["MODIFY"],
                "coverage_tags": ["MODIFY", "SINGLE_REQUIREMENT"],
                "introduce_only": False,
            }
            for number, history_length in enumerate(history_lengths, start=1)
        ]
        candidates = {"project_id": "P1", "candidates": rows}
        evaluations = [
            evaluation(
                rows[0],
                ambiguity_decision_value="HIGH",
                multi_requirement_value="HIGH",
            ),
            evaluation(
                rows[1],
                ambiguity_decision_value="HIGH",
                multi_requirement_value="MEDIUM",
            ),
            evaluation(
                rows[2],
                ambiguity_decision_value="HIGH",
                multi_requirement_value="LOW",
            ),
            evaluation(
                rows[3],
                ambiguity_decision_value="MEDIUM",
                multi_requirement_value="LOW",
            ),
        ]

        statistics = build_threshold_selection_statistics(
            candidates, evaluations, self.config
        )
        rows_by_threshold = {
            row["score_threshold"]: row for row in statistics["rows"]
        }
        self.assertEqual(
            rows_by_threshold[5],
            {
                "score_threshold": 5,
                "history_turns_0_to_49": 1,
                "history_turns_50_to_99": 2,
                "history_turns_100_plus": 1,
                "total_selected": 4,
            },
        )
        self.assertEqual(rows_by_threshold[8]["total_selected"], 3)
        self.assertEqual(rows_by_threshold[9]["history_turns_50_to_99"], 1)
        self.assertEqual(rows_by_threshold[10]["history_turns_0_to_49"], 1)
        self.assertEqual(rows_by_threshold[10]["total_selected"], 1)
        markdown = render_threshold_selection_markdown(statistics)
        self.assertIn("| 10 | 1 | 0 | 0 | 1 |", markdown)


class AsyncEvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_api_and_resume_fingerprint(self) -> None:
        config = TargetSelectionConfig.from_mapping({})
        candidate = {
            "candidate_id": "C1",
            "message_id": 2,
            "requirement_ids": ["REQ_A"],
        }
        packet = {
            "schema_version": "target-candidate-packet-v1",
            "project_id": "P1",
            "candidate_id": "C1",
            "candidate_task": {"message_id": 2},
            "triggered_events": [],
            "pre_task_requirement_states": [],
            "requirement_history": [],
            "historical_evidence_messages": [],
        }
        response = evaluation(candidate)
        api = FakeApi({"C1": response})
        first = await evaluate_candidate_packets(
            [packet], api=api, prompt="prompt", config=config
        )
        self.assertEqual(api.calls, ["C1"])
        second_api = FakeApi({"C1": response})
        second = await evaluate_candidate_packets(
            [packet],
            api=second_api,
            prompt="prompt",
            config=config,
            existing_evaluations=first,
        )
        self.assertEqual(second_api.calls, [])
        self.assertEqual(first, second)


class HumanReviewAndGoldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = TargetSelectionConfig.from_mapping({})

    def test_human_review_accept_and_add_back(self) -> None:
        rows = [
            {
                "candidate_id": "C1",
                "message_id": 2,
                "conversation_turn_index": 2,
                "history_turn_count": 1,
                "speaker": "client",
                "text": "first",
                "event_ids": ["REQ_A_E002"],
                "requirement_ids": ["REQ_A"],
                "event_types": ["MODIFY"],
                "coverage_tags": ["MODIFY", "SINGLE_REQUIREMENT"],
                "introduce_only": False,
            },
            {
                "candidate_id": "C2",
                "message_id": 3,
                "conversation_turn_index": 3,
                "history_turn_count": 2,
                "speaker": "client",
                "text": "second",
                "event_ids": ["REQ_B_E002"],
                "requirement_ids": ["REQ_B"],
                "event_types": ["REMOVE"],
                "coverage_tags": ["REMOVE", "SINGLE_REQUIREMENT"],
                "introduce_only": False,
            },
        ]
        candidate_tasks = {"project_id": "P1", "candidates": rows}
        evaluations = [evaluation(rows[0]), evaluation(rows[1], recommended=False)]
        auto = {"project_id": "P1", "selected_candidates": [rows[0]]}
        review = {
            "project_id": "P1",
            "decisions": [
                {"candidate_id": "C1", "decision": "ACCEPT", "reason": "keep"},
                {"candidate_id": "C2", "decision": "ADD_BACK", "reason": "coverage"},
            ],
        }
        selected = finalize_selected_targets(
            auto, candidate_tasks, evaluations, review, self.config
        )
        self.assertEqual(
            [row["selection_source"] for row in selected["selected_targets"]],
            ["LLM_PLUS_HUMAN", "HUMAN_ADD_BACK"],
        )
        self.assertEqual(
            [row["target_id"] for row in selected["selected_targets"]],
            ["P1_T001", "P1_T002"],
        )

    def test_gold_replays_selected_multi_requirement_task(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1}),
                    event("REQ_A", 2, 2, "MODIFY", value_updates={"a": 2}),
                ],
            ),
            requirement(
                "REQ_B",
                [
                    event("REQ_B", 1, 1, "INTRODUCE", value_updates={"b": 1}),
                    event("REQ_B", 2, 2, "REMOVE"),
                ],
            ),
            requirement(
                "REQ_KEEP",
                [event("REQ_KEEP", 1, 1, "INTRODUCE", value_updates={"k": 1})],
            ),
        )
        messages = normalized(
            message(1, original_index=0), message(2, original_index=1)
        )
        graph = build_requirement_state_graph(stage1)
        selected = selected_targets_for(graph, messages, 2)
        selected["selected_targets"][0].update(
            {
                "selection_source": "LLM_AUTO_ACCEPT",
                "human_review": "SKIPPED",
                "ai_selection_score": 8,
                "ai_score_threshold": 7,
            }
        )
        gold = build_gold_states(selected, messages, graph)
        target = task(gold, 2)
        self.assertEqual(target["selection_source"], "LLM_AUTO_ACCEPT")
        self.assertEqual(target["ai_selection_score"], 8)
        self.assertEqual(target["task_event_ids"], ["REQ_A_E002", "REQ_B_E002"])
        self.assertEqual(target["affected_requirement_ids"], ["REQ_A", "REQ_B"])
        self.assertEqual(target["preserved_requirement_ids"], ["REQ_KEEP"])
        pre = snapshot_map(target, "pre_task_gold_state")
        post = snapshot_map(target, "post_task_gold_state")
        self.assertEqual(pre["REQ_KEEP"], post["REQ_KEEP"])
        removed_state = graph["requirement_graphs"][1]["nodes"][1]
        self.assertEqual(removed_state["lifecycle_status"], "REMOVED")
        self.assertEqual(validate_gold_states(
            gold,
            graph,
            normalized_project=messages,
            selected_targets=selected,
        ), [])

    def test_late_introduce_preserves_observed_pre_task_state(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event(
                        "REQ_A",
                        1,
                        "failure",
                        "RUNTIME_FAILURE",
                        execution={"status": "FAILED", "observed_behavior": "failed"},
                        speaker="freelancer",
                    ),
                    event(
                        "REQ_A",
                        2,
                        "request",
                        "INTRODUCE",
                        value_updates={"a": 1},
                    ),
                ],
            )
        )
        messages = normalized(
            message("failure", speaker="freelancer", original_index=4),
            message("request", original_index=8),
        )
        graph = build_requirement_state_graph(stage1)
        selected = selected_targets_for(graph, messages, "request")
        gold = build_gold_states(selected, messages, graph)
        target = task(gold, "request")
        self.assertIn("REQ_A", snapshot_map(target, "pre_task_gold_state"))
        self.assertEqual(
            snapshot_map(target, "post_task_gold_state")["REQ_A"], "REQ_A_S002"
        )


if __name__ == "__main__":
    unittest.main()
