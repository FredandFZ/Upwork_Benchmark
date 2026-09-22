"""Phase 0B validator tests.

The coverage and overlap rules have to be strict enough that a missed address is
a hard failure, and loose enough that a correct-but-imperfectly-formatted
response is not rejected.  Both directions are asserted here, because getting
either wrong is costly: too loose leaks PII, too strict makes a long message
permanently unprocessable.
"""

from __future__ import annotations

import unittest

from Code.PII.discovery import adapt_messages
from Code.PII.errors import PiiValidationError
from Code.PII.phase0b_entities import (
    TYPE_POLICY,
    merge_entity_registry,
    required_coverage_spans,
    validate_discovery_response,
)
from Code.PII.models import PiiOccurrence
from Code.PII.secret_shield import nominate_secret_spans, shield_project
from Code.PII.textutil import private_resource_identifiers

# One address and one handle, each appearing twice, plus a Slack-style link --
# the shape that made a real 582-word message unprocessable.
REPEATED = (
    "Reach Will at will@rebuild.example or ping @RebuildTeam. "
    "Site is <http://rebuild.example|rebuild.example>. "
    "Again: will@rebuild.example, and @RebuildTeam handles support."
)


def safe_message(text: str):
    messages = adapt_messages(
        [{"message": text, "message_user_type": "client", "sender_id": "u1", "created_ts": "t"}],
        "P",
    )
    _registry, safe = shield_project(
        "P", messages, preserve_short_max_words=2, short_message_max_words=4
    )
    return safe[0]


def occurrence(source: str, entity_type: str, **extra):
    body = {
        "source": source,
        "entity_type": entity_type,
        "normalized_value": source,
        "confidence": "HIGH",
    }
    body.update(extra)
    return body


def payload(*occurrences, ordinal: int = 1):
    return {"messages": [{"ordinal": ordinal, "occurrences": list(occurrences)}]}


class CoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.safe = safe_message(REPEATED)

    def test_repeated_values_are_each_required_once_not_per_repetition(self):
        """Reporting a value once where it appears twice is correct work.

        Phase 3 replaces by value across the whole text and the audit re-checks
        the whole row, so one record per (message, value) is sufficient.
        """

        spans = required_coverage_spans(self.safe.safe_text)
        values = [self.safe.safe_text[start:end] for start, end, _ in spans]
        self.assertEqual(values.count("will@rebuild.example"), 2, "fixture sanity")
        self.assertEqual(values.count("@RebuildTeam"), 2, "fixture sanity")

        result = validate_discovery_response(
            payload(
                occurrence("<http://rebuild.example|rebuild.example>", "PRIVATE_URL"),
                occurrence("@RebuildTeam", "SOCIAL_ACCOUNT"),
                occurrence("will@rebuild.example", "EMAIL"),
            ),
            [self.safe],
        )
        self.assertEqual(len(result[1]), 3)

    def test_a_genuinely_missing_address_is_still_rejected(self):
        with self.assertRaises(PiiValidationError) as caught:
            validate_discovery_response(
                payload(
                    occurrence("<http://rebuild.example|rebuild.example>", "PRIVATE_URL"),
                    occurrence("@RebuildTeam", "SOCIAL_ACCOUNT"),
                ),
                [self.safe],
            )
        self.assertIn("DISCOVERY_COVERAGE_GAP", caught.exception.failures)

    def test_a_genuinely_missing_handle_is_still_rejected(self):
        with self.assertRaises(PiiValidationError) as caught:
            validate_discovery_response(
                payload(
                    occurrence("<http://rebuild.example|rebuild.example>", "PRIVATE_URL"),
                    occurrence("will@rebuild.example", "EMAIL"),
                ),
                [self.safe],
            )
        self.assertIn("DISCOVERY_COVERAGE_GAP", caught.exception.failures)

    def test_missing_secret_token_is_rejected(self):
        safe = safe_message("The api key is sk_live_51H8xYzAbCdEfGhIjKlMnOpQr, keep it safe.")
        self.assertTrue(safe.secret_tokens, "fixture sanity: a token must exist")
        with self.assertRaises(PiiValidationError) as caught:
            validate_discovery_response(payload(), [safe])
        self.assertIn("DISCOVERY_COVERAGE_GAP", caught.exception.failures)


class OverlapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.safe = safe_message(REPEATED)

    def test_nested_declaration_is_dropped_not_rejected(self):
        """A model listing both a link and the domain inside it is harmless."""

        result = validate_discovery_response(
            payload(
                occurrence("<http://rebuild.example|rebuild.example>", "PRIVATE_URL"),
                occurrence("rebuild.example", "PRIVATE_DOMAIN"),  # nested in the link
                occurrence("@RebuildTeam", "SOCIAL_ACCOUNT"),
                occurrence("will@rebuild.example", "EMAIL"),
            ),
            [self.safe],
        )
        sources = [item.source for item in result[1]]
        self.assertIn("<http://rebuild.example|rebuild.example>", sources)
        self.assertNotIn("rebuild.example", sources, "the nested record must be dropped")

    def test_maximal_span_wins_when_the_wider_record_comes_second(self):
        result = validate_discovery_response(
            payload(
                occurrence("rebuild.example", "PRIVATE_DOMAIN"),
                occurrence("<http://rebuild.example|rebuild.example>", "PRIVATE_URL"),
                occurrence("@RebuildTeam", "SOCIAL_ACCOUNT"),
                occurrence("will@rebuild.example", "EMAIL"),
            ),
            [self.safe],
        )
        sources = [item.source for item in result[1]]
        self.assertIn("<http://rebuild.example|rebuild.example>", sources)
        self.assertNotIn("rebuild.example", sources)


class PolicyTests(unittest.TestCase):
    def test_policy_is_enforced_not_accepted_from_the_model(self):
        safe = safe_message("We deploy on GitHub and bill through Stripe.")
        with self.assertRaises(PiiValidationError) as caught:
            validate_discovery_response(
                payload(
                    occurrence("GitHub", "PRIVATE_ORGANIZATION", policy="SYNTHESIZE"),
                ),
                [safe],
            )
        self.assertIn("DISCOVERY_CATEGORY_UNKNOWN", caught.exception.failures)

    def test_public_names_are_preserved(self):
        safe = safe_message("We deploy on GitHub and bill through Stripe.")
        result = validate_discovery_response(
            payload(
                occurrence("GitHub", "PUBLIC_THIRD_PARTY"),
                occurrence("Stripe", "PUBLIC_THIRD_PARTY"),
            ),
            [safe],
        )
        for item in result[1]:
            self.assertEqual(item.policy, TYPE_POLICY[item.entity_type])
            self.assertEqual(item.policy, "PRESERVE")

    def test_omitting_a_present_public_requirement_is_rejected(self):
        safe = safe_message("Store the finished PDF with Pinata on IPFS.")
        with self.assertRaises(PiiValidationError) as caught:
            validate_discovery_response(payload(), [safe])
        self.assertIn("DISCOVERY_COVERAGE_GAP", caught.exception.failures)


class AmbiguousCommonWordTests(unittest.TestCase):
    def test_common_verb_colliding_with_a_brand_name_is_not_required(self):
        """'zoom in' is not a mention of the Zoom product.

        Case-insensitive matching against PUBLIC_ALLOWLIST previously forced a
        DISCOVERY_COVERAGE_GAP for any lowercase use of an ordinary word that
        happens to share a single-word public brand's spelling.
        """

        safe = safe_message(
            "If you zoom in, you'll be able to see the text and logo clearly."
        )
        labels = [label for _, _, label in required_coverage_spans(safe.safe_text)]
        self.assertNotIn("PUBLIC_REQUIREMENT", labels)

    def test_properly_capitalized_brand_mention_is_still_required(self):
        safe = safe_message("Let's hop on a Zoom call at noon.")
        labels = [label for _, _, label in required_coverage_spans(safe.safe_text)]
        self.assertIn("PUBLIC_REQUIREMENT", labels)


