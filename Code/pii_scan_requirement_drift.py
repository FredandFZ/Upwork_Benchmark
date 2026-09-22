#!/usr/bin/env python3
"""Find requirement terms a published project lost, by diffing it against its source.

Phase 2 may only re-value *identities*.  A file format, a standard, a tool
version or a part number is the requirement itself: replacing ``.pdf`` with
``.tiff`` states a different requirement, and for a requirements benchmark that
is a silent data defect rather than a privacy measure.

Phase 6B cannot catch this on its own.  Its preserve check reads
``PUBLIC_ALLOWLIST`` and the operator's ``--preserve-term`` list; the terms
phase 1A declares per message in ``must_preserve_terms`` never reach it.  In
this corpus that is 756 of the 797 declared terms.

So this scans the published artifact instead, which needs neither the plan nor
the annotations -- both of which are pruned once a project completes.  The
signal it keys on is that a phase-2 slot decision is *project-wide*: a corrupted
format does not go missing from one message, it disappears from every message
and a substitute appears in the same places.  Paraphrase cannot produce that,
which is what makes the check survive the fact that every message was rewritten.

What it cannot do is read intent.  A term that vanished because phase 0B
classified it as private is indistinguishable here from one phase 2 re-valued,
so findings are evidence to review, not violations.  The ranking exists to make
that review short.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:  # ``python Code/pii_scan_requirement_drift.py``
    from PII._compat import read_json
    from PII.models import MessageSemantics, PiiEntityRegistry
    from PII.phase0b_entities import POLICY_SYNTHESIZE
    from PII.textutil import overlaps_any, pii_shaped_spans
except ModuleNotFoundError:  # ``python -m Code.pii_scan_requirement_drift``
    from Code.PII._compat import read_json
    from Code.PII.models import MessageSemantics, PiiEntityRegistry
    from Code.PII.phase0b_entities import POLICY_SYNTHESIZE
    from Code.PII.textutil import overlaps_any, pii_shaped_spans


# A dotted extension or an all-caps token is a shape a person's name does not
# take, which is what makes it usable as a substitute candidate without a plan.
TECHNICAL_TOKEN_RE = re.compile(
    r"(?<![\w.])\.[A-Za-z][A-Za-z0-9]{1,5}(?![\w.])"
    r"|(?<![\w.])[A-Z][A-Z0-9]{1,7}(?![\w.])"
)


# A dotted extension is the one requirement term that needs no annotation to
# recognise, and effectively never doubles as an identity.  Harvesting it from
# the source is what keeps a pruned project -- one whose phase 1A record is gone
# -- from being checked only against terms other projects happened to declare.
EXTENSION_RE = re.compile(r"(?<![\w.])\.[A-Za-z][A-Za-z0-9]{1,5}(?![\w.])")
ACRONYM_RE = re.compile(r"(?<![\w.])[A-Z][A-Z0-9]{2,7}(?![\w.])")


def source_extensions(messages: Sequence[str]) -> dict[str, set[str]]:
    spellings: dict[str, Counter[str]] = {}
    for text in messages:
        for match in EXTENSION_RE.finditer(text):
            value = match.group(0)
            spellings.setdefault(value.casefold(), Counter())[value] += 1
    return {
        counter.most_common(1)[0][0]: {"<source extension>"}
        for counter in spellings.values()
    }


def source_acronyms(messages: Sequence[str], minimum: int) -> dict[str, set[str]]:
    """All-caps source tokens, as a last resort for a project with no record.

    A pruned project can only borrow a vocabulary other projects declared, and
    four fifths of what phase 1A declares is specific to one project.  Every
    all-caps token is therefore offered instead, which needs no record at all.

    The cost is that an acronym is the one technical shape an *identity* also
    takes -- a site code, a client abbreviation -- so this reports legitimate
    replacements too and is strictly a review aid.  It stays off by default for
    that reason.
    """

    counts: Counter[str] = Counter()
    for text in messages:
        for match in ACRONYM_RE.finditer(text):
            counts[match.group(0)] += 1
    return {term: {"<source acronym>"} for term, count in counts.items() if count >= minimum}


def load_messages(path: Path) -> list[str]:
    rows = read_json(path)
    if not isinstance(rows, list):
        raise ValueError(f"{path} is not a message list")
    return [str((row or {}).get("message") or "") for row in rows]


def declared_terms(
    work_root: Path,
) -> tuple[dict[str, set[str]], dict[str, dict[str, set[str]]]]:
    """Requirement terms phase 1A declared, per project and corpus-wide.

    Using the pipeline's own annotations rather than a hand-written list keeps
    the vocabulary honest: it is what this corpus actually treats as a
    requirement, not what one reader guessed it would.  A term a SYNTHESIZE
    entity owns in the same project is dropped -- phase 1A is contracted not to
    file a private name here, and where it did, the entity decision wins.

    Spellings are folded to the most frequently declared one, because casing
    decides how the term is matched: ``PDF`` (46 declarations) and ``pdf`` (7)
    are one requirement, and the majority spelling is the one that describes it.

    Both scopes are returned because they are not interchangeable.  A term is a
    requirement *in the project that declared it*: ``Pro`` and ``Plus`` are
    subscription tiers in one project and the words "pros and cons" and "plus"
    in another.  A project whose run directory survives is therefore checked
    against its own vocabulary; only a pruned one has to borrow the corpus.
    """

    spellings: dict[str, Counter[str]] = {}
    projects: dict[str, set[str]] = {}
    per_project: dict[str, dict[str, Counter[str]]] = {}
    for run_dir in sorted(path for path in work_root.iterdir() if path.is_dir()):
        semantics_path = run_dir / "phase1a_message_semantics" / "semantics.json"
        if not semantics_path.is_file():
            continue
        entities_path = run_dir / "phase0b_pii_discovery" / "entities.json"
        owned: set[str] = set()
        if entities_path.is_file():
            registry = PiiEntityRegistry.from_json(read_json(entities_path))
            owned = {
                form.strip().casefold()
                for entity in registry.entities
                if entity.policy == POLICY_SYNTHESIZE
                for form in (entity.canonical_value, *entity.surface_forms())
                if form and form.strip()
            }
        for record in (
            MessageSemantics.from_json(item) for item in read_json(semantics_path)
        ):
            for fact in record.semantic_facts:
                for term in fact.get("must_preserve_terms") or []:
                    if not isinstance(term, str):
                        continue
                    value = term.strip()
                    key = value.casefold()
                    if not value or key in owned:
                        continue
                    spellings.setdefault(key, Counter())[value] += 1
                    projects.setdefault(key, set()).add(run_dir.name)
                    per_project.setdefault(run_dir.name, {}).setdefault(
                        key, Counter()
                    )[value] += 1

    def fold(counters: Mapping[str, Counter[str]]) -> dict[str, set[str]]:
        return {
            counter.most_common(1)[0][0]: projects[key]
            for key, counter in counters.items()
        }

    return fold(spellings), {
        project_id: fold(counters) for project_id, counters in per_project.items()
    }


def term_flags(term: str) -> int:
    """How forgiving matching may be about case, given how the term is written.

    This follows ``find_terms_outside_pii``: a single-word term that is not an
    acronym is also an ordinary English word, so it is matched case-sensitively.
    One extra condition is needed here.  A one- or two-character acronym --
    ``DO`` for DigitalOcean, ``AI``, ``GH``, ``FB`` -- collides with a common
    word often enough that case-insensitive matching drowns the report: ``DO``
    alone produced a finding in six projects, every one of them the verb.
    """

    if " " in term:
        return re.IGNORECASE
    if term.isupper() and len(term.strip(".")) > 2:
        return re.IGNORECASE
    return 0


def term_pattern(term: str) -> str:
    """``literal_term_pattern`` with the plural inside the word boundary.

    ``PDF(?!\\w)s?`` can never match ``PDFs``: the lookahead rejects the ``s``
    before the optional group is reached.  Phase 1A declares plurals as their
    own terms, so this only makes an already-declared requirement easier to
    find -- it does not widen what counts as one.
    """

    prefix = r"(?<!\w)" if term[:1].isalnum() else ""
    suffix = r"s?(?!\w)" if term[-1:].isalnum() else ""
    return prefix + re.escape(term) + suffix


def term_count(text: str, term: str) -> int:
    """Whole-token occurrences outside complete PII values.

    The PII-span exclusion keeps a format name inside a synthetic link from
    masking the fact that the prose lost it.
    """

    excluded = pii_shaped_spans(text)
    pattern = re.compile(term_pattern(term), flags=term_flags(term))
    return sum(
        1
        for match in pattern.finditer(text)
        if not overlaps_any(match.span(), excluded)
    )


def technical_tokens(text: str) -> Counter[str]:
    return Counter(
        match.group(0).casefold() for match in TECHNICAL_TOKEN_RE.finditer(text)
    )


def find_substitute(
    source: Sequence[str], published: Sequence[str], term: str
) -> tuple[str, int] | None:
    """The token that took the term's place, corroborated per message.

    A project-wide count is enough to notice a loss but not to name its cause.
    Looking only at the messages that *had* the term and no longer do, and
    asking which technical token is new in those same messages, separates a
    substitution from an ordinary paraphrase: a paraphrase leaves no consistent
    newcomer behind.

    Several formats often change in the same message, so mere frequency picks
    the wrong partner.  Ranking by *per-message count agreement* pairs them
    correctly: the token that appears exactly as often as the lost term did, in
    each message where it was lost, is the one that replaced it.
    """

    observations: list[tuple[int, Counter[str]]] = []
    for before, after in zip(source, published):
        occurrences = term_count(before, term)
        if not occurrences or term_count(after, term):
            continue
        source_tokens = technical_tokens(before)
        newcomers = Counter(
            {
                token: count
                for token, count in technical_tokens(after).items()
                if token not in source_tokens
            }
        )
        observations.append((occurrences, newcomers))
    if not observations:
        return None

    best: tuple[str, tuple[int, int]] | None = None
    for token in {name for _count, newcomers in observations for name in newcomers}:
        agreeing = sum(
            1 for count, newcomers in observations if newcomers.get(token, 0) == count
        )
        present = sum(1 for _count, newcomers in observations if token in newcomers)
        score = (agreeing, present)
        if best is None or score > best[1]:
            best = (token, score)
    return (best[0], best[1][1]) if best else None


def engine_of(manifest_path: Path) -> str:
    if not manifest_path.is_file():
        return "unknown"
    manifest = read_json(manifest_path)
    if not isinstance(manifest, Mapping):
        return "unknown"
    engine = manifest.get("engine_version")
    if engine:
        return f"v{engine}"
    signature = manifest.get("signature")
    if isinstance(signature, Mapping) and signature.get("cleaning_version"):
        return f"v{signature['cleaning_version']}"
    return "unknown"


def scan_project(
    project_id: str,
    *,
    source_root: Path,
    output_root: Path,
    vocabulary: Mapping[str, Iterable[str]],
    scope: str,
    min_occurrences: int,
    include_acronyms: bool = False,
) -> dict[str, Any] | None:
    source_path = source_root / project_id / "chat_messages.json"
    published_path = output_root / project_id / "chat_messages.json"
    if not source_path.is_file() or not published_path.is_file():
        return None
    source = load_messages(source_path)
    published = load_messages(published_path)
    if len(source) != len(published):
        return {
            "project_id": project_id,
            "engine": engine_of(output_root / "_manifests" / f"{project_id}.json"),
            "scope": scope,
            "error": (
                f"message count differs ({len(source)} -> {len(published)}); "
                "the two files are not comparable"
            ),
            "findings": [],
        }

    source_text = "\n".join(source)
    published_text = "\n".join(published)
    terms = {**source_extensions(source), **dict(vocabulary)}
    if include_acronyms:
        terms = {**source_acronyms(source, min_occurrences), **terms}
    findings: list[dict[str, Any]] = []
    for term in sorted(terms):
        before = term_count(source_text, term)
        if before < min_occurrences:
            continue
        after = term_count(published_text, term)
        if after >= before:
            continue
        # A term that merely thins out is paraphrase; one that leaves entirely,
        # or nearly so, is a decision applied project-wide.
        if after and after > before // 3:
            continue
        substitute = find_substitute(source, published, term)
        findings.append(
            {
                "term": term,
                "source_count": before,
                "published_count": after,
                "substitute": substitute[0] if substitute else None,
                "substitute_messages": substitute[1] if substitute else 0,
                "declared_by_projects": sorted(terms[term]),
            }
        )
    findings.sort(
        key=lambda item: (item["substitute_messages"], item["source_count"]),
        reverse=True,
    )
    return {
        "project_id": project_id,
        "engine": engine_of(output_root / "_manifests" / f"{project_id}.json"),
        "scope": scope,
        "messages": len(source),
        "findings": findings,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", action="append")
    parser.add_argument("--source-root", type=Path, default=root / "Datasets" / "project")
    parser.add_argument(
        "--output-root", type=Path, default=root / "Datasets" / "PII_clean_project"
    )
    parser.add_argument("--work-root", type=Path, default=root / "outputs" / "pii_runs")
    parser.add_argument(
        "--min-occurrences",
        type=int,
        default=2,
        help="Ignore terms the source uses fewer times than this (default 2).",
    )
    parser.add_argument(
        "--include-source-acronyms",
        action="store_true",
        help=(
            "Also check every all-caps source token, for projects whose phase 1A "
            "record was pruned. Reports legitimate identity replacements too."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit the full report as JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    corpus, per_project = declared_terms(args.work_root)
    wanted = set(args.project_id) if args.project_id else None
    projects = sorted(
        path.name
        for path in args.output_root.iterdir()
        if path.is_dir() and path.name != "_manifests" and (wanted is None or path.name in wanted)
    )

    reports = [
        report
        for project_id in projects
        if (
            report := scan_project(
                project_id,
                source_root=args.source_root,
                output_root=args.output_root,
                vocabulary=per_project.get(project_id) or corpus,
                scope="own" if project_id in per_project else "corpus",
                min_occurrences=args.min_occurrences,
                include_acronyms=args.include_source_acronyms
                and project_id not in per_project,
            )
        )
        is not None
    ]

    if args.json:
        print(
            json.dumps(
                {"corpus_vocabulary_terms": len(corpus), "projects": reports},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    own = sum(1 for report in reports if report.get("scope") == "own")
    print(
        f"vocabulary: {len(corpus)} requirement term(s) declared by phase 1A across "
        f"{len(per_project)} surviving run directories\n"
        f"{own} project(s) checked against their own declarations; "
        f"{len(reports) - own} borrowed the corpus vocabulary (advisory only)\n"
    )
    flagged = 0
    for report in reports:
        if report.get("error"):
            print(f"[{report['project_id']}] {report['engine']}: {report['error']}")
            continue
        if not report["findings"]:
            continue
        flagged += 1
        confidence = "own terms" if report["scope"] == "own" else "corpus terms, advisory"
        print(
            f"[{report['project_id']}] {report['engine']}  "
            f"{report['messages']} message(s)  [{confidence}]"
        )
        for item in report["findings"]:
            arrow = (
                f" -> {item['substitute']} (in {item['substitute_messages']} message(s))"
                if item["substitute"]
                else ""
            )
            print(
                f"    {item['term']!r}: {item['source_count']} -> "
                f"{item['published_count']}{arrow}"
            )
    print(f"\n{flagged} of {len(reports)} published project(s) have at least one finding.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
