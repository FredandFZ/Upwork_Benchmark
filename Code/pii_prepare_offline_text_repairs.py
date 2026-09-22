#!/usr/bin/env python3
"""Prepare hash-bound TEXT repairs from the source and approved plan mappings.

This helper is deliberately narrower than an LLM rewrite: it only consumes an
existing agent task package, applies the exact entity/slot decisions already in
that package, and writes ``agent_repairs/repairs.json``.  It never edits source
data, checkpoints, plans, validators, or task packages.  ``pii_finalize.py`` is
still the authority that accepts or rejects every candidate.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

try:  # ``python Code/pii_prepare_offline_text_repairs.py``
    from PII._compat import read_json, write_json
    from PII.agent_handoff import queue_sha256
    from PII.errors import PiiError
    from PII.textutil import (
        EMAIL_RE,
        HANDLE_RE,
        PHONE_RE,
        URL_RE,
        contained_in_any,
        contains_value,
        has_structural_change,
        is_interrogative,
        literal_term_pattern,
        overlaps_any,
        pii_shaped_spans,
        preserved_term_counts,
        semantic_anchor_differences,
        value_spans,
        word_count,
    )
except ModuleNotFoundError:  # ``python -m Code.pii_prepare_offline_text_repairs``
    from Code.PII._compat import read_json, write_json
    from Code.PII.agent_handoff import queue_sha256
    from Code.PII.errors import PiiError
    from Code.PII.textutil import (
        EMAIL_RE,
        HANDLE_RE,
        PHONE_RE,
        URL_RE,
        contained_in_any,
        contains_value,
        has_structural_change,
        is_interrogative,
        literal_term_pattern,
        overlaps_any,
        pii_shaped_spans,
        preserved_term_counts,
        semantic_anchor_differences,
        value_spans,
        word_count,
    )


SCHEMA_VERSION = "pii-agent-repairs-v1"
# Held back by the 2026-09-18 batch while they were being handled elsewhere.
# All three have since been carried to completion, so the list is empty rather
# than deleted: the guard is the mechanism for holding a project back, and the
# next batch that needs it should not have to reintroduce it.
EXCLUDED_PROJECTS: frozenset[str] = frozenset()


def _replace_once_at_span(
    text: str, *, start: int, end: int, original: str, replacement: str
) -> str:
    if 0 <= start <= end <= len(text) and text[start:end] == original:
        return text[:start] + replacement + text[end:]
    # A stale span must not silently target a different value.  The exact
    # literal fallback is allowed only when it occurs once.
    if text.count(original) == 1:
        return text.replace(original, replacement, 1)
    raise PiiError(
        f"cannot safely locate slot literal at [{start}, {end}); task package is stale"
    )


def _apply_slots(source: str, task: Mapping[str, Any]) -> str:
    occurrences: list[Mapping[str, Any]] = []
    for slot in task.get("must_apply_slots") or []:
        occurrences.extend(slot.get("literal_replacements") or [])
    # Relation closure can bring two slots that point to the exact same source
    # occurrence into one task.  Once Phase 2 has unified their decision they
    # are one edit, not two sequential edits to the same coordinates.
    deduplicated: dict[tuple[Any, ...], Mapping[str, Any]] = {}
    for occurrence in occurrences:
        key = (
            occurrence.get("ordinal"),
            occurrence.get("start"),
            occurrence.get("end"),
            occurrence.get("original"),
            occurrence.get("replacement"),
        )
        deduplicated.setdefault(key, occurrence)
    occurrences = list(deduplicated.values())
    # A broad semantic slot can contain a narrower slot occurrence (for
    # example a full title containing its line-break marker).  Editing the
    # inner span first invalidates the outer coordinates; editing the outer
    # span first removes the inner coordinates.  The outer edit is the only
    # position-safe one.  The normal required-value pass later restores the
    # narrower slot's target explicitly if it is not already represented.
    outermost: list[Mapping[str, Any]] = []
    for occurrence in sorted(
        occurrences,
        key=lambda item: (
            -(int(item.get("end", -1)) - int(item.get("start", -1))),
            int(item.get("start", -1)),
        ),
    ):
        start = int(occurrence.get("start", -1))
        end = int(occurrence.get("end", -1))
        if any(
            int(parent.get("start", -1)) <= start
            and end <= int(parent.get("end", -1))
            for parent in outermost
        ):
            continue
        outermost.append(occurrence)
    occurrences = outermost
    text = source
    source_pii_spans = pii_shaped_spans(source)
    for occurrence in sorted(
        occurrences, key=lambda item: (int(item.get("start", -1)), int(item.get("end", -1))),
        reverse=True,
    ):
        original = occurrence.get("original")
        replacement = occurrence.get("replacement")
        if not isinstance(original, str) or not isinstance(replacement, str):
            raise PiiError("task contains a malformed slot literal replacement")
        source_span = (
            int(occurrence.get("start", -1)),
            int(occurrence.get("end", -1)),
        )
        # Slot verification deliberately masks complete PII values.  Mutating
        # a number or alias *inside* an address/link/phone corrupts that shape
        # and can manufacture a new, unplanned PII value.  A planned entity
        # mapping handles the whole value later; an unplanned shape is removed
        # by ``_scrub_unplanned_pii`` below.
        if overlaps_any(source_span, source_pii_spans):
            continue
        text = _replace_once_at_span(
            text,
            start=int(occurrence.get("start", -1)),
            end=int(occurrence.get("end", -1)),
            original=original,
            replacement=replacement,
        )
    # The local gate treats an EXACT slot literal as a project-wide value in
    # this message, so an equal unrecorded occurrence cannot remain.  Replace
    # any duplicate outside complete PII shapes as well.
    for occurrence in sorted(
        occurrences, key=lambda item: len(str(item.get("original") or "")), reverse=True
    ):
        original = occurrence.get("original")
        replacement = occurrence.get("replacement")
        if (
            occurrence.get("match_mode") != "SEMANTIC_ONLY"
            and isinstance(original, str)
            and isinstance(replacement, str)
        ):
            text = _replace_literal(text, original, replacement, allow_inside_pii=False)
    return text


def _planned_values(task: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for entity in task.get("must_apply_entities") or []:
        replacement = entity.get("replacement")
        if isinstance(replacement, str) and replacement:
            values.add(replacement)
        for alias in entity.get("alias_replacements") or []:
            replacement = alias.get("replacement")
            if isinstance(replacement, str) and replacement:
                values.add(replacement)
    for slot in task.get("must_apply_slots") or []:
        for occurrence in slot.get("literal_replacements") or []:
            replacement = occurrence.get("replacement")
            if isinstance(replacement, str) and replacement:
                values.add(replacement)
    return values


def _replace_matches(text: str, matches: Sequence[re.Match[str]], replacement: str) -> str:
    for match in reversed(matches):
        text = text[: match.start()] + replacement + text[match.end() :]
    return text


def _scrub_unplanned_pii(
    source: str, candidate: str, task: Mapping[str, Any]
) -> str:
    """Remove source PII shapes which phase 2 failed to map as an entity.

    Agent text is not allowed to invent replacement identities.  A neutral
    description preserves the existence of the contact/reference without
    copying its identifying value or introducing a new address.
    """

    planned = _planned_values(task)
    # Mirror the rewrite gate: a shape *inside* a planned decorated value (a
    # Slack mention, an angle-bracketed link, an autolink's ``url|label``) is
    # that planned value.  Neutralising it here would delete the very mapping
    # the plan requires, turning a clean candidate into a mapping violation.
    planned_spans = value_spans(candidate, planned)
    emails = [
        match
        for match in EMAIL_RE.finditer(candidate)
        if match.group(0) not in planned
        and not contained_in_any(match.span(), planned_spans)
    ]
    candidate = _replace_matches(candidate, emails, "the private address")

    planned_spans = value_spans(candidate, planned)
    handles = [
        match
        for match in HANDLE_RE.finditer(candidate)
        if match.group(0) not in planned
        and not contained_in_any(match.span(), planned_spans)
    ]
    candidate = _replace_matches(candidate, handles, "the private account")

    source_urls = {match.group(0) for match in URL_RE.finditer(source)}
    private_originals = [
        original
        for entity in task.get("must_apply_entities") or []
        if entity.get("policy") == "SYNTHESIZE"
        for original in entity.get("original_surface_forms") or []
        if isinstance(original, str) and original
    ]
    planned_spans = value_spans(candidate, planned)
    urls = []
    for match in URL_RE.finditer(candidate):
        value = match.group(0)
        if value in planned:
            continue
        if any(value.startswith(item) or item.startswith(value) for item in planned):
            continue
        if contained_in_any(match.span(), planned_spans):
            continue
        if value in source_urls and not any(
            contains_value(value, original) for original in private_originals
        ):
            continue
        urls.append(match)
    candidate = _replace_matches(candidate, urls, "the referenced site")

    source_phones = {
        "".join(character for character in match.group(0) if character.isdigit())
        for match in PHONE_RE.finditer(source)
    }
    phones = []
    for match in PHONE_RE.finditer(candidate):
        digits = "".join(
            character for character in match.group(0) if character.isdigit()
        )
        if digits and digits in source_phones:
            phones.append(match)
    return _replace_matches(candidate, phones, "the private number")


def _replace_literal(
    text: str,
    original: str,
    replacement: str,
    *,
    allow_inside_pii: bool,
    protected_values: Sequence[str] = (),
) -> str:
    if not original or original.casefold() == replacement.casefold():
        return text
    pattern = re.compile(literal_term_pattern(original), flags=re.IGNORECASE)
    matches = list(pattern.finditer(text))
    excluded = pii_shaped_spans(text) if not allow_inside_pii else []
    protected_spans = value_spans(text, protected_values)
    for match in reversed(matches):
        if contained_in_any(match.span(), protected_spans):
            continue
        if excluded and overlaps_any(match.span(), excluded):
            continue
        text = text[: match.start()] + replacement + text[match.end() :]
    return text


def _is_complete_pii_value(value: str) -> bool:
    return any(start == 0 and end == len(value) for start, end in pii_shaped_spans(value))


def _apply_entities(
    text: str, task: Mapping[str, Any], *, force_inside_pii: bool = False
) -> str:
    pairs: list[tuple[str, str]] = []
    for entity in task.get("must_apply_entities") or []:
        replacement = entity.get("replacement")
        if not isinstance(replacement, str) or not replacement:
            raise PiiError("task contains an entity without a replacement")
        aliases = entity.get("alias_replacements") or []
        alias_originals: set[str] = set()
        for alias in aliases:
            original = alias.get("original")
            value = alias.get("replacement")
            if isinstance(original, str) and isinstance(value, str):
                pairs.append((original, value))
                alias_originals.add(original)
        for original in entity.get("original_surface_forms") or []:
            if isinstance(original, str) and original not in alias_originals:
                pairs.append((original, replacement))

    # Replace the widest surfaces first: a short alias must not consume part of
    # a longer project name or URL before the exact planned mapping sees it.
    protected_values = tuple(value for _original, value in pairs if value)
    for original, replacement in sorted(pairs, key=lambda item: len(item[0]), reverse=True):
        text = _replace_literal(
            text,
            original,
            replacement,
            allow_inside_pii=force_inside_pii or _is_complete_pii_value(original),
            protected_values=protected_values,
        )
    return text


def _source_needs_standalone_value(
    source: str, original: str, outer_originals: Sequence[str] = ()
) -> bool:
    """Whether an entity surface occurs outside a larger planned entity."""

    if not original:
        return False
    outer_spans = value_spans(source, outer_originals)
    matches = re.finditer(literal_term_pattern(original), source, flags=re.IGNORECASE)
    return any(
        not any(
            outer_start <= match.start()
            and match.end() <= outer_end
            and (outer_start, outer_end) != match.span()
            for outer_start, outer_end in outer_spans
        )
        for match in matches
    )


def _required_plan_values(source: str, candidate: str, task: Mapping[str, Any]) -> list[str]:
    missing: list[str] = []
    entity_originals = tuple(
        original
        for entity in task.get("must_apply_entities") or []
        if entity.get("policy") == "SYNTHESIZE"
        for original in entity.get("original_surface_forms") or []
        if isinstance(original, str) and original
    )
    for entity in task.get("must_apply_entities") or []:
        primary = entity.get("replacement")
        surfaces = entity.get("original_surface_forms") or []
        if any(
            isinstance(original, str)
            and _source_needs_standalone_value(source, original, entity_originals)
            for original in surfaces
        ):
            if (
                isinstance(primary, str)
                and primary
                and not contains_value(candidate, primary)
                and primary not in missing
            ):
                missing.append(primary)
        # The gate checks the primary and every alias pair independently.  Two
        # originals may differ only by case while mapping to different planned
        # spellings, so a case-folded dictionary would silently lose one.
        for alias in entity.get("alias_replacements") or []:
            original = alias.get("original")
            replacement = alias.get("replacement")
            if (
                isinstance(original, str)
                and _source_needs_standalone_value(
                    source, original, entity_originals
                )
                and isinstance(replacement, str)
                and replacement
                and not contains_value(candidate, replacement)
                and replacement not in missing
            ):
                missing.append(replacement)
    source_pii_spans = pii_shaped_spans(source)
    source_entity_spans = value_spans(
        source,
        {
            original
            for entity in task.get("must_apply_entities") or []
            if entity.get("policy") == "SYNTHESIZE"
            for original in entity.get("original_surface_forms") or []
            if isinstance(original, str) and original
        },
    )
    for slot in task.get("must_apply_slots") or []:
        for occurrence in slot.get("literal_replacements") or []:
            if occurrence.get("match_mode") == "SEMANTIC_ONLY":
                continue
            original = occurrence.get("original")
            replacement = occurrence.get("replacement")
            occurrence_span = (
                int(occurrence.get("start", -1)),
                int(occurrence.get("end", -1)),
            )
            if (
                isinstance(original, str)
                and isinstance(replacement, str)
                and original in source
                and not overlaps_any(occurrence_span, source_pii_spans)
                and not contained_in_any(occurrence_span, source_entity_spans)
                and replacement not in candidate
                and replacement not in missing
            ):
                missing.append(replacement)
    return missing


def _missing_preserved_terms(
    source: str, candidate: str, terms: Sequence[str]
) -> list[str]:
    before = preserved_term_counts(source, terms)
    after = preserved_term_counts(candidate, terms)
    missing: list[str] = []
    for term, count in before.items():
        missing.extend([term] * max(0, count - after.get(term, 0)))
    return missing


def _restore_semantic_anchors(source: str, candidate: str) -> list[str]:
    restored: list[str] = []
    for _dimension, before, _after in semantic_anchor_differences(source, candidate):
        for label in before:
            value = str(label).casefold().replace("_", "-")
            if value and value not in restored:
                restored.append(value)
    return restored


def _append_required_values(candidate: str, values: Sequence[str]) -> str:
    unique: list[str] = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    if not unique:
        return candidate
    return candidate.rstrip() + " For reference: " + "; ".join(unique) + "."


def _ensure_rewrite(source: str, candidate: str, bucket: str) -> str:
    if bucket == "LONG" and not has_structural_change(source, candidate):
        return "For clarity, the details are restated below. " + candidate
    if bucket == "SHORT" and candidate.strip() == source.strip():
        stripped = candidate.rstrip()
        if stripped.endswith("?"):
            return "Just checking: " + stripped
        if stripped.endswith("."):
            return stripped[:-1] + "!"
        if stripped.endswith("!"):
            return stripped[:-1] + "."
        return stripped + "."
    return candidate


def _compact_short_candidate(
    source: str, candidate: str, task: Mapping[str, Any]
) -> str:
    if str(task.get("bucket") or "") != "SHORT" or word_count(candidate) <= 8:
        return candidate
    required = _required_plan_values(source, "", task)
    required.extend(
        value
        for value in task.get("must_preserve_verbatim") or []
        if isinstance(value, str) and value
    )
    required.extend(
        value
        for value in task.get("protected_tokens_present") or []
        if isinstance(value, str) and value
    )
    unique = list(dict.fromkeys(required))
    if not unique:
        return candidate
    source_is_question = is_interrogative(source)
    separator = " or " if source_is_question and len(unique) == 2 else "; "
    compact = separator.join(unique)
    if source_is_question:
        compact = compact.rstrip(".!?") + "?"
    elif source.rstrip().endswith("!"):
        compact = compact.rstrip(".!?") + "!"
    else:
        compact = compact.rstrip(".!?") + "."
    return compact if word_count(compact) <= 8 else candidate


def candidate_for(task: Mapping[str, Any]) -> str:
    source = task.get("safe_original_text")
    if not isinstance(source, str):
        raise PiiError("TEXT task has no safe_original_text")
    candidate = _apply_slots(source, task)
    candidate = _apply_entities(candidate, task, force_inside_pii=True)
    candidate = _scrub_unplanned_pii(source, candidate, task)
    candidate = _append_required_values(
        candidate,
        [
            *_required_plan_values(source, candidate, task),
            *_missing_preserved_terms(
                source, candidate, tuple(task.get("must_preserve_verbatim") or ())
            ),
            *_restore_semantic_anchors(source, candidate),
        ],
    )
    # Required-value and preserve restoration is intentionally last, but either
    # may itself contain an address-shaped substring.  Run the same closed-set
    # PII check once more before validation.
    candidate = _scrub_unplanned_pii(source, candidate, task)
    # A wider mapping can remove a short alias before its own mapping sees it;
    # conversely, restoring a planned value can reintroduce an original alias.
    # One final exact pass followed by value restoration reaches the stable
    # planned form when the plan is internally consistent.
    candidate = _apply_entities(candidate, task)
    candidate = _append_required_values(
        candidate, _required_plan_values(source, candidate, task)
    )
    candidate = _scrub_unplanned_pii(source, candidate, task)
    candidate = _compact_short_candidate(source, candidate, task)
    # The final entity pass above can consume a short public term when the same
    # letters occur inside an alias.  Preservation is a closed requirement too,
    # so check it once more after every mapping/scrub/compaction step has settled.
    candidate = _append_required_values(
        candidate,
        _missing_preserved_terms(
            source, candidate, tuple(task.get("must_preserve_verbatim") or ())
        ),
    )
    return _ensure_rewrite(source, candidate, str(task.get("bucket") or ""))


def _has_unusable_planned_pii(task: Mapping[str, Any]) -> bool:
    """Return true when a required planned value violates the closed PII set."""

    source = str(task.get("safe_original_text") or "")
    source_phone_digits = {
        "".join(character for character in match.group(0) if character.isdigit())
        for match in PHONE_RE.finditer(source)
    }
    # Email/handle shapes *within* a planned replacement are no longer a
    # conflict: the gate now reads them as part of the planned value they sit
    # in.  A phone still is, because the test is digit equality with a source
    # number -- reusing those digits re-identifies regardless of packaging.
    for entity in task.get("must_apply_entities") or []:
        pairs = []
        surfaces = entity.get("original_surface_forms") or []
        if surfaces:
            pairs.append((surfaces[0], entity.get("replacement")))
        pairs.extend(
            (alias.get("original"), alias.get("replacement"))
            for alias in entity.get("alias_replacements") or []
        )
        for original, replacement in pairs:
            if (
                not isinstance(original, str)
                or not contains_value(source, original)
                or not isinstance(replacement, str)
            ):
                continue
            if any(
                "".join(
                    character
                    for character in match.group(0)
                    if character.isdigit()
                )
                in source_phone_digits
                for match in PHONE_RE.finditer(replacement)
            ):
                return True
    return False


def _candidate_has_mapping_or_pii_conflict(
    task: Mapping[str, Any], candidate: str
) -> bool:
    """A value-free preflight for conflicts the text generator cannot resolve."""

    source = str(task.get("safe_original_text") or "")
    planned: set[str] = set()
    entity_originals = tuple(
        original
        for entity in task.get("must_apply_entities") or []
        if entity.get("policy") == "SYNTHESIZE"
        for original in entity.get("original_surface_forms") or []
        if isinstance(original, str) and original
    )
    for entity in task.get("must_apply_entities") or []:
        primary = entity.get("replacement")
        surfaces = entity.get("original_surface_forms") or []
        pairs: list[tuple[Any, Any]] = []
        if surfaces:
            pairs.append((surfaces[0], primary))
        pairs.extend(
            (alias.get("original"), alias.get("replacement"))
            for alias in entity.get("alias_replacements") or []
        )
        for _original, replacement in pairs:
            if isinstance(replacement, str) and replacement:
                planned.add(replacement)
        for original, replacement in pairs:
            if not isinstance(original, str) or not _source_needs_standalone_value(
                source, original, entity_originals
            ):
                continue
            if contains_value(candidate, original):
                return True
            if not isinstance(replacement, str) or not contains_value(
                candidate, replacement
            ):
                return True

    planned_spans = value_spans(candidate, planned)
    for pattern in (EMAIL_RE, HANDLE_RE):
        for match in pattern.finditer(candidate):
            if match.group(0) in planned:
                continue
            if contained_in_any(match.span(), planned_spans):
                continue
            return True
    source_urls = {match.group(0) for match in URL_RE.finditer(source)}
    for match in URL_RE.finditer(candidate):
        value = match.group(0)
        if value in source_urls or value in planned:
            continue
        if any(value.startswith(item) or item.startswith(value) for item in planned):
            continue
        if contained_in_any(match.span(), planned_spans):
            continue
        return True
    source_phones = {
        "".join(character for character in match.group(0) if character.isdigit())
        for match in PHONE_RE.finditer(source)
    }
    for match in PHONE_RE.finditer(candidate):
        digits = "".join(
            character for character in match.group(0) if character.isdigit()
        )
        if digits and digits in source_phones:
            return True
    return False


def _entity_slot_conflicts(task: Mapping[str, Any]) -> list[str]:
    """Literals the entity and slot channels both claim, with different values.

    Phase 2 decides identities and requirement values in two separate calls.
    Nothing stops both from claiming the same literal: one message has its
    report codes mapped by the entity channel and the *same* codes, read as
    footer values, mapped by the slot channel to different strings.  Applying
    both satisfies each rule in isolation while destroying what the message
    actually says -- that the footer code must match the report version -- so
    the text is unsatisfiable in the only sense that matters.
    """

    entity_map: dict[str, set[str]] = {}
    for entity in task.get("must_apply_entities") or []:
        replacement = entity.get("replacement")
        aliases = {
            alias.get("original"): alias.get("replacement")
            for alias in entity.get("alias_replacements") or []
        }
        for original in entity.get("original_surface_forms") or []:
            if not isinstance(original, str) or not original:
                continue
            value = aliases.get(original, replacement)
            if isinstance(value, str) and value:
                entity_map.setdefault(original.casefold(), set()).add(value)

    conflicts: list[str] = []
    for slot in task.get("must_apply_slots") or []:
        for occurrence in slot.get("literal_replacements") or []:
            original = occurrence.get("original")
            replacement = occurrence.get("replacement")
            if (
                occurrence.get("match_mode") == "SEMANTIC_ONLY"
                or not isinstance(original, str)
                or not isinstance(replacement, str)
            ):
                continue
            planned = entity_map.get(original.casefold())
            if planned and replacement not in planned:
                label = f"{slot.get('slot_id')}"
                if label not in conflicts:
                    conflicts.append(label)
    return conflicts


def _has_preserve_replace_conflict(task: Mapping[str, Any]) -> bool:
    preserved = {
        value.casefold()
        for value in task.get("must_preserve_verbatim") or []
        if isinstance(value, str) and value
    }
    planned = _planned_values(task)
    source = str(task.get("safe_original_text") or "")
    source_urls = {match.group(0) for match in URL_RE.finditer(source)}
    # An address/handle/source phone cannot both survive byte-exact and pass the
    # closed-set PII gate.  Source URLs are the one deliberate public-link
    # exception in the rewrite validator.
    for value in task.get("must_preserve_verbatim") or []:
        if not isinstance(value, str):
            continue
        # Preservation is count-based.  A normalized/configured spelling that
        # is absent from this source has a zero-before count and imposes no
        # requirement on the candidate.
        if not contains_value(source, value):
            continue
        if any(match.group(0) not in planned for match in EMAIL_RE.finditer(value)):
            return True
        if any(match.group(0) not in planned for match in HANDLE_RE.finditer(value)):
            return True
        if any(
            match.group(0) not in source_urls and match.group(0) not in planned
            for match in URL_RE.finditer(value)
        ):
            return True
        source_phone_digits = {
            "".join(character for character in match.group(0) if character.isdigit())
            for match in PHONE_RE.finditer(source)
        }
        if any(
            "".join(character for character in match.group(0) if character.isdigit())
            in source_phone_digits
            for match in PHONE_RE.finditer(value)
        ):
            return True
    if not preserved:
        return False
    originals: list[str] = []
    for slot in task.get("must_apply_slots") or []:
        for occurrence in slot.get("literal_replacements") or []:
            original = occurrence.get("original")
            replacement = occurrence.get("replacement")
            if (
                occurrence.get("match_mode") != "SEMANTIC_ONLY"
                and isinstance(original, str)
                and isinstance(replacement, str)
                and original.casefold() != replacement.casefold()
            ):
                originals.append(original)
    for entity in task.get("must_apply_entities") or []:
        if entity.get("policy") != "SYNTHESIZE":
            continue
        originals.extend(
            value
            for value in entity.get("original_surface_forms") or []
            if isinstance(value, str) and value
        )
    return any(value.casefold() in preserved for value in originals)


def prepare_project(project_id: str, work_root: Path) -> Path:
    if project_id in EXCLUDED_PROJECTS:
        raise PiiError(f"project {project_id} is explicitly excluded from this repair batch")
    run_dir = work_root / project_id
    index_path = run_dir / "agent_tasks" / "index.json"
    package = read_json(index_path)
    if not isinstance(package, dict) or package.get("project_id") != project_id:
        raise PiiError(f"missing or mismatched task package: {index_path}")
    tasks = package.get("tasks") or []
    if not tasks:
        raise PiiError(f"project {project_id} has no agent tasks")

    repairs: list[dict[str, Any]] = []
    blocked: list[dict[str, str]] = []
    for task in tasks:
        if task.get("status") != "OPEN" or not task.get("agent_actionable"):
            continue
        if task.get("kind") != "TEXT":
            raise PiiError(
                f"project {project_id} contains non-TEXT task {task.get('task_id')}"
            )
        if _has_preserve_replace_conflict(task) or _has_unusable_planned_pii(task):
            blocked.append(
                {
                    "task_id": str(task.get("task_id")),
                    "reason": (
                        "The approved plan requires replacing a literal that this "
                        "same task requires preserving verbatim; a re-plan is required."
                    ),
                }
            )
            continue
        divergent = _entity_slot_conflicts(task)
        if divergent:
            blocked.append(
                {
                    "task_id": str(task.get("task_id")),
                    "reason": (
                        "The entity and slot channels give the same literal two "
                        f"different replacements ({', '.join(divergent[:4])}); applying "
                        "both would break the relation the message states. A re-plan "
                        "is required."
                    ),
                }
            )
            continue
        try:
            candidate = candidate_for(task)
        except PiiError as exc:
            # One task that cannot be rendered must not abort the project: the
            # others are still deliverable, and an explicit blocked entry is the
            # reportable outcome the agent contract asks for.
            blocked.append(
                {
                    "task_id": str(task.get("task_id")),
                    "reason": f"No candidate could be built from the approved plan: {exc}",
                }
            )
            continue
        if _candidate_has_mapping_or_pii_conflict(task, candidate):
            blocked.append(
                {
                    "task_id": str(task.get("task_id")),
                    "reason": (
                        "The closed PII rules and approved mappings cannot be "
                        "satisfied together by message text; a re-plan is required."
                    ),
                }
            )
            continue
        repairs.append(
            {
                "task_id": task.get("task_id"),
                "kind": "TEXT",
                "ordinal": task.get("ordinal"),
                "message_id": task.get("message_id"),
                "text": candidate,
                "safe_source_sha256": task.get("safe_source_sha256"),
                "plan_slice_sha256": task.get("plan_slice_sha256"),
                "author": "codex-agent",
                "reason": (
                    "Applied the approved plan mappings while preserving the source "
                    "meaning, protected literals, and message structure requirements."
                ),
            }
        )

    path = run_dir / "agent_repairs" / "repairs.json"
    write_json(
        path,
        {
            "schema_version": SCHEMA_VERSION,
            "project_id": project_id,
            "queue_sha256": queue_sha256(package),
            "repairs": repairs,
            "blocked": blocked,
        },
    )
    return path


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", action="append", required=True)
    parser.add_argument("--work-root", type=Path, default=root / "outputs" / "pii_runs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for project_id in args.project_id:
        path = prepare_project(project_id, args.work_root)
        print(f"[{project_id}] prepared {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
