# ReqMemBench Task-centered Gold State and RQ1--RQ4

This step deterministically derives task-centered benchmark artifacts from an
existing Requirement State Graph. It does not call a model and does not reread
the raw project data in `Datasets/`.

For the upgraded sample, the data flow is:

```text
outputs/stage1_upgrade_runs/42204309/normalized_project.json
        +
outputs/stage2_v06/42204309/requirement_state_graph.json
        ->
outputs/stage2_v06/42204309/gold_states.json
        +
outputs/stage2_v06/42204309/evaluation_instances/rq1_rq4_instances.json
```

Run the requested sample:

```powershell
python Code/stage2_generate_task_gold.py `
  --state-graph outputs/stage2_v06/42204309/requirement_state_graph.json `
  --stage1-source outputs/stage1_upgrade_runs/42204309/normalized_project.json
```

The Stage 1 source is used only to recover the original Task message ID,
speaker, and text; `normalized_project.json` is preferred because it retains
the complete ordered message catalog. Supported forms are upgrade-run
`normalized_project.json`, upgrade-run `verified_events.json`, and a canonical
assembled Stage 1 annotation.

Task discovery selects Client messages with at least one `INTRODUCE`, `MODIFY`,
`DEFER`, `RESUME`, `REMOVE`, or `AMBIGUOUS` Graph Edge. All Graph Events from a
selected message stay in one Task. Execution-only messages are excluded unless
`--include-execution-only-tasks` is supplied.

For every Task, `gold_states.json` stores complete Project snapshots immediately
before and through the Task. It stores State references only and deliberately
does not persist derived Requirement transitions. Removed Requirements remain
in snapshots; Requirements introduced by the current Task are absent before it
and present afterward.

The separate RQ artifact derives:

- RQ1: affected Requirements and pre-task supporting Events;
- RQ2: `PRESERVED`, `UPDATED`, or `UNRESOLVED` Scope transitions (new
  Requirements are ineligible);
- RQ3: correct post-task State and per-dimension Pre/Post changes;
- RQ4: dimension-level `USE`/`OVERRIDE`, or `CLARIFY` for an open blocking
  ambiguity.

`IGNORE` distractors are intentionally not generated because the current
annotation has no explicit semantic-relation field that can prove an unaffected
Requirement is irrelevant. The selection policy is isolated in
`build_rq4_gold` for a future controlled distractor strategy.

`task_gold_validation.json` reports snapshot, provenance, leakage, eligibility,
and label statistics. Optional `--audit-event-provenance` additionally requires
the Graph's Event IDs, types, and source messages to match
`<stage1-root>/<project_id>/verified_events.json` (or an explicit
`--event-provenance-source`) exactly.

Known limitation: without a retained global message-order table, opaque
non-numeric message IDs cannot be ordered safely. The builder rejects them
instead of guessing. Numeric IDs, including this sample's IDs, are supported.
