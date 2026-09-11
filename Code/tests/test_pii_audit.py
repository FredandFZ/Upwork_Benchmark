"""Phase 6 tests: deterministic rendering and every hard-fail audit check.

The audit is the definition of "correct" for the whole pipeline, so each check
gets a targeted fixture that makes exactly it fire.  A check with no test here
is a check nobody can trust.
"""

from __future__ import annotations

import unittest

from Code.PII.config import (
    BUCKET_LONG,
    BUCKET_PRESERVE_SHORT,
    PRESERVED_BUCKETS,
)
from Code.PII.discovery import adapt_messages, build_cleaned_chat
from Code.PII.errors import AuditFailure, PiiError
from Code.PII.models import (
    EntityReplacement,
    IdentityBundle,
    MessageState,
    PROVENANCE_LLM_REWRITE,
    PROVENANCE_PRESERVED,
    PiiEntity,
    PiiEntityRegistry,
    PiiOccurrence,
    SecretPlanEntry,
    SemanticRegistry,
    SemanticSlot,
    SlotHistoryEntry,
    SlotReplacement,
    TransformationPlan,
)
from Code.PII.phase6_render import (
    AUDIT_CHECKS,
    CHECK_COVERAGE_INCOMPLETE,
    CHECK_INCONSISTENT_SLOT_VALUE,
    CHECK_INTERNAL_PLACEHOLDER_PRESENT,
    CHECK_ORIGINAL_EMAIL_PRESENT,
    CHECK_ORIGINAL_PERSON_PRESENT,
    CHECK_ORIGINAL_SECRET_PRESENT,
    CHECK_ORIGINAL_SENDER_ID_PRESENT,
    CHECK_PLAN_REPLACEMENT_COLLISION,
    CHECK_PRESERVED_ROW_DRIFTED,
    CHECK_PRESERVED_VALUE_LOST,
    CHECK_PROVENANCE_INVALID,
    CHECK_REQUIRED_CHANGE_NOT_APPLIED,
    CHECK_SECRET_TOKEN_MULTIPLICITY,
    CHECK_UNEXPECTED_CREDENTIAL_LIKE_VALUE,
    CHECK_UNRESOLVED_MESSAGE_PRESENT,
    AuditInputs,
    audit_final_texts,
    render_final_texts,
)
from Code.PII.secret_shield import render_credential, shield_project

RAW_CHAT = [
    {
        "message": "Hi Joseph, please send the deploy key to scott@northstar.io when you get a chance.",
        "message_user_type": "client",
        "sender_id": "aa11bb22cc33",
        "created_ts": "2026-01-02T03:04:05Z",
    },
    {
        "message": "ok",
        "message_user_type": "freelancer",
        "sender_id": "dd44ee55ff66",
        "created_ts": "2026-01-02T03:05:05Z",
    },
    {
        "message": "Password: Hunter2!xK9qz",
        "message_user_type": "client",
        "sender_id": "aa11bb22cc33",
        "created_ts": "2026-01-02T03:06:05Z",
    },
    {
        "message": "We agreed on 5 winners and the OAuth flow stays as specified.",
        "message_user_type": "client",
        "sender_id": "aa11bb22cc33",
        "created_ts": "2026-01-02T03:07:05Z",
    },
]

PROJECT_ID = "42204309"
PRESERVE_TERMS = ("OAuth",)


