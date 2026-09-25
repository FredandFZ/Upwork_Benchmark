# RQ4 专用 Code Environment 增量迁移与验收指南

## 1. 文档目的

本文供负责更新 ReqMemBench Code Environment 的 Agent 使用。目标是把 PII CLEAN 前按全部 Gold 时间点生成的旧代码环境，迁移为由 `outputs_new` 驱动、只服务 RQ4 的新代码环境。

迁移后的基本单位是：

- 每个项目保留一个零业务 Requirement 的项目级 `C_env`；
- 只为需要进入 RQ4 构建或校准流程的 target 导出一个 `C(t^-)`；
- RQ1–RQ3 的 Phase A 不创建、不挂载、也不读取 repository；
- 同一 target 的 C1/C2 共用同一个 `pre_repo.zip`，不能按 condition 重复构建；
- 没有进入 RQ4 build plan 的 Gold target 不需要出现在 `Code Environment/<project_id>/targets/` 中。

本文说明迁移、验证和交付方法，不负责替代 RQ3 Gold 人工冻结、hidden validator 设计或正式 Agent 运行。

## 2. 核心结论

旧结果可以增量复用，但必须分层处理。

可以复用的部分包括：

- 已验证且无业务语义的项目级 `C_env`；
- lockfile、编译器与运行时版本、构建脚本、容器入口和中性 smoke tests；
- 与 Requirement State 无关的框架骨架；
- 旧 target repository 中经证明稳定、无 PII、无未来状态的基础设施文件。

必须依据新输入重新生成或重新验证的部分包括：

- RQ4 target 集合及新 `target_id`；
- 每个 target 的 `C(t^-)` Requirement 投影；
- 由 Requirement ID、State ID、attributes、scope 或 lifecycle 派生的代码和工件；
- runtime 聚合文件、生成的状态模型及相关测试；
- runtime-failure fixture 和 target-specific defect seed；
- target manifest、target index、replay ledger、checksums、validation report 和 ZIP；
- future-state、validator、reference-delivery、evaluator-metadata 和 PII 泄漏审计。

不能把迁移理解为替换 JSON 路径、修改 `Txxx` 编号或重写 manifest。PII CLEAN 可能改变 Requirement ID、标题、属性值、family、target 数量和 target 编号；旧代码中的 graph-derived 文件通常需要重新投影。

## 3. 规范边界

### 3.1 C_env 与 C(t-) 是两类不同工件

`C_env` 是保留技术栈、构建链和最小可执行入口，同时移除评测 Requirement 业务实现的零业务基线。它不是第一个任务前的业务代码，也不是任何 RQ4 Agent 的直接任务答案。

对 target message `t`，`C(t^-)` 定义为：

```text
已应用全部 source_message_id < t 的 Requirement Events，
尚未应用 source_message_id == t 的任何 Event。
```

同一 message 的全部 Events 必须作为原子 EventGroup。不能在导出 `C(t^-)` 前提前应用其中一部分。

### 3.2 只减少导出，不减少历史回放

新版只导出 RQ4 target repository，但构造器仍必须按新 Requirement State Graph 回放全部 EventGroup。未被选为 RQ4 target 的中间消息仍可能改变后续代码状态，不能从 timeline 中删除。

正确做法是维护一条私有、连续的代码演化链，只在 RQ4 target 前导出 snapshot：

```text
C_env
  -> apply EventGroup(m1)
  -> apply EventGroup(m2)
  -> ...
  -> export C(t1-) only if t1 is in the RQ4 build plan
  -> apply EventGroup(t1)
  -> ...
  -> export C(t2-) only if t2 is in the RQ4 build plan
```

不需要为非 RQ4 时间点创建 `pre_repo.zip`、manifest 或公开目录。若生成器需要 checkpoint，可保存在私有 staging/construction workspace，不能混入 Agent-visible archive。

### 3.3 RQ1–RQ3 不使用代码环境

正式实验必须保持两阶段隔离：

