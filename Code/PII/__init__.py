"""Resumable, fail-closed PII cleaning pipeline (v7) for ReqMemBench chats.

Public surface is intentionally narrow; import submodules directly for internals.
The pipeline facade is re-exported once the orchestration module exists.
"""

from __future__ import annotations

from .config import ENGINE_VERSION, PHASES, PiiConfig, ProjectFiles
from .errors import (
    AuditFailure,
    PiiError,
    PiiValidationError,
    UnresolvedMessagesError,
)

__all__ = [
    "AuditFailure",
    "ENGINE_VERSION",
    "PHASES",
    "PiiConfig",
    "PiiError",
    "PiiValidationError",
    "ProjectFiles",
    "UnresolvedMessagesError",
]
