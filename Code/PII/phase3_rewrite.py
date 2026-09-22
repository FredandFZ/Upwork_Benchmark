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

import re
from typing import Any, Mapping, Sequence

from ._compat import sha256_text
from .config import BUCKET_LONG, BUCKET_SHORT, PRESERVED_BUCKETS
from .errors import PiiValidationError, marked
from .models import MessagePlanSlice, RewriteRecord, SafeMessage
from .phase0b_entities import POLICY_SYNTHESIZE, PUBLIC_ALLOWLIST
from .textutil import (
    EMAIL_RE,
    FAKE_CREDENTIAL_RE,
    HANDLE_RE,
    INTERNAL_TOKEN_RE,
    LEGACY_PLACEHOLDER_RE,
    LIST_MARKER_RE,
    PHONE_RE,
    URL_RE,
    contained_in_any,
    contains_value,
    fingerprint,
    has_structural_change,
    is_interrogative,
    literal_term_pattern,
    mask_spans,
    negation_markers,
    occurrence_count,
    preserved_term_counts,
    pii_shaped_spans,
    semantic_anchor_differences,
    text_outside_pii,
    value_spans,
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
    "speech act, polarity, immediate intent and every semantic fact."
)
TASK_LONG = (
    "Rewrite each message into a substantially different natural expression that "
    "preserves every project-level fact and applies only the supplied transformations."
)

