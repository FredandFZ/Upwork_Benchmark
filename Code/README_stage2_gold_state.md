# ReqMemBench Task-centered Gold State

This step deterministically derives task-centered benchmark artifacts from an
existing Requirement State Graph. It does not call a model and does not reread
the raw project data in `Datasets/`.

For the upgraded sample, the data flow is:

```text
outputs/stage1_upgrade_runs/42204309/normalized_project.json
        +
outputs/stage2_v06/42204309/requirement_state_graph.json
        +
Code/config/stage2_gold_state.json
        ->
outputs/stage2_v06/42204309/gold_states.json
```

Run the requested sample:

```powershell
python Code/stage2_generate_gold_state.py `
  --state-graph outputs/stage2_v06/42204309/requirement_state_graph.json `
  --stage1-source outputs/stage1_upgrade_runs/42204309/normalized_project.json `
  --config Code/config/stage2_gold_state.json
```

The command writes only `gold_states.json` and `gold_state_validation.json` to
the State Graph directory (or `--output-dir`). It does not construct or write
RQ evaluation instances.

## Inputs and schema responsibilities

`requirement_state_graph.json` contains one linear graph per Requirement.
`nodes` are complete Requirement States; ordered `edges` identify the Event,
Event type, source message ID, and `from_state_id`/`to_state_id`. The graph is
the sole source for Event grouping and State reconstruction.

The Stage 1 source is used only to recover the original Task message ID,
speaker, and text; `normalized_project.json` is preferred because it retains
the complete ordered message catalog. Supported forms are upgrade-run
`normalized_project.json`, upgrade-run `verified_events.json`, and a canonical
assembled Stage 1 annotation. The graph intentionally does not duplicate
speaker or text. If no Stage 1 message source is available, graph-anchored Tasks
are still generated with `speaker: null` and `text: null`; metadata is never
invented.

The sample and design are consistent on graph replay, but the design's example
shows Task metadata in Gold output even though the actual State Graph has no
such fields. This is why a Stage 1/history source is normally supplied.

Sample provenance note: the supplied graph is internally valid, but its Event
sequence differs from each supplied Event-bearing Stage 1 artifact at 14 Event
IDs (later insertions shifted IDs/types/messages in two Requirements). The
builder conservatively treats the State Graph as the Gold replay source and
uses `normalized_project.json` only for message metadata. Running
`--audit-event-provenance` surfaces this mismatch and stops instead of silently
repairing or guessing.

## Task selection

Task discovery selects Client messages with at least one `INTRODUCE`, `MODIFY`,
`DEFER`, `RESUME`, `REMOVE`, or `AMBIGUOUS` Graph Edge. All Graph Events from a
selected message stay in one Task. Execution-only messages are excluded unless
enabled in the config or with `--include-execution-only-tasks`.

`Code/config/stage2_gold_state.json` exposes Event priority, early/middle/late
sampling ratios, execution-only inclusion, the per-project cap, and random
seed. When the cap is `null`, all eligible Tasks are retained. With a cap,
approximate position quotas are allocated across timeline thirds. Within each
third, a Task's highest-priority Event type controls preference; seeded
shuffling deterministically breaks equal-priority ties. Ratios are sampling
guidelines and unused capacity is redistributed.

## Gold State retrieval

For every Task, `gold_states.json` stores complete Project snapshots immediately
before and through the Task. It stores State references only and deliberately
does not persist derived Requirement transitions. Removed Requirements remain
in snapshots; Requirements introduced by the current Task are absent before it
and present afterward. If one Requirement has several ordered Events at the
same message, Pre-task uses the last earlier State and Post-task uses the final
same-message Event's `to_state_id`. `affected_requirement_ids` comes only from
Task Events. `preserved_requirement_ids` is exactly the Pre-task Requirement
set minus affected Requirements, and every preserved State reference is reused
unchanged in Post-task Gold.

## Validation

Before Gold is written, validation checks graph chain/order consistency, State
and Event references, exact Task Event grouping, exact affected/preserved sets,
duplicate Requirement IDs, complete Pre/Post snapshots, final same-message
State selection, INTRODUCE/REMOVE behavior, preserved State equality, and
supporting-Event boundaries that prevent future leakage. Failures identify the
project, target message, and Requirement where applicable.

`gold_state_validation.json` reports snapshot, provenance, and leakage
statistics. Optional `--audit-event-provenance` additionally requires
the Graph's Event IDs, types, and source messages to match
`<stage1-root>/<project_id>/verified_events.json` (or an explicit
`--event-provenance-source`) exactly.

Known limitation: without a retained global message-order table, opaque
non-numeric message IDs cannot be ordered safely. The builder rejects them
instead of guessing. Numeric IDs, including this sample's IDs, are supported.
