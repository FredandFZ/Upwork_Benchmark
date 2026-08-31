from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from .storage import append_jsonl, read_jsonl, safe_filename


AUTH_URL = "https://usicore.umami.staging.platform.usw2.upwork/v1/auth/token"
LLM_URL = "https://ai.staging.platform.usw2.upwork/providers/v1/chat/completions"
RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}


class ApiError(RuntimeError):
    pass


class Stage1ApiClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        api_key: str,
        budget_id: str,
        model: str,
        reasoning_effort: str,
        retries: int,
        max_concurrent_requests: int,
        log_path: Path,
        failed_response_dir: Path,
        reasoning_effort_overrides: dict[str, str] | None = None,
    ) -> None:
        self.http_client = http_client
        self.api_key = api_key
        self.budget_id = budget_id
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.reasoning_effort_overrides = dict(reasoning_effort_overrides or {})
        self.retries = retries
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        self.log_path = log_path
        self.failed_response_dir = failed_response_dir
        self._token: str | None = None
        self._token_lock = asyncio.Lock()
        self._log_lock = asyncio.Lock()

    async def _get_token(self, force: bool = False) -> str:
        async with self._token_lock:
            if self._token and not force:
                return self._token
            response = await self.http_client.post(AUTH_URL, headers={"X-API-Key": self.api_key})
            if response.status_code != 200:
                raise ApiError(f"JWT request failed ({response.status_code}): {response.text[:500]}")
            try:
                data = response.json()
            except json.JSONDecodeError:
                token = response.text.strip()
            else:
                token = None
                if isinstance(data, dict):
                    token = data.get("token") or data.get("jwt") or data.get("accessToken") or data.get("access_token")
                    nested = data.get("data")
                    if not token and isinstance(nested, dict):
                        token = nested.get("token") or nested.get("jwt")
            if not isinstance(token, str) or not token.strip():
                raise ApiError("JWT endpoint returned no usable token")
            self._token = token.strip()
            return self._token

    async def call(
        self,
        *,
        project_id: str,
        run_mode: str,
        messages: list[dict[str, str]],
        target_requirement: str | None = None,
        validator: Callable[[dict[str, Any]], None] | None = None,
        failed_response_redactor: Callable[[str], str] | None = None,
    ) -> dict[str, Any]:
        effective_reasoning_effort = self.reasoning_effort_for(run_mode)
        last_error: Exception | None = None
        raw_content = ""
        for attempt in range(self.retries + 1):
            raw_content = ""
            started = datetime.now(timezone.utc)
            request_id: str | None = None
            usage: dict[str, Any] = {}
            status = "failure"
            try:
                async with self.semaphore:
                    token = await self._get_token()
                    response = await self.http_client.post(
                        LLM_URL,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "x-budget-id": self.budget_id,
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.model,
                            "reasoning_effort": effective_reasoning_effort,
                            "messages": messages,
                        },
                    )
                request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
                if response.status_code == 401 and attempt < self.retries:
                    await self._get_token(force=True)
                    raise _RetryableError(f"LLM authorization failed ({response.status_code})")
                if response.status_code in RETRYABLE_STATUS_CODES:
                    raise _RetryableError(f"Transient LLM error {response.status_code}: {response.text[:300]}")
                if response.status_code != 200:
                    raise ApiError(f"LLM request failed ({response.status_code}): {response.text[:1000]}")
                payload = response.json()
                request_id = request_id or (payload.get("id") if isinstance(payload, dict) else None)
                usage = payload.get("usage", {}) if isinstance(payload, dict) else {}
                choices = payload.get("choices") if isinstance(payload, dict) else None
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    raise ApiError("LLM response has no choices[0]")
                message = choices[0].get("message")
                if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                    raise ApiError("LLM response has no text content")
                raw_content = message["content"]
                result = parse_json_response(raw_content)
                if validator:
                    validator(result)
                status = "success"
                await self._log_call(
                    project_id,
                    run_mode,
                    target_requirement,
                    started,
                    status,
                    attempt,
                    usage,
                    request_id,
                    None,
                    effective_reasoning_effort,
                )
                return result
            except (_RetryableError, httpx.HTTPError, json.JSONDecodeError, ValueError, ApiError) as exc:
                last_error = exc
                error_text = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                if failed_response_redactor is not None:
                    # Some callers intentionally submit sensitive source text to
                    # the model.  Keep diagnostic artifacts useful without
                    # retaining a model response that could contain that text.
                    try:
                        raw_content = failed_response_redactor(raw_content)
                        error_text = failed_response_redactor(error_text)
                    except Exception:
                        raw_content = "[REDACTED: failed-response redaction unavailable]"
                        error_text = "[REDACTED: failure details unavailable]"
                await self._save_failed_response(
                    project_id, run_mode, target_requirement, attempt, raw_content, error_text
                )
                await self._log_call(
                    project_id,
                    run_mode,
                    target_requirement,
                    started,
                    status,
                    attempt,
                    usage,
                    request_id,
                    error_text,
                    effective_reasoning_effort,
                )
                retryable = isinstance(exc, (_RetryableError, httpx.HTTPError, json.JSONDecodeError, ValueError))
                if not retryable or attempt >= self.retries:
                    break
                await asyncio.sleep(min(2**attempt, 8))
        raise ApiError(
            f"{run_mode}{f'/{target_requirement}' if target_requirement else ''} failed after "
            f"{self.retries + 1} attempt(s): "
            f"{type(last_error).__name__ if last_error else 'unknown error'}"
            f"{f': {last_error}' if last_error and str(last_error) else ''}"
        )

    def reasoning_effort_for(self, run_mode: str) -> str:
        """Return the effective reasoning effort for one API run mode."""
        return self.reasoning_effort_overrides.get(run_mode, self.reasoning_effort)

    async def _log_call(
        self,
        project_id: str,
        run_mode: str,
        target_requirement: str | None,
        started: datetime,
        status: str,
        retry_count: int,
        usage: dict[str, Any],
        request_id: str | None,
        error: str | None,
        reasoning_effort: str,
    ) -> None:
        input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
        output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
        row = {
            "project_id": project_id,
            "run_mode": run_mode,
            "target_requirement": target_requirement,
            "model": self.model,
            "reasoning_effort": reasoning_effort,
            "timestamp": started.isoformat(),
            "success": status == "success",
            "retry_count": retry_count,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "api_request_id": request_id,
            "error": error,
        }
        async with self._log_lock:
            append_jsonl(self.log_path, row)

    async def _save_failed_response(
        self,
        project_id: str,
        run_mode: str,
        target_requirement: str | None,
        attempt: int,
        raw_content: str,
        error: str,
    ) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        name = safe_filename(f"{project_id}_{run_mode}_{target_requirement or 'global'}_{timestamp}_a{attempt + 1}.json")
        path = self.failed_response_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "project_id": project_id,
                    "run_mode": run_mode,
                    "target_requirement": target_requirement,
                    "attempt": attempt + 1,
                    "error": error,
                    "raw_response": raw_content,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


class _RetryableError(RuntimeError):
    pass


def parse_json_response(content: str) -> dict[str, Any]:
    candidate = content.strip()
    if not candidate:
        raise ValueError("LLM returned an empty response")
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        lines = lines[1:] if lines else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    value = json.loads(candidate)
    if not isinstance(value, dict):
        raise ValueError("LLM JSON response must be an object")
    return value


def summarize_calls(log_path: Path, project_id: str) -> dict[str, Any]:
    rows = [row for row in read_jsonl(log_path) if row.get("project_id") == project_id]
    successful = [row for row in rows if row.get("success")]
    counts = Counter(str(row.get("run_mode", "")).lower() for row in successful)
    return {
        "calls": dict(sorted(counts.items())),
        "total_calls": len(successful),
        "total_attempts": len(rows),
        "input_tokens": sum(int(row.get("input_tokens") or 0) for row in rows),
        "output_tokens": sum(int(row.get("output_tokens") or 0) for row in rows),
    }
