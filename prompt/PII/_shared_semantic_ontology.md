# Semantic ontology

**Prompt version:** `pii-v7-semantic-ontology-1`

Shared by message semantic extraction, project consolidation and verification.

## Speech act

What the message *does*, not what it is about.

`REQUEST`, `COMMITMENT`, `ACCEPTANCE`, `REJECTION`, `QUESTION`, `ANSWER`,
`STATEMENT`, `REPORT`, `ACKNOWLEDGEMENT`, `PROPOSAL`, `COMPLAINT`, `OTHER`

## Polarity

`AFFIRMATIVE`, `NEGATIVE`, `CONDITIONAL`, `UNCERTAIN`

Polarity is load-bearing. "We will ship Friday", "We will not ship Friday" and
"We might ship Friday" are three different project facts.

## Execution status

Where the work stands, as of this message.

`NOT_STARTED`, `IN_PROGRESS`, `DELIVERED`, `VERIFIED`, `BLOCKED`, `FAILED`,
`ABANDONED`, `NOT_APPLICABLE`

## Ambiguity

`NONE`, `UNDERSPECIFIED`, `CONFLICTING`, `OPEN_QUESTION`, `RESOLVED`

Ambiguity must be preserved, not tidied away. A message that leaves a question
open must still leave it open after rewriting, and a message that resolves one
must still resolve it.

## Decision kinds

`APPROVE`, `REJECT`, `DEFER`, `CHANGE`, `CONFIRM`, `CANCEL`

## Semantic slots

A **slot** is a project parameter identified by its *meaning*, not by the shape
of its value.

The point is that the same literal can be two different parameters, and two
different literals can be the same parameter over time.

- "5 winners" and "5 rounds" are two slots that happen to share the number `5`.
- "$10,000 each" early on and "$12,000 each" later are one slot with a history.

Name a slot for what it *is*, in `UPPER_SNAKE_CASE`, specific enough to be
unambiguous within the project: `BIG_BLOCK_WINNER_COUNT`,
`BIG_BLOCK_PRIZE_PER_WINNER`, `LAUNCH_DEADLINE`, `PAYOUT_THRESHOLD`.

Do **not** name a slot after the value's datatype. `NUMBER_1`, `AMOUNT`,
`DATE_2` carry no meaning and are rejected.

### Value types

`COUNT`, `AMOUNT`, `PERCENTAGE`, `DURATION`, `DATE`, `VERSION`, `FILENAME`,
`IDENTIFIER`, `THRESHOLD`, `RATE`, `DIMENSION`, `OTHER`

### What is not a slot

- **Ordered-list numbering.** The `1.`, `2.`, `3.` that organise a checklist are
  layout, not data. Leave them alone.
- **Technical identifiers.** The `721` in `ERC-721` and the `256` in `AES-256`
  are part of a standard's name.
- **Anything inside a protected token, an address, a link or a handle.** Those
  are complete values handled as units elsewhere.

## Slot history

Each slot carries an ordered history:

- `INTRODUCE` — the first time the parameter is set. `old_value` is null.
- `MODIFY` — the value changed. `old_value` must equal the previous entry's
  `new_value`.
- `CONFIRM` — restated without changing.
- `REMOVE` — the parameter was dropped.

The chain must be continuous and ordered by message position. A broken chain
loses the requirement evolution that the dataset exists to capture.

## Relations

An arithmetic invariant between slots, written as `LHS = RHS` over slot ids:

```text
BIG_BLOCK_WINNER_COUNT * BIG_BLOCK_PRIZE_PER_WINNER = BIG_BLOCK_POOL_TOTAL
```

Only `+ - * /`, parentheses, numeric literals and slot ids are allowed.

Record a relation only when the conversation actually asserts it. A relation is
re-evaluated exactly by local code, so an invented one will be rejected — and a
real one that the conversation itself contradicts must be recorded as it stands
rather than silently "fixed".