```text
Phase A: task + condition history -> RQ1/RQ2/RQ3 response -> freeze
Phase B: 仅在 Agent=ACT 且 RQ4 eligible 时开放全新 pre_repo -> RQ4
```

RQ1–RQ3 workspace 不得包含 repository、archive path、代码树、代码搜索入口或 build/test 输出。`pre_repo.zip` 只能由 Phase B Runner 在独立 workspace 中全新解压。

## 4. 权威输入与优先级

每个项目的迁移至少使用以下新输入：

```text
outputs_new/stage2/<project_id>/gold_states.json
outputs_new/stage2/<project_id>/requirement_state_graph.json
outputs_new/stage1_runs/<project_id>/normalized_project.json
outputs_new/stage2/<project_id>/target_time_selection/gold_state_validation.json
outputs_new/stage2/<project_id>/RQ3/index.json
outputs_new/stage2/<project_id>/RQ3/<target_id>_RQ3.json
```

如果已经存在经过审核的正式 RQ4 构建计划或 RQ4 index，还应读取：

```text
outputs_new/stage2/<project_id>/rq4_code_environment_build_plan.json
outputs_new/stage2/<project_id>/RQ4/index.json
```

权威性从高到低为：

1. 已冻结的 condition-specific RQ3 Gold、人工确认的 RQ4 build plan 和正式 RQ4 index；
2. 新 Gold State、State Graph 和 normalized history；
3. 新 target selection 记录；
4. 旧 Code Environment、旧 RQ4 index 和旧生成器，仅作为复用来源与迁移证据。

以下内容不能单独决定新 RQ4 target 集合：

- `gold_states.json.primary_rq_targets`；
- 旧 `outputs/stage2/<project_id>/RQ4/index.json`；
- 旧 target 目录中的 `Txxx`；
- “之前为该时间点生成过 repository”这一事实。

新版 RQ instance 构造器明确忽略遗留 `primary_rq_targets`。target 是否适合 RQ4 由 RQ3 Gold、可执行性、validator 和 leakage gate 决定。

## 5. 先确定 RQ4 pre-repo build plan

### 5.1 为什么需要 build plan

当前构造器只有在对应 Code Environment 已存在时才能生成 RQ4 candidate；但我们又需要先知道哪些 target 要构建 Code Environment。为避免循环依赖，迁移流程增加一个 researcher-side `rq4_code_environment_build_plan.json`。

build plan 只决定“哪些 target 需要构建一个 pre-repo”，不代表这些 target 已经具备正式 RQ4 评分资格。

### 5.2 正式 BUILD 条件

一个 target 进入正式 `BUILD` 集合，应满足：

1. 新 Gold 和 State Graph 中存在非空 affected transition；
2. C1/C2 的 RQ3 Gold 已完成冻结，且语义 Gold 一致；
3. 最终 RQ3 Gold decision 为 `ACT`；
4. target 对应至少一个可由本地确定性测试观察的外部行为或生成工件；
5. 不是纯配置镜像、主观视觉判断或必须依赖外部语义 API 的任务；
6. 项目技术环境足以构造可运行 pre-repo。

如果 RQ3 Gold 尚未冻结，但研究者需要提前验证迁移流程，可以把 target 标记为 `SMOKE_ONLY`。此类 repository 不能用于正式 RQ4 分数，直到 RQ3、validator、校准和 leakage gate 全部完成。

### 5.3 排除原因

建议使用与 RQ4 evaluation design 一致的有限枚举：

```text
RQ3_NOT_ACT
NO_RUNNABLE_ENVIRONMENT
NO_DETERMINISTIC_OBSERVABLE
CONFIG_ONLY_NO_INDEPENDENT_BEHAVIOR
SUBJECTIVE_VISUAL_OR_SEMANTIC
VALIDATOR_NOT_READY
REPOSITORY_GOLD_LEAKAGE
```

`VALIDATOR_NOT_READY` 不一定阻止 pre-repo 的准备和 smoke test，但必须阻止 `FORMAL_ELIGIBLE` 和正式评分。

