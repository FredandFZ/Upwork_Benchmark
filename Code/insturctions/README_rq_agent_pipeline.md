# RQ1--RQ3 isolated evaluation pipeline

This pipeline keeps researcher-side Gold separate from Agent-visible inputs.
One Agent reasoning run is keyed by `target × condition × agent configuration ×
repetition`, not by `target × RQ`. The same frozen response is projected into
the eligible RQ1--RQ3 scorers.

RQ1 is active only for C1 Full History. RQ2 and RQ3 are active for both C1 and
C2 Oracle Relevant History. With the current 349-target release this produces
698 Agent runs and 1,745 RQ-condition score records per Agent configuration and
repetition.

## 1. Validate or materialize all formal packages

Validation performs every Gold/readiness/leakage check without writing inputs:

```powershell
python Code/materialize_rq123_release.py --validate-only
```

Materialize the 698 reusable input packages:

```powershell
python Code/materialize_rq123_release.py `
  --stage2-root outputs_new/stage2 `
  --output-root outputs_new/rq_agent_inputs
```

Each package has an immutable `package_id` and contains:

```text
<input_release>/<project>/<target>/<condition>/
├── public/
│   ├── task.json
│   ├── history.jsonl
│   ├── instructions.md
│   └── response.schema.json
└── private/
    └── package_manifest.json
```

The public directory contains no Gold, internal Requirement IDs, repository,
condition label, target ID, or private manifest. RQ1--RQ3 materialization never
reads Code Environment.

For a one-target smoke package, `Code/materialize_rq_agent_inputs.py` remains
available. Its optional workspace is named by `package_id`; formal automated
runs should let the Agent runner create and delete per-run workspaces instead.

## 2. Freeze one experiment configuration

Copy `Code/config/rq123_experiment.example.json` to an experiment-specific
configuration and replace every placeholder. Record the exact Agent runtime,
model version, reasoning effort, tool policy, command, timeout, and repetition count.
Do not put credential values in the JSON file; `environment_allowlist` contains
names only.

For the installed Codex CLI on Windows, start from
`Code/config/rq123_codex_experiment.example.json`. It invokes `codex.cmd` rather
than the PowerShell shim, uses an ephemeral non-resumable session, ignores user
configuration and project rules, and writes the final message to
`agent_response.json`. The public `response.schema.json` remains the benchmark
contract and is enforced by the local freeze validator. Do not pass it to Codex
CLI via `--output-schema`: RQ states intentionally use dynamic attribute keys,
which the Responses API strict-schema subset does not accept.
Before a real run, make sure `CODEX_HOME` points to the authenticated Codex
configuration used for the experiment; the runner passes the variable by name
but never records its value.

For Claude Code, use
`Code/config/rq123_claude_code_experiment.example.json` or the concrete
Sonnet 5/high five-target pilot config. The adapter runs Claude in restricted,
non-persistent, tool-free mode and extracts the JSON Schema result from the
CLI `structured_output` envelope. The complete cross-device procedure,
preflight, exact pilot cases, and artifact handoff are documented in
`Code/insturctions/README_rq123_claude_code.md`. Do not add session resume flags
or use Claude `--bare` with a local subscription login.

The identity hierarchy is:

```text
package_id      = public input identity
agent_config_id = Agent model/version/parameters/tools/prompt identity
run_id          = package_id + agent_config_id + repetition
judge_config_id = Judge provider/model/version/prompt/runtime identity
```

Changing the Agent model, run prompt, instructions, response schema, tool
policy, or repetition creates a different `run_id`. Changing only the Judge
creates a new `judge_config_id` and does not require rerunning the Agent.

## 3. Run isolated Agents

First inspect the queue without launching Agents:

```powershell
python Code/run_rq123_agents.py `
  --config <experiment-config.json> `
  --package-root outputs_new/rq_agent_inputs `
  --dry-run
```

Then run a small end-to-end pilot, for example five packages:

```powershell
python Code/run_rq123_agents.py `
  --config <experiment-config.json> `
  --package-root outputs_new/rq_agent_inputs `
  --run-root outputs_new/rq_runs `
  --limit 5
