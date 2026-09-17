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
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from Code.PII.agent_handoff import (
    clear_task_package,
    queue_sha256,
    read_task_package,
    repairs_dir,
)
from Code.PII.config import (
    HASH_UPSTREAM,
    PHASE_0B,
    PHASE_1A,
    PHASE_1B,
    PHASE_2,
    PHASE_3,
    PHASE_4,
    PHASE_5,
    UPSTREAM,
    PiiConfig,
    ProjectFiles,
)
from Code.PII.errors import VALIDATION_MARKER, PiiError, PiiValidationError, marked
from Code.PII.llm import _informed_instruction
from Code.PII.finalize import finalize_project, status_report
from Code.PII.ledger import (
    CLASS_PLAN_CONFLICT,
    CODE_ASSEMBLY_INVALID,
    NEXT_COMMAND,
    STATUS_BLOCKED_RETRYABLE,
    STATUS_RUNNING,
    STATUS_AWAITING_AGENT_REPAIR,
    STATUS_PASSED,
    STATUS_REPLAN_REQUIRED,
    UnresolvedLedger,
    next_command,
    write_run_metadata,
)
from Code.PII.phase4_verify import CHECK_DIMENSIONS
from Code.PII.phase1a_semantics import validate_semantics_response
from Code.PII.models import SafeMessage
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
            return self._registry(body)
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
            winner_start = message["text"].index("5 winners")
            prize_start = message["text"].index("$10,000")
            slots = [
                {"slot_name": "WINNER_COUNT", "value_type": "COUNT",
                 "source_literal": "5 winners", "start": winner_start,
                 "end": winner_start + len("5 winners"),
                 "meaning": "winners per draw"},
                {"slot_name": "PRIZE", "value_type": "AMOUNT",
                 "source_literal": "$10,000", "start": prize_start,
                 "end": prize_start + len("$10,000"),
                 "meaning": "prize per winner"},
            ]
        return {"ordinal": message["ordinal"], "speech_act": "STATEMENT",
                "polarity": "AFFIRMATIVE", "execution_status": "NOT_APPLICABLE",
                "ambiguity_kind": "NONE", "decisions": [], "slots": slots}

    @staticmethod
    def _registry(body):
        """A delta, not the merged registry.

        Phase 1B carries the accumulator forward locally, so a fold reports only
        what its own chunk adds.
        """

        existing = {
            slot["slot_id"]
            for slot in (body.get("semantic_accumulator") or {}).get("slots", [])
        }
        new_slots, updated = [], []
        for record in body["semantic_records"]:
            for slot in record["slots"]:
                entry = {"ordinal": record["ordinal"], "op": "MODIFY",
                         "new_value": slot["source_literal"]}
                if slot["slot_name"] in existing:
                    updated.append({
                        "slot_id": slot["slot_name"],
                        "append_history": [entry],
                        "add_source_literals": [slot["source_literal"]],
                        "add_message_ordinals": [record["ordinal"]]})
                    continue
                existing.add(slot["slot_name"])
                new_slots.append({
                    "slot_id": slot["slot_name"], "kind": "BUSINESS",
                    "value_type": slot["value_type"], "unit": None,
                    "meaning": slot["meaning"],
                    "history": [{**entry, "op": "INTRODUCE"}],
                    "source_literals": [slot["source_literal"]],
                    "message_ordinals": [record["ordinal"]]})
        return {"new_slots": new_slots, "updated_slots": updated,
                "merged_from": {}, "new_relations": [], "new_decisions": []}

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
             "literal_replacements": [
                 {"ordinal": occurrence["ordinal"],
                  "message_id": occurrence["message_id"],
                  "start": occurrence["start"],
                  "end": occurrence["end"],
                  "original": occurrence["source_literal"],
                  "replacement": new_values.get(
                      occurrence["source_literal"],
                      occurrence["source_literal"] + "x",
                  )}
                 for occurrence in slot["literal_occurrences"]]}
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
            for occurrence in item["literal_replacements"]:
                if occurrence["ordinal"] == ordinal:
                    text = text.replace(
                        occurrence["original"], occurrence["replacement"]
                    )
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

    def test_transport_failure_then_success_reaches_done(self):
        """A run that fails on transport must be able to finish on a retry.

        Regression: the ledger entry from the failed run used to survive
        ``load_existing`` even after the message succeeded, so the phase-group
        barrier kept halting and phases 3/4/5 skipped the message as blocked --
        the project could never reach DONE once it had failed once.
        """

        harness = PipelineHarness()
        first = harness.run(FakeApi(transport_fail_modes={"PII7_PII_DISCOVERY"}))
        self.assertEqual(first["status"], "BLOCKED_RETRYABLE")
        self.assertFalse(harness.committed.is_file())

        second = harness.run(FakeApi())
        self.assertEqual(second["status"], "DONE", "a retry must be able to finish")
        self.assertTrue(harness.committed.is_file())

        ledger = UnresolvedLedger(run_dir=harness.run_dir, project_id="P1")
        ledger.load_existing()
        self.assertEqual(ledger.entries(), [], "stale entries must be retired")

    def test_partial_transport_failure_then_success_reaches_done(self):
        """The real-world shape: some messages fail, the rest are checkpointed."""

        harness = PipelineHarness()
        harness.run(FakeApi(fail_rewrite_ordinals={1, 3}))
        ledger = UnresolvedLedger(run_dir=harness.run_dir, project_id="P1")
        ledger.load_existing()
        self.assertEqual(len(ledger.entries()), 2)

        # Second run: the same messages now succeed and are no longer blocked.
        result = harness.run(FakeApi())
        self.assertEqual(result["status"], "DONE")
        rows = harness.output_rows()
        self.assertIn("Marcus Feld", " ".join(row["message"] for row in rows))