### 5.4 build plan 建议结构

```json
{
  "schema_version": "rq4-code-environment-build-plan-v1",
  "project_id": "<project_id>",
  "input_release": "<outputs_new release or fingerprint>",
  "source_sha256": {
    "gold_states": "<sha256>",
    "requirement_state_graph": "<sha256>",
    "normalized_project": "<sha256>"
  },
  "targets": [
    {
      "target_id": "<project_id>_Txxx",
      "target_message_id": 123,
      "target_fingerprint": "<sha256>",
      "rq3_gold_by_condition": {"C1": "ACT", "C2": "ACT"},
      "deterministic_observable": true,
      "build_status": "BUILD",
      "legacy_match": {
        "matched_by": "SOURCE_MESSAGE_ID",
        "legacy_target_id": "<old target id or null>",
        "legacy_message_id": 123
      }
    }
  ],
  "excluded_targets": [
    {
      "target_id": "<project_id>_Tyyy",
      "target_message_id": 456,
      "reason": "RQ3_NOT_ACT"
    }
  ]
}
```

同一 target 不因 C1/C2 生成两份 repository。只要 target 被批准构建，就生成一份共享 `pre_repo.zip`。

### 5.5 端到端执行顺序

接手单个项目后，Agent 按以下顺序工作：

1. 读取新 Gold、Graph、normalized history、Gold validation 和 RQ3 records；
2. 读取已冻结 build plan；若不存在，只生成候选计划并标记 review blocker，不得自行猜测正式 RQ4 集合；
3. 对旧 Code Environment 做只读审计并冻结 checksums；
4. 判断项目级 C_env 是复用、局部修复还是重建；
5. 按 source message 对齐旧、新 targets，生成复用矩阵；
6. 在 staging 中修复生成器的路径、Requirement ID、target count 和 fixture 硬编码；
7. 使用新 Graph 回放完整 Event timeline，只在 build plan targets 前导出 `C(t^-)`；
8. 清理旧 graph-derived 文件，重新投影新 State，并为 bug target 恢复正确的失败前提；
9. 从 fresh extraction 运行项目级和每个 target 的 install/build/test；
10. 生成 deterministic ZIP、manifests、indexes 和 reports；
11. 运行独立 replay、archive、tree hash、PII、secret 和 leakage audit；
12. 使用 RQ instance CLI 执行 RQ1–RQ4 `--validate-only` join；
13. 完成 hidden validator 的 pre-repo/reference/partial-delivery 校准；
14. 所有硬门通过后再把 staging package 提升为 canonical Code Environment。

任一步骤失败都保留 staging 和诊断证据，不得用旧 validation report、手改 `overall=pass` 或跳过测试继续交付。

## 6. 迁移前检查

迁移 Agent 必须先完成只读审计，再修改文件。

### 6.1 验证新上游工件

- `gold_state_validation.json.status == PASSED`；
- Gold、State Graph、normalized history 的 `project_id` 一致；
- 每个 target message 存在于 normalized history；
- `conversation_turn_index`、target message position 和 history count 一致；
- task Event 全部来自 target message；
- Event owner 集合等于 affected Requirement 集合；
- 每个 Gold State ID 都能在对应 Requirement graph 中找到。

### 6.2 冻结旧包

记录旧包的目录树、文件哈希、target manifest、target index 和 validation report。不要直接在唯一旧副本上改写。迁移应先写入 sibling staging directory，全部验证通过后再提升为 canonical package。

### 6.3 判断 C_env 能否原样复用

项目级 `C_env` 只有同时满足下列条件才能复用：

- 技术栈和可观测源代码/交付物没有改变；
- C_env 确实是零业务 Requirement 基线，而不是旧 `C(t^-)`；
- install、build、run/deploy 和 smoke test 仍通过；
- 新 PII/secret 扫描通过；
- 新 Requirement universe 的 forbidden-domain scan 没有未解释命中；
- C_env 中没有旧项目名、旧 PII 或未来 Requirement 提示；
- source snapshot、manifest 和 checksum 可以重新验证。

