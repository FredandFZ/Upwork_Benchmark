# RQ4：40-target Phase A → Phase B → Agent Judge 流程

RQ4 正式集合由 99 个原始时间点收缩为 40 个具有确定性 Acceptance Criteria 的 target。
每个 target 同时运行 C1 与 C2，因此一个 repetition 包含 80 个 Phase A package。

## 1. 冻结 40-target registry

```powershell
python Code/build_rq4_agent_judge_registry.py
```

输出：

```text
ccfa-workfiles/experiments/rq4-validation/rq4_agent_judge_registry.json
```

Registry 绑定 target fingerprint、RQ3 Gold、pre-repo、Acceptance Criteria、通用 Judge prompt
及 response schema 的 SHA-256。Judge 输入会删除内部 Requirement/State ID。

## 2. 生成并验证 Phase A packages

```powershell
python Code/materialize_rq4_phase_a_inputs.py
python Code/validate_rq4_phase_a_link.py
```

输出位于 `outputs_new/rq4_agent_inputs/`。每个 package 的公共部分仍然只有 `task.json`、
`history.jsonl`、`instructions.md` 和 `response.schema.json`；Acceptance Criteria、Code Environment
路径与 Judge 配置只保存在 private manifest。

## 3. 运行 Phase A

复制 `Code/config/rq4_experiment.example.json`，填入实际的 Phase A、Phase B 与 Judge Agent
命令。先检查将要启动的 80 个隔离运行：

```powershell
python Code/run_rq123_agents.py `
  --config path/to/rq4_experiment.json `
  --package-root outputs_new/rq4_agent_inputs `
  --run-root outputs_new/rq4_runs `
  --dry-run
```

正式运行时去掉 `--dry-run`。Phase A response 会先冻结；只有：

```text
decision == ACT
AND rq4.eligible == true
AND rq4.execution_ready == true
```

才会把 Phase B gate 写成 `OPEN`。C1 与 C2 使用相同 pre-repo、Acceptance Criteria 和 Judge
contract，但保持独立 run、workspace 和 Agent session。

## 4. 运行 Phase B coding Agent

```powershell
python Code/run_rq4_phase_b_agents.py `
  --config path/to/rq4_experiment.json `
  --run-root outputs_new/rq4_runs
```

Runner 只发现 gate 为 `OPEN` 的 Phase A runs。它会安全解压 pre-repo，放入冻结的 Phase A
response，运行 Coding Agent，然后重新核对 Phase A hash，并冻结 `final_repository.zip`。

Phase A 选择 `CLARIFY` 时不开放 repository；对于 Gold-eligible RQ4 run，最终聚合时记为
`NO_CODE_SUBMISSION / FAIL`。

## 5. 运行通用 Agent Judge

```powershell
python Code/run_rq4_agent_judges.py `
  --config path/to/rq4_experiment.json `
  --run-root outputs_new/rq4_runs
```

Judge 在最终 repository 的隔离副本上运行。Runner 先执行固定 Build 与 Regression，再把 task、
私有 Acceptance Criteria 和检查结果写入 `judge_input.json`。Judge 必须对每条 AC 返回
`PASS`、`FAIL` 或 `UNSURE` 及执行证据；Judge 运行前后的 repository tree hash 必须相同。

最终结果由本地 finalizer 计算：

```text
PASS   = Build PASS ∧ Regression PASS ∧ every AC PASS
FAIL   = Build FAIL ∨ Regression FAIL ∨ any AC FAIL
REVIEW_REQUIRED = any AC UNSURE
JUDGE_ERROR      = harness/schema/tool error
```

`REVIEW_REQUIRED` 与 `JUDGE_ERROR` 不进入正式 PASS/FAIL 分母。

## 6. 聚合

```powershell
python Code/aggregate_rq4_results.py `
  --run-root outputs_new/rq4_runs `
  --output outputs_new/rq_results/rq4_summary.json
```

汇总保存微平均与 project macro-average Success Rate、Execution Coverage、C1/C2 计数和逐 run 状态。`paired_comparison`
只纳入同一 project、target、Agent 配置和 repetition 下 C1/C2 均完成评分的共同支持集合，报告两条件的
配对 Success Rate、`C2-C1` 差值与两种 discordant pair 计数。未完成 pipeline 的 run 保持
`PENDING`，不能静默当作模型失败。