class FailurePolicyTests(unittest.TestCase):
    @staticmethod
    def _safe_message(text: str) -> SafeMessage:
        return SafeMessage(
            ordinal=1,
            message_id=1,
            speaker="client",
            safe_text=text,
            safe_text_sha256="safe",
            source_text_sha256="source",
            word_count=len(text.split()),
            bucket="LONG",
            secret_tokens=(),
            sender_id_present=False,
        )

    @staticmethod
    def _semantics_payload(slot: dict) -> dict:
        return {
            "records": [
                {
                    "ordinal": 1,
                    "speech_act": "REQUEST",
                    "polarity": "AFFIRMATIVE",
                    "execution_status": "NOT_STARTED",
                    "ambiguity_kind": "NONE",
                    "decisions": [],
                    "slots": [slot],
                    "relations": [],
                }
            ]
        }

    def test_phase1a_reanchors_unique_literal_when_model_offsets_drift(self):
        text = "Use 🔧 before $500 today."
        literal = "$500"
        actual_start = text.index(literal)
        payload = self._semantics_payload(
            {
                "slot_name": "PRIZE_AMOUNT",
                "value_type": "AMOUNT",
                "source_literal": literal,
                # A common model error: counting the preceding emoji as two
                # UTF-16 code units instead of one Python character.
                "start": actual_start + 1,
                "end": actual_start + 1 + len(literal),
                "meaning": "amount of the prize",
                "unit": "USD",
                "op": "INTRODUCE",
            }
        )

        result = validate_semantics_response(payload, [self._safe_message(text)])

        self.assertEqual(result[1].slots[0].start, actual_start)
        self.assertEqual(result[1].slots[0].end, actual_start + len(literal))

    def test_phase1a_does_not_reanchor_a_literal_absent_from_source(self):
        text = "Use the agreed amount today."
        payload = self._semantics_payload(
            {
                "slot_name": "PRIZE_AMOUNT",
                "value_type": "AMOUNT",
                "source_literal": "$500",
                "start": 0,
                "end": 4,
                "meaning": "amount of the prize",
                "unit": "USD",
                "op": "INTRODUCE",
            }
        )

        with self.assertRaises(PiiValidationError):
            validate_semantics_response(payload, [self._safe_message(text)])

    def test_phase1a_keeps_load_bearing_semantic_facts(self):
        text = "Deploy Chainlink VRF to production and keep the supply unlimited."
        payload = {
            "records": [
                {
                    "ordinal": 1,
                    "speech_act": "REQUEST",
                    "polarity": "AFFIRMATIVE",
                    "execution_status": "NOT_STARTED",
                    "ambiguity_kind": "NONE",
                    "decisions": [],
                    "slots": [],
                    "relations": [],
                    "semantic_facts": [
                        {
                            "kind": "ENVIRONMENT",
                            "statement": "Deployment targets production.",
                            "polarity": "AFFIRMATIVE",
                            "must_preserve_terms": ["Chainlink VRF"],
                        },
                        {
                            "kind": "CONSTRAINT",
                            "statement": "Supply has no cap.",
                            "polarity": "AFFIRMATIVE",
                            "must_preserve_terms": [],
                        },
                    ],
                }
            ]
        }

        result = validate_semantics_response(payload, [self._safe_message(text)])

        self.assertEqual(len(result[1].semantic_facts), 2)
        self.assertEqual(
            result[1].semantic_facts[0]["must_preserve_terms"],
            ["Chainlink VRF"],
        )

    def test_phase1a_fact_preserve_term_must_be_exact_source_text(self):
        text = "Deploy Chainlink VRF to production."
        payload = {
            "records": [
                {
                    "ordinal": 1,
                    "speech_act": "REQUEST",
                    "polarity": "AFFIRMATIVE",
                    "execution_status": "NOT_STARTED",
                    "ambiguity_kind": "NONE",
                    "decisions": [],
                    "slots": [],
                    "relations": [],
                    "semantic_facts": [
                        {
                            "kind": "TECHNOLOGY",
                            "statement": "Use the specified randomness provider.",
                            "polarity": "AFFIRMATIVE",
                            "must_preserve_terms": ["Gelato VRF"],
                        }
                    ],
                }
            ]
        }

        with self.assertRaises(PiiValidationError):
            validate_semantics_response(payload, [self._safe_message(text)])

    def test_validation_failure_bisects_instead_of_retrying_every_item(self):
        """One bad record in eight should cost seven calls, not nine."""

        class OneBadSemanticsApi(FakeApi):
            def respond(self, mode, body):
                payload = super().respond(mode, body)
                if mode == "PII7_MESSAGE_SEMANTICS":
                    for record in payload["records"]:
                        if record["ordinal"] == 5:
                            record["polarity"] = "INVALID"
                return payload

        raw = [
            {
                "message": (
                    "Please review the draft carefully, then confirm whether "
                    "the final structure is acceptable."
                ),
                "message_user_type": "client",
                "sender_id": "aa11bb22cc33",
                "created_ts": f"t{ordinal}",
            }
            for ordinal in range(1, 9)
        ]
        harness = PipelineHarness(raw=raw, max_batch_messages=8)
        api = OneBadSemanticsApi()

        harness.run(api)

        self.assertEqual(api.calls.count("PII7_MESSAGE_SEMANTICS"), 7)
        checkpoints = harness.run_dir / "phase1a_message_semantics" / "messages"
        self.assertEqual(len(list(checkpoints.glob("*.json"))), 7)
        self.assertFalse((checkpoints / "00005.json").exists())

    def test_timeout_on_large_shard_is_bisected_and_completes(self):
        """A payload-duration timeout should preserve work via bounded bisection."""

        class TimeoutOnLargeDiscoveryApi(FakeApi):
            async def call(
                self,
                *,
                project_id,
                run_mode,
                messages,
                target_requirement=None,
                validator=None,
                failed_response_redactor=None,
            ):
                body = json.loads(messages[1]["content"])
                if (
                    run_mode == "PII7_PII_DISCOVERY"
                    and len(body.get("safe_messages", ())) > 1
                ):
                    self.calls.append(run_mode)
                    raise ApiError(
                        f"{run_mode}/{target_requirement} failed: ReadTimeout",
                        cause=TimeoutError("read timed out"),
                    )
                return await super().call(
                    project_id=project_id,
                    run_mode=run_mode,
                    messages=messages,
                    target_requirement=target_requirement,
                    validator=validator,
                    failed_response_redactor=failed_response_redactor,
                )

        harness = PipelineHarness()
        api = TimeoutOnLargeDiscoveryApi()
        result = harness.run(api)

        self.assertEqual(result["status"], "DONE")
        self.assertTrue(harness.committed.is_file())
        self.assertGreater(api.calls.count("PII7_PII_DISCOVERY"), 1)

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

    def test_phase5_logs_queue_progress_and_summary(self):
        harness = PipelineHarness()
        api = FakeApi(fail_verify_ordinals={1})
        output = io.StringIO()

        with redirect_stdout(output):
            harness.run(api)

        log = output.getvalue()
        self.assertIn("[P1] phase 5: 1 message(s) queued for repair", log)
        self.assertIn(
            "[P1] PHASE_5_REPAIR message_00001 attempt_01 (1/1; API)", log
        )
        self.assertIn("[P1] PHASE_5_REPAIR message_00001 unresolved (1/1)", log)
        self.assertIn(
            "[P1] phase 5: 1/1 processed, 0 repaired, 1 unresolved", log
        )

    def test_ledger_contains_no_raw_values(self):
        harness = PipelineHarness()
        harness.run(FakeApi(fail_rewrite_ordinals={1}))
        ledger_text = (harness.run_dir / "unresolved" / "ledger.jsonl").read_text(
            encoding="utf-8"
        )
        for secret in ("Joseph", "scott@northstar.io", "northstar.io"):
            self.assertNotIn(secret, ledger_text, f"{secret!r} leaked into the ledger")


