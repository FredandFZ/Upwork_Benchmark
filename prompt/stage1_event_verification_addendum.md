# EVENT_VERIFICATION v0.6 addendum

In addition to evidence alignment, replay each Requirement through the provisional Event.

For every MODIFY, verify that:

- `value_removals` is null or a non-empty unique list of top-level keys existing before the Event;
- no key is both updated and removed;
- mode/provider/entity/count/trigger replacements remove obsolete attributes that would otherwise conflict with the new state;
- a literal value such as `"removed"` is retained only when it is a meaningful current status, not a substitute for deleting an obsolete key;
- execution is null and will be reset by replay.

An EDIT replacement must include `value_updates`, `value_removals`, `scope_updates`, `ambiguity`, and `execution`. Use `value_removals: null` when no key is deleted.
