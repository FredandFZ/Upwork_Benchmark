# Agent repair instructions

**Prompt version:** `pii-v7-agent-repair-1`

You are repairing individual chat messages that the automated PII pipeline could
not finish. This file is for you (Claude Code) reading files on a local machine —
it is not sent to an API.

## 1. Your role and its limits

You write **one file**: `agent_repairs/repairs.json` in the project's run
directory.

You do **not**: run the pipeline, set credentials, edit the source dataset, edit
any phase checkpoint, edit the transformation plan, edit the task package, edit
the validators or the audit, `git add`, or delete any artifact.

The validators exist to catch mistakes, including yours. Making your text pass by
changing them defeats the entire pipeline.

## 2. What to read, in order

```text
1. <run_dir>/run_metadata.json          status, blocked phase, next command
2. <run_dir>/agent_tasks/index.json     the queue: header + every task
3. <run_dir>/agent_tasks/task_NNNNN.json  one task at a time
```

The index header tells you two things that matter:

- `blocked_phase` — `REWRITE_VERIFY` means you write final text;
  `EXTRACTION` means you supply a missing annotation instead (see §9).
- `protected_tokens` — the **complete** list of protected tokens in this
  project. A token outside this list may not appear in anything you write.

## 3. The five invariants, in priority order

When they conflict, the higher one wins.

1. **No real identity survives.** No original person name, email address,
   phone number, private domain, private link, repository, account identifier or
   wallet address may appear in your text.
2. **Protected tokens are byte-exact.** Every `<SECRET_CANDIDATE:S001>` in the
   source appears in your text, spelled identically, the same number of times.
   Never alter, renumber, reformat, drop or duplicate one.
3. **Apply the plan exactly.** Use the replacements in `must_apply_entities` and
   `must_apply_slots`. **Never invent a name.** If you choose your own
   replacement, that message will contradict every other message in the project.
4. **Keep the project meaning.** Requirement content, decisions, negation,
   ambiguity, execution status, causal and temporal relations, and every term in
   `must_preserve_verbatim` stay intact.
5. **Read naturally.** The result should look like something a person typed.

## 4. What "natural synthetic" means

| | |
|---|---|
| ✗ | `[PERSON_001] asked about [PROJECT_NAME_002]` — placeholders are rejected |
| ✓ | `Marcus asked about Ledgerline` — using the plan's replacements |
| ✗ | `Daniel asked about the project` — invented a name not in the plan |
| ✗ | `The key is FAKE_API_KEY_83A7F291C04E` — never write a rendered credential |
| ✓ | `The key is <SECRET_CANDIDATE:S001>` — keep the token; rendering happens later |

The last pair matters most. Phase 6A renders credentials deterministically after
you. Leave the token alone and you cannot get the format wrong.

## 5. Per-failure-code playbook

`failure_code` tells you what the pipeline objected to.

| Code | The objection | The minimal fix | The trap |
|---|---|---|---|
| `REWRITE_UNCHANGED` | text identical to the source | reword it | don't just add punctuation |
| `REWRITE_STRUCTURE_UNCHANGED` | reworded but not restructured | move a clause, change voice, split/combine sentences | don't start with the same two words |
| `REWRITE_WORD_BAND_VIOLATED` | a short message grew too long | stay at or under 8 words | don't drop a required replacement to save words |
| `REWRITE_RESIDUAL_ORIGINAL_ENTITY` | an original value survived | apply the replacement from `must_apply_entities` / `must_apply_slots` | check every alias and short form |
| `REWRITE_PLAN_MAPPING_VIOLATED` | a required replacement is missing | insert the planned replacement | use the plan's exact string |
| `REWRITE_PROTECTED_TOKEN_DAMAGED` | a protected token changed | copy it byte for byte, same count | don't "tidy" the angle brackets |
| `REWRITE_PRESERVED_TERM_ALTERED` | a preserved term was changed or lost | restore it exactly, same count | these are requirement terms, not filler |
| `REWRITE_LIST_MARKER_DAMAGED` | ordered-list numbering changed | restore `1.`, `2.`, `3.` and their order | numbering is layout, never data |
| `REWRITE_LEGACY_PLACEHOLDER` | a `[X_001]` placeholder appeared | write natural text instead | |
| `REWRITE_PII_REINTRODUCED` | an unplanned address/link/handle appeared | remove it, or use the planned one | |
| `REPAIR_EXHAUSTED` | the automated repair ran out of attempts | read `verifier_failures` and fix those | see §6 |
| `VERIFY_FAILED` | the independent verifier rejected the meaning | read `verifier_failures` | don't fix by deleting the fact |

## 6. Read the attempt history first

`attempt_history` lists what was already tried and why each attempt failed.
`last_candidate_text` is the closest previous attempt.

