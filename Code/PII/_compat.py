"""Single import shim for the shared ``stage1`` helpers.

``Code/pii_clean.py`` runs as a script (``sys.path[0] == Code/``) while the unit
tests import ``Code.PII.*``.  Only this module absorbs that difference; every
other module in the package imports from here with a relative import.
"""

from __future__ import annotations

try:  # ``python Code/pii_clean.py``
    from stage1.api_client import ApiError, Stage1ApiClient, parse_json_response
    from stage1.config import ANNOTATION_MODEL, REASONING_EFFORT
    from stage1.storage import (
        append_jsonl,
        id_key,
        read_json,
        read_jsonl,
        safe_filename,
        sha256_text,
        write_json,
    )
except ModuleNotFoundError:  # ``python -m unittest Code.tests.test_pii_*``
    from Code.stage1.api_client import ApiError, Stage1ApiClient, parse_json_response
    from Code.stage1.config import ANNOTATION_MODEL, REASONING_EFFORT
    from Code.stage1.storage import (
        append_jsonl,
        id_key,
        read_json,
        read_jsonl,
        safe_filename,
        sha256_text,
        write_json,
    )

__all__ = [
    "ANNOTATION_MODEL",
    "ApiError",
    "REASONING_EFFORT",
    "Stage1ApiClient",
    "append_jsonl",
    "id_key",
    "parse_json_response",
    "read_json",
    "read_jsonl",
    "safe_filename",
    "sha256_text",
    "write_json",
]