def entity_registry() -> PiiEntityRegistry:
    person = PiiEntity(
        entity_id="E0001",
        entity_type="PERSON",
        policy="SYNTHESIZE",
        canonical_value="Joseph",
        normalized_key="joseph",
        bundle_id="B0001",
        confidence="HIGH",
        occurrences=(
            PiiOccurrence(
                ordinal=1,
                message_id=1,
                source="Joseph",
                start=3,
                end=9,
                entity_type="PERSON",
                policy="SYNTHESIZE",
                normalized_value="joseph",
                link_hint=None,
                confidence="HIGH",
            ),
        ),
    )
    email = PiiEntity(
        entity_id="E0002",
        entity_type="EMAIL",
        policy="SYNTHESIZE",
        canonical_value="scott@northstar.io",
        normalized_key="scott@northstar.io",
        bundle_id="B0001",
        confidence="HIGH",
        occurrences=(
            PiiOccurrence(
                ordinal=1,
                message_id=1,
                source="scott@northstar.io",
                start=37,
                end=55,
                entity_type="EMAIL",
                policy="SYNTHESIZE",
                normalized_value="scott@northstar.io",
                link_hint="B0001",
                confidence="HIGH",
            ),
        ),
    )
    return PiiEntityRegistry(
        entities=(person, email),
        bundles=(
            IdentityBundle(
                bundle_id="B0001", kind="PERSON_IDENTITY", entity_ids=("E0001", "E0002")
            ),
        ),
    )


def semantic_registry() -> SemanticRegistry:
    return SemanticRegistry(
        slots=(
            SemanticSlot(
                slot_id="WINNER_COUNT",
                kind="BUSINESS",
                value_type="COUNT",
                unit=None,
                current_value="5",
                meaning="number of winners per draw",
                history=(
                    SlotHistoryEntry(ordinal=4, op="INTRODUCE", old_value=None, new_value="5"),
                ),
                source_literals=("5 winners",),
                message_ordinals=(4,),
            ),
        ),
        relations=(),
        decisions=(),
    )


def plan() -> TransformationPlan:
    return TransformationPlan(
        plan_version=1,
        entity_replacements=(
            EntityReplacement(
                entity_id="E0001",
                entity_type="PERSON",
                policy="SYNTHESIZE",
                original="Joseph",
                replacement="Marcus",
                bundle_id="B0001",
            ),
            EntityReplacement(
                entity_id="E0002",
                entity_type="EMAIL",
                policy="SYNTHESIZE",
                original="scott@northstar.io",
                replacement="marcus.f@northstar-demo.example",
                bundle_id="B0001",
                depends_on=("E0001",),
            ),
        ),
        slot_replacements=(
            SlotReplacement(
                slot_id="WINNER_COUNT",
                value_type="COUNT",
                history=(
                    SlotHistoryEntry(ordinal=4, op="INTRODUCE", old_value=None, new_value="7"),
                ),
                literal_map={"5 winners": "7 winners"},
            ),
        ),
        secret_replacements=(
            SecretPlanEntry(
                secret_id="S001",
                internal_token="<SECRET_CANDIDATE:S001>",
                kind="PASSWORD",
            ),
        ),
    )


class AuditFixture:
    """A fully clean project, plus helpers to break exactly one invariant."""

    def __init__(self) -> None:
        self.messages = adapt_messages(RAW_CHAT, PROJECT_ID)
        self.secret_registry, self.safe_messages = shield_project(
            PROJECT_ID,
            self.messages,
            preserve_short_max_words=2,
            short_message_max_words=4,
        )
        self.plan = plan()
        fake = render_credential(PROJECT_ID, "S001", "PASSWORD")
        self.final_texts = {
            1: "When you have a moment, Marcus, the deploy key should go to "
            "marcus.f@northstar-demo.example.",
            2: "ok",
            3: f"Password: {fake}",
            4: "The OAuth flow is unchanged, and 7 winners is what we settled on.",
        }
        self.states = {
            1: self._state(1, BUCKET_LONG, True, self.final_texts[1]),
            2: self._state(2, BUCKET_PRESERVE_SHORT, False, self.final_texts[2]),
            3: self._state(3, BUCKET_LONG, True, self.final_texts[3]),
            4: self._state(4, BUCKET_LONG, True, self.final_texts[4]),
        }

    @staticmethod
    def _state(ordinal: int, bucket: str, requires_change: bool, text: str) -> MessageState:
        state = MessageState(
            ordinal=ordinal,
            message_id=ordinal,
            bucket=bucket,
            requires_change=requires_change,
        )
        state.mark_done(
            text,
            provenance=PROVENANCE_LLM_REWRITE if requires_change else PROVENANCE_PRESERVED,
            text_sha256=f"sha-{ordinal}",
            verified=True,
        )
        return state

    def inputs(self, **overrides: object) -> AuditInputs:
        base = dict(
            project_id=PROJECT_ID,
            original_chat=RAW_CHAT,
            messages=self.messages,
            safe_messages=self.safe_messages,
            states=self.states,
            secret_registry=self.secret_registry,
            entity_registry=entity_registry(),
            semantic_registry=semantic_registry(),
            plan=self.plan,
            preserve_terms=PRESERVE_TERMS,
            sender_ids=("aa11bb22cc33", "dd44ee55ff66"),
        )
        base.update(overrides)
        return AuditInputs(**base)  # type: ignore[arg-type]

    def report(self, **overrides: object):
        texts = overrides.pop("final_texts", self.final_texts)
        cleaned = build_cleaned_chat(RAW_CHAT, texts)
        return audit_final_texts(self.inputs(**overrides), texts, cleaned)


