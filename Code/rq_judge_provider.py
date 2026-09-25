"""Provider-neutral LLM Judge calls for ReqMemBench evaluation requests."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
import json
import re

try:  # Package import in tests; script import in CLIs.
    from .evaluation.alignment import validate_alignment_response
    from .evaluation.rq1 import validate_relation_response
    from .evaluation.state import validate_semantic_fact_response
    from .rq_run_identity import RQRunConfigError, file_sha256, judge_config_id
except ImportError:  # pragma: no cover
    from evaluation.alignment import validate_alignment_response
    from evaluation.rq1 import validate_relation_response
    from evaluation.state import validate_semantic_fact_response
    from rq_run_identity import RQRunConfigError, file_sha256, judge_config_id


RQ1_ALIGNMENT_REQUEST = "rq1-alignment-request-v1"
REQUIREMENT_ALIGNMENT_REQUEST = "requirement-alignment-request-v1"
STATE_SEMANTIC_REQUEST = "state-semantic-request-v1"
CLARIFICATION_REQUEST = "rq3-clarification-semantic-request-v1"


class RQJudgeError(RuntimeError):
    """Raised when a Judge request or provider response is invalid."""


@dataclass(frozen=True)
class JudgeCallResult:
    response: dict[str, Any]
    provider: str
    model: str
    model_version: str
    reasoning_effort: str
    request_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    started_at: str
    completed_at: str

    def record(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("response")
        return value


class JudgeProvider(Protocol):
    config_id: str

    async def call(
        self,
        request: Mapping[str, Any],
        *,
        response_schema: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> JudgeCallResult: ...

    async def aclose(self) -> None: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _array_ids(
    request: Mapping[str, Any], array_name: str, fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    rows = request.get(array_name)
    if not isinstance(rows, list):
        raise RQJudgeError(f"judge request.{array_name} must be an array")
    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise RQJudgeError(f"judge request.{array_name}[{index}] must be an object")
        item: dict[str, Any] = {}
        for field in fields:
            value = row.get(field)
            if not isinstance(value, str) or not value:
                raise RQJudgeError(
                    f"judge request.{array_name}[{index}].{field} is invalid"
                )
            item[field] = value
        output.append(item)
    return output


def response_schema_for_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Build a strict response schema with request-specific IDs and labels."""

    version = request.get("schema_version")
    required = request.get("required_response")
    if not isinstance(required, Mapping) or not isinstance(
        required.get("schema_version"), str
    ):
        raise RQJudgeError("judge request has no valid required_response")
    response_version = required["schema_version"]
    if version in {RQ1_ALIGNMENT_REQUEST, REQUIREMENT_ALIGNMENT_REQUEST}:
        pairs = _array_ids(
            request, "candidate_pairs", ("prediction_ref", "gold_ref")
        )
        prediction_refs = sorted({row["prediction_ref"] for row in pairs})
        gold_refs = sorted({row["gold_ref"] for row in pairs})
        relations = request.get("relation_values")
        item_properties = {
            "prediction_ref": {"type": "string", "enum": prediction_refs},
            "gold_ref": {"type": "string", "enum": gold_refs},
            "relation": {"type": "string", "enum": relations},
        }
    elif version == STATE_SEMANTIC_REQUEST:
        facts = _array_ids(request, "facts", ("fact_id",))
        item_properties = {
            "fact_id": {
                "type": "string",
                "enum": [row["fact_id"] for row in facts],
            },
            "relation": {
                "type": "string",
                "enum": request.get("relation_values"),
            },
        }
    elif version == CLARIFICATION_REQUEST:
        candidates = _array_ids(request, "candidates", ("candidate_id",))
        item_properties = {
            "candidate_id": {
                "type": "string",
                "enum": [row["candidate_id"] for row in candidates],
            },
            "issue_relation": {
                "type": "string",
                "enum": request.get("issue_relation_values"),
            },
            "question_validity": {
                "type": "string",
                "enum": request.get("question_validity_values"),
            },
        }
    else:
        raise RQJudgeError(f"unsupported Judge request schema {version!r}")
    for name, spec in item_properties.items():
        values = spec.get("enum")
        if isinstance(values, list) and not values:
            raise RQJudgeError(f"Judge response field {name} has an empty enum")
    item_fields = list(item_properties)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "relations"],
        "properties": {
            "schema_version": {"const": response_version},
            "relations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": item_fields,
                    "properties": item_properties,
                },
            },
        },
    }


