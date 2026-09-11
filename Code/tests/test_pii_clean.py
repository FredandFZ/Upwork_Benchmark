from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from Code.PII_Clean import (
    DeterministicPiiCleaner,
    LlmPiiReplacementState,
    PiiCleanError,
    ProjectFiles,
    align_whitespace_only_annotation_texts,
    apply_message_texts,
    assert_only_allowed_fields_changed,
    assert_only_chat_fields_changed,
    build_batches,
    build_cleaned_chat,
    classify_context_batch,
    copy_project_except_chat,
    context_occurrence_candidates,
    contextual_values,
    discover_project_terms,
    has_structural_change,
    load_manual_rewrites,
    protected_numbers,
    redact_pii_batch,
    rewrite_batch,
    restore_phase_one_checkpoint,
    restore_phase_two_checkpoint,
    restore_context_classification_checkpoint,
    save_context_classification_checkpoint,
    save_phase_one_checkpoint,
    save_phase_two_checkpoint,
    should_rewrite,
    structural_list_markers,
    sync_annotation_texts,
    validate_and_adapt_chat_messages,
    validate_context_classification_response,
    validate_pii_response,
    validate_rewrite_response,
)
from Code.stage1.api_client import ApiError
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
    def test_replaces_project_name_but_keeps_technical_and_feature_terms(self):
        messages = [
            {
                "message_id": 1,
                "speaker": "client",
                "text": (
                    "We can rename it BooksOnChain later while keeping ReactNative "
                    "and gameification mechanics unchanged."
                ),
            },
            {
                "message_id": 2,
                "speaker": "freelancer",
                "text": "The follow-up transaction emits RandomReferralReward after completion.",
            },
            {
                "message_id": 3,
                "speaker": "client",
                "text": "Please use GoogleDataStudio for the reporting dashboard.",
            },
            {
                "message_id": 4,
                "speaker": "freelancer",
                "text": "GoogleDataStudio is already configured for the dashboard.",
            },
        ]
        project_terms = discover_project_terms(messages)
        cleaner = DeterministicPiiCleaner(messages, project_terms=project_terms)
        sanitized = cleaner.sanitize_message(messages[0])

        self.assertEqual(project_terms, ("BooksOnChain",))
        self.assertIn("[PROJECT_NAME_001]", sanitized)
        self.assertIn("ReactNative", sanitized)
        self.assertIn("gameification mechanics", sanitized)

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

    def test_standalone_url_bypasses_llm_rewrite(self):
        self.assertFalse(
            should_rewrite(
                "<https://docs.example.com/document/d/private-document-id/edit>",
                5,
            )
        )
        self.assertFalse(
            should_rewrite(
                "<https://docs.google.com/document/d/private-document-id/edit>",
                5,
            )
        )

    def test_greeting_does_not_treat_question_word_as_a_name(self):
        message = {"message_id": 1, "speaker": "client", "text": "Hi, could you review this today?"}
        cleaner = DeterministicPiiCleaner([message])
        self.assertEqual(cleaner.sanitize_message(message), message["text"])

    def test_signature_shape_does_not_register_function_word_as_name(self):
        messages = [
            {"message_id": 1, "speaker": "client", "text": "Thanks\nTo"},
            {
                "message_id": 2,
                "speaker": "client",
                "text": "I am open to suggestions for the project.",
            },
        ]
        cleaner = DeterministicPiiCleaner(messages)

        self.assertIsNone(cleaner.registry.existing_token("CLIENT_NAME", "To"))
        self.assertEqual(cleaner.sanitize_message(messages[1]), messages[1]["text"])

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

    def test_date_time_is_not_registered_as_a_phone_number(self):
        message = {
            "message_id": 3,
            "speaker": "client",
            "text": "Schedule it for 2031-06-18 10:30.",
        }
        cleaner = DeterministicPiiCleaner([message])

        self.assertEqual(cleaner.sanitize_message(message), message["text"])

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

        cleaned = build_cleaned_chat(
            chat,
            texts,
            {"1": "[SENDER_ID_001]", "2": "[SENDER_ID_002]"},
        )
        assert_only_chat_fields_changed(chat, cleaned)

        self.assertEqual(cleaned[0]["message_user_type"], chat[0]["message_user_type"])
        self.assertEqual(cleaned[0]["custom"], {"keep": True})
        self.assertIn("[EMAIL_001]", cleaned[0]["message"])
        self.assertNotIn("created_ts", cleaned[0])
        self.assertNotIn("sender_id", cleaned[0])
        self.assertNotIn("created_ts", cleaned[1])
        self.assertNotIn("sender_id", cleaned[1])
        self.assertNotIn("message_id", cleaned[0])

        retained_metadata = copy.deepcopy(cleaned)
        retained_metadata[0]["sender_id"] = "[SENDER_ID_001]"
        with self.assertRaisesRegex(PiiCleanError, "retained sender_id or created_ts"):
            assert_only_chat_fields_changed(chat, retained_metadata)

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


class ContextClassificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.message = {
            "message_id": 1,
            "speaker": "client",
            "text": '1. Try code "1" if NFT #1 exists.',
        }
        self.message["context_candidates"] = context_occurrence_candidates(
            self.message["text"]
        )
        self.payload = {
            "classified_messages": [
                {
                    "message_id": 1,
                    "occurrences": [
                        {"occurrence_id": "C001", "category": "LIST_INDEX"},
                        {"occurrence_id": "C002", "category": "NUMBER"},
                        {"occurrence_id": "C003", "category": "NUMBER"},
                    ],
                }
            ]
        }

    def test_same_literal_is_classified_by_occurrence(self):
        candidates = self.message["context_candidates"]
        self.assertEqual([item["source"] for item in candidates], ["1", "1", "1"])

        result = validate_context_classification_response(
            self.payload, [self.message]
        )

        self.assertEqual(result["1"][0]["action"], "PRESERVE")
        self.assertEqual(result["1"][1]["action"], "REPLACE")
        self.assertEqual(result["1"][2]["action"], "REPLACE")

    def test_context_classification_checkpoint_round_trip(self):
        classified = validate_context_classification_response(
            self.payload, [self.message]
        )
        signature = {"cleaning_version": "6.0"}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "P1" / "phase0_context.json"
            save_context_classification_checkpoint(
                path, signature, [self.message], classified
            )
            restored = restore_context_classification_checkpoint(
                path, signature, [self.message]
            )

        self.assertEqual(restored, classified)

    async def test_context_classification_uses_api_and_full_message(self):
        class FakeApi:
            def __init__(self, payload):
                self.payload = payload
                self.calls = []

            async def call(self, **kwargs):
                self.calls.append(kwargs)
                kwargs["validator"](self.payload)
                return self.payload

        api = FakeApi(self.payload)
        result = await classify_context_batch(api, "P1", 1, [self.message])

        self.assertIn("1", result)
        self.assertEqual(api.calls[0]["run_mode"], "PII_CLEAN_CONTEXT_CLASSIFY")
        request_body = json.loads(api.calls[0]["messages"][1]["content"])
        self.assertEqual(request_body["messages"][0]["text"], self.message["text"])

    def test_rewrite_uses_occurrence_level_classification(self):
        classified = validate_context_classification_response(
            self.payload, [self.message]
        )
        rewrite_input = dict(self.message)
        rewrite_input["context_occurrences"] = classified["1"]

        result = validate_rewrite_response(
            {
                "rewrites": [
                    {
                        "message_id": 1,
                        "text": '1. If NFT #7 exists, test code "8".',
                    }
                ]
            },
            [rewrite_input],
        )

        self.assertIn("#7", result["1"])

    def test_llm_classified_technical_number_is_preserved(self):
        rewrite_input = {
            "message_id": 2,
            "speaker": "client",
            "text": "Use HTTP/2 with 3 nodes.",
            "context_occurrences": (
                {
                    "occurrence_id": "C001",
                    "source": "2",
                    "category": "TECHNICAL_IDENTIFIER",
                    "action": "PRESERVE",
                },
                {
                    "occurrence_id": "C002",
                    "source": "3",
                    "category": "NUMBER",
                    "action": "REPLACE",
                },
            ),
        }

        result = validate_rewrite_response(
            {
                "rewrites": [
                    {
                        "message_id": 2,
                        "text": "With 7 nodes, use HTTP/2.",
                    }
                ]
            },
            [rewrite_input],
        )

        self.assertIn("HTTP/2", result["2"])

    def test_llm_list_headings_are_not_compared_as_line_list_markers(self):
        source = (
            "Choose a payment plan:\n"
            "1. Review the first route.\n"
            "2. Review the second route.\n"
            "Option 1: Basic checkout\n"
            "Option 2: Advanced checkout\n"
            "The fee is $25."
        )
        rewrite_input = {
            "message_id": 140,
            "speaker": "client",
            "text": source,
            "require_structure_change": False,
            "context_occurrences": (
                {"occurrence_id": "C001", "source": "1", "category": "LIST_INDEX", "action": "PRESERVE"},
                {"occurrence_id": "C002", "source": "2", "category": "LIST_INDEX", "action": "PRESERVE"},
                {"occurrence_id": "C003", "source": "1", "category": "LIST_INDEX", "action": "PRESERVE"},
                {"occurrence_id": "C004", "source": "2", "category": "LIST_INDEX", "action": "PRESERVE"},
                {"occurrence_id": "C005", "source": "$25", "category": "AMOUNT", "action": "REPLACE"},
            ),
        }

        result = validate_rewrite_response(
            {
                "rewrites": [
                    {
                        "message_id": 140,
                        "text": (
                            "Available payment plans are listed below:\n"
                            "1. Start by reviewing the first route.\n"
                            "2. Then review the second route.\n"
                            "Option 1: Basic checkout\n"
                            "Option 2: Advanced checkout\n"
                            "A $80 fee applies."
                        ),
                    }
                ]
            },
            [rewrite_input],
        )

        self.assertIn("Option 1", result["140"])

    def test_rejects_changed_llm_list_heading(self):
        rewrite_input = {
            "message_id": 141,
            "speaker": "client",
            "text": "Compare Option 1 and Option 2 before selecting a route.",
            "context_occurrences": (
                {"occurrence_id": "C001", "source": "1", "category": "LIST_INDEX", "action": "PRESERVE"},
                {"occurrence_id": "C002", "source": "2", "category": "LIST_INDEX", "action": "PRESERVE"},
            ),
        }

        with self.assertRaisesRegex(ValueError, "marked for preservation"):
            validate_rewrite_response(
                {
                    "rewrites": [
                        {
                            "message_id": 141,
                            "text": "Before choosing a route, compare Option 7 with Option 4.",
                        }
                    ]
                },
                [rewrite_input],
            )


