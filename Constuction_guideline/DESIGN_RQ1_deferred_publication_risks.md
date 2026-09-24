# RQ1 延期修改：论文发表风险与修改方案

## 1. 文档状态

本文记录 RQ1 问题 4–8。它们已完成设计与代码层面的核查，但**不在本轮实现**；本轮只修改
问题 1–3。后续开始正式 benchmark run 或撰写论文主结果前，应按本文逐项处理。

核查基线为 2026-09-21 的项目 `42204309`：RQ1 共 25 个 targets、84 个 Gold Atoms；25 个
targets 全部为 `LONG`，8 个 target 只有 1 个 Gold Atom，14 个 target 不超过 2 个 Gold Atoms。

危险等级定义：

- **P0 / 阻断正式结论**：不修会直接威胁指标效度、可复现性或论文主要结论；
- **P1 / 投稿前必修**：不会使 scorer 立即失效，但会使实验对比或论文论证明显不完整；
- **P2 / 增强项**：可以作为补充实验，不影响第一版主结论成立。

| 编号 | 问题 | 当前判断 | 危险等级 | 修改时点 |
|---|---|---|---|---|
| 4 | Gold Atom 缺少可判定边界的 canonical description | 存在，但“Judge 唯一依据是标题”并不完全成立 | P0 | 冻结 Judge prompt 前 |
| 5 | Judge 可靠性未测量、无稳定性兜底 | 存在 | P0 | 正式模型比较前 |
| 6 | RQ1 scorer 缺少系统 calibration | 存在 | P0 | 任何正式批量运行前 |
| 7 | 缺少 baseline 与 human ceiling | 存在 | P1 | 论文主实验完成前 |
| 8 | replicate、CI、分层与外推边界不足 | 存在 | P0 | 预注册/冻结实验协议前 |

---

## 2. 问题 4：`canonical_summary` 等于 `requirement_title`

### 2.1 问题描述与核查结果

当前 84/84 个 Gold Atoms 的 `canonical_summary` 与 `requirement_title` 完全相同。标题通常是
3–5 词的名词短语，不能稳定表达 Atom 的内部 attributes、scope、排除边界以及它与同 family
Requirements 的区别。对于以下 hard pairs，标题尤其不足：

- `Small Block Prize Mechanism` 与 `Big Block Prize Mechanism`；
- `Code-Used Referral Commission`、`No-Referral Commission Allocation`、
  `Code-Used Prize Ticket Issuance`、`No-Referral Ticket Allocation`；
- 同一 family 中 accounting、allocation、issuance 等可以独立演化的 Atoms。

需要修正原问题中的一个表述：当前 alignment request 除 `canonical_summary` 外，还向 Judge 提供
target task、Gold Atom 的历史 trajectory 文本以及 Prediction 自选的 evidence。因此标题并不是
“唯一语义依据”。不过，Gold 侧仍没有一个显式、稳定的 Atom boundary；Judge 只能从历史文本
自行归纳 `covers / excludes / internal rule fragments`。这使 `SUBPART_OF_ATOM`、
`MERGED_ATOMS` 与 `RELATED_DIFFERENT_ATOM` 的边界依赖 Judge 的临场解释。

另一个耦合风险是：Prediction evidence 同时出现在 Requirement relation request 中。虽然 evidence
overlap 不是代码中的合法 edge 门槛，Judge 仍可能被证据选择质量影响，从而把 Evidence 错误传导
到 Requirement label。

### 2.2 修改方案

1. 从 target 前的 Pre-task State 和 Requirement Graph 确定性生成 `canonical_description`，至少包含：
   - `covers`：该 Atom 当前负责的行为、对象和触发条件；
   - `key_attributes`：决定语义边界的稳定字段；
   - `scope`：components、contexts、persistence；
   - `excludes`：同 family、同 target 中容易混淆但独立演化的 sibling Atoms；
   - `internal_fragments`：属于 Atom 内部、不能单独视为 Requirement 的典型规则片段。
2. 描述必须由已有 State/Graph 字段按固定模板生成，不新增人工撰写 Gold，不读取 target 之后信息。
3. alignment request 同时提供简短标题和结构化 description；relation definitions 明确要求优先依据
   `covers/excludes` 判定 Atom 边界。
4. 建立 hard-pair fixture，覆盖上述 prize、commission、ticket 和 accounting 同族 Atoms。
5. 对 Prediction evidence 做反事实稳定性测试：保持 summary 不变，删除、替换或打乱 evidence，测量
   relation label flip rate。若 flip rate 过高，再比较“summary + canonical description”和
   “summary + description + evidence”两种 Judge 输入。

### 2.3 验收条件

- 84 个现有 Atoms 均生成非空、非标题复制的 canonical description；
- description 的字段全部可追溯到 target 前 State/Graph；
- hard-pair 人工校准集中，`MERGED_ATOMS`、`SUBPART_OF_ATOM`、
  `RELATED_DIFFERENT_ATOM` 的混淆矩阵达到预设门槛；