```

For every target-condition, the runner:

1. creates a fresh opaque workspace;
2. copies only the four public input files and embeds their complete contents
   in the stdin prompt;
3. starts a new operating-system process;
4. sends `prompt/rq_agent_run_prompt.md` plus the embedded inputs through
   standard input, so the Agent needs no filesystem or external tool call;
5. captures either exact JSON stdout or the configured workspace output file;
6. validates and freezes the response;
7. terminates the process on timeout; and
8. deletes the workspace in a `finally` block on success or failure.

Before freezing a new run, the runner also verifies and embeds its private RQ
source instances below `private/source_instances/`. The run manifest refers to
those copies by paths relative to the run directory. This evaluator-only data
never enters the Agent workspace, but makes a complete frozen run relocatable
to a separate Judge machine. Legacy frozen runs with absolute source paths
remain readable on their original machine.

No conversation/thread/previous-response identifier is passed between cases.
C1 and C2 of the same target are separate runs. The runner preserves frozen
responses and audit logs, but never reuses the Agent's workspace or process
memory. By default, ephemeral workspaces are created under the operating
system's temporary directory rather than under the repository. Filesystem and
network enforcement must also be enabled by the configured
Agent command's sandbox; the prompt is not treated as a security boundary.

Completed frozen runs are skipped on restart, so the command is resumable.

## 4. Run the LLM Judge and deterministic scorers

The evaluator-generated request objects remain the sole semantic contract. The
Judge emits discrete relation labels only; all metric calculation stays in the
deterministic RQ1/RQ2/RQ3 scorers.

Internal experiments use:

```json
"judge": {
  "provider": "upwork_stage1",
  "api_interface_version": "stage1-chat-completions-v1",
  "model": "<fixed-model>",
  "model_version": "<exact-version>",
  "reasoning_effort": "high",
  "max_concurrent_requests": 4,
  "retries": 3,
  "timeout_seconds": 900
}
```

Set `UPWORK_API_KEY` and `UPWORK_BUDGET_ID`, then run:

```powershell
python Code/run_rq123_judges.py `
  --config <experiment-config.json> `
  --run-root outputs_new/rq_runs
```

`upwork_stage1` wraps the existing Stage 1 JWT and `/chat/completions` client.
The public provider uses the official OpenAI Python SDK and Responses API with
strict JSON Schema:

```json
"judge": {
  "provider": "openai",
  "api_interface_version": "openai-responses-v1",
  "model": "<fixed-openai-model>",
  "model_version": "<exact-version-or-snapshot>",
  "reasoning_effort": "high",
  "max_concurrent_requests": 1,
  "retries": 3,
  "timeout_seconds": 900
}
```

Set `OPENAI_API_KEY` for this provider. The released repository should keep the
provider-neutral interface and OpenAI implementation, while excluding internal
Upwork endpoints, authentication details, credentials, and logs.

Wrong-branch RQ3 decisions are scored locally without an LLM call. Empty valid
Judge requests also receive a deterministic empty response. Infrastructure,
transport, schema, or incomplete-response failures remain failures and are not
converted into zero benchmark scores.

## 5. Aggregate results

```powershell
python Code/aggregate_rq123_results.py `
  --run-root outputs_new/rq_runs `
  --experiment-id <experiment-id-from-config> `
  --output outputs_new/rq_results/rq123_summary.json
```

The summary separates Agent configuration, Judge configuration, repetition,
RQ, and condition. It includes benchmark and project aggregates, paired
`C2 - C1` deltas for RQ2/RQ3, the RQ2 oracle-aligned constant-state baseline,
and RQ3 all-ACT/all-CLARIFY baselines. Agent and Judge commands write ledgers
below `outputs_new/rq_runs/experiments/<experiment_id>/`; the Judge and
aggregator use those ledgers instead of scanning unrelated experiments.

## 6. Manual freeze entry point

`Code/freeze_rq_phase_a_response.py` remains available for recovery and audit,
but it now consumes a per-execution `private/run_manifest.json` produced from an
immutable package manifest. It must not be pointed at
`private/package_manifest.json`.

RQ2 and RQ3 Gold are currently offline-Agent reviewed and frozen. Formal
materialization is therefore open for all 349 retained targets. RQ4 remains a
separate Phase B task and is not required for this RQ1--RQ3 pipeline.

## 7. Zero-context operator prompts

To hand the complete workflow to a fresh Agent with no conversation history,
use exactly one provider-specific operator prompt:

- `prompt/rq123_codex_full_run_operator.md`
- `prompt/rq123_claude_code_full_run_operator.md`

After reading the selected file, the Agent only needs the exact model ID,
reasoning effort, and target count. Target count means unique targets, so C1
and C2 produce twice as many isolated Agent calls. Both prompts freeze an
explicit deterministic case list, keep provider output roots separate, enforce
preflight and dry-run gates, and continue through Judge and aggregation when
Judge credentials are available.
