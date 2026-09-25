# ReqMemBench Phase A Reasoning Instructions v1

Read `task.json` and `history.jsonl`. No repository is available in this phase.

Use only the evidence visible in the current workspace. Do not assume that omitted
history exists.

Your response must complete the following reasoning tasks in one JSON object:

1. Identify the historical requirements relevant to the current client task. For
   each requirement, cite only visible `message_id` values as evidence.
2. Reconstruct the complete requirement state that was valid immediately before
   the current task. Handle updates, overrides, removals, lifecycle, scope,
   ambiguity, and execution evidence. Do not apply the current task to this
   pre-task state.
3. Decide whether the visible evidence is sufficient to act on the current task.
   Use `ACT` only when it determines a unique material post-task state; otherwise
   use `CLARIFY` and ask concrete questions that would resolve the blocking facts.
4. For `ACT`, return the complete closed-world post-task state for every affected
   requirement. Preserve fields that remain valid, omit fields that were removed
   or replaced, and list removed attribute names in `removed_attribute_keys`.

Use your own stable `requirement_ref` values. Do not invent internal benchmark
identifiers. Return only JSON conforming to `response.schema.json`; do not include
private chain-of-thought or prose outside the JSON object.
