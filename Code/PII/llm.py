"""Shared LLM plumbing: request assembly, redaction, and sharded execution.

:func:`run_sharded_phase` is the single implementation of bounded batch
bisection that v6 duplicated as per-message fallback three times
(``Code/PII_Clean.py:1740``, ``:2040``, ``:2416``).  Centralizing it also
centralizes the two properties that matter:

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
from .errors import (
    VALIDATION_MARKER,
    PiiError,
    PiiValidationError,
    api_error_is_validation_failure,
)
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
    "PRESERVED_TERMS",
    "CONSTRAINTS",
    "PLAN_SLICE",
    "SAFE_ORIGINAL",
    "SYNTHETIC_REWRITE",
    "LOCAL_SEMANTIC_ANCHORS",
    "VERDICT",
    "REPAIR_INSTRUCTION",
)

_SECTION_NAMES = frozenset(SECTION_ORDER)

JSON_ONLY_REMINDER = (
    "Return JSON only, with no Markdown fences and no surrounding commentary."
)

# A large request can repeatedly time out at an upstream gateway even while
# smaller requests to the same service succeed.  In that case, retrying the
# byte-identical payload does not help.  Bound the fallback so a genuine
# service outage cannot fan one shard out into an unbounded number of calls.
MAX_TRANSPORT_BISECTION_DEPTH = 2


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


def transport_failure_may_benefit_from_split(error: BaseException) -> bool:
    """Return whether a smaller payload may avoid this transport failure.

    Timeouts and retryable upstream 5xx/408 responses can be payload-duration
    dependent.  Authentication failures, rate limits and connection failures
    are not, so splitting those would only multiply unsuccessful API calls.
    ``_RetryableError`` is private to the shared client; inspect its stable,
    deliberately short status message instead of importing that private type.
    """

    cause = getattr(error, "cause", None) or error
    if isinstance(cause, TimeoutError):
        return True
    type_names = {cls.__name__.lower() for cls in type(cause).__mro__}
    if any("timeout" in name for name in type_names):
        return True
    message = str(cause).lower()
    if "timed out" in message or "timeout" in message:
        return True
    return any(
        marker in message
        for marker in (
            "transient llm error 408",
            "transient llm error 500",
            "transient llm error 502",
            "transient llm error 503",
            "transient llm error 504",
        )
    )


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
    """Execute every shard, bisecting a content failure down to its bad items.

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

    async def fail_items(
        items: Sequence[Any], error: BaseException, *, transport: bool
    ) -> None:
        for item in items:
            await on_failure(item, error, transport)

    async def isolate_content_failure(
        items: Sequence[Any],
        shard: Shard,
        error: BaseException,
        *,
        repair_already_attempted: bool = False,
    ) -> None:
        if len(items) == 1:
            if repair_already_attempted:
                await on_failure(items[0], error, False)
            else:
                await run_single(items[0], shard)
            return
        midpoint = len(items) // 2
        halves = (items[:midpoint], items[midpoint:])
        if progress is not None:
            progress(
                f"{phase} {shard.shard_id} failed validation; "
                f"bisecting {len(items)} item(s)"
            )
        for index, half in enumerate(halves, start=1):
            await run_validation_subset(
                Shard(f"{shard.shard_id}_v{index}", tuple(half))
            )

    async def run_validation_subset(shard: Shard) -> None:
        """Run one half with repair guidance and retain a passing half whole."""

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
                repair_instruction=repair_instruction,
            )
        except ApiError as exc:
            if api_error_is_validation_failure(exc):
                await isolate_content_failure(
                    shard.items,
                    shard,
                    exc,
                    repair_already_attempted=True,
                )
                return
            if (
                len(shard.items) > 1
                and transport_failure_may_benefit_from_split(exc)
            ):
                midpoint = len(shard.items) // 2
                halves = (shard.items[:midpoint], shard.items[midpoint:])
                if progress is not None:
                    progress(
                        f"{phase} {shard.shard_id} transport exhausted; "
                        f"bisecting {len(shard.items)} item(s)"
                    )
                for index, half in enumerate(halves, start=1):
                    await run_transport_split(
                        Shard(f"{shard.shard_id}_t{index}", tuple(half)), 1
                    )
                return
            await fail_items(shard.items, exc, transport=True)
            return
        except PiiValidationError as exc:
            await isolate_content_failure(
                shard.items,
                shard,
                exc,
                repair_already_attempted=True,
            )
            return
        except Exception as exc:
            await fail_items(shard.items, exc, transport=False)
            return
        await commit(results, shard.items)

    async def run_transport_split(shard: Shard, depth: int) -> None:
        """Retry a likely payload-sensitive transport failure in smaller halves."""

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
            if api_error_is_validation_failure(exc):
                await isolate_content_failure(shard.items, shard, exc)
                return
            if (
                depth < MAX_TRANSPORT_BISECTION_DEPTH
                and len(shard.items) > 1
                and transport_failure_may_benefit_from_split(exc)
            ):
                midpoint = len(shard.items) // 2
                halves = (shard.items[:midpoint], shard.items[midpoint:])
                if progress is not None:
                    progress(
                        f"{phase} {shard.shard_id} transport exhausted; "
                        f"bisecting {len(shard.items)} item(s)"
                    )
                for index, items in enumerate(halves, start=1):
                    await run_transport_split(
                        Shard(f"{shard.shard_id}_t{index}", tuple(items)), depth + 1
                    )
                return
            await fail_items(shard.items, exc, transport=True)
            return
        except PiiValidationError as exc:
            await isolate_content_failure(shard.items, shard, exc)
            return
        except Exception as exc:
            await fail_items(shard.items, exc, transport=False)
            return
        await commit(results, shard.items)

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
                    if (
                        len(shard.items) > 1
                        and transport_failure_may_benefit_from_split(exc)
                    ):
                        midpoint = len(shard.items) // 2
                        halves = (shard.items[:midpoint], shard.items[midpoint:])
                        if progress is not None:
                            progress(
                                f"{phase} {shard.shard_id} transport exhausted; "
                                f"bisecting {len(shard.items)} item(s)"
                            )
                        for index, items in enumerate(halves, start=1):
                            await run_transport_split(
                                Shard(f"{shard.shard_id}_t{index}", tuple(items)), 1
                            )
                    else:
                        await fail_items(shard.items, exc, transport=True)
                    return
                await isolate_content_failure(shard.items, shard, exc)
                return
            except PiiValidationError as exc:
                # A validation error that reached us unwrapped (no ApiError
                # envelope) is still a content failure, so it still deserves
                # bounded isolation rather than failing the whole shard.
                await isolate_content_failure(shard.items, shard, exc)
                return
            except Exception as exc:
                await fail_items(shard.items, exc, transport=False)
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
    instruction: str | None = None
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
                repair_instruction=instruction,
            )
        except ApiError as exc:
            last = exc
            if not api_error_is_validation_failure(exc):
                raise
            instruction = _informed_instruction(repair_instruction, exc)
    assert last is not None
    raise last


def _informed_instruction(base: str, error: ApiError) -> str:
    """Restate the rule *and* name what actually failed.

    Without this the retry is a blind re-roll: every attempt re-sends a byte
    identical request, so a chunk of 121 entities kept failing on the same three
    while the model was never told which three or why.  Validator messages carry
    only ids, rule codes and synthetic values, so they are safe to return to the
    model that produced them.
    """

    detail = str(getattr(error, "cause", None) or "").replace(VALIDATION_MARKER, "").strip()
    if not detail:
        return base
    return (
        f"{base}\n\nThe previous attempt failed on exactly these points; "
        f"fix each one and change nothing else:\n{detail}"
    )