如果这些条件成立，应直接复用并重新记录 checksum，不要为了 graph ID 变化重建零业务基线。

## 7. 旧 target 与新 target 的对齐

### 7.1 禁止按 T 编号对齐

`T001`、`T002` 等编号会随 target selection 改变。旧 `T002` 和新 `T002` 可能对应完全不同的消息。

对齐键必须优先使用：

```text
project_id + target_message_id/source_message_id
```

并辅以：

- normalized message position；
- 脱敏前后任务语义；
- task Event source message；
- target fingerprint 或上游 input release。

不能以文本逐字节相同作为必要条件，因为 PII CLEAN 会合法改变名称、金额、URL、账号和其他 slot value。

### 7.2 三类迁移情况

| 情况 | 处理 |
|---|---|
| 新旧 target 具有相同 source message | 复用旧 repository 的稳定脚手架，重新投影所有 graph-derived 文件 |
| 新 target 没有旧 snapshot | 从最新已验证的迁移 checkpoint 继续顺序回放；没有可靠 checkpoint 时从 C_env 开始 |
| 旧 target 不再进入 build plan | 不复制到新 active package；保留在 legacy evidence 中，不进入新 target index |

旧 target 只能作为复用来源，不能因为“目录已存在”自动进入新包。

## 8. 文件级复用规则

### 8.1 通常可以复用

- lockfile 和由证据支持的依赖版本；
- 中性的 package/build/run/test scripts；
- Dockerfile、Makefile、compiler config 和 framework convention；
- 不含业务语义的 server/app shell；
- 环境 smoke tests；
- 中性的 C_env README。

复用前仍需做 PII、future-state 和 domain-term 扫描。

### 8.2 必须重新投影

- 以 Requirement ID 或标题命名的文件；
- feature modules、state snapshots 和 runtime registry；
- 从 attributes、scope、lifecycle、ambiguity 或 execution 生成的代码；
- 项目状态合约、数据模型、schema、文档或设计工件；
- requirement-to-code mapping；
- target-specific fixtures；
- manifest、target index、replay report 和 source checksums。

重新投影前，应删除 staging repository 中旧 graph-derived 目录的全部内容，防止已移除或重命名的 Requirement 文件残留。不能只覆盖新文件而保留旧文件。

### 8.3 硬编码迁移检查

生成器中出现以下硬编码时必须改造：

- 旧 Requirement ID；
- 固定 target 数量；
- 按 `Txxx` 绑定 temporal fixture；
- 旧 `outputs` 输入路径；
- 旧项目名、金额、账号、URL 或 PII slot；
- 报告中的旧 RQ4 target list；
- 只适用于旧 target 编号的 defect seed。

temporal fixture 应按 `target_message_id`、Event 语义或稳定 fixture ID 绑定，不能按会变化的 `Txxx` 绑定。

## 9. 新 timeline 的构造与回放

### 9.1 建立 EventGroup

从新 State Graph 的全部 edges 构建 timeline：

1. 按 normalized history 中的真实 message position 排序；
2. 同一 message 内按 graph index 和 edge index 的稳定顺序排序；
3. 相同 `source_message_id` 的 Events 组成原子 EventGroup；
4. 初始化 `current_state = {}`；
5. 每条 edge 应满足当前 state 等于 `from_state_id`，然后再更新为 `to_state_id`。

### 9.2 target 导出顺序

```text
for each EventGroup(m):
    if m belongs to an approved RQ4 build target:
        assert current_state == target.pre_task_gold_state
        materialize repository from current_state
        verify target change is not already implemented
        export pre_repo and manifest

    apply all events in EventGroup(m) atomically

    if m belongs to an approved RQ4 build target:
        assert current_state == target.post_task_gold_state
        mark post_state_verified_against_gold = true
```

即使只导出少量 RQ4 target，回放报告也应覆盖完整 graph timeline，并记录所有 EventGroup。

### 9.3 lifecycle 与 execution 处理

