"""Shared LLM plumbing: request assembly, redaction, and sharded execution.

:func:`run_sharded_phase` is the single implementation of the batch -> per-message
fallback that v6 duplicated three times (``Code/PII_Clean.py:1740``, ``:2040``,
``:2416``).  Centralizing it also centralizes the two properties that matter:

* one failing item never aborts its shard, its phase, or the run -- the phase
  runs to completion so a single run enumerates every problem;
* every successful item is committed immediately, so a later failure in the same
  shard cannot discard work that already validated.

``redactor_for`` returns a non-optional redactor.  v6 made the redactor an
optional argument and relied on remembering to pass it
(``Code/stage1/api_client.py:148-157``); a phase wired without one would have
written raw model output containing source text into the failure artifacts.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Protocol, Sequence, TypeVar

from ._compat import ApiError
from .config import RUN_MODE
from .errors import PiiError, PiiValidationError, api_error_is_validation_failure
from .textutil import message_file_stem

T = TypeVar("T")

# Deterministic section order keeps the serialized request -- and therefore its
# hash -- stable across runs.  stage1's own SECTION_ORDER
# (``Code/stage1/prompt_builder.py:9-19``) is annotation-specific and would
# reject every v7 section, so this package carries its own.
SECTION_ORDER: tuple[str, ...] = (
    "PROJECT_METADATA",
    "POLICY",
    "MODE",
    "SAFE_MESSAGES",
    "NEIGHBOR_CONTEXT",
    "SECRET_TOKENS",
    "PII_ENTITIES",
    "SEMANTIC_ACCUMULATOR",
    "SEMANTIC_RECORDS",
    "IDENTITY_BUNDLES",
    "SLOT_CLUSTER",
    "RESERVED_VALUES",
    "CONSTRAINTS",
    "PLAN_SLICE",
    "SAFE_ORIGINAL",
    "SYNTHETIC_REWRITE",
    "VERDICT",
    "REPAIR_INSTRUCTION",
)

_SECTION_NAMES = frozenset(SECTION_ORDER)

JSON_ONLY_REMINDER = (
    "Return JSON only, with no Markdown fences and no surrounding commentary."
)


class WorkItem(Protocol):
    """The minimum a shardable unit must expose."""

    ordinal: int
    message_id: Any


@dataclass(frozen=True)
class Shard:
    """One API request's worth of work."""

    shard_id: str
    items: tuple[Any, ...]

    def __len__(self) -> int:
        return len(self.items)


def build_shards(
    items: Sequence[Any], *, max_items: int, max_chars: int, sizer: Callable[[Any], int]
) -> list[Shard]:
    """Split work by item count **and** serialized size.

    Both limits are required: across the corpus, message count and character
    volume are uncorrelated (one project has 210 messages but 182 KB of text),
    so a count-only limit produces wildly uneven requests.
    """

    shards: list[Shard] = []
    current: list[Any] = []
    current_chars = 0
    for item in items:
        size = sizer(item)
        if current and (len(current) >= max_items or current_chars + size > max_chars):
            shards.append(Shard(f"shard_{len(shards) + 1:04d}", tuple(current)))
            current = []
            current_chars = 0
        current.append(item)
        current_chars += size
    if current:
        shards.append(Shard(f"shard_{len(shards) + 1:04d}", tuple(current)))
    return shards


def build_phase_messages(
    prompt: str,
    sections: Mapping[str, Any],
    *,
    task: str,
    repair_instruction: str | None = None,
) -> list[dict[str, str]]:
    """Assemble the two-message request for one phase call."""

    unknown = sorted(set(sections).difference(_SECTION_NAMES))
    if unknown:
        raise PiiError(f"unknown request section(s): {', '.join(unknown)}")
    body: dict[str, Any] = {"task": task}
    for name in SECTION_ORDER:
        if name in sections:
            body[name.lower()] = sections[name]
    if repair_instruction:
        body["validation_repair"] = repair_instruction
    body["output"] = JSON_ONLY_REMINDER
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
    ]


def request_payload_hash_input(
    sections: Mapping[str, Any], *, task: str
) -> dict[str, Any]:
    """The part of a request that belongs in a shard's ``scope`` hash."""

    return {
        "task": task,
        "sections": {
            name: sections[name] for name in SECTION_ORDER if name in sections
        },
    }


def redactor_for(phase: str) -> Callable[[str], str]:
    """A never-null redactor for failure artifacts.

    Every v7 phase submits source-derived text, so a failed response may echo
    it.  The artifacts keep the phase identity and nothing else.
    """

    message = f"[REDACTED: raw {phase} response withheld]"

    def _redact(_raw: str) -> str:
        return message

    return _redact


def run_mode_for(phase: str) -> str:
    try:
        return RUN_MODE[phase]
    except KeyError:
        raise PiiError(f"phase {phase} has no API run mode") from None


async def call_phase(
    api: Any,
    *,
    phase: str,
    project_id: str,
    target: str,
    prompt: str,
    sections: Mapping[str, Any],
    task: str,
    validator: Callable[[dict[str, Any]], None],
    parse: Callable[[dict[str, Any]], T],
    repair_instruction: str | None = None,
) -> T:
    """One validated API call.  Raises ``ApiError`` when attempts are exhausted."""

    payload = await api.call(
        project_id=project_id,
        run_mode=run_mode_for(phase),
        target_requirement=target,
        messages=build_phase_messages(
            prompt, sections, task=task, repair_instruction=repair_instruction
        ),
        validator=validator,
        failed_response_redactor=redactor_for(phase),
    )
    return parse(payload)


