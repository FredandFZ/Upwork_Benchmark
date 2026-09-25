# RQ instance-to-Agent smoke pipeline

This pipeline keeps researcher-side Gold separate from Agent-visible inputs.
One Agent reasoning run is keyed by `target × condition`, not by `target × RQ`.
The same frozen response is later projected into the eligible RQ1--RQ3 scorers.

## 1. Build RQ1--RQ3 instances

```powershell
python Code/stage2_generate_rq_instances.py `
  --project-id 42204309 `
  --gold-states outputs_new/stage2/42204309/gold_states.json `
  --state-graph outputs_new/stage2/42204309/requirement_state_graph.json `
  --messages outputs_new/stage1_runs/42204309/normalized_project.json `
  --rq-ids RQ1 RQ2 RQ3 `
  --input-release 42204309-stage12-v1 `
  --output-dir outputs_new/stage2/42204309
```

RQ1 is active only for C1 Full History. RQ2 and RQ3 are active for C1 and C2
Oracle Relevant History. Building only RQ1--RQ3 never reads Code Environment.

## 2. Materialize one target and stage opaque Agent workspaces

```powershell
python Code/materialize_rq_agent_inputs.py `
  --project-dir outputs_new/stage2/42204309 `
  --target-id 42204309_T001 `
  --condition C1 --condition C2 `
  --mode smoke `
  --output-root outputs_new/rq_agent_inputs `
  --workspace-root outputs_new/rq_agent_workspaces
```

The static package stores public files and a separate private manifest. The
optional workspace root contains only opaque `run_<hash>/` directories with:

- `task.json`
- `history.jsonl`
- `instructions.md`
- `response.schema.json`

Launch one fresh, isolated Agent session per opaque workspace. Do not mount the
repository, Stage 2 outputs, private manifests, or another run's workspace.
Save the Agent's JSON response outside the public input directory.

## 3. Freeze the Phase A response

```powershell
python Code/freeze_rq_phase_a_response.py `
  --private-manifest <static-package>/private/run_manifest.json `
  --public-dir <static-package>/public `
  --response <agent-output>/agent_response.json `
  --freeze-root outputs_new/rq_runs
```

The freezer checks the unified response shape, rejects evidence IDs outside the
condition-visible history, verifies that all public inputs are unchanged, and
records the response hash and UTC timestamp. It opens the Phase B gate only when
the frozen Agent decision is `ACT` and the private RQ4 record is both eligible
and execution-ready.

`SMOKE` packages are runnable but marked `NOT_SCORED`. `FORMAL` materialization
refuses any active RQ whose reviewed Gold is not frozen. For project 42204309,
RQ2 and RQ3 still require review/freeze before formal scoring, and a rebuilt,
target-aligned Code Environment plus validators is required before RQ4.