| State 情况 | pre-repo 处理 |
|---|---|
| `ACTIVE` 且无阻塞 ambiguity | 实现当前完整 State |
| `REMOVED` | 旧入口和行为已不存在；保留必要迁移兼容但不保留未来提示 |
| `DEFERRED` | 当前产品不提供该行为，不保留面向 Agent 的 TODO |
| OPEN ambiguity | 保持最后已确认行为，不猜测未知值 |
| `RUNTIME_FAILURE` | 保留或重建可重复触发的 bug，不提前修复 |
| `RUNTIME_VERIFICATION` | 已验证修复应处于 regression-passing 状态 |
| `NON_CODE_ACTION` | repository no-op，并在研究者侧 manifest 记录原因 |

Runtime failure target 的标准 regression suite 仍应通过。目标 bug 应由单独 reproduction check 或后续 hidden Target Test 证明失败，不能让普通 `npm test`、`forge test` 等环境回归命令永久失败。

## 10. 输出目录与最小交付物

新 active package 建议保持现有 loader 可识别的布局：

```text
Code Environment/<project_id>/
├── C_env/
│   └── <project_id>_C_env_complete.zip
├── targets/
│   └── Txxx_before_<message_id>/
│       ├── pre_repo.zip
│       └── manifest.json
├── reports/
│   ├── rq4_code_environment_build_plan.json
│   ├── replay_manifest.json
│   ├── target_index.json
│   ├── source_checksums.json
│   ├── validation_report.json
│   ├── independent_audit_report.json
│   └── reconstruction_report.md
├── tools/
│   ├── reconstruct_all.<ext>
│   └── audit_outputs.<ext>
└── README.md
```

`targets/` 和 `target_index.json` 应只包含 build plan 中的 target。非 RQ4 target 不需要空目录或占位 manifest。

### 10.1 每个 target manifest 的必需字段

为兼容 RQ instance loader，每个 manifest 至少包含：

```json
{
  "project_id": "<project_id>",
  "target_id": "<project_id>_Txxx",
  "before_message_id": 123,
  "target_event_ids": ["..."],
  "target_event_types": ["MODIFY"],
  "pre_state_verified_against_gold": true,
  "post_state_verified_against_gold": true,
  "repo_sha256": "<canonical tree sha256>",
  "repository_classification": "simulated-executable-pre-state",
  "requirements_to_code": [],
  "temporal_fixture": null,
  "migration_provenance": {
    "input_release": "<new release>",
    "legacy_target_id": "<old id or null>",
    "legacy_message_id": 123,
    "reuse_mode": "SCAFFOLD_REUSED_STATE_REPROJECTED"
  }
}
```

`requirements_to_code`、State IDs、migration provenance 和 fixture metadata 属于 researcher-side 数据，只放在 ZIP 外的 manifest/report 中，不能复制进 Agent-visible `pre_repo.zip`。

### 10.2 repository tree hash

tree hash 必须：

- 对相对 POSIX path 排序；
- 同时哈希 path 和文件内容；
- 排除 `.git`、`node_modules`、build cache 和临时输出；
- 在解压后可独立复算；
- 与 manifest、target index 和 RQ4 instance 中的值一致。

## 11. 测试与验收门

每个 gate 都必须产出机器可读结果。任一硬门失败时，不得把 staging package 提升为 canonical Code Environment。

### Gate A 上游与 build plan

- 新 Gold validation 为 `PASSED`；
- source files 的 SHA-256 已记录；
- build plan target ID 和 message ID 唯一；
- build plan 与冻结 RQ3 Gold 一致；
- 没有使用遗留 `primary_rq_targets` 决定集合；
- active target set 与 `target_index.json`、target manifests 完全一致。

### Gate B 全量 replay 与时间边界

- 每条 Event 的 `from_state_id` 与 replay current state 一致；
- 同 message Events 原子应用；
- 每个导出 target 的 pre-state 与新 Gold 完全相等；
- 应用 target EventGroup 后的 post-state 与新 Gold 完全相等；
- replay 覆盖所有 EventGroup，而不是只覆盖 RQ4 target messages；
- target message 的任何新行为都未提前出现在 `C(t^-)`。