class RenderingTests(unittest.TestCase):
    def test_credential_rendering_is_deterministic_and_project_scoped(self):
        first = render_credential("P1", "S001", "API_KEY")
        self.assertEqual(first, render_credential("P1", "S001", "API_KEY"))
        self.assertNotEqual(first, render_credential("P2", "S001", "API_KEY"))
        self.assertNotEqual(first, render_credential("P1", "S002", "API_KEY"))
        self.assertRegex(first, r"^FAKE_API_KEY_[0-9A-F]{12}$")

    def test_render_reads_only_accepted_text(self):
        fixture = AuditFixture()
        fixture.states[3].quarantine()
        with self.assertRaises(PiiError):
            render_final_texts(fixture.states, fixture.secret_registry)

    def test_render_substitutes_every_internal_token(self):
        fixture = AuditFixture()
        state = fixture.states[3]
        state.mark_done(
            "Password: <SECRET_CANDIDATE:S001>",
            provenance=PROVENANCE_LLM_REWRITE,
            text_sha256="sha-3",
            verified=True,
        )
        rendered = render_final_texts(fixture.states, fixture.secret_registry)
        self.assertNotIn("<SECRET_CANDIDATE:", rendered[3])
        self.assertIn(render_credential(PROJECT_ID, "S001", "PASSWORD"), rendered[3])


class CleanProjectTests(unittest.TestCase):
    def test_clean_project_passes_every_check(self):
        report = AuditFixture().report()
        self.assertTrue(report.ok, report.to_json()["violations"])
        self.assertEqual(report.message_count, 4)
        self.assertEqual(report.checks_run, AUDIT_CHECKS)

    def test_cleaned_chat_drops_sender_id_and_created_ts(self):
        fixture = AuditFixture()
        cleaned = build_cleaned_chat(RAW_CHAT, fixture.final_texts)
        for row in cleaned:
            self.assertNotIn("sender_id", row)
            self.assertNotIn("created_ts", row)
            self.assertIn("message_user_type", row)


