from __future__ import annotations

import json
from typing import Any

from .config import RUN_MODES


SECTION_ORDER = (
    "PROJECT_METADATA",
    "MESSAGES",
    "EVIDENCE_INDEX",
    "CURRENT_INVENTORY",
    "CURRENT_EVENTS",
    "TARGET_REQUIREMENT",
    "IMPACT_SOURCE",
    "IMPACT_CANDIDATES",
    "LOCAL_CONTEXT",
)


def _render(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def build_stage_messages(
    common_prompt: str,
    run_mode: str,
    sections: dict[str, Any],
    stage_instructions: str | None = None,
) -> list[dict[str, str]]:
    if run_mode not in RUN_MODES:
        raise ValueError(f"Unsupported RUN_MODE: {run_mode}")
    unknown = set(sections).difference(SECTION_ORDER)
    if unknown:
        raise ValueError(f"Unsupported prompt section(s): {', '.join(sorted(unknown))}")
    blocks = [f"<RUN_MODE>\n{run_mode}\n</RUN_MODE>"]
    if stage_instructions and stage_instructions.strip():
        blocks.append(f"<STAGE_INSTRUCTIONS>\n{stage_instructions.strip()}\n</STAGE_INSTRUCTIONS>")
    for name in SECTION_ORDER:
        if name in sections:
            blocks.append(f"<{name}>\n{_render(sections[name])}\n</{name}>")
    blocks.append("Return JSON only, without Markdown fences or surrounding commentary.")
    return [
        {"role": "system", "content": common_prompt.rstrip()},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]


def build_single_pass_messages(prompt: str, normalized: dict[str, Any]) -> list[dict[str, str]]:
    content = (
        f"{prompt.rstrip()}\n\n"
        f"Project ID: {normalized['project_id']}\n\n"
        "Complete normalized chat history:\n"
        f"{json.dumps(normalized['messages'], ensure_ascii=False, indent=2)}\n\n"
        "Return only the canonical Stage 1 JSON object."
    )
    return [{"role": "user", "content": content}]
