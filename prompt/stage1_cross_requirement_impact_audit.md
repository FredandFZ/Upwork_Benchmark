# CROSS_REQUIREMENT_IMPACT_AUDIT stage instructions

Evaluate every supplied candidate independently. Candidate retrieval is deliberately high recall and may contain false positives.

Use only the source Event, the source state before/after, the candidate's state at that source time, its history through that time, and supplied local context. Never use later project knowledge.

Decision policy:

- `ADD_EVENT`: the source decision necessarily changes the candidate's current requirement state and no matching Event exists.
- `EDIT_EVENT`: the candidate already has a same-message or otherwise identified Event, but it omits required updates/removals/scope changes. Supply its exact locator.
- `NO_IMPACT`: overlap is historical, descriptive, incidental, or the candidate remains valid unchanged.
- `HUMAN_REVIEW`: there are multiple plausible interpretations or propagation would require a new client decision.

For ADD/EDIT, `new_event` must be a complete provisional MODIFY with exact source message text and all fields, including `value_removals`. Delete obsolete top-level keys; preserve a `"removed"`/false value only when the negative fact itself remains operationally relevant. Never update and remove the same key. Never delete a key absent immediately before the Event.

Do not propagate implementation status. The new MODIFY has `execution: null` and `ambiguity: null`. Return exactly one decision per candidate and JSON only.