class ViolationTests(unittest.TestCase):
    """Each test breaks one invariant and asserts the matching check fires."""

    def assert_fires(self, report, check: str) -> None:
        fired = {violation.check for violation in report.violations}
        self.assertIn(check, fired, f"expected {check}, got {sorted(fired)}")

    def test_unresolved_message_blocks_commit(self):
        report = AuditFixture().report(unresolved_message_ids=(3,))
        self.assert_fires(report, CHECK_UNRESOLVED_MESSAGE_PRESENT)

    def test_quarantined_message_cannot_reach_output(self):
        fixture = AuditFixture()
        fixture.states[3].quarantine()
        report = fixture.report()
        self.assert_fires(report, CHECK_PROVENANCE_INVALID)

    def test_original_text_reused_is_detected(self):
        fixture = AuditFixture()
        texts = dict(fixture.final_texts)
        texts[4] = RAW_CHAT[3]["message"]
        report = fixture.report(final_texts=texts)
        self.assert_fires(report, CHECK_REQUIRED_CHANGE_NOT_APPLIED)

    def test_preserved_row_must_not_drift(self):
        fixture = AuditFixture()
        texts = dict(fixture.final_texts)
        texts[2] = "sure"
        report = fixture.report(final_texts=texts)
        self.assert_fires(report, CHECK_PRESERVED_ROW_DRIFTED)

    def test_surviving_person_name_is_detected(self):
        fixture = AuditFixture()
        texts = dict(fixture.final_texts)
        texts[1] = "Joseph should receive the deploy key at marcus.f@northstar-demo.example."
        report = fixture.report(final_texts=texts)
        self.assert_fires(report, CHECK_ORIGINAL_PERSON_PRESENT)

    def test_non_reserved_email_domain_is_detected(self):
        fixture = AuditFixture()
        texts = dict(fixture.final_texts)
        texts[1] = "Send it to marcus.f@realcompany.com when you can, Marcus."
        report = fixture.report(final_texts=texts)
        self.assert_fires(report, CHECK_ORIGINAL_EMAIL_PRESENT)

    def test_reserved_synthetic_email_is_allowed(self):
        """The v6 rule banned all addresses; v7 must permit synthetic ones."""

        report = AuditFixture().report()
        fired = {violation.check for violation in report.violations}
        self.assertNotIn(CHECK_ORIGINAL_EMAIL_PRESENT, fired)

    def test_internal_token_surviving_is_detected(self):
        fixture = AuditFixture()
        texts = dict(fixture.final_texts)
        texts[3] = "Password: <SECRET_CANDIDATE:S001>"
        report = fixture.report(final_texts=texts)
        self.assert_fires(report, CHECK_INTERNAL_PLACEHOLDER_PRESENT)

    def test_legacy_placeholder_surviving_is_detected(self):
        fixture = AuditFixture()
        texts = dict(fixture.final_texts)
        texts[1] = "Please send the deploy key to [EMAIL_001], [PERSON_001]."
        report = fixture.report(final_texts=texts)
        self.assert_fires(report, CHECK_INTERNAL_PLACEHOLDER_PRESENT)

    def test_original_secret_surviving_is_detected(self):
        fixture = AuditFixture()
        texts = dict(fixture.final_texts)
        texts[3] = "Password: Hunter2!xK9qz"
        report = fixture.report(final_texts=texts)
        self.assert_fires(report, CHECK_ORIGINAL_SECRET_PRESENT)

    def test_dropped_credential_changes_multiplicity(self):
        fixture = AuditFixture()
        texts = dict(fixture.final_texts)
        texts[3] = "Password: see the vault."
        report = fixture.report(final_texts=texts)
        self.assert_fires(report, CHECK_SECRET_TOKEN_MULTIPLICITY)

    def test_invented_credential_is_detected(self):
        fixture = AuditFixture()
        texts = dict(fixture.final_texts)
        texts[3] = "Password: sk_test2_xxxxxxxxxxxxxxxxxxxxxxxx"
        report = fixture.report(final_texts=texts)
        self.assert_fires(report, CHECK_UNEXPECTED_CREDENTIAL_LIKE_VALUE)

    def test_raw_sender_id_in_body_is_detected(self):
        fixture = AuditFixture()
        texts = dict(fixture.final_texts)
        texts[4] = "The OAuth flow is unchanged for aa11bb22cc33, and 7 winners stands."
        report = fixture.report(final_texts=texts)
        self.assert_fires(report, CHECK_ORIGINAL_SENDER_ID_PRESENT)

    def test_lost_preserved_term_is_detected(self):
        fixture = AuditFixture()
        texts = dict(fixture.final_texts)
        texts[4] = "The sign-in flow is unchanged, and 7 winners is what we settled on."
        report = fixture.report(final_texts=texts)
        self.assert_fires(report, CHECK_PRESERVED_VALUE_LOST)

    def test_unapplied_slot_value_is_detected(self):
        fixture = AuditFixture()
        texts = dict(fixture.final_texts)
        texts[4] = "The OAuth flow is unchanged, and 5 winners is what we settled on."
        report = fixture.report(final_texts=texts)
        self.assert_fires(report, CHECK_INCONSISTENT_SLOT_VALUE)

    def test_missing_final_text_is_detected(self):
        fixture = AuditFixture()
        texts = {key: value for key, value in fixture.final_texts.items() if key != 4}
        report = audit_final_texts(fixture.inputs(), texts)
        self.assert_fires(report, CHECK_COVERAGE_INCOMPLETE)

    def test_plan_replacement_collision_is_detected(self):
        fixture = AuditFixture()
        colliding = TransformationPlan(
            plan_version=1,
            entity_replacements=(
                EntityReplacement(
                    entity_id="E0001",
                    entity_type="PERSON",
                    policy="SYNTHESIZE",
                    original="Joseph",
                    replacement="Marcus",
                ),
                EntityReplacement(
                    entity_id="E0002",
                    entity_type="EMAIL",
                    policy="SYNTHESIZE",
                    original="scott@northstar.io",
                    replacement="Marcus",
                ),
            ),
            slot_replacements=fixture.plan.slot_replacements,
            secret_replacements=fixture.plan.secret_replacements,
        )
        report = fixture.report(plan=colliding)
        self.assert_fires(report, CHECK_PLAN_REPLACEMENT_COLLISION)

    def test_replacement_equal_to_original_is_detected(self):
        fixture = AuditFixture()
        identity = TransformationPlan(
            plan_version=1,
            entity_replacements=(
                EntityReplacement(
                    entity_id="E0001",
                    entity_type="PERSON",
                    policy="SYNTHESIZE",
                    original="Joseph",
                    replacement="joseph",
                ),
            ),
            slot_replacements=(),
            secret_replacements=(),
        )
        report = fixture.report(plan=identity)
        self.assert_fires(report, CHECK_PLAN_REPLACEMENT_COLLISION)

    def test_report_raises_with_every_violation_named(self):
        fixture = AuditFixture()
        texts = dict(fixture.final_texts)
        texts[1] = "Joseph should get it at scott@northstar.io."
        texts[3] = "Password: Hunter2!xK9qz"
        report = fixture.report(final_texts=texts)
        with self.assertRaises(AuditFailure) as caught:
            report.raise_if_failed()
        fired = {violation["check"] for violation in caught.exception.violations}
        # One pass names all of them rather than stopping at the first.
        self.assertIn(CHECK_ORIGINAL_PERSON_PRESENT, fired)
        self.assertIn(CHECK_ORIGINAL_SECRET_PRESENT, fired)
        self.assertGreaterEqual(len(fired), 2)

    def test_violations_never_contain_raw_values(self):
        fixture = AuditFixture()
        texts = dict(fixture.final_texts)
        texts[1] = "Joseph should get it at scott@northstar.io."
        texts[3] = "Password: Hunter2!xK9qz"
        report = fixture.report(final_texts=texts)
        serialized = str(report.to_json())
        for secret in ("Joseph", "scott@northstar.io", "Hunter2!xK9qz", "northstar.io"):
            self.assertNotIn(secret, serialized, f"{secret!r} leaked into the audit report")


class BucketPolicyTests(unittest.TestCase):
    def test_preserved_buckets_are_the_only_verbatim_path(self):
        self.assertEqual(PRESERVED_BUCKETS, frozenset({"EMPTY", "PRESERVE_SHORT"}))

    def test_preserved_state_rejects_required_change(self):
        state = MessageState(ordinal=1, message_id=1, bucket=BUCKET_LONG, requires_change=True)
        with self.assertRaises(PiiError):
            state.mark_done(
                "original", provenance=PROVENANCE_PRESERVED, text_sha256="x", verified=True
            )


if __name__ == "__main__":
    unittest.main()
