# Pilot Experiment Protocol

## Why this comes after annotation

Annotation defines the hidden truth. Evaluation instances define what the agent sees. Experiments compare agent behavior under controlled access to history.

## Recommended pilot conditions

Run the **same target instances** under four information conditions.

### C0 — No History

Agent receives:
- current task
- current repository snapshot if available

Agent does not receive prior project chat.

Purpose:
- estimate ordinary coding/reasoning ability without longitudinal memory.

### C1 — Full History

Agent receives:
- current task
- all chronologically prior project messages
- current repository snapshot if available

Use `instances_full_history.jsonl`.

Purpose:
- main ReqMemBench setting.
- tests whether the agent itself can select, scope, update, and act on history.

### C2 — Oracle Relevant History

Agent receives:
- current task
- only the human-annotated relevant historical messages

The pilot `instances.jsonl` approximates this controlled condition for many diagnostic cases.

Purpose:
- separates **history-selection failure (RQ1)** from downstream reasoning/execution failure.

### C3 — Oracle Requirement State

Agent receives:
- current task
- a compact gold summary of the currently valid requirement state
- repository snapshot if available

Purpose:
- upper-bound condition.
- if C3 still fails RQ5, the bottleneck is implementation rather than memory management.

## Key comparisons

| Comparison | Diagnosis |
|---|---|
| C1 vs C0 | Does project history help overall? |
| C2 vs C1 | How much loss comes from selecting the wrong history? |
| C3 vs C2 | How much loss comes from scope/validity/decision reasoning? |
| RQ5 under C3 | Can the agent implement correctly even when memory is solved? |

## Primary reporting

For each model/agent report:
- RQ1 score
- RQ2 score
- RQ3 score
- RQ4 score
- RQ5 score
- Macro score (secondary headline only)
- Functional test success where executable snapshots are available

## RQ4 error analysis

Do not report only accuracy. Count:
- `Unnecessary Clarification`: gold USE/OVERRIDE, predicted CLARIFY
- `Unsupported Assumption`: gold CLARIFY, predicted USE
- `Stale Memory Use`: gold OVERRIDE, predicted USE of old state
- `Irrelevant Memory Use`: gold IGNORE, predicted USE

These errors have different practical severity.

## RQ5 evidence policy

Evidence strength:
1. `L1_CODE_TEST` — source/code/test evidence
2. `L2_RUNTIME` — observed client/runtime behavior
3. `L3_DOCUMENTARY` — written implementation claim or deliverable documentation

Final benchmark should prioritize L1 cases when repository snapshots are available.

## Pilot interpretation

This project is a **design-validation pilot**, not a paper-scale benchmark.
Before scaling:
1. manually review the 19 gold instances,
2. have a second annotator independently label a subset,
3. compute inter-annotator agreement,
4. revise ambiguous label definitions,
5. then batch-annotate more projects.
