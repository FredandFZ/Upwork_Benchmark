# EVENT_VERIFICATION addendum

In addition to evidence alignment, replay each Requirement through the provisional Event.

## Mandatory implementation-relevance gate

For every `INTRODUCE` and especially every `MODIFY`, classify each entry in `value_updates`, `value_removals`, and `scope_updates` independently.

An attribute is implementation-relevant only when it changes at least one of:

- software behavior or system-enforced business logic;
- UI/UX behavior or product copy rendered by the software;
- validation, authentication, authorization, API, schema, data, or state semantics;
- provider, protocol, algorithm, configuration, infrastructure, deployment, or runtime behavior;
- an executable test/tooling artifact explicitly requested as a deliverable;
- a concrete acceptance condition used to judge implemented behavior.

Delete project-management content, including freelancer/project deadlines, delivery schedules, meetings, staffing, availability, budgets, invoices, contracts, milestone funding/payment administration, generic progress or effort estimates, hand-off logistics, reminders, and communication preferences.

Time values require an explicit distinction:

- executable expiration, timeout, retention, recurrence, delayed execution, or another system-controlled temporal rule is implementation-relevant;
- a date or duration for the freelancer/project to finish work is not implementation-relevant.

Use the following mandatory verdict behavior:

1. Return `DELETE` when the whole `INTRODUCE` or `MODIFY` is non-implementation-related.
2. Return `EDIT` for a mixed Event and remove every non-implementation attribute while preserving supported implementation-relevant attributes.
3. Return `DELETE` if a cleaned `MODIFY` would have no `value_updates`, `value_removals`, or `scope_updates`.
4. Do not preserve an administrative attribute merely because it already exists in provisional Requirement state.
5. For every `KEEP` or `EDIT`, make `decision_note` name the concrete software behavior, artifact, configuration, data rule, interface, or acceptance condition affected. If none can be identified from the evidence, return `DELETE`.

Examples:

```text
"Finish this feature within 10 days."
-> DELETE the deadline-only Event or EDIT the deadline out of a mixed Event

"The account expires 10 days after registration."
-> KEEP the executable expiration-rule change when the evidence supports it
```

## MODIFY state-replay integrity

For every retained or edited `MODIFY`, also verify that:

- `value_removals` is null or a non-empty unique list of top-level keys existing before the Event;
- no key is both updated and removed;
- mode/provider/entity/count/trigger replacements remove obsolete attributes that would otherwise conflict with the new state;
- a literal value such as `"removed"` is retained only when it is a meaningful current status, not a substitute for deleting an obsolete key;
- execution is null and will be reset by replay.

An EDIT replacement must include `value_updates`, `value_removals`, `scope_updates`, `ambiguity`, and `execution`. Use `value_removals: null` when no key is deleted.