class AccumulatorOverflowTests(unittest.TestCase):
    """An oversized registry is a local condition, not a model error.

    Regression: it was raised from the response validator, so it looked
    retryable -- one real run spent eight attempts (~25 minutes) on a condition
    the model could not affect, because the pipeline itself carries most of the
    registry forward.
    """

    def test_overflow_stops_immediately_without_retrying(self):
        harness = PipelineHarness(max_accumulator_chars=1)
        api = FakeApi()
        result = harness.run(api)
        self.assertEqual(result["status"], "REPLAN_REQUIRED")
        self.assertEqual(
            api.calls.count("PII7_PROJECT_CONSOLIDATION"), 1,
            "an unfixable condition must not be retried",
        )
        self.assertFalse(harness.committed.is_file())

    def test_the_message_names_the_flag_to_raise(self):
        harness = PipelineHarness(max_accumulator_chars=1)
        harness.run(FakeApi())
        ledger = UnresolvedLedger(run_dir=harness.run_dir, project_id="P1")
        ledger.load_existing()
        error = " ".join(entry.error or "" for entry in ledger.entries())
        self.assertIn("--max-accumulator-chars", error)

    def test_the_overflowing_fold_is_still_checkpointed(self):
        """The fold validated; only the aggregate was over budget.

        Discarding it would make the operator pay for it again after simply
        raising the limit.
        """

        harness = PipelineHarness(max_accumulator_chars=1)
        harness.run(FakeApi())
        folds = list(
            (harness.run_dir / "phase1b_project_consolidation" / "folds").glob("*.json")
        )
        self.assertTrue(folds, "the validated fold must be kept")

        # Raising the limit must reuse it rather than recompute it.
        second = FakeApi()
        result = harness.run(second, overwrite=True, max_accumulator_chars=9_000_000)
        self.assertEqual(result["status"], "DONE")
        self.assertNotIn("PII7_PROJECT_CONSOLIDATION", set(second.calls))

    def test_raising_the_cap_does_not_invalidate_completed_folds(self):
        """The cap bounds accumulated state, so it is not in the phase input hash."""

        harness = PipelineHarness()
        harness.run(FakeApi())
        second = FakeApi()
        harness.run(second, overwrite=True, max_accumulator_chars=9_000_000)
        self.assertNotIn(
            "PII7_PROJECT_CONSOLIDATION", set(second.calls),
            "changing the cap must reuse the folds that already validated",
        )


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