class SecretAndPrivateIdentifierRegressionTests(unittest.TestCase):
    def test_markdown_escaped_webhook_secret_is_detected(self):
        value = "whsec" + r"\_" + "Ab9Cd8Ef7Gh6Jk5Lm4Np3Qr2"
        candidates = nominate_secret_spans(f"Webhook secret: {value}")
        self.assertEqual([item.value for item in candidates], [value])
        self.assertEqual(candidates[0].kind, "WEBHOOK_SECRET")

    def test_contextual_64_hex_key_is_detected_but_transaction_hash_is_not(self):
        value = "ab12" * 16
        self.assertTrue(nominate_secret_spans(f"Paste this key into the box: {value}"))
        self.assertFalse(nominate_secret_spans(f"Transaction hash: {value}"))

    def test_private_app_identifier_inside_public_url_is_extracted(self):
        value = "k6j6pbuyhm4bgcdd"
        url = f"https://dashboard.example/apps/{value}/webhooks"
        self.assertEqual(private_resource_identifiers(url), (value,))


class MergeTests(unittest.TestCase):
    def test_one_record_per_value_still_links_the_message(self):
        """The security property behind the relaxed coverage rule.

        The entity must still be attached to this message, or its plan slice
        would omit the replacement and the original could survive.
        """

        safe = safe_message(REPEATED)
        result = validate_discovery_response(
            payload(
                occurrence("<http://rebuild.example|rebuild.example>", "PRIVATE_URL"),
                occurrence("@RebuildTeam", "SOCIAL_ACCOUNT"),
                occurrence("will@rebuild.example", "EMAIL"),
            ),
            [safe],
        )
        registry = merge_entity_registry(result)
        for_message = registry.for_ordinal(1)
        types = {item.entity_type for item in for_message}
        self.assertIn("EMAIL", types)
        self.assertIn("SOCIAL_ACCOUNT", types)
        self.assertIn("PRIVATE_URL", types)

    def test_link_hints_are_scoped_to_one_message(self):
        """Two API responses may both start their arbitrary labels at ``L1``."""

        first = PiiOccurrence(
            ordinal=1,
            message_id="m1",
            source="Alice Example",
            start=0,
            end=13,
            entity_type="PERSON",
            policy="SYNTHESIZE",
            normalized_value="Alice Example",
            link_hint="L1",
            confidence="HIGH",
        )
        second = PiiOccurrence(
            ordinal=2,
            message_id="m2",
            source="Bob Example",
            start=0,
            end=11,
            entity_type="PERSON",
            policy="SYNTHESIZE",
            normalized_value="Bob Example",
            link_hint="L1",
            confidence="HIGH",
        )

        registry = merge_entity_registry({1: (first,), 2: (second,)})

        self.assertEqual(registry.bundles, ())

    def test_link_hint_still_bundles_entities_within_one_message(self):
        person = PiiOccurrence(
            ordinal=1,
            message_id="m1",
            source="Alice Example",
            start=0,
            end=13,
            entity_type="PERSON",
            policy="SYNTHESIZE",
            normalized_value="Alice Example",
            link_hint="L1",
            confidence="HIGH",
        )
        email = PiiOccurrence(
            ordinal=1,
            message_id="m1",
            source="alice@private.invalid",
            start=17,
            end=38,
            entity_type="EMAIL",
            policy="SYNTHESIZE",
            normalized_value="alice@private.invalid",
            link_hint="L1",
            confidence="HIGH",
        )

        registry = merge_entity_registry({1: (person, email)})

        self.assertEqual(len(registry.bundles), 1)
        self.assertEqual(set(registry.bundles[0].entity_ids), {"E0001", "E0002"})


if __name__ == "__main__":
    unittest.main()
