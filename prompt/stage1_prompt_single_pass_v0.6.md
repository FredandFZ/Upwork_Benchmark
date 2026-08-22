# ReqMemBench Stage 1 single-pass compatibility prompt

Return one canonical ReqMemBench Stage 1 annotation object and JSON only. Use `annotation_version: "v0.6"`.

Every Event must contain exactly: `event_id` (which may be omitted because code regenerates it), `source_message`, `event_type`, `value_updates`, `value_removals`, `scope_updates`, `ambiguity`, and `execution`.

`value_removals` is null except on MODIFY. On MODIFY it may be a non-empty unique array of top-level attribute keys that exist before the Event and become obsolete. A key cannot be both updated and removed. A literal value such as `"removed"` represents a retained current business status; it does not delete the attribute. Replay removals before updates. Any MODIFY resets execution to null.

Use the Event types and evidence/authority rules from ReqMemBench Stage 1. Preserve raw source message ID, speaker, and text exactly. Do not invent Events or merge independently evolving Requirements. Include every historically valid Requirement; deterministic code applies corpus eligibility filters.