Start from `last_candidate_text` and fix what the findings name. Do not repeat an
approach that already failed — that information is in front of you.

## 7. Bucket rules

`rewrite_directive.bucket`:

- `SHORT` — stay brief, at or under 8 words. Keep the speech act, the polarity
  and the interrogative form. Structural change is **not** required.
- `LONG` — structural change **is** required: move a clause, change voice, or
  split/combine sentences. Rewording alone will be rejected again.

## 8. The file you write

`<run_dir>/agent_repairs/repairs.json`. Run
`python .\Code\pii_finalize.py --project-id <id> --write-template` to get a
prefilled skeleton.

```json
{
  "schema_version": "pii-agent-repairs-v1",
  "project_id": "42204309",
  "queue_sha256": "<copy from the index: it is recomputed and checked>",
  "repairs": [
    {
      "task_id": "42204309:PHASE_3_REWRITE:00231",
      "kind": "TEXT",
      "ordinal": 231,
      "message_id": 231,
      "text": "Once the sandbox is live, Marcus should raise the pool to 7 winners at $12,500 each.",
      "safe_source_sha256": "<copy verbatim from the task>",
      "plan_slice_sha256": "<copy verbatim from the task>",
      "author": "claude-code",
      "reason": "Fronted the precondition and restored the approval the verifier said was missing."
    }
  ],
  "blocked": []
}
```

Rules for this file:

- **Copy both hashes verbatim** from the task. They prove your repair was written
  against the current source *and* the current plan. If either changed, the
  repair is rejected rather than misapplied.
- **Unknown keys are rejected.** A typo in a key name would silently disable the
  guard it belongs to, so the whole key set is closed.
- **`reason` is mandatory and must not quote an original value.** This is
  enforced: an address, a link, or any original name from the plan in `reason`
  rejects the repair. `reason` is the field most likely to end up in a terminal
  or a commit message, and "changed William to Marcus" is a re-identification
  key. Describe the *change you made*, not the values.

## 9. `EXTRACTION` tasks

If `kind` is `EXTRACTION`, the pipeline could not analyse the message, so there
is no plan for it yet. Supply the missing annotation instead of text:

```json
{
  "task_id": "...", "kind": "EXTRACTION", "ordinal": 231,
  "safe_source_sha256": "...",
  "annotation": {"occurrences": [...], "semantics": {...}},
  "author": "claude-code", "reason": "..."
}
```

These are consumed by the **next `pii_clean.py` run**, not by `finalize` — the
plan has to be rebuilt with the message included. Follow the field shapes in
`prompt/PII/phase0b_pii_discovery.md` and
`prompt/PII/phase1a_message_semantics.md`.

## 10. Pre-flight self-check

Before you save, verify each repair yourself:

- [ ] Every `protected_tokens_present` token appears, spelled identically, the
      same number of times.
- [ ] No token outside the header's `protected_tokens` list appears.
- [ ] Every `must_apply_entities` original and alias is **absent**; every
      replacement is **present**.
- [ ] Every `must_apply_slots` original literal is **absent**; every replacement
      literal is **present**.
- [ ] Every `relation_constraints` expression still holds with the new numbers.
- [ ] Every `must_preserve_verbatim` term is present, with the same count.
- [ ] No `[SOMETHING_001]` placeholder.
- [ ] No `FAKE_*` credential written by you.
- [ ] No email address, link or handle that the plan did not supply.
- [ ] Ordered-list numbers unchanged.
- [ ] `SHORT` is at or under 8 words; `LONG` is structurally different.
- [ ] Both hashes copied verbatim; `reason` non-empty and quotes no original.

## 11. When you think the task is wrong

**Do not force a fix.** If a task cannot be satisfied — the plan contradicts
itself, or fixing it would require changing a replacement that other messages
already use — add it to `blocked` and say why:

```json
"blocked": [{"task_id": "...", "reason": "needs E0007's replacement changed; requires a re-plan"}]
```

Finalize surfaces these as needing a re-plan rather than text. Inventing a
plausible-looking fix for an impossible task is worse than reporting it.

## 12. Partial work is fine

You may submit some tasks and leave others. `--validate-only` gives feedback on
what you did submit. Nothing is committed until every open task is covered, so
there is no risk in submitting incrementally.

## 13. Hand-off

When you are done, tell the operator to run:

```powershell
python .\Code\pii_finalize.py --project-id <id> --validate-only
python .\Code\pii_finalize.py --project-id <id>
```

## 14. A note on what you are reading

The task files contain **real** names, addresses and business values — that is
unavoidable, because repairing meaning requires the original meaning. They do
**not** contain any real credential: those were replaced with protected tokens
before any data left the local process, and they are the one category you
structurally cannot see.

Keep this data in this session. Do not echo original values into your replies,
your `reason` fields, log output, or a commit message. The files are deleted
automatically once the project completes.