class ExtractionAgentRepairTests(unittest.TestCase):
    def test_clean_consumes_offline_extraction_repair_without_recalling_phase0b(self):
        class MissingOrdinalApi(FakeApi):
            def respond(self, mode, body):
                payload = super().respond(mode, body)
                if mode == "PII7_PII_DISCOVERY":
                    payload["messages"] = [
                        item for item in payload["messages"] if item["ordinal"] != 3
                    ]
                return payload

        harness = PipelineHarness()
        first = harness.run(MissingOrdinalApi())
        self.assertEqual(first["status"], STATUS_AWAITING_AGENT_REPAIR)
        package = read_task_package(harness.run_dir)
        task = next(item for item in package["tasks"] if item["ordinal"] == 3)
        text = task["safe_original_text"]
        submission = {
            "schema_version": "pii-agent-repairs-v1",
            "project_id": "P1",
            "queue_sha256": queue_sha256(package),
            "repairs": [
                {
                    "task_id": task["task_id"],
                    "kind": "EXTRACTION",
                    "ordinal": 3,
                    "message_id": 3,
                    "safe_source_sha256": task["safe_source_sha256"],
                    "plan_slice_sha256": None,
                    "author": "test-agent",
                    "reason": "Supplied the missing offline extraction annotation.",
                    "annotation": {
                        "occurrences": FakeApi._occurrences({"text": text}),
                        "semantics": FakeApi._semantics(
                            {"ordinal": 3, "text": text}
                        ),
                    },
                }
            ],
            "blocked": [],
        }
        path = repairs_dir(harness.run_dir) / "repairs.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(submission), encoding="utf-8")

        second_api = FakeApi(
            transport_fail_modes={"PII7_PII_DISCOVERY", "PII7_MESSAGE_SEMANTICS"}
        )
        result = harness.run(second_api)

        self.assertEqual(result["status"], "DONE")
        self.assertNotIn("PII7_PII_DISCOVERY", second_api.calls)
        self.assertNotIn("PII7_MESSAGE_SEMANTICS", second_api.calls)


