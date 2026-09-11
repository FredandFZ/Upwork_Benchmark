# Output contract

**Prompt version:** `pii-v7-output-contract-1`

These rules apply to every phase of this pipeline.

1. Return **one JSON object and nothing else**. No Markdown fences, no prose
   before or after, no trailing commentary.
2. Return **exactly the keys the phase asks for**. Do not add a confidence
   score, an explanation field, a `notes` field, or any other key that was not
   requested. Unknown keys cause the whole response to be rejected.
3. Echo every identifier **with its original JSON value and type**. If the input
   says `"ordinal": 231`, return the integer `231`, not the string `"231"`.
4. Return **one entry for every supplied item**, in the input order. Never add,
   omit, merge, split or reorder items. A missing item rejects the response.
5. Never invent an item that was not supplied.
6. Every quoted substring you return must be an **exact, character-for-character
   substring of the supplied text**, including its capitalisation, punctuation
   and internal whitespace. Do not normalise, trim or re-case it.
7. The request may include a `validation_repair` field. When present, the
   previous response was rejected by a deterministic local validator. Read it
   carefully and fix exactly what it names — the same mistake will be rejected
   again.
8. Text of the form `<SECRET_CANDIDATE:S001>` is a **protected token**. A real
   credential was removed before the text reached you. Copy such tokens byte for
   byte wherever they appear. Never alter, renumber, reformat, drop, duplicate
   or explain them, and never write a value that looks like a real credential.
9. Never emit a bracketed placeholder such as `[PERSON_001]`, `[EMAIL_002]` or
   `[PROJECT_NAME_003]`. The final dataset must read like a natural
   conversation; bracketed placeholders are rejected.
10. If a rule here conflicts with a phase-specific rule, the phase-specific rule
    wins.
