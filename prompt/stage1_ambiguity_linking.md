# ReqMemBench AMBIGUITY_LINKING

You perform one narrow post-verification task for exactly one Requirement.
The supplied Events are final verified Events. They are already in chronological
order and already carry the exact Event IDs used by final assembly.

Your only job is to decide when each `AMBIGUOUS` Event becomes resolved.

## Immutable input

- Do not add, delete, edit, merge, split, move, or retype any Event.
- Do not change Requirement ontology, titles, families, source messages, or evidence.
- Do not question or re-anchor an Event's source evidence.
- Use only Event IDs that appear in `CURRENT_EVENTS` for the target Requirement.
- Return exactly one decision for every `AMBIGUOUS` Event in the target Requirement.

## Resolution test

First identify the exact Requirement state made uncertain by the AMBIGUOUS Event.
Represent it with one or more paths such as:

- `attributes.process_reward_delivery_copy`
- `scope.components`
- `scope.contexts`
- `scope.persistence`
- `lifecycle_status`

Then inspect every later potential resolver in order. A later Event resolves the
ambiguity only if its own semantic change directly settles the same uncertain
choice, value, scope boundary, or lifecycle question.

Allowed resolver Event types are `INTRODUCE`, `MODIFY`, `DEFER`, `RESUME`, and
`REMOVE`. Execution Events and later AMBIGUOUS Events are not resolvers.

A later Event is not a resolver merely because:

- it is a `MODIFY`;
- it changes another attribute in the same Requirement;
- its dimension is also VALUE, SCOPE, or LIFECYCLE;
- it occurs near the AMBIGUOUS Event;
- it is a generic acknowledgement;
- it reports implementation, failure, or verification;
- it restates the uncertainty without selecting an answer.

When an intermediate Event is a plausible resolver type but changes unrelated
state, place its ID in `non_resolving_intermediate_event_ids` and continue
searching. Stop at the earliest later Event that explicitly and completely
settles the exact ambiguity. If no Event does, return `UNRESOLVED`.

One resolver may resolve multiple distinct AMBIGUOUS Events. Each ambiguity
still receives its own decision. One ambiguity must never be assigned multiple
resolvers; select the earliest complete resolver.

Use `HIGH` confidence only when the affected state and resolution are explicit.
Use `MEDIUM` or `LOW` when interpretation, coreference, or completeness is
uncertain. The pipeline applies only HIGH-confidence RESOLVED links.

## Calibration example

```text
E002 AMBIGUOUS:
Prize delivery is unclear between one-click claim and automatic wallet transfer.

E003 MODIFY:
Changes Small/Big prize-draw amounts.

E004 MODIFY:
Changes reward delivery to paid directly to the wallet.
```

Correct decision:

```json
{
  "ambiguity_event_id": "REQ_ABOUT_PAGE_CONTENT_E002",
  "affected_state_paths": [
    "attributes.process_reward_delivery_copy"
  ],
  "resolution_status": "RESOLVED",
  "resolver_event_id": "REQ_ABOUT_PAGE_CONTENT_E004",
  "non_resolving_intermediate_event_ids": [
    "REQ_ABOUT_PAGE_CONTENT_E003"
  ],
  "decision_note": "E003 changes prize-draw amounts; E004 resolves automatic versus claim-based reward delivery.",
  "confidence": "HIGH"
}
```

E003 must not close the ambiguity because it changes unrelated state.

## Output schema

Return JSON only:

```json
{
  "run_mode": "AMBIGUITY_LINKING",
  "requirement_id": "REQ_EXAMPLE",
  "decisions": [
    {
      "ambiguity_event_id": "REQ_EXAMPLE_E002",
      "affected_state_paths": [
        "attributes.example_attribute"
      ],
      "resolution_status": "RESOLVED",
      "resolver_event_id": "REQ_EXAMPLE_E004",
      "non_resolving_intermediate_event_ids": [
        "REQ_EXAMPLE_E003"
      ],
      "decision_note": "The later Event directly settles the same uncertain attribute.",
      "confidence": "HIGH"
    }
  ]
}
```

For an unresolved ambiguity, use:

```json
{
  "ambiguity_event_id": "REQ_EXAMPLE_E002",
  "affected_state_paths": [
    "attributes.example_attribute"
  ],
  "resolution_status": "UNRESOLVED",
  "resolver_event_id": null,
  "non_resolving_intermediate_event_ids": [],
  "decision_note": "No later Event settles the uncertain value.",
  "confidence": "HIGH"
}
```
