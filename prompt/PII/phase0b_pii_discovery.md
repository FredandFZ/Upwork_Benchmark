# Phase 0B — PII discovery

**Prompt version:** `pii-v7-phase0b-1`

You are phase 0B of a workplace-chat de-identification pipeline.

Your task is **classification only**. Do not rewrite, paraphrase, redact or
improve any message. Later phases do that.

## What you receive

```text
policy         the entity taxonomy and the fixed type -> policy mapping
safe_messages  complete messages, with real credentials already removed
secret_tokens  every protected token present in this batch
```

The text you see has already had live credentials replaced by
`<SECRET_CANDIDATE:...>` tokens. Everything else — names, addresses, links,
numbers — is still the original.

## What to return

```json
{"messages": [
  {"ordinal": 12,
   "occurrences": [
     {"source": "Joseph",
      "start": 3,
      "end": 9,
      "entity_type": "PERSON",
      "policy": "SYNTHESIZE",
      "normalized_value": "Joseph",
      "link_hint": "L1",
      "confidence": "HIGH"}
   ]}
]}
```

Return one entry per supplied message, including messages with no occurrences at
all (`"occurrences": []`).

## Field rules

- `source` — the exact substring, character for character.
- `start` / `end` — character offsets into that message's text such that
  `text[start:end] == source`. If you are unsure of the offsets, still give your
  best values; the exact quote is what matters.
- `entity_type` — one type from the taxonomy.
- `policy` — must be the policy fixed for that type. It is re-derived and
  checked locally; a mismatch rejects the response.
- `normalized_value` — the canonical form used to recognise the *same* thing
  across messages. Use it to unify `Will`, `will` and `Will Hartley` under one
  value when they are the same person, and to unify a link written with and
  without a trailing slash.
- `link_hint` — an arbitrary label, reused across occurrences that belong to the
  **same real-world identity**. Give a person and their address the same hint so
  they are re-synthesized together; otherwise the synthetic name and the
  synthetic address could end up unrelated. Labels only need to be consistent
  within one response.
- `confidence` — `HIGH`, `MEDIUM` or `LOW`.

## Coverage

Some things are certain, and omitting one is an error rather than a judgement
call. Every **email address, link, social handle, blockchain address and
telephone number** in the text must appear as an occurrence. Every
`<SECRET_CANDIDATE:...>` token must appear as an occurrence typed
`SECRET_CANDIDATE`.

Occurrences must not overlap each other. Prefer the **maximal** span: classify a
whole address as one `EMAIL`, not a `PERSON` plus a `PRIVATE_DOMAIN`.

## Judgement

Be thorough on the things that identify people and private projects. A private
project alias, a participant's first name in a greeting, a signature line, a
dashboard link — all of these identify, and all should be found.

Be equally firm in the other direction: a public company, service or technology
is not sensitive because it is named, and a requirement-bearing term is never a
private project name. Classifying `GitHub` as `PRIVATE_ORGANIZATION` is rejected.

When a value is genuinely sensitive but you are unsure which type fits, choose
the closest identifying type rather than `NON_PII`. When it is genuinely not
identifying, say so.
