# Incremental value-removal audit

This is a migration-only `CONSISTENCY_AUDIT`. The Requirement inventory and existing Event set are frozen. Do not add, delete, move, split, merge, rename, or reclassify Requirements or Events.

Inspect every supplied Requirement by replaying its Events chronologically. For each existing MODIFY, determine whether its replacement/cancellation/mode switch/provider switch/count change/trigger change/scope narrowing made one or more previously established top-level attributes obsolete.

Return only:

- `EDIT_EVENT`, when an existing MODIFY must gain/correct `value_removals`; or
- `HUMAN_REVIEW`, when deletion is plausible but not entailed safely.

Do not return an EDIT merely to add `value_removals: null`; deterministic migration already did that. Do not alter unrelated semantics. An EDIT replacement must be a complete semantic replacement containing:

```json
{
  "event_type": "MODIFY",
  "value_updates": null,
  "value_removals": null,
  "scope_updates": null,
  "ambiguity": null,
  "execution": null
}
```

Preserve the original MODIFY's supported `value_updates` and `scope_updates`. Add a non-empty unique `value_removals` list only for keys that exist immediately before that Event. A key cannot be both updated and removed.

Distinguish deletion from a retained negative fact:

- delete an obsolete detail with `value_removals`;
- retain `status: "removed"`, `enabled: false`, or an equivalent value only when the negative fact itself remains operationally relevant.

Return the ordinary `CONSISTENCY_AUDIT` JSON schema with `run_mode` and `patches`. Output JSON only.
