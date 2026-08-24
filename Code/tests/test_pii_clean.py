from __future__ import annotations

import copy
import unittest

from Code.PII_Clean import (
    DeterministicPiiCleaner,
    PiiCleanError,
    apply_message_texts,
    assert_only_allowed_fields_changed,
    build_batches,
    should_rewrite,
    sync_annotation_texts,
    validate_rewrite_response,
)
from Code.stage1.validation import validate_stage1_annotation


def normalized_fixture():
    return {
        "project_id": "P1",
        "project_title": "Test",
        "project_metadata": {},
        "messages": [
            {
                "message_id": 1,
                "speaker": "client",
                "text": "Hi Bob, email me at alice@example.com and use https://private.example/login.",
                "created_ts": "2026-01-01",
                "original_index": 0,
                "sender_id": "client-account-123",
            },
            {
                "message_id": 2,
                "speaker": "freelancer",
                "text": "Thank you!",
                "created_ts": "2026-01-02",
                "original_index": 1,
                "sender_id": "freelancer-account-456",
            },
        ],
    }


def annotation_fixture():
    return {
        "benchmark": "ReqMemBench",
        "annotation_version": "v0.6",
        "project": {"project_id": "P1", "project_title": "Test", "sessions": []},
        "requirement_families": [],
        "requirements": [
            {
                "requirement_id": "REQ_CONTACT",
                "title": "Contact",
                "family_id": None,
                "events": [
                    {
                        "event_id": "REQ_CONTACT_E001",
                        "source_message": {
                            "message_id": 1,
                            "speaker": "client",
                            "text": "Hi Bob, email me at alice@example.com and use https://private.example/login.",
                        },
                        "event_type": "INTRODUCE",
                        "value_updates": {"contact": True},
                        "value_removals": None,
                        "scope_updates": None,
                        "ambiguity": None,
                        "execution": None,
                    }
                ],
            }
        ],
    }


class PiiReplacementTests(unittest.TestCase):
    def test_replaces_names_email_url_and_inline_credentials(self):
        messages = [
            {
                "message_id": 1,
                "speaker": "client",
                "text": "Hi Bob, email alice@example.com; login: devuser; password: S3cret!Pass; use https://x.test/a.",
            },
            {"message_id": 2, "speaker": "freelancer", "text": "Thanks, Alice\nAlice"},
        ]
        cleaner = DeterministicPiiCleaner(messages)
        first = cleaner.sanitize_message(messages[0])
        second = cleaner.sanitize_message(messages[1])

        self.assertIn("[FREELANCER_NAME_001]", first)
        self.assertIn("[EMAIL_001]", first)
        self.assertIn("[URL_001]", first)
        self.assertIn("[ACCOUNT_001]", first)
        self.assertIn("[PASSWORD_001]", first)
        self.assertNotIn("Bob", first)
        self.assertNotIn("alice@example.com", first)
        self.assertIn("[CLIENT_NAME_001]", second)

    def test_adjacent_login_tokens_are_classified_consistently(self):
        messages = [
            {"message_id": 1, "speaker": "client", "text": "https://private.example/wp-admin"},
            {"message_id": 2, "speaker": "client", "text": "devaccount"},
            {"message_id": 3, "speaker": "client", "text": "A9!verySecret"},
            {"message_id": 4, "speaker": "client", "text": "A9!verySecret"},
        ]
        cleaner = DeterministicPiiCleaner(messages)

        self.assertEqual(cleaner.sanitize_message(messages[1]), "[ACCOUNT_001]")
        self.assertEqual(cleaner.sanitize_message(messages[2]), "[PASSWORD_001]")
        self.assertEqual(cleaner.sanitize_message(messages[3]), "[PASSWORD_001]")

    def test_short_messages_are_kept_after_pii_replacement(self):
        self.assertFalse(should_rewrite("Thank you!", 5))
        self.assertFalse(should_rewrite("Send it to [EMAIL_001].", 5))
        self.assertTrue(should_rewrite("Please send the revised design files before tomorrow morning.", 5))

    def test_greeting_does_not_treat_question_word_as_a_name(self):
        message = {"message_id": 1, "speaker": "client", "text": "Hi, could you review this today?"}
        cleaner = DeterministicPiiCleaner([message])
        self.assertEqual(cleaner.sanitize_message(message), message["text"])


class RewriteValidationTests(unittest.TestCase):
    def test_requires_placeholders_and_numbers_to_remain_exact(self):
        inputs = [
            {
                "message_id": 7,
                "speaker": "client",
                "text": "Please send [URL_001] with the $25 file by 2026-01-02 tomorrow.",
            }
        ]
        cleaner = DeterministicPiiCleaner(inputs)
        valid = {
            "rewrites": [
                {
                    "message_id": 7,
                    "text": "By tomorrow, please provide the $25 file together with [URL_001] on 2026-01-02.",
                }
            ]
        }
        result = validate_rewrite_response(valid, inputs, cleaner)
        self.assertIn("7", result)

        invalid = copy.deepcopy(valid)
        invalid["rewrites"][0]["text"] = invalid["rewrites"][0]["text"].replace("$25", "$30")
        with self.assertRaisesRegex(ValueError, "numbers"):
            validate_rewrite_response(invalid, inputs, cleaner)

    def test_rejects_unchanged_long_message(self):
        inputs = [
            {"message_id": "m1", "speaker": "client", "text": "Please provide the complete revised document tomorrow."}
        ]
        cleaner = DeterministicPiiCleaner(inputs)
        with self.assertRaisesRegex(ValueError, "unchanged"):
            validate_rewrite_response(
                {"rewrites": [{"message_id": "m1", "text": inputs[0]["text"]}]},
                inputs,
                cleaner,
            )

    def test_batch_limits(self):
        messages = [
            {"message_id": 1, "text": "a" * 5},
            {"message_id": 2, "text": "b" * 5},
            {"message_id": 3, "text": "c" * 5},
        ]
        batches = build_batches(messages, max_messages=2, max_chars=9)
        self.assertEqual([[item["message_id"] for item in batch] for batch in batches], [[1], [2], [3]])


class AnnotationSyncTests(unittest.TestCase):
    def test_only_message_text_and_annotation_source_text_change(self):
        normalized = normalized_fixture()
        annotation = annotation_fixture()
        texts = {"1": "Hello [FREELANCER_NAME_001], use [EMAIL_001] and [URL_001].", "2": "Thank you!"}

        pii_cleaner = DeterministicPiiCleaner(normalized["messages"])
        cleaned_normalized = apply_message_texts(normalized, texts, pii_cleaner)
        cleaned_annotation, updated = sync_annotation_texts(annotation, cleaned_normalized)
        assert_only_allowed_fields_changed(normalized, cleaned_normalized, annotation, cleaned_annotation)
        validate_stage1_annotation(cleaned_annotation, cleaned_normalized)

        self.assertEqual(updated, 1)
        self.assertEqual(cleaned_normalized["messages"][0]["sender_id"], "[SENDER_ID_001]")
        self.assertEqual(
            cleaned_annotation["requirements"][0]["events"][0]["source_message"]["text"],
            texts["1"],
        )
        self.assertEqual(cleaned_annotation["requirements"][0]["events"][0]["value_updates"], {"contact": True})

    def test_speaker_mismatch_fails(self):
        normalized = normalized_fixture()
        annotation = annotation_fixture()
        annotation["requirements"][0]["events"][0]["source_message"]["speaker"] = "freelancer"
        with self.assertRaisesRegex(PiiCleanError, "Speaker mismatch"):
            sync_annotation_texts(annotation, normalized)


if __name__ == "__main__":
    unittest.main()