### Gate C C_env 正向和负向验证

正向验证：

- clean install；
- build/compile；
- run/deploy 或等价最小入口；
- smoke tests；
- 在干净环境重复执行得到一致结果。

负向验证：

- 没有 Benchmark Requirement 业务行为；
- 没有业务模块、专用 schema、业务 fixture 和未来 TODO；
- 没有 Requirement 答案、validator、reference delivery 或 hidden tests；
- 没有真实 credentials、生产地址、个人信息和旧 PII；
- forbidden lexicon 命中均已人工解释或清除。

### Gate D 每个 pre-repo 的可运行性

所有命令以项目 manifest 中记录的固定命令为准，不应假设所有项目都使用 npm。至少验证：

- 从新解压目录执行 clean install；
- build、lint/typecheck 或领域等价检查；
- 已有 regression tests；
- 可执行入口或生成工件；
- 多次构建的关键工件具有确定性；
- 不依赖个人绝对路径、已有 cache、真实密钥或外部可变服务。

领域特定项目还应验证工件结构，例如 DOCX/PDF 的 ZIP/CRC、KiCad 的结构与拓扑、智能合约的编译与测试等。缺失本地原生工具时，必须记录 `NOT_RUN` 和原因，不能伪报 `PASS`；只有已有的等价确定性检查可以记为通过。

### Gate E RQ4 precondition 和 defect fidelity

- pre-repo 的 Build 和 Regression 必须通过；
- target 新增或修改行为在 pre-repo 中必须尚未成立；
- REMOVE target 中待删除的旧行为应仍然存在；
- OPEN ambiguity 不得被提前猜测；
- Runtime failure target 必须能稳定复现目标 bug；
- target-specific fixture 与新 message/Event 语义一致；
- 不能因为迁移而顺手修复 Agent 本应完成的任务。

### Gate F ZIP 和安全

- archive CRC 通过；
- 无绝对路径和 `..` path traversal；
- 无 symlink；
- 无 `.git`、Git object 或 construction history；
- 无 evaluator-side reports、Gold、State Graph 和 build plan；
- 解压后的 tree hash 等于 manifest；
- deterministic archive 重建后 SHA-256 一致；
- ZIP 仅含 Agent 在 Phase B 合法可见的 repository。

### Gate G RQ4-specific leakage audit

必须分别检查：

```text
future/post-task state leakage
hidden validator leakage
acceptance criteria leakage
reference delivery leakage
evaluator metadata leakage
PII/credential leakage
```

合法的 pre-task 业务实现可以保留，因为它是 RQ4 起点；但内部 Requirement/Event/State ID、expected code path、未来测试名和正确 patch 不得暴露。

### Gate H 独立审计

独立审计器不能复用生成器的内存状态。它应从磁盘重新读取新 Gold、State Graph、build plan、manifests 和 ZIP，并完成：

- 独立 replay；
- target set equality；
- pre/post Gold equality；
- archive 安全和 tree hash 复算；
- fresh extraction 后的 build/test；
- leakage 和 PII scan；
- report/manifest/index 交叉一致性。

`validation_report.json.overall` 和 `independent_audit_report.json.overall` 都必须为 `PASS`。

## 12. Hidden validator 与正式 RQ4 校准

Code Environment 验收通过后，RQ4 仍需完成 target-specific hidden validator。Validator 不得放入 `pre_repo.zip` 或 Agent workspace。

每个 validator 检查三项：

```text
BuildPass AND TargetTestPass AND RegressionPass
```

正式使用前必须校准：

1. Pre-repo：Build 和 Regression 通过，Target Test 失败；
2. Reference delivery：三项全部通过；
3. 多行为 target 的 partial delivery：至少缺失一项必要行为时 Target Test 失败。

如果 pre-repo 已通过 Target Test，说明 repository 提前包含答案或测试没有覆盖 target；如果 reference delivery 失败，或 partial delivery 意外通过，validator 不能冻结。