async def run_sharded_phase(
    api: Any,
    *,
    phase: str,
    project_id: str,
    prompt: str,
    task: str,
    shards: Sequence[Shard],
    build_sections: Callable[[Sequence[Any]], Mapping[str, Any]],
    validator_for: Callable[[Sequence[Any]], Callable[[dict[str, Any]], None]],
    parse: Callable[[dict[str, Any], Sequence[Any]], Mapping[str, Any]],
    repair_instruction: str,
    on_success: Callable[[Any, Any], Awaitable[None]],
    on_failure: Callable[[Any, BaseException, bool], Awaitable[None]],
    max_concurrent_shards: int = 1,
    progress: Callable[[str], None] | None = None,
) -> None:
    """Execute every shard, degrading to per-item calls on a content failure.

    ``parse`` returns a mapping keyed by ``ordinal``.  ``on_failure`` receives
    ``(item, error, is_transport)`` -- the transport flag is what keeps a
    ``ConnectError`` out of the agent repair queue, since no hand-written text
    can fix one.
    """

    if not shards:
        return
    semaphore = asyncio.Semaphore(max(1, max_concurrent_shards))

    async def commit(results: Mapping[int, Any], items: Sequence[Any]) -> None:
        by_ordinal = {item.ordinal: item for item in items}
        for ordinal, value in sorted(results.items()):
            item = by_ordinal.get(ordinal)
            if item is not None:
                await on_success(item, value)

    async def run_single(item: Any, shard: Shard) -> None:
        target = f"{shard.shard_id}_m{message_file_stem(item.ordinal, item.message_id)}"
        try:
            results = await call_phase(
                api,
                phase=phase,
                project_id=project_id,
                target=target,
                prompt=prompt,
                sections=build_sections([item]),
                task=task,
                validator=validator_for([item]),
                parse=lambda payload: parse(payload, [item]),
                repair_instruction=repair_instruction,
            )
        except ApiError as exc:
            await on_failure(item, exc, not api_error_is_validation_failure(exc))
            return
        except Exception as exc:  # a validator escaping as a non-ValueError
            await on_failure(item, exc, False)
            return
        await commit(results, [item])

    async def run_shard(shard: Shard) -> None:
        async with semaphore:
            if progress is not None:
                progress(f"{phase} {shard.shard_id} ({len(shard)} item(s))")
            try:
                results = await call_phase(
                    api,
                    phase=phase,
                    project_id=project_id,
                    target=shard.shard_id,
                    prompt=prompt,
                    sections=build_sections(shard.items),
                    task=task,
                    validator=validator_for(shard.items),
                    parse=lambda payload: parse(payload, shard.items),
                )
            except ApiError as exc:
                if not api_error_is_validation_failure(exc):
                    # Transport exhausted: nothing about this shard's content is
                    # known to be wrong, so do not isolate item by item.
                    for item in shard.items:
                        await on_failure(item, exc, True)
                    return
                if len(shard.items) == 1:
                    # Already minimal; a repair-instruction retry is still worth
                    # one attempt because the instruction itself is new context.
                    await run_single(shard.items[0], shard)
                    return
                if progress is not None:
                    progress(
                        f"{phase} {shard.shard_id} failed validation; "
                        f"isolating {len(shard)} item(s)"
                    )
                for item in shard.items:
                    await run_single(item, shard)
                return
            except PiiValidationError as exc:
                # A validation error that reached us unwrapped (no ApiError
                # envelope) is still a content failure, so it still deserves
                # per-item isolation rather than failing the whole shard.
                if len(shard.items) == 1:
                    await on_failure(shard.items[0], exc, False)
                    return
                if progress is not None:
                    progress(
                        f"{phase} {shard.shard_id} failed validation; "
                        f"isolating {len(shard)} item(s)"
                    )
                for item in shard.items:
                    await run_single(item, shard)
                return
            except Exception as exc:
                for item in shard.items:
                    await on_failure(item, exc, False)
                return
            await commit(results, shard.items)

    await asyncio.gather(*(run_shard(shard) for shard in shards))


async def run_single_call(
    api: Any,
    *,
    phase: str,
    project_id: str,
    target: str,
    prompt: str,
    sections: Mapping[str, Any],
    task: str,
    validator: Callable[[dict[str, Any]], None],
    parse: Callable[[dict[str, Any]], T],
    repair_instruction: str = "",
    attempts: int = 2,
) -> T:
    """A project-level call (phases 1B and 2) with one repair-instruction retry.

    Project-level artifacts are not per-message, so there is nothing to isolate;
    the only useful escalation is to restate the violated rule and try again.
    """

    last: BaseException | None = None
    for attempt in range(max(1, attempts)):
        try:
            return await call_phase(
                api,
                phase=phase,
                project_id=project_id,
                target=target if attempt == 0 else f"{target}_retry{attempt}",
                prompt=prompt,
                sections=sections,
                task=task,
                validator=validator,
                parse=parse,
                repair_instruction=repair_instruction if attempt else None,
            )
        except ApiError as exc:
            last = exc
            if not api_error_is_validation_failure(exc):
                raise
    assert last is not None
    raise last
