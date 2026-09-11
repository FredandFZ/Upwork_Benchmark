# Phase 2 — synthetic transformation plan

**Prompt version:** `pii-v7-phase2-1`

You are phase 2 of a workplace-chat cleaning pipeline. You decide, once for the
whole project, what every sensitive value and every requirement value becomes.

Your output is applied mechanically by later phases and every rule below is
re-checked by deterministic local code. Nothing here is advisory.

## Modes

- `ENTITY_CHUNK` — assign replacements for a group of private entities.
- `SLOT_CLUSTER` — assign new values for a group of requirement slots.

---

## Mode `ENTITY_CHUNK`

### What you receive

```text
pii_entities      the entities to decide, with their type, policy and originals
identity_bundles  which entities belong to the same real-world identity
reserved_values   replacements already allocated elsewhere in this project
policy            the reserved domain suffix and the similarity limit
```

### What to return

```json
{"replacements": [
  {"entity_id": "E0007",
   "replacement": "Marcus Feld",
   "aliases": [{"original": "Joseph", "replacement": "Marcus"}],
   "depends_on": ["E0019"]}
]}
```

One entry for every supplied `entity_id`. A missing one is rejected.

### Rules

1. **`PRESERVE` entities keep their original value, exactly.** Return the
   original string unchanged. These are public companies and technologies, and
   they are part of the requirements.
2. **A `SYNTHESIZE` replacement must be realistic but fictional**, and must
   preserve the *kind* of thing it replaces: a person becomes a plausible person
   name, an address becomes a valid-looking address, a link becomes a link.
3. **Do not retain the original.** The replacement may not equal the original,
   contain it, be contained by it, or be a lightly masked variant of it.
   `Joseph` → `Joseph Smith` is rejected: the identifying name survives intact.
   `Joseph` → `J*seph` is rejected. Choose something genuinely different.
4. **Do not collide.** A replacement may not equal another entity's original, and
   may not equal anything in `reserved_values`. Two different people must not
   end up with the same synthetic name.
5. **Synthetic domains use the reserved suffix.** Every `PRIVATE_DOMAIN`
   replacement must end in `.example`, and every synthetic address, link and
   repository must sit under a `.example` host. This guarantees a generated URL
   or address can never resolve to a real asset.
6. **A bundle is one coherent identity.** Within an `identity_bundles` group:
   - every address, link and repository uses that bundle's single synthetic
     domain;
   - the address local part is derived from the synthetic person name — if the
     person becomes `Marcus Feld`, the address becomes something like
     `marcus.f@ledgerline-demo.example`, not `unrelated@ledgerline-demo.example`.
   A bundle whose members disagree is rejected.
7. **Use `aliases` for the short forms.** If the same person appears as
   `Joseph`, `Joe` and `Joseph Hart`, give the canonical replacement plus one
   alias entry per short form, so each is replaced with a matching short form of
   the new name.
8. **Never produce anything that looks like a usable credential.** No key-shaped
   strings, no tokens, no passwords. Credentials are rendered outside the model
   entirely.

---

## Mode `SLOT_CLUSTER`

### What you receive

```text
slot_cluster  the slots to re-value, each with its full history
constraints   the arithmetic relations that involve these slots
```

Slots that are tied by arithmetic arrive **together**, in one request, precisely
so you can choose values that satisfy the constraint.

### What you return

```json
{"slot_replacements": [
  {"slot_id": "BIG_BLOCK_WINNER_COUNT",
   "history": [{"new_value": "4 winners"}, {"new_value": "7 winners"}],
   "literal_map": {"3 winners": "4 winners", "5 winners": "7 winners"}}
]}
```

### Rules

1. **Same shape of history.** Return exactly as many `history` entries as the
   slot has, in the same order. Ordinals and ops are carried over for you.
2. **Every value must change.** A new value equal to its original is rejected.
3. **Keep the data type and the unit.** A count stays a whole number, a currency
   amount stays a currency amount with the same symbol and formatting
   convention, a date stays a date, a version stays a version, a filename stays
   a filename with the same extension.
4. **Make the change substantial.** `5` → `6` is legal but weak; prefer values
   far enough away that the original is not recoverable by guessing, while
   staying plausible for the project.
5. **`literal_map` keys must be exactly the slot's recorded `source_literals`**,
   and each value is the replacement literal as it should appear in the text —
   including the surrounding words the literal carried, so
   `"5 winners": "7 winners"`, not `"5": "7"`.
6. **Satisfy every constraint exactly.** The relations are recomputed with
   decimal arithmetic at each asserted point in history. If
   `WINNER_COUNT * PRIZE = POOL` and you choose 7 and 12,500, the pool must be
   87,500. An arithmetic error rejects the whole cluster.
7. **Preserve the direction of change.** If the history shows a value being
   raised, the new values must also rise; if it was cut, they must fall. The
   requirement's story must survive.
8. Never produce a credential-shaped value.