只有 RQ3 Gold、validator、校准记录和 leakage audit 全部完成后，才能把 `execution_ready` 设为 `true` 并产生正式 `PASS/FAIL`。

## 13. 与 RQ instance 构造器的最终 join

### 13.1 构建前只生成 RQ1–RQ3

Code Environment 尚未迁移完成时，可先生成 reasoning instances：

```powershell
python Code/stage2_generate_rq_instances.py `
  --project-id <project_id> `
  --rq-ids RQ1 RQ2 RQ3 `
  --stage2-root outputs_new/stage2 `
  --stage1-run-root outputs_new/stage1_runs `
  --output-dir outputs_new/stage2/<project_id> `
  --validate-only
```

### 13.2 Code Environment 完成后验证全部 RQ join

```powershell
python Code/stage2_generate_rq_instances.py `
  --project-id <project_id> `
  --rq-ids RQ1 RQ2 RQ3 RQ4 `
  --stage2-root outputs_new/stage2 `
  --stage1-run-root outputs_new/stage1_runs `
  --code-environment-dir "Code Environment/<project_id>" `
  --output-dir outputs_new/stage2/<project_id> `
  --validate-only
```

通过后再去掉 `--validate-only` 写入实例。

当项目需要完整 `rq_instance_manifest.json` 时，应一次构建 RQ1–RQ4；不要仅运行 `--rq-ids RQ4` 后覆盖原本包含 RQ1–RQ3 的项目 manifest。

Stage 2 RQ instance 单元测试：

```powershell
python -m unittest Code.tests.test_stage2_rq_instances -v
```

最终 join 必须确认：

- RQ4 instance 数等于 Code Environment 中满足 candidate 规则的 target 数；
- 每个 `before_message_id` 等于新 target message ID；
- manifest Event IDs/types 与新 Gold/Graph 一致；
- archive、manifest、validation report 和 target index 的 hashes 可复算；
- RQ4 构造阶段没有解压 archive；
- RQ1–RQ3 source artifacts 不引用 Code Environment。

## 14. 42204309 迁移注意事项

当前新 release 的状态是：

- `outputs_new/stage2/42204309/gold_states.json` 和 State Graph 已生成；
- Gold validation 为 `PASSED`；
- 新 RQ1–RQ3 instances 已生成；
- 新 `RQ4/index.json` 尚未生成；
- 新 RQ3 records 仍包含人工冻结 blocker，因此当前不能把任何旧 RQ4 列表直接宣布为正式新分母。

该项目已验证以下迁移风险：

1. 旧、新 target ID 不能直接对齐；必须按 source message 对齐；
2. 旧、新 Requirement ID 大量重命名，不能保留旧 feature 文件；
3. 项目级 C_env 是零业务基线，可以在重新通过 scan/test 后复用；
4. 旧生成器硬编码了旧输入路径、旧 Requirement ID、固定 target 数和按 T 编号绑定的 temporal fixture；
5. 即使最终只导出 RQ4 targets，也必须回放新 graph 中的全部 EventGroup；
6. 旧 all-target package 应保留为 legacy evidence，但不能作为新 active target index；
7. 新 RQ4 build plan 未冻结前，只能进行 `SMOKE_ONLY` 迁移，不能发布正式 RQ4 score。

迁移 42204309 时，应先修复生成器，再在 staging 中完成一个 RQ4 pilot target。Pilot 必须覆盖：Gold replay、脚手架复用、graph-derived 文件清理、新投影、runtime failure/fixture 对齐、fresh extraction build/test、ZIP audit 和 RQ4 instance `--validate-only` join。Pilot 通过后再批量处理 build plan 中剩余 targets。

## 15. 常见错误

| 错误 | 后果 | 正确处理 |
|---|---|---|
| 为全部 Gold targets 继续导出 repository | 浪费构建和审计成本，并违反 RQ4-only scope | 只导出 build plan targets，timeline 仍全量回放 |
| 使用 `primary_rq_targets` | 遗留字段可能与新版 RQ4 规则不一致 | 使用冻结 RQ3 Gold、build plan 和新 RQ4 index |
| 按 T 编号复用旧目录 | target 编号重排后语义错位 | 按 source message 和 fingerprint 对齐 |
| 只覆盖新 feature，不删除旧文件 | 已删除/重命名 Requirement 泄漏 | 清空 graph-derived 区域后完整重投影 |
| 从最近旧 target 直接复制并交付 | 中间 Events 可能缺失 | 从验证过的 checkpoint 顺序重放到 t- |
| 把 target bug 修好后再导出 | Agent 无法执行真实修复任务 | 保留可复现 bug，Target Test 在 pre-repo 上应失败 |
| 将 failing target test 放入公开 regression | pre-repo 环境被误判为不可运行 | regression 通过；失败由独立 reproduction/hidden test 观察 |
| 把 validator 或 acceptance criteria 放进 ZIP | 产生答案泄漏 | 仅保存在 evaluator-side registry |
| 只测试生成器工作目录 | cache 和本机状态可能掩盖问题 | 从 fresh extraction 做 clean install/build/test |
| 修改 validator 后沿用旧结果 | 不同 run 的评分标准不一致 | 升级 validator version 并重跑相关结果 |

## 16. 迁移 Agent Definition of Done

迁移 Agent 只有在以下项目全部完成后才能报告完成：

- [ ] 使用 `outputs_new`，未混用旧 Gold/Graph；
- [ ] RQ4 build plan 已提供或已由研究者冻结；
- [ ] target 通过 message ID/fingerprint 对齐，未按 T 编号猜测；
- [ ] C_env 完成正向运行与负向零业务/PII 检查；
- [ ] 完整 Event timeline 已回放；
- [ ] 只导出 build plan 中的 targets；
- [ ] 所有 selected pre/post states 与新 Gold 完全匹配；
- [ ] 旧 graph-derived 文件已彻底清理并按新 graph 重投影；
- [ ] runtime failures 和 temporal fixtures 与新 target 语义一致；
- [ ] 每个 pre-repo 在 fresh extraction 中通过 install/build/regression；
- [ ] target change 未提前实现；
- [ ] ZIP CRC、安全路径、symlink、`.git` 和 tree hash 检查通过；
- [ ] future state、validator、reference delivery、evaluator metadata、secret 和 PII 扫描通过；
- [ ] `target_index.json` 与 manifests 的 target set 完全相等；
- [ ] generator validation 和 independent audit 都为 `PASS`；
- [ ] RQ1–RQ4 `--validate-only` join 通过；
- [ ] 未把 Code Environment 暴露给 RQ1–RQ3 Phase A；
- [ ] 正式 RQ4 target 已完成 validator 三类校准；
- [ ] canonical 目录只在 staging 全部门通过后更新，legacy evidence 仍可追溯。

## 17. 依据文档

本指南综合并收敛以下现有规范：

- `Cenv_code_environment_reconstruction_method.docx`：C_env 的零业务基线、减法式/合成式重建和双重验收；
- `Constuction_guideline/DESIGN_RQ_instance_construction.md`：RQ4 candidate、Code Environment join 和 instance schema；
- `Constuction_guideline/DESIGN_RQ_evaluation.md`：RQ4 eligibility、hidden validator、校准、PASS/FAIL 与聚合；
- `Constuction_guideline/DESIGN_RQ_agent_input_materialization.md`：Phase A/Phase B 权限隔离、fresh extraction 和 leakage audit；
- `Code/insturctions/README_stage2_rq_instances.md`：实际 CLI、校验器和 RQ instance 测试；
- `Code Environment/42204309/reports/Code_State_Reconstruction_Pipeline_Design_v1.md`：完整 Event timeline、`C(t^-)` 导出和时间泄漏检查。

发生冲突时，优先采用新版 RQ construction/evaluation/materialization 规范；旧 Code Environment 报告只作为迁移证据，不作为新 target eligibility 的权威来源。