def validate_judge_response(
    request: Mapping[str, Any], response: Mapping[str, Any]
) -> dict[str, Any]:
    version = request.get("schema_version")
    value = dict(response)
    if version == RQ1_ALIGNMENT_REQUEST:
        validate_relation_response(request, value)
    elif version == REQUIREMENT_ALIGNMENT_REQUEST:
        validate_alignment_response(request, value)
    elif version == STATE_SEMANTIC_REQUEST:
        validate_semantic_fact_response(request, value)
    elif version == CLARIFICATION_REQUEST:
        expected = {
            row["candidate_id"]
            for row in _array_ids(request, "candidates", ("candidate_id",))
        }
        required = request["required_response"]["schema_version"]
        if set(value) != {"schema_version", "relations"}:
            raise RQJudgeError("clarification response has invalid fields")
        if value.get("schema_version") != required:
            raise RQJudgeError("clarification response has invalid schema_version")
        rows = value.get("relations")
        if not isinstance(rows, list):
            raise RQJudgeError("clarification response.relations must be an array")
        seen: set[str] = set()
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping) or set(row) != {
                "candidate_id",
                "issue_relation",
                "question_validity",
            }:
                raise RQJudgeError(f"relations[{index}] has invalid fields")
            candidate_id = row.get("candidate_id")
            if candidate_id not in expected or candidate_id in seen:
                raise RQJudgeError(f"invalid or repeated candidate {candidate_id!r}")
            if row.get("issue_relation") not in request["issue_relation_values"]:
                raise RQJudgeError(f"relations[{index}] has invalid issue relation")
            if row.get("question_validity") not in request["question_validity_values"]:
                raise RQJudgeError(f"relations[{index}] has invalid question validity")
            seen.add(str(candidate_id))
        if seen != expected:
            raise RQJudgeError(
                f"clarification response is incomplete: {sorted(expected - seen)[:5]}"
            )
    else:
        raise RQJudgeError(f"unsupported Judge request schema {version!r}")
    return value