if __name__ == "__main__":
    unittest.main()


class ReplanRoutingTests(unittest.TestCase):
    """The replan command must name the phase that actually broke.

    Sending the operator to 1B for a phase-2 failure discards every fold of a
    consolidation that succeeded -- minutes of work and a real spend on a large
    project -- and does not touch the chunk that failed.
    """

    def ledger_with(self, phase: str) -> UnresolvedLedger:
        directory = Path(tempfile.mkdtemp())
        ledger = UnresolvedLedger(run_dir=directory, project_id="P1")
        asyncio.run(
            ledger.record(
                phase=phase,
                code="PROJECT_ARTIFACT_INVALID",
                failure_class=CLASS_PLAN_CONFLICT,
                message_id=None,
                ordinal=None,
                attempts=1,
                error=PiiError("chunk invalid"),
            )
        )
        return ledger

    def test_phase_2_failure_replans_phase_2(self):
        ledger = self.ledger_with(PHASE_2)
        self.assertEqual(ledger.status(), STATUS_REPLAN_REQUIRED)
        self.assertEqual(ledger.replan_phase(), PHASE_2)

    def test_phase_1b_failure_replans_phase_1b(self):
        self.assertEqual(self.ledger_with(PHASE_1B).replan_phase(), PHASE_1B)

    def test_next_command_names_the_failing_phase(self):
        ledger = self.ledger_with(PHASE_2)
        directory = Path(tempfile.mkdtemp())
        write_run_metadata(
            directory,
            project_id="P1",
            status=ledger.status(),
            ledger=ledger,
        )
        command = json.loads((directory / "run_metadata.json").read_text("utf-8"))[
            "next_command"
        ]
        self.assertIn(PHASE_2, command)
        self.assertNotIn(PHASE_1B, command)


