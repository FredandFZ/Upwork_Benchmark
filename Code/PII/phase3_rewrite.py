"""Phase 3: rewrite each message, applying the plan.

``assert_rewrite_invariants`` is the single gate every candidate text passes,
whoever wrote it -- phase 3, phase 5, or a repairing agent via ``finalize``.
The agent gets no privileged path around it.

Two subtleties in the comparisons:

* **Entity originals are checked on the raw text**, because a surviving address
  or name is exactly what must be caught.
* **Slot literals are checked on the text with PII-shaped values masked**,
  because the digits inside a synthetic URL or address are part of that value,
  not a retained business number.  v6 documented this trap at
  ``Code/PII_Clean.py:1822-1831``.

Bucket policy: ``EMPTY`` and ``PRESERVE_SHORT`` keep the shielded original byte
for byte; ``SHORT`` must differ but is not required to restructure; ``LONG``
must pass :func:`textutil.has_structural_change`.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ._compat import sha256_text
from .config import BUCKET_LONG, BUCKET_SHORT, PRESERVED_BUCKETS
from .errors import PiiValidationError, marked
from .models import MessagePlanSlice, RewriteRecord, SafeMessage
from .phase0b_entities import POLICY_SYNTHESIZE
from .textutil import (
    EMAIL_RE,
    FAKE_CREDENTIAL_RE,
    HANDLE_RE,
    INTERNAL_TOKEN_RE,
    LEGACY_PLACEHOLDER_RE,
    LIST_MARKER_RE,
    PHONE_RE,
    URL_RE,
    contains_value,
    fingerprint,
    has_structural_change,
    is_interrogative,
    negation_markers,
    occurrence_count,
    preserved_term_counts,
    text_outside_pii,
    word_count,
)

SHORT_WORD_TOLERANCE = 2
# The band exists to stop a brief acknowledgement being inflated into a
# paragraph -- so it is an absolute ceiling with headroom, not a tight window
# around the source length.  A 2-word ``Password: <token>`` promoted into SHORT
# has no natural rewrite within +/-2 words ("The account password is <token>" is
# five), and pinning it to the source would make the task unsatisfiable.
SHORT_WORD_CEILING = 8

TASK_SHORT = (
    "Rewrite each short message with clearly different wording while preserving its "
    "speech act, polarity and immediate intent."
)
TASK_LONG = (
    "Rewrite each message into a substantially different natural expression that "
    "preserves its project-level meaning and applies every supplied transformation."
)

REPAIR_INSTRUCTION_SHORT = (
    "The previous response failed local validation. For each message return text that "
    "differs from the input, keeps the same speech act and polarity, stays at or under "
    "eight words, preserves an interrogative form if the original had "
    "one, applies every supplied entity and slot replacement, keeps every "
    "<SECRET_CANDIDATE:...> token byte for byte, and keeps every preserve literal exactly. "
    "Never emit a bracketed placeholder such as [PERSON_001]."
)
REPAIR_INSTRUCTION_LONG = (
    "The previous response failed local validation. For each message make an unmistakable "
    "structural change -- move an information-bearing clause, change voice, or split or "
    "combine sentences -- rather than substituting synonyms in the original order. Apply "
    "every supplied entity and slot replacement so no original value survives, keep every "
    "<SECRET_CANDIDATE:...> token byte for byte, keep every preserve literal and every "
    "ordered-list number exactly, and never emit a bracketed placeholder such as "
    "[PERSON_001]."
)


def task_for(bucket: str) -> str:
    return TASK_LONG if bucket == BUCKET_LONG else TASK_SHORT


def repair_instruction_for(bucket: str) -> str:
    return REPAIR_INSTRUCTION_LONG if bucket == BUCKET_LONG else REPAIR_INSTRUCTION_SHORT


def partition_by_bucket(
    safe_messages: Sequence[SafeMessage],
) -> dict[str, list[SafeMessage]]:
    buckets: dict[str, list[SafeMessage]] = {}
    for item in safe_messages:
        buckets.setdefault(item.bucket, []).append(item)
    return buckets


def preserved_record(safe: SafeMessage) -> RewriteRecord:
    """The record for a bucket that keeps its text verbatim.

    Reachable only for ``EMPTY`` and ``PRESERVE_SHORT``, which the pipeline has
    already confirmed carry no entity, secret token or slot.
    """

    if safe.bucket not in PRESERVED_BUCKETS:
        raise PiiValidationError(
            marked(f"bucket {safe.bucket} may not be preserved verbatim")
        )
    return RewriteRecord(
        ordinal=safe.ordinal,
        message_id=safe.message_id,
        bucket=safe.bucket,
        text=safe.safe_text,
        text_sha256=safe.safe_text_sha256,
        applied_entity_ids=(),
        applied_slot_ids=(),
        retained_secret_tokens=safe.secret_tokens,
        structural_change=False,
        source="LOCAL_PRESERVED",
        attempt=1,
    )


def build_sections(
    items: Sequence[SafeMessage],
    slices: Mapping[int, MessagePlanSlice],
    *,
    bucket: str,
) -> dict[str, Any]:
    return {
        "POLICY": {
            "bucket": bucket,
            "require_structural_change": bucket == BUCKET_LONG,
            "short_word_ceiling": SHORT_WORD_CEILING if bucket == BUCKET_SHORT else None,
        },
        "SAFE_MESSAGES": [
            {
                "ordinal": item.ordinal,
                "message_id": item.message_id,
                "speaker": item.speaker,
                "text": item.safe_text,
                "word_count": item.word_count,
            }
            for item in items
        ],
        "PLAN_SLICE": {
            str(item.ordinal): slices[item.ordinal].to_json()
            for item in items
            if item.ordinal in slices
        },
    }


def shard_sizer(item: SafeMessage) -> int:
    return len(item.safe_text) + 400


# --------------------------------------------------------------------------- #
# The shared gate
# --------------------------------------------------------------------------- #


def rewrite_violations(
    safe: SafeMessage, candidate: str, slice_: MessagePlanSlice
) -> list[str]:
    """Every local reason ``candidate`` is not an acceptable rewrite."""

    violations: list[str] = []
    bucket = safe.bucket

    # -- pipeline-internal representation may never survive ----------------- #
    if LEGACY_PLACEHOLDER_RE.search(candidate):
        violations.append(
            "REWRITE_LEGACY_PLACEHOLDER: output contains a bracketed placeholder"
        )
    if FAKE_CREDENTIAL_RE.search(candidate):
        violations.append(
            "REWRITE_FAKE_CREDENTIAL: only phase 6A may introduce a rendered credential"
        )

    # -- secret tokens: byte-exact, same multiset --------------------------- #
    expected_tokens = sorted(safe.secret_tokens)
    actual_tokens = sorted(INTERNAL_TOKEN_RE.findall(candidate))
    if expected_tokens != actual_tokens:
        violations.append(
            "REWRITE_PROTECTED_TOKEN_DAMAGED: secret tokens changed "
            f"({len(expected_tokens)} expected, {len(actual_tokens)} present)"
        )

    # -- preserved literals keep their exact count -------------------------- #
    before = preserved_term_counts(safe.safe_text, slice_.preserve_literals)
    after = preserved_term_counts(candidate, slice_.preserve_literals)
    for term, count in before.items():
        if count and after.get(term, 0) != count:
            violations.append(
                f"REWRITE_PRESERVED_TERM_ALTERED: {fingerprint('PRESERVE', term)} "
                f"count {count} -> {after.get(term, 0)}"
            )

    # -- ordered-list numbering is layout, not data ------------------------- #
    if list(LIST_MARKER_RE.findall(safe.safe_text)) != list(
        LIST_MARKER_RE.findall(candidate)
    ):
        violations.append("REWRITE_LIST_MARKER_DAMAGED: ordered-list numbering changed")

    # -- entity originals gone, planned replacements present ---------------- #
    planned_values: set[str] = set()
    for item in slice_.entity_replacements:
        planned_values.update(item.replacements())
        if item.policy != POLICY_SYNTHESIZE:
            continue
        for original, replacement in item.pairs():
            present_in_source = contains_value(safe.safe_text, original)
            if contains_value(candidate, original):
                violations.append(
                    "REWRITE_RESIDUAL_ORIGINAL_ENTITY: "
                    f"{item.entity_id} ({fingerprint(item.entity_type, original)}) survived"
                )
            elif present_in_source and not contains_value(candidate, replacement):
                violations.append(
                    "REWRITE_PLAN_MAPPING_VIOLATED: "
                    f"{item.entity_id} replacement was not applied"
                )

    # -- slot literals, compared outside complete PII values ---------------- #
    masked_candidate = text_outside_pii(candidate)
    masked_source = text_outside_pii(safe.safe_text)
    for item in slice_.slot_replacements:
        for original_literal, new_literal in item.literal_map.items():
            if not original_literal:
                continue
            in_source = occurrence_count(masked_source, original_literal, ignore_case=False)
            if not in_source:
                continue
            if occurrence_count(masked_candidate, original_literal, ignore_case=False):
                violations.append(
                    f"REWRITE_RESIDUAL_ORIGINAL_ENTITY: slot {item.slot_id} kept its "
                    "original literal"
                )
            elif not occurrence_count(masked_candidate, new_literal, ignore_case=False):
                violations.append(
                    f"REWRITE_PLAN_MAPPING_VIOLATED: slot {item.slot_id} new value "
                    "was not applied"
                )

    # -- no unplanned PII shape --------------------------------------------- #
    for pattern, label in (
        (EMAIL_RE, "EMAIL"),
        (HANDLE_RE, "HANDLE"),
    ):
        for match in pattern.finditer(candidate):
            if match.group(0) not in planned_values:
                violations.append(
                    f"REWRITE_PII_REINTRODUCED: unplanned {label} "
                    f"{fingerprint(label, match.group(0))}"
                )
    for match in URL_RE.finditer(candidate):
        value = match.group(0)
        if value not in planned_values and not any(
            value.startswith(planned) or planned.startswith(value)
            for planned in planned_values
        ):
            violations.append(
                f"REWRITE_PII_REINTRODUCED: unplanned URL {fingerprint('URL', value)}"
            )
    source_phones = {
        "".join(character for character in match.group(0) if character.isdigit())
        for match in PHONE_RE.finditer(safe.safe_text)
    }
    for match in PHONE_RE.finditer(candidate):
        digits = "".join(character for character in match.group(0) if character.isdigit())
        if digits and digits in source_phones:
            violations.append(
                "REWRITE_PII_REINTRODUCED: a source phone number survived"
            )

    # -- bucket policy ------------------------------------------------------ #
    if bucket in PRESERVED_BUCKETS:
        if candidate != safe.safe_text:
            violations.append(
                f"REWRITE_WORD_BAND_VIOLATED: bucket {bucket} must keep its text verbatim"
            )
        return violations

    if not candidate.strip():
        violations.append("REWRITE_SCHEMA_INVALID: rewrite is empty")
        return violations

    if candidate.strip() == safe.safe_text.strip():
        violations.append("REWRITE_UNCHANGED: rewrite is identical to the input")

    if bucket == BUCKET_SHORT:
        length = word_count(candidate)
        ceiling = max(safe.word_count + SHORT_WORD_TOLERANCE, SHORT_WORD_CEILING)
        floor = max(1, safe.word_count - SHORT_WORD_TOLERANCE)
        if length > ceiling:
            violations.append(
                f"REWRITE_WORD_BAND_VIOLATED: short rewrite grew to {length} words, "
                f"over the ceiling of {ceiling}"
            )
        elif length < floor:
            violations.append(
                f"REWRITE_WORD_BAND_VIOLATED: short rewrite shrank to {length} words, "
                f"under the floor of {floor}"
            )
        if negation_markers(candidate) != negation_markers(safe.safe_text):
            violations.append("REWRITE_POLARITY_CHANGED: negation markers changed")
        if is_interrogative(safe.safe_text) != is_interrogative(candidate):
            violations.append("REWRITE_POLARITY_CHANGED: interrogative form changed")
    elif bucket == BUCKET_LONG:
        if not has_structural_change(safe.safe_text, candidate):
            violations.append(
                "REWRITE_STRUCTURE_UNCHANGED: sentence structure was not changed"
            )

    return violations


def assert_rewrite_invariants(
    safe: SafeMessage, candidate: str, slice_: MessagePlanSlice
) -> None:
    violations = rewrite_violations(safe, candidate, slice_)
    if violations:
        raise PiiValidationError(
            marked(
                f"rewrite for ordinal {safe.ordinal} is invalid: "
                + "; ".join(violations[:8])
            ),
            failures=tuple(item.split(":", 1)[0] for item in violations),
            details=tuple({"violation": item} for item in violations),
        )


def make_record(
    safe: SafeMessage,
    candidate: str,
    slice_: MessagePlanSlice,
    *,
    source: str,
    attempt: int = 1,
) -> RewriteRecord:
    applied_entities = tuple(
        item.entity_id
        for item in slice_.entity_replacements
        if item.policy == POLICY_SYNTHESIZE
        and any(contains_value(candidate, value) for value in item.replacements())
    )
    applied_slots = tuple(
        item.slot_id
        for item in slice_.slot_replacements
        if any(
            occurrence_count(candidate, value, ignore_case=False)
            for value in item.literal_map.values()
        )
    )
    return RewriteRecord(
        ordinal=safe.ordinal,
        message_id=safe.message_id,
        bucket=safe.bucket,
        text=candidate,
        text_sha256=sha256_text(candidate),
        applied_entity_ids=applied_entities,
        applied_slot_ids=applied_slots,
        retained_secret_tokens=tuple(sorted(INTERNAL_TOKEN_RE.findall(candidate))),
        structural_change=has_structural_change(safe.safe_text, candidate),
        source=source,
        attempt=attempt,
    )


def validate_rewrite_response(
    payload: Mapping[str, Any],
    items: Sequence[SafeMessage],
    slices: Mapping[int, MessagePlanSlice],
    *,
    source: str = "LLM",
    attempt: int = 1,
) -> dict[int, RewriteRecord]:
    failures: list[str] = []
    codes: list[str] = []
    raw = payload.get("rewrites")
    if not isinstance(raw, list):
        raise PiiValidationError(
            marked("REWRITE_SCHEMA_INVALID: response must contain a rewrites list"),
            failures=("REWRITE_SCHEMA_INVALID",),
        )

    expected = {item.ordinal: item for item in items}
    result: dict[int, RewriteRecord] = {}
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            failures.append(f"rewrites[{index}] must be an object")
            codes.append("REWRITE_SCHEMA_INVALID")
            continue
        ordinal = entry.get("ordinal")
        if not isinstance(ordinal, int) or ordinal not in expected:
            failures.append(f"rewrites[{index}] has an unknown ordinal")
            codes.append("REWRITE_SCHEMA_INVALID")
            continue
        if ordinal in result:
            failures.append(f"ordinal {ordinal} appears twice")
            codes.append("REWRITE_SCHEMA_INVALID")
            continue
        text = entry.get("text")
        if not isinstance(text, str):
            failures.append(f"ordinal {ordinal} text is not a string")
            codes.append("REWRITE_SCHEMA_INVALID")
            continue
        safe = expected[ordinal]
        slice_ = slices.get(ordinal)
        if slice_ is None:
            failures.append(f"ordinal {ordinal} has no plan slice")
            codes.append("REWRITE_SCHEMA_INVALID")
            continue
        violations = rewrite_violations(safe, text, slice_)
        if violations:
            failures.extend(f"ordinal {ordinal}: {item}" for item in violations[:4])
            codes.extend(item.split(":", 1)[0] for item in violations)
            continue
        result[ordinal] = make_record(safe, text, slice_, source=source, attempt=attempt)

    missing = sorted(set(expected).difference(result))
    if missing and not failures:
        failures.append(f"omitted ordinals {missing[:20]}")
        codes.append("REWRITE_SCHEMA_INVALID")

    if failures:
        raise PiiValidationError(
            marked("phase 3 validation failed: " + "; ".join(failures[:8])),
            failures=tuple(dict.fromkeys(codes)),
        )
    return result


def validate_cached_rewrite(
    body: Any, safe: SafeMessage, slice_: MessagePlanSlice
) -> None:
    """Re-validate a restored rewrite against the current rules and slice."""

    record = RewriteRecord.from_json(body)
    if record.ordinal != safe.ordinal:
        raise PiiValidationError(marked("cached rewrite belongs to another message"))
    if record.bucket != safe.bucket:
        raise PiiValidationError(marked("cached rewrite used a different bucket"))
    assert_rewrite_invariants(safe, record.text, slice_)
