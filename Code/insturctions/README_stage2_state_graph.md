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

- `MODIFY` first deletes every top-level key in
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
- Every Stage 1 Requirement receives one Requirement Graph. Stage 2 never
  removes a Requirement merely because `INTRODUCE` is absent.
- A lifecycle whose first Event is `INTRODUCE` uses
  `initialization_mode: "EXPLICIT_INTRODUCE"` and replays normally from that
  Event.
- If visible history begins with `MODIFY`, lifecycle, ambiguity, or execution
  evidence, replay begins at that first observable Event with
  `initialization_mode: "OBSERVED_HISTORY"`. Unknown attributes, scope, and
  lifecycle remain empty or null until evidence establishes them; the builder
  does not invent an `INTRODUCE` Event or a complete initial implementation.
- If `INTRODUCE` appears later, all earlier Events remain as State Nodes and
  Edges. The later `INTRODUCE` establishes the formal ACTIVE baseline. It
  resets execution inherited from the incomplete pre-introduction observation,
  but it closes no ambiguity unless it explicitly links to that ambiguity.
- A Requirement with no Events is retained as an empty graph with
  `initialization_mode: "NO_EVENTS"`, `nodes: []`, and `edges: []`.
- During an incomplete observed baseline, a `value_removals` entry may establish
  that an attribute is currently absent even when its earlier value was outside
  the visible history. Once an explicit baseline exists, removing an already
  absent attribute remains a consistency error.
- Every valid Stage 1 Event remains a State Node and Edge. A `RESUME` is not
  suppressed merely because an earlier `MODIFY` resolved an ambiguity.
- `supporting_event_ids` contains the minimal set of Events that directly
  establish the current snapshot; the full trajectory remains available in the
  graph's edges.
- Transitions that cannot be replayed safely (for example, an Event after
  `REMOVE`) stop generation with a consistency error.

Explicit ambiguity replay:

- `AMBIGUOUS` opens one entry keyed by its exact Event ID.
- Stage 2 stores all currently open entries in an internal
  `open_ambiguities: dict[str, dict]`; several ambiguities may be open at once.
- A later Event closes only the IDs listed in its
  `resolves_ambiguity_event_ids` field.
- An unlinked `MODIFY`, `INTRODUCE`, `DEFER`, `RESUME`, or `REMOVE` does not
  close any ambiguity. Dimension-based inference is not used as a fallback.
- A missing `resolves_ambiguity_event_ids` field in an older annotation is
  normalized to `null`, so the ambiguity remains open rather than being
  guessed closed.
- The `ambiguity` field in each State Node is `null` when no ambiguity is open;
  otherwise it is an object keyed by ambiguity Event ID. For example:

```json
{
  "ambiguity": {
    "REQ_X_E002": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The delivery method is unclear.",
      "source_event_id": "REQ_X_E002"
    }
  }
}
```

Stage 2 validates every resolution link before replay: the target must exist,
belong to the same Requirement, be an earlier `AMBIGUOUS` Event, and be
resolved at most once. Dangling, future, cross-Requirement, duplicate, and
unsupported-resolver links stop graph generation with a consistency error.

Each Requirement Graph therefore includes:

```json
{
  "graph_id": "REQ_X_GRAPH",
  "requirement_id": "REQ_X",
  "title": "Requirement title",
  "family_id": null,
  "initialization_mode": "EXPLICIT_INTRODUCE | OBSERVED_HISTORY | NO_EVENTS",
  "has_explicit_introduce": true,
  "nodes": [],
  "edges": []
}
```

The number of `requirement_graphs` in a successfully generated project is
always equal to the number of Requirements in its Stage 1 annotation. This
preserves incomplete Requirements for later initial-code-environment
simulation instead of silently dropping them.