- evidence 反事实扰动的 relation label 不稳定率被量化并进入论文附录。

---

## 3. 问题 5：Judge 可靠性未测量，也没有兜底

### 3.1 问题描述

当前设计冻结 model/version、prompt、schema 和 scorer version，也会把 schema/LLM 基础设施失败
记为 `JUDGE_ERROR`；这些措施解决的是可复现配置与显式失败，不证明 relation label 本身可靠。
Requirement F1 的 TP edge 只由 `SAME_ATOM` 产生，一次错误标签会把一个潜在 TP 同时变成 FP 和
FN。目前缺少：

- Judge 与人工 reference labels 的一致性测量；
- 同一 Judge 重复调用的 label 稳定性；
- 第二 Judge model 的敏感性分析；
- relation label 不稳定时的确定性处理规则。

这里的人工工作是对**指标进行抽样校准**，不是对每个 benchmark response 做人工复核，因此不
违反正式 scoring 的 “no per-instance human review” 原则。

### 3.2 修改方案

1. 建立分层校准集：按 target Gold Atom 数、同 family hard pairs、预期 relation label、summary
   overlap 和 evidence overlap 分层抽样 Prediction–Gold pairs。
2. 至少两名独立标注者在冻结指南下标注；报告 raw agreement、Cohen/Fleiss κ、每类 precision/
   recall 和 confusion matrix。类别极不均衡时，同时报告 Krippendorff's α 或 prevalence 信息。
3. 冻结 Judge 配置后，对校准集独立运行 3 次；报告逐 pair label entropy、任何 label flip rate 和
   `SAME_ATOM` flip rate。正式协议可采用三次多数票；无法形成多数或涉及
   `SAME_ATOM ↔ non-SAME_ATOM` 冲突时记为 `JUDGE_UNSTABLE`，不得静默选第一次结果。
4. 选择第二个 Judge model 重跑完整校准集及至少一轮正式结果；报告 relation agreement、target-level
   score 差异、模型排名的 Kendall τ/Spearman ρ，以及 winner reversal 数量。
5. 增加 evidence 反事实 ablation，区分“Atom 语义判断不稳定”和“被 Prediction evidence 污染”。

### 3.3 验收条件

- 预先写明校准集抽样方法、人工标注指南和可接受的一致性阈值；
- 主 Judge 达到阈值后才允许正式评分；
- 三次调用的不稳定率、第二 Judge ablation 和模型排序敏感性进入正文或附录；
- `JUDGE_ERROR`、`JUDGE_UNSTABLE` 与 Agent 得 0 分在结果文件和统计分母中严格区分。

---

## 4. 问题 6：缺少 RQ1 scorer calibration

### 4.1 问题描述

RQ4 §6.6 要求 validator 在错误 pre-repo 与正确 delivery 上做双向校准；RQ1 尚无同等级的强制
校准协议。现有单元测试覆盖若干 relation 和 evidence 分支，但没有把“全部 25 个正式 targets 的
oracle 必须满分”写成发布门槛，也没有系统验证 merge/split 与 Evidence 解耦后的精确计数。

### 4.2 修改方案

建立两层 calibration：

1. **确定性 scorer calibration**：直接提供受控 alignment response，隔离 Judge 波动。
2. **Judge + scorer 端到端 calibration**：把 oracle prediction 真实送入冻结 Judge，再进入 scorer。

强制用例包括：

- 全量 oracle：每个 Gold Atom 使用 Gold description/summary，并为每个 evidence group 选择一个
  acceptable message；25/25 targets 的 Requirement F1、Evidence F1 和 Exact Set Accuracy 必须为 1；
- merge perturbation：用一个 Prediction 合并两个 Gold Atoms，其余保持 oracle。Requirement 应精确
  增加 1 FP、2 FN；若合并项引用两个 Atoms 的全部正确 evidence，Evidence 不因粒度错误降分；
- split perturbation：把一个 Gold Atom 替换为两个 `SUBPART_OF_ATOM` Predictions，其余保持 oracle，
  精确验证 Requirement TP/FP/FN；
- evidence omission：删除一个 required group 的唯一 claim，Evidence 精确增加 1 FN；
- irrelevant evidence：增加一个不在任何 acceptable/neutral 集合中的 claim，Evidence 精确增加 1 FP；
- acceptable duplicate/neutral evidence：增加同组 alternative 或 neutral claim，不得增加 FP；
- unified response fixture：含 `pre_task_state`、`decision`、`post_task_states`、`clarifications` 的合法
  response 必须被 RQ1 projection 接收，未知字段仍必须拒绝。

把这些用例做成 release-blocking regression tests，并保存每个 scorer schema version 的 golden
result fixtures。

### 4.3 验收条件

- 全量 oracle calibration 在 CI 中 25/25 通过；
- 每种定向扰动的 TP/FP/FN 与预先手算结果完全一致；
- Judge + scorer oracle 若不能满分，必须先修 Judge/description，不得通过修改期望值掩盖；
- scorer version、fixture hash 和 calibration report 随正式结果归档。

---

