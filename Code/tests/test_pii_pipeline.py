"""End-to-end pipeline tests against a scripted fake API client.

The behaviours asserted here are the ones the design exists to guarantee:

* a single run enumerates **every** failing message instead of stopping at the
  first one;
* an unresolved message is never silently replaced by its original text, and no
  output is committed while one exists;
* resume performs zero API calls when nothing changed, and a prompt edit
  invalidates exactly its own phase and that phase's descendants;
* the agent repair round trip commits natural synthetic content, and every
  staleness and leak guard rejects a bad submission.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from Code.PII.agent_handoff import queue_sha256, read_task_package, repairs_dir
from Code.PII.config import PHASE_0B, PHASE_1A, PiiConfig, ProjectFiles
from Code.PII.errors import PiiError, PiiValidationError
from Code.PII.finalize import finalize_project, status_report
from Code.PII.ledger import (
    STATUS_AWAITING_AGENT_REPAIR,
    STATUS_PASSED,
    UnresolvedLedger,
)
from Code.PII.phase4_verify import CHECK_DIMENSIONS
from Code.PII.pipeline import PiiPipeline
from Code.PII.prompts import PromptSet
from Code.stage1.api_client import ApiError

PROMPT_KEYS = (
    "PHASE_0B_PII_DISCOVERY",
    "PHASE_1A_MESSAGE_SEMANTICS",
    "PHASE_1B_PROJECT_CONSOLIDATION",
    "PHASE_2_TRANSFORMATION_PLAN",
    "PHASE_3A_SHORT",
    "PHASE_3B_LONG",
    "PHASE_4_VERIFICATION",
    "PHASE_5_REPAIR",
)

RAW = [
    {
        "message": "Hi Joseph, the deploy key goes to scott@northstar.io. We agreed on 5 winners at $10,000 each.",
        "message_user_type": "client",
        "sender_id": "aa11bb22cc33",
        "created_ts": "t1",
    },
    {
        "message": "ok",
        "message_user_type": "freelancer",
        "sender_id": "dd44ee55ff66",
        "created_ts": "t2",
    },
    {
        "message": "Please also confirm the OAuth scopes with Stripe. We need that finished before Friday, Joseph.",
        "message_user_type": "client",
        "sender_id": "aa11bb22cc33",
        "created_ts": "t3",
    },
]


def prompt_set(overrides: dict[str, str] | None = None) -> PromptSet:
    hashes = {key: f"sha-{key}" for key in PROMPT_KEYS}
    hashes.update(overrides or {})
    return PromptSet(
        texts={key: f"PROMPT {key}" for key in PROMPT_KEYS},
        paths={},
        versions={key: "v1" for key in PROMPT_KEYS},
        hashes=hashes,
        agent_instructions="AGENT DOC",
        agent_instructions_path=Path("prompt/PII/agent_repair_instructions.md"),
        agent_instructions_sha256="agentsha",
    )


class FakeApi:
    """A cooperative model, with per-run-mode failure injection."""

    def __init__(self, *, fail_rewrite_ordinals: set[int] | None = None,
                 transport_fail_modes: set[str] | None = None,
                 fail_verify_ordinals: set[int] | None = None) -> None:
        self.calls: list[str] = []
        self.fail_rewrite_ordinals = fail_rewrite_ordinals or set()
        self.transport_fail_modes = transport_fail_modes or set()
        self.fail_verify_ordinals = fail_verify_ordinals or set()
        # Appended to every long rewrite, so a test can make the rewrite output
        # genuinely differ between runs.
        self.rewrite_suffix = ""

    async def call(self, *, project_id, run_mode, messages, target_requirement=None,
                   validator=None, failed_response_redactor=None):
        self.calls.append(run_mode)
        if run_mode in self.transport_fail_modes:
            raise ApiError(
                f"{run_mode} failed after 4 attempt(s): ConnectError",
                cause=ConnectionError("connection refused"),
            )
        body = json.loads(messages[1]["content"])
        payload = self.respond(run_mode, body)
        if validator:
            # Mirror Stage1ApiClient: a validator rejection is retried and then
            # re-raised wrapped in ApiError, carrying the cause. Reproducing that
            # here is what exercises the real batch -> per-message fallback.
            try:
                validator(payload)
            except ValueError as exc:
                raise ApiError(
                    f"{run_mode}/{target_requirement} failed after 1 attempt(s): "
                    f"{type(exc).__name__}: {exc}",
                    cause=exc,
                ) from exc
        return payload

    # -- scripted responses ------------------------------------------------- #

    def respond(self, mode, body):
        if mode == "PII7_PII_DISCOVERY":
            return {"messages": [
                {"ordinal": m["ordinal"], "occurrences": self._occurrences(m)}
                for m in body["safe_messages"]]}
        if mode == "PII7_MESSAGE_SEMANTICS":
            return {"records": [self._semantics(m) for m in body["safe_messages"]]}
        if mode == "PII7_PROJECT_CONSOLIDATION":
            return {"registry": self._registry(body)}
        if mode == "PII7_TRANSFORMATION_PLAN":
            return self._plan(body)
        if mode == "PII7_REWRITE":
            return {"rewrites": [self._rewrite(m, body) for m in body["safe_messages"]]}
        if mode == "PII7_VERIFICATION":
            return {"verdicts": [self._verdict(m) for m in body["safe_original"]]}
        if mode == "PII7_REPAIR":
            ordinal = body["safe_original"][0]["ordinal"]
            # Unhelpful on purpose: returns the rejected text, so repair exhausts.
            return {"rewrites": [{"ordinal": ordinal,
                                  "text": body["synthetic_rewrite"][str(ordinal)]}]}
        raise AssertionError(mode)

    @staticmethod
    def _occurrences(message):
        text = message["text"]
        found = []
        if "Joseph" in text:
            found.append({"source": "Joseph", "entity_type": "PERSON",
                          "normalized_value": "Joseph", "link_hint": "L1",
                          "confidence": "HIGH"})
        if "scott@northstar.io" in text:
            found.append({"source": "scott@northstar.io", "entity_type": "EMAIL",
                          "normalized_value": "scott@northstar.io", "link_hint": "L1",
                          "confidence": "HIGH"})
        for word in ("Stripe", "OAuth"):
            if word in text:
                kind = "PUBLIC_THIRD_PARTY" if word == "Stripe" else "PUBLIC_TECHNOLOGY"
                found.append({"source": word, "entity_type": kind,
                              "normalized_value": word, "confidence": "HIGH"})
        return found

    @staticmethod
    def _semantics(message):
        slots = []
        if "5 winners" in message["text"]:
            slots = [
                {"slot_name": "WINNER_COUNT", "value_type": "COUNT",
                 "source_literal": "5 winners", "meaning": "winners per draw"},
                {"slot_name": "PRIZE", "value_type": "AMOUNT",
                 "source_literal": "$10,000", "meaning": "prize per winner"},
            ]
        return {"ordinal": message["ordinal"], "speech_act": "STATEMENT",
                "polarity": "AFFIRMATIVE", "execution_status": "NOT_APPLICABLE",
                "ambiguity_kind": "NONE", "decisions": [], "slots": slots}

    @staticmethod
    def _registry(body):
        slots = []
        for record in body["semantic_records"]:
            for slot in record["slots"]:
                slots.append({
                    "slot_id": slot["slot_name"], "kind": "BUSINESS",
                    "value_type": slot["value_type"], "unit": None,
                    "current_value": slot["source_literal"], "meaning": slot["meaning"],
                    "history": [{"ordinal": record["ordinal"], "op": "INTRODUCE",
                                 "old_value": None, "new_value": slot["source_literal"]}],
                    "source_literals": [slot["source_literal"]],
                    "message_ordinals": [record["ordinal"]]})
        known = {slot["slot_id"] for slot in slots}
        for slot in (body.get("semantic_accumulator") or {}).get("slots", []):
            if slot["slot_id"] not in known:
                slots.append(slot)
        return {"slots": slots, "relations": [], "decisions": [], "merged_from": {}}

    @staticmethod
    def _plan(body):
        if body.get("mode") == "ENTITY_CHUNK":
            values = {"PERSON": "Marcus Feld",
                      "EMAIL": "marcus.f@ledgerline-demo.example"}
            return {"replacements": [
                {"entity_id": item["entity_id"],
                 "replacement": values.get(item["entity_type"], item["original"])}
                for item in body["pii_entities"]]}
        new_values = {"5 winners": "7 winners", "$10,000": "$12,500"}
        return {"slot_replacements": [
            {"slot_id": slot["slot_id"],
             "history": [{"new_value": new_values.get(entry["new_value"],
                                                      entry["new_value"] + "x")}
                         for entry in slot["history"]],
             "literal_map": {literal: new_values.get(literal, literal + "x")
                             for literal in slot["source_literals"]}}
            for slot in body["slot_cluster"]]}

    def _rewrite(self, message, body):
        ordinal = message["ordinal"]
        if ordinal in self.fail_rewrite_ordinals:
            # Unchanged text: rejected by the local gate.
            return {"ordinal": ordinal, "text": message["text"]}
        slice_ = body["plan_slice"][str(ordinal)]
        text = message["text"]
        for item in slice_["entity_replacements"]:
            if item["policy"] == "SYNTHESIZE":
                text = text.replace(item["original"], item["replacement"])
        for item in slice_["slot_replacements"]:
            for original, replacement in item["literal_map"].items():
                text = text.replace(original, replacement)
        if body["policy"]["bucket"] == "LONG":
            text = _restructure(text) + self.rewrite_suffix
        else:
            text = text.rstrip(".") + " indeed."
        return {"ordinal": ordinal, "text": text}

    def _verdict(self, message):
        ordinal = message["ordinal"]
        if ordinal in self.fail_verify_ordinals:
            checks = {name: "PASS" for name in CHECK_DIMENSIONS}
            checks["decisions"] = "FAIL"
            return {"ordinal": ordinal, "status": "FAIL", "checks": checks,
                    "findings": [{"code": "DECISION_LOST", "detail": "approval lost",
                                  "evidence": {"kind": "NONE"}, "severity": "HIGH"}]}
        return {"ordinal": ordinal, "status": "PASS",
                "checks": {name: "PASS" for name in CHECK_DIMENSIONS}, "findings": []}


def _restructure(text: str) -> str:
    """Reorder clauses so the rewrite passes the structural-change gate.

    Prefixing or suffixing is not a structural change -- the local gate looks for
    a sentence-count change, an inversion of unique anchor tokens, or a
    substantially different token sequence. Reversing sentence or clause order
    produces a genuine inversion.
    """

    sentences = [part.strip() for part in text.split(". ") if part.strip()]
    if len(sentences) >= 2:
        ordered = list(reversed(sentences))
        return ". ".join(part.rstrip(".") for part in ordered) + "."
    clauses = [part.strip() for part in text.rstrip(".").split(", ") if part.strip()]
    if len(clauses) >= 2:
        ordered = [clauses[-1], *clauses[:-1]]
        return ", ".join(ordered) + "."
    return f"What we settled on: {text.rstrip('.')}."


class PipelineHarness:
    def __init__(self, raw=RAW, **config_overrides):
        self.root = Path(tempfile.mkdtemp())
        source = self.root / "project" / "P1"
        source.mkdir(parents=True)
        (source / "chat_messages.json").write_text(json.dumps(raw), encoding="utf-8")
        (source / "job.txt").write_text("job description", encoding="utf-8")
        self.project = ProjectFiles("P1", source, source / "chat_messages.json")
        options = dict(
            output_root=self.root / "out",
            work_root=self.root / "runs",
            model="m",
            reasoning_effort="high",
            keep_run_artifacts=True,
        )
        options.update(config_overrides)
        self.config = PiiConfig(**options)

    @property
    def run_dir(self) -> Path:
        return self.root / "runs" / "P1"

    @property
    def committed(self) -> Path:
        return self.root / "out" / "P1" / "chat_messages.json"

    def run(self, api: FakeApi, prompts: PromptSet | None = None, **config_overrides):
        config = self.config
        if config_overrides:
            from dataclasses import replace

            config = replace(config, **config_overrides)
        pipeline = PiiPipeline(
            api, config, prompts or prompt_set(), run_root=self.root / "runs"
        )
        return asyncio.run(pipeline.run(self.project))

    def output_rows(self):
        return json.loads(self.committed.read_text(encoding="utf-8"))


class HappyPathTests(unittest.TestCase):
    def test_full_run_commits_natural_synthetic_content(self):
        harness = PipelineHarness()
        result = harness.run(FakeApi())
        self.assertEqual(result["status"], "DONE")
        rows = harness.output_rows()
        joined = " ".join(row["message"] for row in rows)

        # The plan was applied.
        self.assertIn("Marcus Feld", joined)
        self.assertIn("marcus.f@ledgerline-demo.example", joined)
        self.assertIn("7 winners", joined)
        self.assertIn("$12,500", joined)
        # Originals are gone.
        self.assertNotIn("Joseph", joined)
        self.assertNotIn("scott@northstar.io", joined)
        self.assertNotIn("5 winners", joined)
        self.assertNotIn("$10,000", joined)
        # Public third parties and requirement terms survive.
        self.assertIn("Stripe", joined)
        self.assertIn("OAuth", joined)
        # No pipeline-internal representation leaks.
        self.assertNotIn("[PERSON", joined)
        self.assertNotIn("<SECRET_CANDIDATE", joined)
        # Dropped fields and copied files.
        for row in rows:
            self.assertNotIn("sender_id", row)
            self.assertNotIn("created_ts", row)
            self.assertIn("message_user_type", row)
        self.assertTrue((harness.root / "out" / "P1" / "job.txt").is_file())

    def test_short_message_with_no_pii_is_preserved_verbatim(self):
        harness = PipelineHarness()
        harness.run(FakeApi())
        self.assertEqual(harness.output_rows()[1]["message"], "ok")

    def test_manifest_records_provenance_and_prompts(self):
        harness = PipelineHarness()
        manifest = harness.run(FakeApi())
        self.assertEqual(manifest["counts"]["provenance"]["PRESERVED_VERIFIED"], 1)
        self.assertEqual(manifest["counts"]["provenance"]["LLM_REWRITE"], 2)
        self.assertIn("PHASE_3B_LONG", manifest["prompts"])


class ResumeTests(unittest.TestCase):
    def test_rerun_with_no_changes_makes_no_api_calls(self):
        harness = PipelineHarness()
        harness.run(FakeApi())
        second = FakeApi()
        result = harness.run(second, overwrite=True)
        self.assertEqual(result["status"], "DONE")
        self.assertEqual(second.calls, [], "resume should reuse every checkpoint")

    def test_editing_the_long_rewrite_prompt_spares_upstream_phases(self):
        harness = PipelineHarness()
        harness.run(FakeApi())
        second = FakeApi()
        harness.run(
            second,
            prompts=prompt_set({"PHASE_3B_LONG": "sha-CHANGED"}),
            overwrite=True,
        )
        modes = set(second.calls)
        # Discovery, semantics, consolidation and the plan are untouched: none of
        # them is downstream of the rewrite prompt.
        self.assertNotIn("PII7_PII_DISCOVERY", modes)
        self.assertNotIn("PII7_MESSAGE_SEMANTICS", modes)
        self.assertNotIn("PII7_PROJECT_CONSOLIDATION", modes)
        self.assertNotIn("PII7_TRANSFORMATION_PLAN", modes)
        # The rewrite itself is redone.
        self.assertIn("PII7_REWRITE", modes)
        # Verification is *not* redone, because the new prompt happened to produce
        # byte-identical text. Downstream hashes chain on upstream *output*, so a
        # rerun that changes nothing costs nothing.
        self.assertNotIn("PII7_VERIFICATION", modes)

    def test_changed_rewrite_text_forces_reverification(self):
        """The companion property: different output does invalidate downstream."""

        harness = PipelineHarness()
        harness.run(FakeApi())
        second = FakeApi()
        second.rewrite_suffix = " Noted."
        harness.run(
            second,
            prompts=prompt_set({"PHASE_3B_LONG": "sha-CHANGED"}),
            overwrite=True,
        )
        modes = set(second.calls)
        self.assertIn("PII7_REWRITE", modes)
        self.assertIn("PII7_VERIFICATION", modes)

    def test_forcing_discovery_spares_semantics(self):
        """0B is not upstream of 1A, so forcing it must not invalidate 1A."""

        harness = PipelineHarness()
        harness.run(FakeApi())
        second = FakeApi()
        harness.run(second, overwrite=True, force_phases=frozenset({PHASE_0B}))
        modes = set(second.calls)
        self.assertIn("PII7_PII_DISCOVERY", modes)
        self.assertNotIn("PII7_MESSAGE_SEMANTICS", modes)

    def test_forcing_semantics_invalidates_the_plan(self):
        harness = PipelineHarness()
        harness.run(FakeApi())
        second = FakeApi()
        harness.run(second, overwrite=True, force_phases=frozenset({PHASE_1A}))
        modes = set(second.calls)
        self.assertIn("PII7_MESSAGE_SEMANTICS", modes)
        self.assertIn("PII7_PROJECT_CONSOLIDATION", modes)
        self.assertIn("PII7_TRANSFORMATION_PLAN", modes)

    def test_changed_source_refuses_to_resume(self):
        harness = PipelineHarness()
        harness.run(FakeApi())
        mutated = json.loads(json.dumps(RAW))
        mutated[2]["message"] = mutated[2]["message"].replace("Friday", "Monday")
        harness.project.chat_path.write_text(json.dumps(mutated), encoding="utf-8")
        with self.assertRaises(PiiError) as caught:
            harness.run(FakeApi(), overwrite=True)
        self.assertIn("changed", str(caught.exception))


class FailurePolicyTests(unittest.TestCase):
    def test_one_run_enumerates_every_failing_message(self):
        harness = PipelineHarness()
        api = FakeApi(fail_rewrite_ordinals={1, 3})
        result = harness.run(api)
        self.assertEqual(result["status"], STATUS_AWAITING_AGENT_REPAIR)
        ledger = UnresolvedLedger(run_dir=harness.run_dir, project_id="P1")
        ledger.load_existing()
        self.assertEqual(
            sorted(entry.ordinal for entry in ledger.entries()),
            [1, 3],
            "both failures must be found in a single run",
        )

    def test_unresolved_message_blocks_commit(self):
        harness = PipelineHarness()
        harness.run(FakeApi(fail_rewrite_ordinals={3}))
        self.assertFalse(
            harness.committed.is_file(),
            "no output may be committed while a message is unresolved",
        )

    def test_quarantined_message_has_no_text_rather_than_the_original(self):
        """The central guarantee: skipping never degrades into reusing the source."""

        harness = PipelineHarness()
        harness.run(FakeApi(fail_rewrite_ordinals={3}))
        texts = harness.run_dir / "phase6_render" / "final_texts.json"
        self.assertFalse(texts.is_file(), "phase 6 must not have produced any text")
        package = read_task_package(harness.run_dir)
        task = next(item for item in package["tasks"] if item["ordinal"] == 3)
        # The task carries the shielded original for the agent to work from, but
        # nothing was written into the dataset.
        self.assertIn("Joseph", task["safe_original_text"])
        self.assertFalse(harness.committed.is_file())

    def test_transport_failure_produces_no_agent_task(self):
        """An agent cannot repair a ConnectError, so it must not be queued one."""

        harness = PipelineHarness()
        result = harness.run(FakeApi(transport_fail_modes={"PII7_PII_DISCOVERY"}))
        self.assertEqual(result["status"], "BLOCKED_RETRYABLE")
        self.assertEqual(result["agent_tasks"], 0)
        self.assertIsNone(read_task_package(harness.run_dir))

    def test_verifier_failure_exhausts_repair_then_defers(self):
        harness = PipelineHarness()
        api = FakeApi(fail_verify_ordinals={1})
        result = harness.run(api)
        self.assertEqual(result["status"], STATUS_AWAITING_AGENT_REPAIR)
        self.assertEqual(api.calls.count("PII7_REPAIR"), 2, "two repair attempts")
        package = read_task_package(harness.run_dir)
        task = next(item for item in package["tasks"] if item["ordinal"] == 1)
        self.assertEqual(task["failure_code"], "REPAIR_EXHAUSTED")
        self.assertTrue(task["verifier_failures"], "findings must reach the agent")
        self.assertTrue(task["attempt_history"], "attempt history must reach the agent")

    def test_ledger_contains_no_raw_values(self):
        harness = PipelineHarness()
        harness.run(FakeApi(fail_rewrite_ordinals={1}))
        ledger_text = (harness.run_dir / "unresolved" / "ledger.jsonl").read_text(
            encoding="utf-8"
        )
        for secret in ("Joseph", "scott@northstar.io", "northstar.io"):
            self.assertNotIn(secret, ledger_text, f"{secret!r} leaked into the ledger")


class AgentRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = PipelineHarness()
        self.harness.run(FakeApi(fail_rewrite_ordinals={3}))
        self.package = read_task_package(self.harness.run_dir)
        self.task = next(
            item for item in self.package["tasks"] if item["ordinal"] == 3
        )
        self.submission_path = repairs_dir(self.harness.run_dir) / "repairs.json"

    def submission(self, **overrides):
        repair = {
            "task_id": self.task["task_id"],
            "kind": "TEXT",
            "ordinal": 3,
            "text": (
                "Before Friday we need this finished, Marcus Feld. Please confirm the "
                "OAuth scopes with Stripe."
            ),
            "safe_source_sha256": self.task["safe_source_sha256"],
            "plan_slice_sha256": self.task["plan_slice_sha256"],
            "author": "claude-code",
            "reason": "Fronted the deadline clause and applied the planned replacement.",
        }
        repair.update(overrides)
        return {
            "schema_version": "pii-agent-repairs-v1",
            "project_id": "P1",
            "queue_sha256": queue_sha256(self.package),
            "repairs": [repair],
            "blocked": [],
        }

    def write(self, payload) -> None:
        self.submission_path.parent.mkdir(parents=True, exist_ok=True)
        self.submission_path.write_text(json.dumps(payload), encoding="utf-8")

    def finalize(self, **kwargs):
        return finalize_project(
            self.harness.project,
            self.harness.config,
            run_root=self.harness.root / "runs",
            **kwargs,
        )

    def test_status_report_names_the_next_command(self):
        report = status_report(self.harness.project, self.harness.root / "runs")
        self.assertEqual(report["status"], STATUS_AWAITING_AGENT_REPAIR)
        self.assertEqual(report["agent_tasks"], 1)
        self.assertIn("pii_finalize", report["next_command"])

    def test_validate_only_writes_nothing(self):
        self.write(self.submission())
        result = self.finalize(validate_only=True)
        self.assertEqual(result["status"], "VALIDATED")
        self.assertFalse(self.harness.committed.is_file())

    def test_accepted_repair_commits_the_project(self):
        self.write(self.submission())
        manifest = self.finalize()
        self.assertEqual(manifest["status"], "DONE")
        self.assertEqual(manifest["repaired_by_agent"], [3])
        rows = self.harness.output_rows()
        self.assertIn("Marcus Feld", rows[2]["message"])
        self.assertNotIn("Joseph", rows[2]["message"])
        self.assertIn("Stripe", rows[2]["message"])
        metadata = json.loads(
            (self.harness.run_dir / "run_metadata.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["status"], STATUS_PASSED)

    def test_stale_source_hash_is_rejected(self):
        self.write(self.submission(safe_source_sha256="0" * 64))
        with self.assertRaises(PiiValidationError):
            self.finalize(validate_only=True)

    def test_stale_plan_slice_hash_is_rejected(self):
        self.write(self.submission(plan_slice_sha256="0" * 64))
        with self.assertRaises(PiiValidationError):
            self.finalize(validate_only=True)

    def test_surviving_original_is_rejected(self):
        self.write(self.submission(
            text="Before Friday we need this finished, Joseph. Please confirm the "
                 "OAuth scopes with Stripe."
        ))
        with self.assertRaises(PiiValidationError):
            self.finalize(validate_only=True)

    def test_lost_preserved_public_name_is_rejected(self):
        self.write(self.submission(
            text="Before Friday we need this finished, Marcus Feld. Please confirm the "
                 "OAuth scopes with Acme."
        ))
        with self.assertRaises(PiiValidationError):
            self.finalize(validate_only=True)

    def test_reason_quoting_an_original_is_rejected(self):
        self.write(self.submission(reason="Replaced Joseph with Marcus Feld."))
        with self.assertRaises(PiiValidationError):
            self.finalize(validate_only=True)

    def test_placeholder_in_repair_is_rejected(self):
        self.write(self.submission(
            text="Before Friday we need this finished, [PERSON_001]. Please confirm the "
                 "OAuth scopes with Stripe."
        ))
        with self.assertRaises(PiiValidationError):
            self.finalize(validate_only=True)

    def test_unknown_key_is_rejected(self):
        payload = self.submission()
        payload["repairs"][0]["saf_source_sha256"] = "typo"
        self.write(payload)
        with self.assertRaises(PiiError):
            self.finalize(validate_only=True)

    def test_missing_reason_is_rejected(self):
        payload = self.submission()
        payload["repairs"][0]["reason"] = "   "
        self.write(payload)
        with self.assertRaises(PiiError):
            self.finalize(validate_only=True)

    def test_uncovered_task_blocks_commit(self):
        payload = self.submission()
        payload["repairs"] = []
        self.write(payload)
        with self.assertRaises(PiiValidationError):
            self.finalize(validate_only=True)
        self.assertFalse(self.harness.committed.is_file())

    def test_second_finalize_is_idempotent(self):
        self.write(self.submission())
        first = self.finalize()
        second = self.finalize()
        self.assertEqual(
            first["output_sha256"], second["output_sha256"],
            "re-finalizing must be byte-identical",
        )


if __name__ == "__main__":
    unittest.main()