class RewriteValidationTests(unittest.TestCase):
    def test_phase_one_checkpoint_restores_validated_rewrite(self):
        candidates = [
            {
                "message_id": 20,
                "speaker": "client",
                "text": "Please deliver the $25 report before tomorrow morning.",
                "must_preserve_terms": (),
                "must_replace_terms": (),
                "require_structure_change": True,
            }
        ]
        rewritten = {
            "20": "Before tomorrow morning, please deliver the $80 report."
        }
        signature = {"cleaning_version": "test"}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "P1" / "phase1_rewrite.json"
            save_phase_one_checkpoint(path, signature, candidates, rewritten)
            restored = restore_phase_one_checkpoint(path, signature, candidates)

        self.assertEqual(restored, rewritten)

    def test_phase_one_checkpoint_accepts_compatible_v57_signature(self):
        candidates = [
            {
                "message_id": 20,
                "speaker": "client",
                "text": "Please deliver the $25 report before tomorrow morning.",
                "must_preserve_terms": (),
                "must_replace_terms": (),
                "require_structure_change": True,
            }
        ]
        rewritten = {
            "20": "Before tomorrow morning, please deliver the $80 report."
        }
        old_signature = {"cleaning_version": "5.7", "source_sha256": "source"}
        current_signature = {"cleaning_version": "6.0", "source_sha256": "source"}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "P1" / "phase1_rewrite.json"
            save_phase_one_checkpoint(path, old_signature, candidates, rewritten)
            restored = restore_phase_one_checkpoint(path, current_signature, candidates)

        self.assertEqual(restored, rewritten)

    def test_phase_one_checkpoint_restores_valid_entries_and_skips_invalid_ones(self):
        candidates = [
            {
                "message_id": 1,
                "speaker": "client",
                "text": "Budget: $25",
                "require_structure_change": False,
            },
            {
                "message_id": 2,
                "speaker": "client",
                "text": "Timeline: 2 days",
                "require_structure_change": False,
            },
        ]
        cached = {
            "1": "Budget: $80",
            "2": "The timeline remains 2 days.",
        }
        signature = {"cleaning_version": "test"}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "P1" / "phase1_rewrite.json"
            save_phase_one_checkpoint(path, signature, candidates, cached)
            restored = restore_phase_one_checkpoint(path, signature, candidates)

        self.assertEqual(restored, {"1": "Budget: $80"})

    def test_loads_source_guarded_manual_rewrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manual.json"
            path.write_text(
                '{"rewrites":[{"project_id":"P1","message_id":7,'
                '"source_sha256":"' + ("a" * 64) + '",'
                '"text":"A reviewed semantic rewrite."}]}',
                encoding="utf-8",
            )
            rewrites = load_manual_rewrites(path)

        self.assertEqual(len(rewrites), 1)
        self.assertEqual(rewrites[0].project_id, "P1")
        self.assertEqual(rewrites[0].message_id, 7)

    def test_numeric_html_entities_are_not_context_values(self):
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
                        "text": "In 4 days, I'll deliver it; I'm ready.",
                    }
                ]
            },
            inputs,
        )
        self.assertIn("4 days", result["2"])

    def test_numbers_inside_protected_technical_identifiers_are_not_context_values(self):
        source = "Use ERC-721 and AES-256 with 3 nodes for the NFT reader."
        self.assertEqual(contextual_values(source), (("NUMBER", "3"),))

        result = validate_rewrite_response(
            {
                "rewrites": [
                    {
                        "message_id": 21,
                        "text": (
                            "For the NFT reader, use ERC-721 and AES-256 with 7 nodes."
                        ),
                    }
                ]
            },
            [
                {
                    "message_id": 21,
                    "speaker": "client",
                    "text": source,
                }
            ],
        )

        self.assertIn("ERC-721", result["21"])
        self.assertIn("AES-256", result["21"])
        self.assertIn("7 nodes", result["21"])

    def test_currency_amounts_take_precedence_over_decimal_versions(self):
        source = "Use the $15.00 button, keep a $15 balance, total 20 USD, and install v2.1."
        self.assertEqual(
            contextual_values(source),
            (
                ("AMOUNT", "$15.00"),
                ("AMOUNT", "$15"),
                ("AMOUNT", "20 USD"),
                ("VERSION", "v2.1"),
            ),
        )

        result = validate_rewrite_response(
            {
                "rewrites": [
                    {
                        "message_id": 22,
                        "text": (
                            "After installing v8.4, maintain a $22 balance; the $22.50 "
                            "button shows a 30 USD total."
                        ),
                    }
                ]
            },
            [{"message_id": 22, "speaker": "client", "text": source}],
        )

        self.assertIn("$22.50", result["22"])

    def test_rejects_word_substitution_without_sentence_restructuring(self):
        inputs = [
            {
                "message_id": 3,
                "speaker": "client",
                "text": "Please send the complete revised document before tomorrow morning.",
            }
        ]
        with self.assertRaisesRegex(ValueError, "sentence structure"):
            validate_rewrite_response(
                {
                    "rewrites": [
                        {
                            "message_id": 3,
                            "text": "Please provide the complete updated document before tomorrow morning.",
                        }
                    ]
                },
                inputs,
            )

    def test_accepts_reordered_sentence_structure(self):
        self.assertTrue(
            has_structural_change(
                "Please send the complete revised document before tomorrow morning.",
                "Before tomorrow morning, please send the complete revised document.",
            )
        )

    def test_rejects_changes_to_protected_requirement_term(self):
        inputs = [
            {
                "message_id": 4,
                "speaker": "client",
                "text": "Please keep the gameification mechanics unchanged while updating the layout.",
                "must_preserve_terms": ("gameification mechanics",),
            }
        ]
        with self.assertRaisesRegex(ValueError, "protected tool, feature, or project term"):
            validate_rewrite_response(
                {
                    "rewrites": [
                        {
                            "message_id": 4,
                            "text": "While updating the layout, please keep the game mechanics unchanged.",
                        }
                    ]
                },
                inputs,
            )

    def test_requires_placeholders_to_remain_and_context_values_to_change(self):
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
                    "text": "By tomorrow, please provide the $40 file together with [URL_001] on 2031-06-18.",
                }
            ]
        }
        result = validate_rewrite_response(valid, inputs)
        self.assertIn("7", result)

        invalid = copy.deepcopy(valid)
        invalid["rewrites"][0]["text"] = invalid["rewrites"][0]["text"].replace("$40", "$25")
        with self.assertRaisesRegex(ValueError, "retained an original"):
            validate_rewrite_response(invalid, inputs)

    def test_requires_versions_filenames_and_public_services_to_change(self):
        inputs = [
            {
                "message_id": 11,
                "speaker": "client",
                "text": "Please upload config-v2.json to Stripe after installing v3.4.",
                "must_preserve_terms": (),
                "must_replace_terms": ("Stripe",),
            }
        ]
        result = validate_rewrite_response(
            {
                "rewrites": [
                    {
                        "message_id": 11,
                        "text": (
                            "After installing v8.1, please upload settings-v7.json "
                            "to Payment Provider A."
                        ),
                    }
                ]
            },
            inputs,
        )
        self.assertNotIn("Stripe", result["11"])
        self.assertNotIn("v3.4", result["11"])
        self.assertNotIn("config-v2.json", result["11"])

        unchanged = {
            "rewrites": [
                {
                    "message_id": 11,
                    "text": (
                        "After installing v3.4, please upload config-v2.json "
                        "to Stripe."
                    ),
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "retained an original"):
            validate_rewrite_response(unchanged, inputs)

    def test_short_context_value_still_requires_phase_one(self):
        self.assertTrue(should_rewrite("Budget: $25", 5))
        self.assertTrue(should_rewrite("2026-01-02", 5))
        self.assertTrue(should_rewrite("release-v2.json", 5))
        self.assertTrue(should_rewrite("Use Stripe", 5))

    def test_public_company_acronym_is_not_protected_as_identifier(self):
        inputs = [
            {
                "message_id": 12,
                "speaker": "client",
                "text": "Please deploy the application through AWS after approval.",
            }
        ]

        result = validate_rewrite_response(
            {
                "rewrites": [
                    {
                        "message_id": 12,
                        "text": "After approval, please deploy the application through Cloud Host A.",
                    }
                ]
            },
            inputs,
        )

        self.assertNotIn("AWS", result["12"])

    def test_public_name_inside_url_is_left_for_phase_two(self):
        inputs = [
            {
                "message_id": 13,
                "speaker": "client",
                "text": (
                    "Please review https://docs.google.com/a and then use Stripe "
                    "for payment."
                ),
            }
        ]

        result = validate_rewrite_response(
            {
                "rewrites": [
                    {
                        "message_id": 13,
                        "text": (
                            "For payment, use Payment Provider A after reviewing "
                            "https://docs.google.com/a."
                        ),
                    }
                ]
            },
            inputs,
        )

        self.assertIn("https://docs.google.com/a", result["13"])
        self.assertNotIn("Stripe", result["13"])

    def test_ordered_list_markers_are_layout_not_context_numbers(self):
        source = (
            "Please use GoDaddy for DNS.\n"
            "1\\. Open settings.\n"
            "2\\. Save changes."
        )
        self.assertEqual(contextual_values(source), ())
        self.assertEqual(structural_list_markers(source), ("1", "2"))

        result = validate_rewrite_response(
            {
                "rewrites": [
                    {
                        "message_id": 14,
                        "text": (
                            "For DNS, use Domain Host A.\n"
                            "1\\. Open settings.\n"
                            "2\\. Save changes."
                        ),
                    }
                ]
            },
            [
                {
                    "message_id": 14,
                    "speaker": "client",
                    "text": source,
                }
            ],
        )

        self.assertNotIn("GoDaddy", result["14"])

    def test_ordered_list_marker_without_space_is_still_structural(self):
        source = "Please provide one item:\n1.We need a demo video for review."
        self.assertEqual(contextual_values(source), ())
        self.assertEqual(structural_list_markers(source), ("1",))
        self.assertEqual(structural_list_markers("1.5 is the target."), ())

        result = validate_rewrite_response(
            {
                "rewrites": [
                    {
                        "message_id": 15,
                        "text": (
                            "For review, please provide the following item:\n"
                            "1. We need a demo video."
                        ),
                    }
                ]
            },
            [
                {
                    "message_id": 15,
                    "speaker": "client",
                    "text": source,
                }
            ],
        )

        self.assertIn("1. We", result["15"])

    def test_dash_ordered_list_markers_are_not_context_numbers(self):
        source = (
            "1 - Keep the first item.\n"
            "2 – Put 5 items on top and 3 on the bottom."
        )
        self.assertEqual(structural_list_markers(source), ("1", "2"))
        self.assertEqual(
            contextual_values(source),
            (("NUMBER", "5"), ("NUMBER", "3")),
        )
        self.assertEqual(structural_list_markers("1-2 days"), ())

        result = validate_rewrite_response(
            {
                "rewrites": [
                    {
                        "message_id": 16,
                        "text": (
                            "1. The first item should be kept.\n"
                            "2. Arrange 7 items on top, leaving 4 on the bottom."
                        ),
                    }
                ]
            },
            [
                {
                    "message_id": 16,
                    "speaker": "client",
                    "text": source,
                }
            ],
        )

        self.assertIn("7 items", result["16"])

    def test_structural_list_classifier_handles_real_format_variants(self):
        weak_sequence = (
            "1-grid of objects\n"
            "2-box with number\n"
            "3-base 10 blocks"
        )
        self.assertEqual(structural_list_markers(weak_sequence), ("1", "2", "3"))
        self.assertEqual(contextual_values(weak_sequence), (("NUMBER", "10"),))

        plain_sequence = (
            "1 #rules\nPurpose: Rules\nDescription: Conduct\n\n"
            "2 #announcements\nPurpose: Updates\nDescription: News\n\n"
            "3 General Voice\nPurpose: Discussion"
        )
        self.assertEqual(structural_list_markers(plain_sequence), ("1", "2", "3"))

        explicit_variants = "***1\\. First***\n2.. Second\n3: Third"
        self.assertEqual(structural_list_markers(explicit_variants), ("1", "2", "3"))

        compact = "1. First item 2. Second item"
        self.assertEqual(structural_list_markers(compact), ("1", "2"))

        for contextual_number in (
            "1 minute",
            "11:00 am to 2:00 pm",
            "3-4 brochures",
            "0.02 ETH",
            "1717 K Street NW",
        ):
            self.assertEqual(structural_list_markers(contextual_number), ())

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


class RewriteBatchCheckpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_singleton_validation_failure_gets_targeted_repair(self):
        inputs = [
            {
                "message_id": 140,
                "speaker": "client",
                "text": "Budget: $25",
                "require_structure_change": False,
            }
        ]

        class FakeApi:
            def __init__(self):
                self.targets = []

            async def call(self, **kwargs):
                target = kwargs["target_requirement"]
                self.targets.append(target)
                if target == "batch_0016":
                    raise ApiError("ValueError: changed structural list numbering")
                payload = {
                    "rewrites": [{"message_id": 140, "text": "Budget: $40"}]
                }
                kwargs["validator"](payload)
                return payload

        api = FakeApi()
        result = await rewrite_batch(api, "P1", 16, inputs, lambda raw: raw)

        self.assertEqual(result, {"140": "Budget: $40"})
        self.assertEqual(
            api.targets,
            ["batch_0016", "batch_0016_message_140"],
        )

    async def test_singleton_fallback_reports_each_success_before_later_failure(self):
        inputs = [
            {
                "message_id": 1,
                "speaker": "client",
                "text": "Budget: $25",
                "require_structure_change": False,
            },
            {
                "message_id": 2,
                "speaker": "client",
                "text": "Timeline: 2 days",
                "require_structure_change": False,
            },
        ]

        class FakeApi:
            async def call(self, **kwargs):
                target = kwargs["target_requirement"]
                if target == "batch_0001":
                    raise ApiError("ValueError: invalid batched rewrite")
                if target == "batch_0001_message_1":
                    payload = {
                        "rewrites": [{"message_id": 1, "text": "Budget: $40"}]
                    }
                    kwargs["validator"](payload)
                    return payload
                raise ApiError("ValueError: invalid singleton rewrite")

        saved_progress: list[dict[str, str]] = []
        with self.assertRaises(ApiError):
            await rewrite_batch(
                FakeApi(),
                "P1",
                1,
                inputs,
                lambda raw: raw,
                lambda progress: saved_progress.append(dict(progress)),
            )

        self.assertEqual(saved_progress, [{"1": "Budget: $40"}])


class LlmPiiPhaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.inputs = [
            {
                "message_id": 1,
                "speaker": "client",
                "text": "Contact Alice at alice@example.com and use ReactNative.",
                "sender_id": "sender-A",
                "must_preserve_terms": ("ReactNative",),
            },
            {
                "message_id": 2,
                "speaker": "freelancer",
                "text": "Alice can confirm it.",
                "sender_id": "sender-A",
                "must_preserve_terms": (),
            },
        ]
        self.auditor = DeterministicPiiCleaner(self.inputs)
        for message in self.inputs:
            self.auditor.sanitize_message(message)
        self.state = LlmPiiReplacementState()

    def valid_payload(self):
        return {
            "cleaned_messages": [
                {
                    "message_id": 1,
                    "text": (
                        "Contact [PERSON_NAME_001] at [EMAIL_001] and use ReactNative."
                    ),
                    "sender_id": "[SENDER_ID_001]",
                    "entities": [
                        {
                            "field": "text",
                            "source": "Alice",
                            "category": "PERSON_NAME",
                            "placeholder": "[PERSON_NAME_001]",
                        },
                        {
                            "field": "text",
                            "source": "alice@example.com",
                            "category": "EMAIL",
                            "placeholder": "[EMAIL_001]",
                        },
                        {
                            "field": "sender_id",
                            "source": "sender-A",
                            "category": "SENDER_ID",
                            "placeholder": "[SENDER_ID_001]",
                        },
                    ],
                },
                {
                    "message_id": 2,
                    "text": "[PERSON_NAME_001] can confirm it.",
                    "sender_id": "[SENDER_ID_001]",
                    "entities": [
                        {
                            "field": "text",
                            "source": "Alice",
                            "category": "PERSON_NAME",
                            "placeholder": "[PERSON_NAME_001]",
                        },
                        {
                            "field": "sender_id",
                            "source": "sender-A",
                            "category": "SENDER_ID",
                            "placeholder": "[SENDER_ID_001]",
                        },
                    ],
                },
            ]
        }

    def test_accepts_llm_pii_replacements_and_commits_stable_mapping(self):
        result = validate_pii_response(
            self.valid_payload(), self.inputs, self.state, self.auditor
        )
        self.state.commit(result.entities)

        self.assertEqual(result.sender_ids["1"], "[SENDER_ID_001]")
        self.assertEqual(self.state.placeholder_for("PERSON_NAME", "alice"), "[PERSON_NAME_001]")
        self.assertEqual(self.state.counts()["SENDER_ID"], 1)

    def test_phase_two_checkpoint_restores_payload_and_mapping(self):
        signature = {"cleaning_version": "test"}
        dependency = "phase-one-output"
        payload = self.valid_payload()
        records = [{"batch_number": 1, "payloads": [payload]}]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "P1" / "phase2_pii.json"
            save_phase_two_checkpoint(
                path, signature, dependency, records
            )
            state, texts, sender_ids, restored_records = (
                restore_phase_two_checkpoint(
                    path,
                    signature,
                    dependency,
                    [self.inputs],
                    self.auditor,
                )
            )

        self.assertEqual(len(restored_records), 1)
        self.assertIn("[EMAIL_001]", texts["1"])
        self.assertEqual(sender_ids["1"], "[SENDER_ID_001]")
        self.assertEqual(
            state.placeholder_for("EMAIL", "alice@example.com"), "[EMAIL_001]"
        )

    def test_rejects_non_pii_edit_from_phase_two(self):
        payload = self.valid_payload()
        payload["cleaned_messages"][0]["text"] = payload["cleaned_messages"][0][
            "text"
        ].replace("Contact", "Email")

        with self.assertRaisesRegex(ValueError, "non-PII content"):
            validate_pii_response(payload, self.inputs, self.state, self.auditor)

    def test_accepts_entities_in_any_response_order(self):
        payload = self.valid_payload()
        payload["cleaned_messages"][0]["entities"].reverse()

        result = validate_pii_response(
            payload, self.inputs, self.state, self.auditor
        )

        self.assertIn("[EMAIL_001]", result.texts["1"])
        self.assertEqual(result.sender_ids["1"], "[SENDER_ID_001]")

    def test_ignores_unused_nested_entity_declaration(self):
        inputs = [
            {
                "message_id": 9,
                "speaker": "client",
                "text": "Contact Alice Smith today.",
                "sender_id": None,
                "must_preserve_terms": (),
            }
        ]
        auditor = DeterministicPiiCleaner(inputs)
        auditor.sanitize_message(inputs[0])
        payload = {
            "cleaned_messages": [
                {
                    "message_id": 9,
                    "text": "Contact [PERSON_NAME_001] today.",
                    "sender_id": None,
                    "entities": [
                        {
                            "field": "text",
                            "source": "Alice Smith",
                            "category": "PERSON_NAME",
                            "placeholder": "[PERSON_NAME_001]",
                        },
                        {
                            "field": "text",
                            "source": "Alice",
                            "category": "PERSON_NAME",
                            "placeholder": "[PERSON_NAME_002]",
                        },
                    ],
                }
            ]
        }

        result = validate_pii_response(
            payload, inputs, LlmPiiReplacementState(), auditor
        )

        self.assertEqual(
            result.entities,
            (("PERSON_NAME", "Alice Smith", "[PERSON_NAME_001]"),),
        )

    def test_rejects_pii_missed_by_llm(self):
        payload = self.valid_payload()
        first = payload["cleaned_messages"][0]
        first["text"] = first["text"].replace("[EMAIL_001]", "alice@example.com")
        first["entities"] = [
            entity for entity in first["entities"] if entity["category"] != "EMAIL"
        ]

        with self.assertRaisesRegex(ValueError, "category=EMAIL"):
            validate_pii_response(payload, self.inputs, self.state, self.auditor)

    def test_rejects_redaction_of_protected_requirement_term(self):
        payload = self.valid_payload()
        first = payload["cleaned_messages"][0]
        first["text"] = first["text"].replace("ReactNative", "[PROJECT_NAME_001]")
        first["entities"].insert(
            2,
            {
                "field": "text",
                "source": "ReactNative",
                "category": "PROJECT_NAME",
                "placeholder": "[PROJECT_NAME_001]",
            },
        )

        with self.assertRaisesRegex(ValueError, "protected requirement term"):
            validate_pii_response(payload, self.inputs, self.state, self.auditor)

    def test_phase_two_redacts_a_public_service_that_survived_phase_one(self):
        inputs = [
            {
                "message_id": 10,
                "speaker": "client",
                "text": "Use Coinbase Commerce for payments.",
                "sender_id": None,
                "must_preserve_terms": (),
            }
        ]
        auditor = DeterministicPiiCleaner(inputs)
        payload = {
            "cleaned_messages": [
                {
                    "message_id": 10,
                    "text": "Use [SERVICE_001] for payments.",
                    "sender_id": None,
                    "entities": [
                        {
                            "field": "text",
                            "source": "Coinbase Commerce",
                            "category": "SERVICE",
                            "placeholder": "[SERVICE_001]",
                        }
                    ],
                }
            ]
        }

        result = validate_pii_response(
            payload, inputs, LlmPiiReplacementState(), auditor
        )

        self.assertEqual(result.texts["10"], "Use [SERVICE_001] for payments.")

    async def test_phase_two_uses_api_and_commits_mapping(self):
        payload = self.valid_payload()

        class FakeApi:
            def __init__(self, response):
                self.response = response
                self.calls = []

            async def call(self, **kwargs):
                self.calls.append(kwargs)
                kwargs["validator"](self.response)
                return self.response

        api = FakeApi(payload)
        result = await redact_pii_batch(
            api,
            "P1",
            1,
            self.inputs,
            self.state,
            self.auditor,
        )

        self.assertEqual(len(api.calls), 1)
        self.assertEqual(api.calls[0]["run_mode"], "PII_CLEAN_REDACT")
        self.assertIn("[EMAIL_001]", result.texts["1"])
        self.assertEqual(self.state.placeholder_for("EMAIL", "alice@example.com"), "[EMAIL_001]")

    def test_empty_sender_id_stays_empty(self):
        inputs = [
            {
                "message_id": 3,
                "speaker": "client",
                "text": "No sensitive content here.",
                "sender_id": "",
                "must_preserve_terms": (),
            }
        ]
        auditor = DeterministicPiiCleaner(inputs)
        result = validate_pii_response(
            {
                "cleaned_messages": [
                    {
                        "message_id": 3,
                        "text": "No sensitive content here.",
                        "sender_id": "",
                        "entities": [],
                    }
                ]
            },
            inputs,
            LlmPiiReplacementState(),
            auditor,
        )
        self.assertEqual(result.sender_ids["3"], "")


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
