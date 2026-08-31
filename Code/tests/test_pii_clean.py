from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from Code.PII_Clean import (
    DeterministicPiiCleaner,
    PiiCleanError,
    ProjectFiles,
    align_whitespace_only_annotation_texts,
    apply_message_texts,
    assert_only_allowed_fields_changed,
    assert_only_chat_fields_changed,
    build_batches,
    build_cleaned_chat,
    copy_project_except_chat,
    protected_numbers,
    should_rewrite,
    sync_annotation_texts,
    validate_and_adapt_chat_messages,
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

    def test_reintroduction_check_is_scoped_to_the_source_message(self):
        cleaner = DeterministicPiiCleaner([])
        cleaner.registry.token("ACCOUNT", "active")
        cleaner.assert_no_known_pii("The task is active.", source_text="Please review the task.", message_id=2)
        with self.assertRaisesRegex(ValueError, "category=ACCOUNT"):
            cleaner.assert_no_known_pii("The account is active.", source_text="account: active", message_id=1)

    def test_natural_login_phrase_is_not_treated_as_a_short_account(self):
        natural = {"message_id": 1, "speaker": "client", "text": "The login is to be enabled tomorrow."}
        explicit = {"message_id": 2, "speaker": "client", "text": "login: ab"}
        cleaner = DeterministicPiiCleaner([natural, explicit])

        self.assertEqual(cleaner.sanitize_message(natural), natural["text"])
        self.assertEqual(cleaner.sanitize_message(explicit), "login: [ACCOUNT_001]")

    def test_known_password_is_replaced_when_reused_inside_a_later_message(self):
        messages = [
            {"message_id": 1, "speaker": "client", "text": "A9verySecretKey"},
            {
                "message_id": 2,
                "speaker": "client",
                "text": "Use A9verySecretKey for the staging login and then confirm access.",
            },
        ]
        cleaner = DeterministicPiiCleaner(messages)

        self.assertEqual(cleaner.sanitize_message(messages[0]), "[PASSWORD_001]")
        self.assertEqual(
            cleaner.sanitize_message(messages[1]),
            "Use [PASSWORD_001] for the staging login and then confirm access.",
        )


class RawDatasetChatTests(unittest.TestCase):
    def test_adapts_and_cleans_only_allowed_chat_fields(self):
        chat = [
            {
                "created_ts": "2026-01-01",
                "message": "Hi Bob, email alice@example.com before tomorrow morning.",
                "message_user_type": "client",
                "sender_id": "sender-123",
                "custom": {"keep": True},
            },
            {
                "created_ts": "2026-01-02",
                "message": "Thank you!",
                "message_user_type": "freelancer",
                "sender_id": "sender-456",
            },
        ]
        adapted = validate_and_adapt_chat_messages(chat, "P1")
        cleaner = DeterministicPiiCleaner(adapted)
        texts = {
            "1": cleaner.sanitize_message(adapted[0]),
            "2": cleaner.sanitize_message(adapted[1]),
        }

        cleaned = build_cleaned_chat(chat, texts, cleaner)
        assert_only_chat_fields_changed(chat, cleaned)

        self.assertEqual(cleaned[0]["created_ts"], chat[0]["created_ts"])
        self.assertEqual(cleaned[0]["message_user_type"], chat[0]["message_user_type"])
        self.assertEqual(cleaned[0]["custom"], {"keep": True})
        self.assertIn("[EMAIL_001]", cleaned[0]["message"])
        self.assertEqual(cleaned[0]["sender_id"], "[SENDER_ID_001]")
        self.assertNotIn("message_id", cleaned[0])

    def test_rejects_chat_without_string_message(self):
        with self.assertRaisesRegex(PiiCleanError, "string message"):
            validate_and_adapt_chat_messages([{"message": None}], "P1")

    def test_copies_other_project_files_but_not_raw_chat(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source" / "P1"
            output = root / "output" / "P1"
            (source / "deliverables").mkdir(parents=True)
            (source / "chat_messages.json").write_text("RAW CHAT", encoding="utf-8")
            (source / "job.txt").write_text("unchanged", encoding="utf-8")
            (source / "deliverables" / "file.txt").write_text("artifact", encoding="utf-8")

            project = ProjectFiles("P1", source, source / "chat_messages.json")
            copy_project_except_chat(project, output)

            self.assertFalse((output / "chat_messages.json").exists())
            self.assertEqual((output / "job.txt").read_text(encoding="utf-8"), "unchanged")
            self.assertEqual(
                (output / "deliverables" / "file.txt").read_text(encoding="utf-8"),
                "artifact",
            )


class RewriteValidationTests(unittest.TestCase):
    def test_numeric_html_entities_are_not_business_numbers(self):
        self.assertEqual(protected_numbers("I&#39;m ready in 2 days."), {"2": 1})
        inputs = [
            {
                "message_id": 2,
                "speaker": "freelancer",
                "text": "I&#39;m ready and I&#39;ll send it in 2 days.",
            }
        ]
        result = validate_rewrite_response(
            {
                "rewrites": [
                    {
                        "message_id": 2,
                        "text": "I'm ready, and I'll deliver it in 2 days.",
                    }
                ]
            },
            inputs,
        )
        self.assertIn("2 days", result["2"])

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
        result = validate_rewrite_response(valid, inputs)
        self.assertIn("7", result)

        invalid = copy.deepcopy(valid)
        invalid["rewrites"][0]["text"] = invalid["rewrites"][0]["text"].replace("$25", "$30")
        with self.assertRaisesRegex(ValueError, "numbers"):
            validate_rewrite_response(invalid, inputs)

    def test_allows_pii_during_phase_one_rewrite(self):
        inputs = [
            {
                "message_id": 8,
                "speaker": "client",
                "text": "Please email Alice at alice@example.com before tomorrow.",
            }
        ]
        result = validate_rewrite_response(
            {
                "rewrites": [
                    {
                        "message_id": 8,
                        "text": "Before tomorrow, please contact Alice via alice@example.com.",
                    }
                ]
            },
            inputs,
        )
        self.assertIn("alice@example.com", result["8"])

    def test_phase_two_scans_the_rewritten_message(self):
        rewritten = {
            "message_id": 9,
            "speaker": "client",
            "text": "Before tomorrow, contact Alice through alice@example.com and https://private.example.",
        }
        cleaner = DeterministicPiiCleaner([rewritten])
        sanitized = cleaner.sanitize_message(rewritten)
        cleaner.assert_no_known_pii(sanitized, source_text=rewritten["text"], message_id=9)
        self.assertIn("[EMAIL_001]", sanitized)
        self.assertIn("[URL_001]", sanitized)
        self.assertNotIn("alice@example.com", sanitized)

    def test_rejects_unchanged_long_message(self):
        inputs = [
            {"message_id": "m1", "speaker": "client", "text": "Please provide the complete revised document tomorrow."}
        ]
        with self.assertRaisesRegex(ValueError, "unchanged"):
            validate_rewrite_response(
                {"rewrites": [{"message_id": "m1", "text": inputs[0]["text"]}]},
                inputs,
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
    def test_whitespace_only_source_difference_is_aligned(self):
        normalized = normalized_fixture()
        annotation = annotation_fixture()
        annotation["requirements"][0]["events"][0]["source_message"]["text"] = (
            "Hi Bob,  email me at alice@example.com and use\nhttps://private.example/login."
        )

        aligned, repaired = align_whitespace_only_annotation_texts(annotation, normalized)

        self.assertEqual(repaired, 1)
        self.assertEqual(
            aligned["requirements"][0]["events"][0]["source_message"]["text"],
            normalized["messages"][0]["text"],
        )
        validate_stage1_annotation(aligned, normalized)

    def test_substantive_source_difference_is_not_aligned(self):
        normalized = normalized_fixture()
        annotation = annotation_fixture()
        annotation["requirements"][0]["events"][0]["source_message"]["text"] = "Different evidence."

        aligned, repaired = align_whitespace_only_annotation_texts(annotation, normalized)

        self.assertEqual(repaired, 0)
        with self.assertRaisesRegex(ValueError, "source text differs"):
            validate_stage1_annotation(aligned, normalized)

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