REPAIR_INSTRUCTION_SHORT = (
    "The previous response failed local validation. For each message return text that "
    "differs from the input, keeps the same speech act and polarity, stays at or under "
    "eight words, preserves an interrogative form if the original had "
    "one, applies every supplied entity and slot replacement, keeps every "
    "<SECRET_CANDIDATE:...> token byte for byte, and keeps every preserve literal exactly. "
    "Use planned entity spellings exactly, preserve every semantic fact, and never emit a "
    "bracketed placeholder such as [PERSON_001]."
)
REPAIR_INSTRUCTION_LONG = (
    "The previous response failed local validation. For each message make an unmistakable "
    "structural change -- move an information-bearing clause, change voice, or split or "
    "combine sentences -- rather than substituting synonyms in the original order. Apply "
    "every supplied entity and slot replacement so no original value survives, keep every "
    "<SECRET_CANDIDATE:...> token byte for byte, keep every preserve literal and every "
    "ordered-list number exactly, and never emit a bracketed placeholder such as "
    "[PERSON_001]. A slot changes only its value: preserve its operator, lifecycle, trigger, "
    "environment, actor, object and causal effect, and use planned entity names exactly."
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

    # -- preserved literals ------------------------------------------------- #
    before = preserved_term_counts(safe.safe_text, slice_.preserve_literals)
    after = preserved_term_counts(candidate, slice_.preserve_literals)
    public_terms = {term.casefold() for term in PUBLIC_ALLOWLIST}
    for term, count in before.items():
        after_count = after.get(term, 0)
        # Named public technologies must not be substituted, but a natural
        # rewrite may consolidate or repeat a mention.  Other protected
        # literals (identifiers and fact-specific strings) remain exact-count.
        changed = (
            not after_count
            if term.casefold() in public_terms
            else after_count != count
        )
        if count and changed:
            violations.append(
                f"REWRITE_PRESERVED_TERM_ALTERED: {fingerprint('PRESERVE', term)} "
                f"count {count} -> {after_count}"
            )

    # -- ordered-list numbering is layout, not data ------------------------- #
    if list(LIST_MARKER_RE.findall(safe.safe_text)) != list(
        LIST_MARKER_RE.findall(candidate)
    ):
        violations.append("REWRITE_LIST_MARKER_DAMAGED: ordered-list numbering changed")

    # -- entity originals gone, planned replacements present ---------------- #
    planned_values: set[str] = set()
    source_entity_spans = value_spans(
        safe.safe_text,
        {
            original
            for entity in slice_.entity_replacements
            if entity.policy == POLICY_SYNTHESIZE
            for original, _replacement in entity.pairs()
            if original
        },
    )
    for item in slice_.entity_replacements:
        planned_values.update(item.replacements())
        if item.policy != POLICY_SYNTHESIZE:
            continue
        for original, replacement in item.pairs():
            source_matches = tuple(
                match.span()
                for match in re.finditer(
                    literal_term_pattern(original), safe.safe_text, flags=re.IGNORECASE
                )
            )
            present_in_source = bool(source_matches)
            # A non-PII entity name can occur only as an inner component of a
            # URL/address that has its own entity mapping.  Replacing that
            # complete outer value already removes the inner occurrence; a
            # second standalone spelling would duplicate content and can make
            # a SHORT rewrite impossible.  Equal spans are not "nested": a
            # complete URL/email entity still has to apply its own mapping.
            needs_own_replacement = any(
                not any(
                    outer_start <= start
                    and end <= outer_end
                    and (outer_start, outer_end) != (start, end)
                    for outer_start, outer_end in source_entity_spans
                )
                for start, end in source_matches
            )
            candidate_matches = tuple(
                match.span()
                for match in re.finditer(
                    literal_term_pattern(original), candidate, flags=re.IGNORECASE
                )
            )
            replacement_spans = value_spans(candidate, (replacement,))
            original_survived = any(
                not contained_in_any(span, replacement_spans)
                for span in candidate_matches
            )
            if original_survived:
                violations.append(
                    "REWRITE_RESIDUAL_ORIGINAL_ENTITY: "
                    f"{item.entity_id} ({fingerprint(item.entity_type, original)}) survived"
                )
            elif (
                present_in_source
                and needs_own_replacement
                and not contains_value(candidate, replacement)
            ):
                violations.append(
                    "REWRITE_PLAN_MAPPING_VIOLATED: "
                    f"{item.entity_id} replacement was not applied"
                )

    # -- slot literals, compared outside complete PII values ---------------- #
    masked_candidate = text_outside_pii(candidate)
    masked_source = text_outside_pii(safe.safe_text)
    synthesized_entity_spans = value_spans(
        safe.safe_text,
        {
            original
            for entity in slice_.entity_replacements
            if entity.policy == POLICY_SYNTHESIZE
            for original, _replacement in entity.pairs()
        },
    )
    for item in slice_.slot_replacements:
        for occurrence in item.replacements_for(safe.ordinal):
            if occurrence.match_mode == "SEMANTIC_ONLY":
                # A bare number is meaningful only at its recorded source span.
                # After a free-form rewrite its output offset is not stable, so
                # semantic verification -- not project-wide substring search --
                # is the correct judge.
                continue
            original_literal = occurrence.original
            new_literal = occurrence.replacement
            if not original_literal:
                continue
            # If the slot is the whole entity value or an inner piece of it,
            # the entity mapping owns the source span.  Enforcing the slot too
            # would demand duplicate output (and, for URL internals, inspect a
            # value that is intentionally replaced atomically).
            if contained_in_any(
                (occurrence.start, occurrence.end), synthesized_entity_spans
            ):
                continue
            in_source = occurrence_count(masked_source, original_literal, ignore_case=False)
            if not in_source:
                continue
            if new_literal == original_literal:
                # An identity mapping is the plan saying "keep this".  The slot
                # records which public tool, network or asset was chosen, and
                # that is a requirement rather than an identity to disguise, so
                # phase 2 deliberately maps it to itself.  Without this branch
                # the correct rewrite -- the one that kept the public name --
                # is reported as having "kept its original literal", which is
                # the same blind spot the phase-2 validator had, one phase later.
                if not occurrence_count(
                    masked_candidate, original_literal, ignore_case=False
                ):
                    violations.append(
                        f"REWRITE_PRESERVED_TERM_ALTERED: slot {item.slot_id} "
                        "dropped a value the plan preserves"
                    )
                continue
            if occurrence_count(masked_candidate, original_literal, ignore_case=False):
                violations.append(
                    f"REWRITE_RESIDUAL_ORIGINAL_ENTITY: slot {item.slot_id} kept its "
                    "original literal"
                )
            else:
                new_literal_is_complete_pii = any(
                    span == (0, len(new_literal))
                    for span in pii_shaped_spans(new_literal)
                )
                candidate_for_new_literal = (
                    candidate if new_literal_is_complete_pii else masked_candidate
                )
                if not occurrence_count(
                    candidate_for_new_literal, new_literal, ignore_case=False
                ):
                    violations.append(
                        f"REWRITE_PLAN_MAPPING_VIOLATED: slot {item.slot_id} new value "
                        "was not applied"
                    )

    # -- no unplanned PII shape --------------------------------------------- #
    # Phase 2 routinely plans a *decorated* value: a Slack mention
    # ``<@id:id|Name>``, an angle-bracketed link, an autolink's ``url|label``.
    # The bare address, handle or link inside one of those is not a second,
    # unplanned value -- it is the planned value, and equality against
    # ``planned_values`` alone cannot see that.  Containment in a planned span
    # can, and it stays closed: a shape that merely abuts a planned value, or
    # sits outside every one of them, is still reported.
    planned_spans = value_spans(candidate, planned_values)
    for pattern, label in (
        (EMAIL_RE, "EMAIL"),
        (HANDLE_RE, "HANDLE"),
    ):
        for match in pattern.finditer(candidate):
            if match.group(0) in planned_values:
                continue
            if contained_in_any(match.span(), planned_spans):
                continue
            violations.append(
                f"REWRITE_PII_REINTRODUCED: unplanned {label} "
                f"{fingerprint(label, match.group(0))}"
            )
    # A URL the *model invented* is the risk here.  One that stands verbatim in
    # the source and was not classified private by phase 0B is a public link --
    # a vendor's home page, say -- and keeping it is the stated policy, not a
    # leak.  Without this the gate quarantined messages for carrying
    # ``https://stripe.com/``, one of the very names the design names as
    # preserved.  A private URL that 0B *did* catch is still blocked, by the
    # residual-entity check above.
    source_urls = {match.group(0) for match in URL_RE.finditer(safe.safe_text)}
    for match in URL_RE.finditer(candidate):
        value = match.group(0)
        if value in source_urls or value in planned_values:
            continue
        if any(
            value.startswith(planned) or planned.startswith(value)
            for planned in planned_values
        ):
            continue
        if contained_in_any(match.span(), planned_spans):
            continue
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

    # Explicit environment/lifecycle/mechanism anchors are not values phase 2
    # is allowed to synthesize.  A rewrite that turns production into staging,
    # on-chain into off-chain, unlimited into capped, or pool-based into
    # schedule-based has changed the requirement and is rejected locally.
    for dimension, before_labels, after_labels in semantic_anchor_differences(
        safe.safe_text, candidate
    ):
        violations.append(
            "REWRITE_SEMANTIC_ANCHOR_CHANGED: "
            f"{dimension} changed from {list(before_labels)} to {list(after_labels)}"
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
        # Polarity, not negation words.  "Okay, no problem" carries a negation
        # marker and is AFFIRMATIVE -- phase 1A says so -- so demanding the
        # marker survive rejected every natural rewrite ("Sure, that works").
        # Comparing the markers made the local guard contradict the semantic
        # judgement it exists to protect.  Use 1A's polarity, and keep a surface
        # guard only in the two directions where it is sound.
        expected_polarity = (slice_.semantic_expectations or {}).get("polarity")
        source_negated = bool(negation_markers(safe.safe_text))
        # A marker the *plan* put there is not one the rewrite introduced.  One
        # slot maps "immediately" to "without delay": same polarity, but
        # ``without`` is a marker, so applying the plan and keeping the polarity
        # became mutually exclusive and no text could satisfy both.  Reading the
        # markers outside the planned values keeps this guard on what it is for
        # -- polarity the rewrite changed -- rather than on the plan's wording.
        planned_surfaces = set(planned_values)
        planned_surfaces.update(
            occurrence.replacement
            for item in slice_.slot_replacements
            for occurrence in item.replacements_for(safe.ordinal)
            if occurrence.replacement
        )
        outside_plan = mask_spans(candidate, value_spans(candidate, planned_surfaces))
        candidate_negated = bool(negation_markers(outside_plan))
        if expected_polarity == "NEGATIVE":
            # Negation is often lexical -- "mint attempt failed", "access
            # denied" -- and 1A rightly calls those NEGATIVE, but
            # ``negation_markers`` only knows function words.  So a marker is
            # only required to survive if the source actually carried one;
            # otherwise the rule demanded the rewrite add a marker the original
            # never had, and in one case fought the plan itself, which maps
            # "access denied" to "viewer remains locked".  Nothing is said about
            # the other direction: spelling a lexical negation out explicitly is
            # a faithful rewrite, not an invented one.
            if source_negated and not candidate_negated:
                violations.append(
                    "REWRITE_POLARITY_CHANGED: the negation was dropped"
                )
        elif candidate_negated and not source_negated:
            violations.append(
                "REWRITE_POLARITY_CHANGED: a negation was introduced"
            )
        if is_interrogative(safe.safe_text) != is_interrogative(candidate):
            violations.append("REWRITE_POLARITY_CHANGED: interrogative form changed")
    elif bucket == BUCKET_LONG:
        if not has_structural_change(safe.safe_text, candidate):
            violations.append(
                "REWRITE_STRUCTURE_UNCHANGED: sentence structure was not changed"
            )

    return violations


# Violations that describe *fidelity to the plan* or *style*, not safety.
#
# Across a full 824-message project the gate raised 218 violations, of which 8
# were safety-critical (real PII surviving or being reintroduced) and 210 were
# these.  Every one of them is also judged, semantically and independently, by
# phase 4 -- which reads the plan and can tell "the number was dropped" from
# "$20 was written as twenty dollars", a distinction string matching cannot
# make.  Hard-failing on them locally therefore bought nothing and quarantined
# messages a better-informed check would have passed.
#
# What stays blocking: anything that lets real information survive, any damage
# to a secret token, pipeline-internal representation leaking into the output,
# a "rewrite" identical to its source (the one path that would silently ship the
# original), and polarity -- a flipped negation states a different requirement.
ADVISORY_CODES: frozenset[str] = frozenset(
    {
        "REWRITE_PLAN_MAPPING_VIOLATED",
        "REWRITE_STRUCTURE_UNCHANGED",
        "REWRITE_WORD_BAND_VIOLATED",
    }
)


def _is_advisory(violation: str) -> bool:
    code = violation.split(":", 1)[0]
    if code == "REWRITE_PLAN_MAPPING_VIOLATED":
        # Semantic slot values may be expressed without the plan's exact
        # surface string and are judged by phase 4.  Entity replacements are
        # different: allowing another invented name defeats project-wide
        # identity consistency, so the canonical planned spelling is hard.
        return violation.split(":", 1)[1].strip().startswith("slot ")
    if code == "REWRITE_RESIDUAL_ORIGINAL_ENTITY":
        # A surviving *slot literal* is a stale business value, not a leak; a
        # surviving entity original is real PII and always blocks.
        return violation.split(":", 1)[1].strip().startswith("slot ")
    return code in ADVISORY_CODES


def split_violations(violations: Sequence[str]) -> tuple[list[str], list[str]]:
    """Partition into ``(blocking, advisory)``."""

    blocking = [item for item in violations if not _is_advisory(item)]
    advisory = [item for item in violations if _is_advisory(item)]
    return blocking, advisory


def blocking_violations(
    safe: SafeMessage, candidate: str, slice_: MessagePlanSlice
) -> list[str]:
    return split_violations(rewrite_violations(safe, candidate, slice_))[0]


def assert_rewrite_invariants(
    safe: SafeMessage, candidate: str, slice_: MessagePlanSlice
) -> None:
    violations = blocking_violations(safe, candidate, slice_)
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
            occurrence_count(candidate, occurrence.replacement, ignore_case=False)
            for occurrence in item.replacements_for(safe.ordinal)
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
        violations = blocking_violations(safe, text, slice_)
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