## 5. 问题 7：缺少 baseline 与 human ceiling

### 5.1 问题描述

当前设计主要给出被测 Coding Agent 的评分协议，没有冻结可复现 baseline，也没有 human ceiling。
因此论文无法回答：完整 Agent 相比简单检索提高了多少、任务本身的人类可达上限是多少、性能是否
主要来自 8 个单 Atom targets。

### 5.2 修改方案

至少实现以下对照：

1. `Random/Recency` sanity baselines：随机或最近消息选择，用于检查指标下限；
2. `BM25 top-k + frozen atomizer`：以 target task 为 query 检索历史消息，再由冻结的轻量 atom
   summarizer 生成 `requirements[]`；
3. `Embedding top-k + frozen atomizer`：与 BM25 使用相同 k、atomizer、response schema 和预算；
4. `Oracle-retrieval upper bound`：只替换检索输入为 Gold relevant trajectory，保留同一 atomizer，
   分离 retrieval 与 atomization 的误差；
5. `Human ceiling`：按 Atom 数、family hard pairs 和 history length 分层抽样；人类参与者只看公共
   task/history，使用相同 response schema，不查看 Gold。报告个人分数、均值、方差和参与者间差异。

`k`、embedding model、BM25 tokenizer、atomizer prompt/model 和预算必须在独立 dev set 上选择并
冻结，不能在 25 个 test targets 上调参。若暂时没有独立 dev project，应明确把结果称为 pilot，
不能把调参后的 test 数字作为无偏主结果。

### 5.3 报告要求

- 主表同时列 Requirement F1、Evidence F1、Exact Set Accuracy；
- 按 Gold Atom 数分层：1、2、3–5、>5；小样本层同时给出 target 数，不只报均值；
- baseline 与主模型使用相同 target、scorer 和 Judge 配置；
- human ceiling 的人工答案不能反向用于修改对应 test target 的 Gold 或 Judge prompt。

---

## 6. 问题 8：统计口径、replicates 与泛化范围

### 6.1 问题描述与核查结果

当前 RQ1 数据有以下限制：

- 25 个 targets 全部来自项目 `42204309`，项目层有效样本量为 1；
- 25/25 targets 的 `difficulty` 都是 `LONG`，SHORT/MEDIUM 分层为空；
- Gold Atom 数分布为：1 个（8 targets）、2 个（6）、3 个（3）、4 个（2）、5 个（3）、
  8 个（1）、11 个（1）、13 个（1）；
- 设计文档中的“第一轮一个 replicate”只适合作为 smoke test，不能作为正式随机模型实验；
- target-level macro 可以避免多 Atom target 在计数上支配总分，但同一项目内 targets 相关，普通
  target bootstrap 不能证明跨项目泛化。

### 6.2 修改方案

1. 每个 `model × condition × target` 至少运行 3 个独立 replicates；冻结 temperature、reasoning、
   tool budget 和 seed 策略，保存每次原始结果。
2. 先在每个 target 内汇总 replicate mean，再计算 target-level macro mean；同时报告 replicate
   variability 和 target variability，不能只把全部 runs 当独立样本。
3. 模型间比较使用配对 target bootstrap CI；多个模型/指标检验时预先指定主指标，并对次要检验
   做 Holm 等多重比较校正。
4. 当前单项目结果只表述为“在项目 42204309 的 target-level 表现”，明确不声明跨项目泛化。
5. 增加项目后，以 project 为一级 cluster 做 hierarchical/cluster bootstrap，并同时报告 project-
   macro 与 target-macro；不能让 target 数多的项目自动获得更大权重。
6. 正式采样补齐 SHORT/MEDIUM targets；在补齐前不绘制空 difficulty 层，也不声称已研究 difficulty
   effect。
7. 除 Atom 数分层外，预先报告 family hard-pair、history length、target change type 等切片；每个
   切片显示样本量和 CI，避免只展示有利切片。

### 6.3 验收条件

- 正式 protocol 明确 replicate 数、聚合顺序、CI resampling unit 和缺失/失败 run 的处理；
- 主表报告 mean、标准差或 replicate dispersion，以及 95% CI；
- 单项目阶段的所有标题、摘要和结论均带有限定语；
- 只有获得多个独立项目并采用 project-clustered inference 后，才允许提出跨项目结论。

---

## 7. 后续执行顺序

建议按以下 gate 推进，避免先产生昂贵正式 runs 再推翻指标：

1. 实现问题 4 的 canonical description 与 hard-pair fixtures；
2. 实现问题 6 的 scorer/oracle calibration，并设为 CI release gate；
3. 完成问题 5 的人工一致性、Judge self-consistency、第二 Judge 和 evidence 反事实实验；
4. 冻结问题 7 的 baselines、human ceiling 采样和预算；
5. 按问题 8 冻结 replicate、CI、分层和泛化协议；
6. 通过所有 gate 后再启动正式批量评估。

在上述 gate 完成前，现有 RQ1 数字只能用于 scorer 工程验证和 pilot，不应作为论文最终主结果。