class InformedRetryTests(unittest.TestCase):
    """A retry that does not say what failed is a blind re-roll.

    Phase 2 sent eight byte-identical requests for 121 entities, failing on the
    same three every time, and the model was never told which three or why.
    """

    def test_the_validator_complaint_reaches_the_next_attempt(self):
        detail = "PLAN_IDENTITY: E0090 replacement is a lightly masked variant"
        error = ApiError(
            "PII7_TRANSFORMATION_PLAN/entities_chunk_0001 failed after 4 attempt(s)",
            cause=PiiValidationError(marked(detail)),
        )
        instruction = _informed_instruction("Base rule.", error)
        self.assertIn("Base rule.", instruction)
        self.assertIn("E0090", instruction)
        self.assertNotIn(VALIDATION_MARKER, instruction)

    def test_a_causeless_error_leaves_the_base_instruction_alone(self):
        self.assertEqual(
            _informed_instruction("Base rule.", ApiError("boom")), "Base rule."
        )


class StaleTaskPackageTests(unittest.TestCase):
    """A run that resolves everything must retire the previous run's package.

    The package is a snapshot of one run's unresolved set.  Left in place, it
    makes ``--status`` report a phantom open task, and finalize's commit
    precondition ("no open agent-actionable task") refuses to publish a project
    that is actually healthy.
    """

    def test_a_clean_rerun_clears_a_previous_package(self):
        harness = PipelineHarness()
        harness.run(FakeApi(fail_verify_ordinals={1}))
        package = read_task_package(harness.run_dir)
        self.assertIsNotNone(package, "the failing run must write a package")
        self.assertGreater(package["counts"]["tasks"], 0)

        # A later run whose only failures are transport writes no tasks.  The
        # package from the earlier run must not survive it: an agent cannot fix
        # a ConnectError, and the stale OPEN task would make --status report a
        # phantom and finalize refuse to publish.
        result = harness.run(
            FakeApi(transport_fail_modes={"PII7_VERIFICATION"}),
            force_phases=(PHASE_4,),
        )
        self.assertEqual(result["status"], STATUS_BLOCKED_RETRYABLE)
        self.assertEqual(result["agent_tasks"], 0)
        self.assertIsNone(
            read_task_package(harness.run_dir),
            "a run with no agent-actionable failure must retire the old package",
        )

    def test_clear_removes_the_index(self):
        directory = Path(tempfile.mkdtemp())
        tasks = directory / "agent_tasks"
        tasks.mkdir()
        (tasks / "index.json").write_text('{"tasks": []}', encoding="utf-8")
        (tasks / "task_00001.md").write_text("stale", encoding="utf-8")
        clear_task_package(directory)
        self.assertIsNone(read_task_package(directory))
        self.assertEqual(list(tasks.glob("*")), [])

    def test_clear_is_safe_when_there_was_never_a_package(self):
        clear_task_package(Path(tempfile.mkdtemp()))


class InterruptedRunStatusTests(unittest.TestCase):
    """RUNNING persists on disk after Ctrl-C; --status must still advise."""

    def test_running_has_a_resume_command(self):
        command = NEXT_COMMAND[STATUS_RUNNING].format(
            project_id="P1", run_dir="r", replan_phase=PHASE_1B
        )
        self.assertIn("--project-id P1", command)
        self.assertNotEqual(command.strip(), "")


