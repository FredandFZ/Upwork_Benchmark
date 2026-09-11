"""Exception hierarchy for the v7 PII cleaning pipeline.

The split between ``ValueError`` and ``RuntimeError`` is load bearing.
``Stage1ApiClient.call`` retries an attempt only when the validator raises a
``ValueError`` subclass (``Code/stage1/api_client.py:173``), and it redacts the
raw model response on that same path.  Therefore every rejection produced by a
local response validator MUST inherit from :class:`PiiValidationError`.  Control
flow errors that should never be retried inherit from :class:`PiiError`.
"""

from __future__ import annotations

from typing import Any, Sequence


class PiiError(RuntimeError):
    """A pipeline invariant was violated; retrying the same call cannot help."""


class PiiValidationError(ValueError):
    """A model response failed local validation and is worth one more attempt.

    ``failures`` carries the machine-readable codes so the batch -> per-message
    fallback, the unresolved ledger and the agent task package can all describe
    the same rejection with the same vocabulary instead of parsing prose.
    """

    def __init__(
        self,
        message: str,
        *,
        failures: Sequence[str] = (),
        details: Sequence[dict[str, Any]] = (),
    ) -> None:
        super().__init__(message)
        self.failures: tuple[str, ...] = tuple(failures)
        self.details: tuple[dict[str, Any], ...] = tuple(details)


class SecretLeakError(PiiValidationError):
    """A model response reintroduced a value the secret shield had removed."""


class PiiLeakError(PiiValidationError):
    """A model response reintroduced a discovered PII value."""


class PlanConsistencyError(PiiValidationError):
    """A transformation plan chunk is internally or globally inconsistent."""


class UnresolvedMessagesError(PiiError):
    """One or more messages could not be cleaned; no output may be committed."""

    def __init__(self, message: str, *, message_ids: Sequence[Any] = ()) -> None:
        super().__init__(message)
        self.message_ids: tuple[Any, ...] = tuple(message_ids)


class AuditFailure(PiiError):
    """Phase 6B found at least one hard-fail violation in the rendered output."""

    def __init__(self, message: str, *, violations: Sequence[dict[str, Any]] = ()) -> None:
        super().__init__(message)
        self.violations: tuple[dict[str, Any], ...] = tuple(violations)


class ResumeSignatureError(PiiError):
    """The raw chat changed, so per-message run artifacts cannot be trusted."""


# ``[PII_V7_VALIDATION]`` is embedded in every validation failure message so the
# disposition check keeps working even against an ``ApiError`` built by an older
# client that does not preserve ``cause``.  See ``api_error_is_validation_failure``.
VALIDATION_MARKER = "[PII_V7_VALIDATION]"


def marked(message: str) -> str:
    """Tag a validation message so it stays recognizable through ``ApiError``."""

    return f"{VALIDATION_MARKER} {message}"


def api_error_is_validation_failure(error: BaseException) -> bool:
    """Whether an exhausted API call failed on content rather than transport.

    Content failures are worth isolating per message and, ultimately, worth
    handing to a repairing agent.  Transport failures are not: an agent cannot
    fix a ``ConnectError``, and asking it to would invite it to invent text for
    a message no model ever read.

    Prefers the structured ``cause`` added to ``ApiError``; falls back to the
    literal marker, then to the exception type names that
    ``Code/stage1/api_client.py:177-182`` formats into the message.
    """

    cause = getattr(error, "cause", None)
    if cause is not None:
        return isinstance(cause, PiiValidationError)
    text = str(error)
    if VALIDATION_MARKER in text:
        return True
    return any(
        name in text
        for name in (
            "PiiValidationError",
            "SecretLeakError",
            "PiiLeakError",
            "PlanConsistencyError",
            "ValueError",
        )
    )
