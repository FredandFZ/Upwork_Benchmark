# ReqMemBench Stage 2 Requirement State Graph

This Stage 2 step deterministically replays the ordered Requirement Events in
each Stage 1 annotation. It does not call a model or reread the raw chat.

Build one project:

```powershell
python Code/stage2_generate_state_graph.py --project-id 42204309
```

Build every `*_stage1_annotation.json` file in the default Stage 1 output
directory:

```powershell
python Code/stage2_generate_state_graph.py
```

Outputs follow the guideline's project-level layout:

```text
outputs/stage2/<project_id>/requirement_state_graph.json
```

Replay behavior:

- Annotation v0.6 `MODIFY` first deletes every top-level key in
  `value_removals`, then applies `value_updates` and per-dimension scope
  updates. Attribute-deletion Events remain supporting evidence for the
  current absence until that key is reintroduced.

- Stage 1 Event array order is preserved. The Stage 1 assembler has already
  sorted Events by original project-history position, including ordered Events
  from the same source message.
- `MODIFY` performs top-level attribute patching and per-dimension scope
  patching. A null scope dimension means “not updated”. Because a modification
  creates a new Requirement version, it also resets execution to null.
- Lifecycle, ambiguity, and execution are independent state dimensions.
- A Requirement with no `INTRODUCE` Event is omitted from the State Graph.
- If a `MODIFY` closes an open ambiguity, an immediately following `RESUME`
  that would not change lifecycle or ambiguity is not emitted as a duplicate
  State Node or Edge.
- `supporting_event_ids` contains the minimal set of Events that directly
  establish the current snapshot; the full trajectory remains available in the
  graph's edges.
- Transitions that cannot be replayed safely (for example, an Event after
  `REMOVE`) stop generation with a consistency error.