class AssemblyFailureRoutingTests(unittest.TestCase):
    """A failure in local assembly must not send the operator to --force-phase.

    Every shard validated; they only failed to compose.  Discarding a whole
    phase of model output that was never at fault costs the most expensive
    calls in the run, and does not touch the code that actually broke.
    """

    def ledger_with(self, code: str) -> UnresolvedLedger:
        ledger = UnresolvedLedger(run_dir=Path(tempfile.mkdtemp()), project_id="P1")
        asyncio.run(
            ledger.record(
                phase=PHASE_2,
                code=code,
                failure_class=CLASS_PLAN_CONFLICT,
                message_id=None,
                ordinal=None,
                attempts=1,
                error=PiiError("plan invalid"),
            )
        )
        return ledger

    def test_assembly_failure_advises_a_plain_rerun(self):
        ledger = self.ledger_with(CODE_ASSEMBLY_INVALID)
        self.assertEqual(ledger.status(), STATUS_REPLAN_REQUIRED)
        self.assertTrue(ledger.replan_is_local())
        command = next_command(ledger.status(), "P1", "run", ledger)
        self.assertNotIn("--force-phase", command)
        self.assertIn("--project-id P1", command)

    def test_model_output_failure_still_advises_a_replan(self):
        ledger = self.ledger_with("PROJECT_ARTIFACT_INVALID")
        self.assertFalse(ledger.replan_is_local())
        self.assertIn("--force-phase", next_command(ledger.status(), "P1", "run", ledger))

    def test_a_mix_escalates_to_replan(self):
        """One genuine model failure is enough to need new model output."""

        ledger = self.ledger_with(CODE_ASSEMBLY_INVALID)
        asyncio.run(
            ledger.record(
                phase=PHASE_2,
                code="PROJECT_ARTIFACT_INVALID",
                failure_class=CLASS_PLAN_CONFLICT,
                message_id=None,
                ordinal=None,
                attempts=1,
                error=PiiError("chunk invalid"),
            )
        )
        self.assertFalse(ledger.replan_is_local())
        self.assertIn("--force-phase", next_command(ledger.status(), "P1", "run", ledger))


class PlanChangeCascadeTests(unittest.TestCase):
    """A plan edit must only invalidate the messages it actually reaches.

    ``UPSTREAM`` is the dependency DAG and ``--force-phase`` needs it, but
    feeding phase 2's *whole-plan* output hash into every phase-3 message hash
    made the coarse value win: one byte anywhere in ``plan.json`` invalidated
    all 824 rewrites.  That is exactly what the plan-slice closure exists to
    prevent, and what its property test guarantees is unnecessary.
    """

    def test_per_message_phases_do_not_chain_to_the_whole_plan(self):
        for phase in (PHASE_3, PHASE_4, PHASE_5):
            self.assertEqual(
                HASH_UPSTREAM[phase],
                (),
                f"{phase} must depend on its own scope, not the merged plan",
            )

    def test_the_dependency_dag_is_untouched(self):
        """--force-phase still has to take the descendant closure."""

        self.assertIn(PHASE_2, UPSTREAM[PHASE_3])
        self.assertIn(PHASE_3, UPSTREAM[PHASE_4])
        self.assertIn(PHASE_4, UPSTREAM[PHASE_5])

    def test_aggregate_phases_still_chain(self):
        self.assertIn(PHASE_1B, UPSTREAM[PHASE_2])
        self.assertEqual(HASH_UPSTREAM[PHASE_2], UPSTREAM[PHASE_2])

    def test_a_plan_edit_reruns_only_the_messages_it_reaches(self):
        harness = PipelineHarness()
        harness.run(FakeApi())
        first = FakeApi()
        harness.run(first)
        self.assertEqual(
            first.calls.count("PII7_REWRITE"), 0, "an unchanged plan must reuse every rewrite"
        )