def deterministic_empty_response(
    request: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Avoid an LLM call when a valid request contains no items to classify."""

    version = request.get("schema_version")
    collection = {
        RQ1_ALIGNMENT_REQUEST: "candidate_pairs",
        REQUIREMENT_ALIGNMENT_REQUEST: "candidate_pairs",
        STATE_SEMANTIC_REQUEST: "facts",
        CLARIFICATION_REQUEST: "candidates",
    }.get(version)
    if collection is None or request.get(collection) != []:
        return None
    required = request.get("required_response")
    if not isinstance(required, Mapping):
        raise RQJudgeError("empty Judge request has no response contract")
    response = {"schema_version": required.get("schema_version"), "relations": []}
    return validate_judge_response(request, response)


def judge_messages(
    request: Mapping[str, Any], *, system_prompt: str
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt.rstrip()},
        {
            "role": "user",
            "content": json.dumps(request, ensure_ascii=False, indent=2),
        },
    ]


def normalize_judge_config(
    value: Mapping[str, Any], *, judge_prompt_path: str | Path
) -> dict[str, Any]:
    provider = value.get("provider")
    if provider not in {"upwork_stage1", "openai"}:
        raise RQRunConfigError("judge.provider must be upwork_stage1 or openai")
    config: dict[str, Any] = {
        "provider": provider,
        "api_interface_version": value.get("api_interface_version"),
        "model": value.get("model"),
        "model_version": value.get("model_version"),
        "reasoning_effort": value.get("reasoning_effort"),
        "max_concurrent_requests": value.get("max_concurrent_requests", 1),
        "retries": value.get("retries", 3),
        "timeout_seconds": value.get("timeout_seconds", 900),
        "judge_prompt_sha256": file_sha256(judge_prompt_path),
        "request_contract": "RQ_EVALUATOR_GENERATED_V1",
        "scorer_versions": {
            "RQ1": "rq1-evaluation-result-v1",
            "RQ2": "rq2-evaluation-result-v1",
            "RQ3": "rq3-evaluation-result-v1",
        },
        "strict_response_validation": True,
    }
    for field in (
        "api_interface_version",
        "model",
        "model_version",
        "reasoning_effort",
    ):
        if not isinstance(config[field], str) or not config[field].strip():
            raise RQRunConfigError(f"judge.{field} must be a non-empty string")
    for field in ("max_concurrent_requests", "retries", "timeout_seconds"):
        number = config[field]
        minimum = 0 if field == "retries" else 1
        if isinstance(number, bool) or not isinstance(number, int) or number < minimum:
            raise RQRunConfigError(f"judge.{field} is invalid")
    config["judge_config_id"] = judge_config_id(config)
    return config


class UpworkStage1JudgeProvider:
    """Internal provider that reuses the authenticated Stage 1 LLM client."""

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        system_prompt: str,
        log_dir: str | Path,
        api_key: str,
        budget_id: str,
        insecure: bool = False,
    ) -> None:
        import httpx
        try:
            from .stage1.api_client import Stage1ApiClient
        except ImportError:  # pragma: no cover
            from stage1.api_client import Stage1ApiClient

        self.config = dict(config)
        self.config_id = str(config["judge_config_id"])
        self.system_prompt = system_prompt
        root = Path(log_dir)
        root.mkdir(parents=True, exist_ok=True)
        self._http = httpx.AsyncClient(
            verify=not insecure,
            trust_env=False,
            timeout=httpx.Timeout(int(config["timeout_seconds"])),
        )
        self._client = Stage1ApiClient(
            http_client=self._http,
            api_key=api_key,
            budget_id=budget_id,
            model=str(config["model"]),
            reasoning_effort=str(config["reasoning_effort"]),
            retries=int(config["retries"]),
            max_concurrent_requests=int(config["max_concurrent_requests"]),
            log_path=root / "api_calls.jsonl",
            failed_response_dir=root / "failed_responses",
        )

    async def call(
        self,
        request: Mapping[str, Any],
        *,
        response_schema: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> JudgeCallResult:
        del response_schema
        started = _utc_now()
        result = await self._client.call(
            project_id=str(metadata.get("project_id", "unknown")),
            run_mode=f"RQ_JUDGE_{metadata.get('judge_stage', 'UNKNOWN')}",
            target_requirement=str(metadata.get("rq_id", "unknown")),
            messages=judge_messages(request, system_prompt=self.system_prompt),
            validator=lambda value: validate_judge_response(request, value),
        )
        return JudgeCallResult(
            response=validate_judge_response(request, result),
            provider="upwork_stage1",
            model=str(self.config["model"]),
            model_version=str(self.config["model_version"]),
            reasoning_effort=str(self.config["reasoning_effort"]),
            request_id=None,
            input_tokens=None,
            output_tokens=None,
            started_at=started,
            completed_at=_utc_now(),
        )

    async def aclose(self) -> None:
        await self._http.aclose()


class OpenAIJudgeProvider:
    """Public provider using the official OpenAI Responses API."""

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        system_prompt: str,
        api_key: str | None = None,
    ) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RQJudgeError(
                "OpenAI provider requires the official 'openai' Python package"
            ) from exc
        self.config = dict(config)
        self.config_id = str(config["judge_config_id"])
        self.system_prompt = system_prompt
        kwargs: dict[str, Any] = {
            "timeout": int(config["timeout_seconds"]),
            "max_retries": int(config["retries"]),
        }
        if api_key:
            kwargs["api_key"] = api_key
        self._client = AsyncOpenAI(**kwargs)

    async def call(
        self,
        request: Mapping[str, Any],
        *,
        response_schema: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> JudgeCallResult:
        del metadata
        started = _utc_now()
        format_name = re.sub(
            r"[^A-Za-z0-9_-]+", "_", str(request.get("schema_version", "judge"))
        )[:64]
        arguments: dict[str, Any] = {
            "model": self.config["model"],
            "instructions": self.system_prompt,
            "input": json.dumps(request, ensure_ascii=False, indent=2),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": format_name,
                    "schema": dict(response_schema),
                    "strict": True,
                }
            },
            "store": False,
        }
        effort = str(self.config["reasoning_effort"])
        if effort.casefold() not in {"none", "not_applicable"}:
            arguments["reasoning"] = {"effort": effort}
        response = await self._client.responses.create(**arguments)
        try:
            parsed = json.loads(response.output_text)
        except (AttributeError, json.JSONDecodeError) as exc:
            raise RQJudgeError("OpenAI Judge returned invalid structured JSON") from exc
        if not isinstance(parsed, dict):
            raise RQJudgeError("OpenAI Judge response must be a JSON object")
        usage = getattr(response, "usage", None)
        return JudgeCallResult(
            response=validate_judge_response(request, parsed),
            provider="openai",
            model=str(self.config["model"]),
            model_version=str(self.config["model_version"]),
            reasoning_effort=effort,
            request_id=getattr(response, "id", None),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            started_at=started,
            completed_at=_utc_now(),
        )

    async def aclose(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result


def create_judge_provider(
    config: Mapping[str, Any],
    *,
    judge_prompt_path: str | Path,
    log_dir: str | Path,
    upwork_api_key: str | None = None,
    upwork_budget_id: str | None = None,
    openai_api_key: str | None = None,
    insecure: bool = False,
) -> JudgeProvider:
    normalized = normalize_judge_config(config, judge_prompt_path=judge_prompt_path)
    prompt = Path(judge_prompt_path).read_text(encoding="utf-8-sig")
    if normalized["provider"] == "upwork_stage1":
        if not upwork_api_key or not upwork_budget_id:
            raise RQJudgeError(
                "upwork_stage1 Judge requires UPWORK_API_KEY and UPWORK_BUDGET_ID"
            )
        return UpworkStage1JudgeProvider(
            normalized,
            system_prompt=prompt,
            log_dir=log_dir,
            api_key=upwork_api_key,
            budget_id=upwork_budget_id,
            insecure=insecure,
        )
    return OpenAIJudgeProvider(
        normalized, system_prompt=prompt, api_key=openai_api_key
    )


__all__ = [
    "JudgeCallResult",
    "JudgeProvider",
    "OpenAIJudgeProvider",
    "RQJudgeError",
    "UpworkStage1JudgeProvider",
    "create_judge_provider",
    "deterministic_empty_response",
    "judge_messages",
    "normalize_judge_config",
    "response_schema_for_request",
    "validate_judge_response",
]
