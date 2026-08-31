# ReqMemBench 整体标注流程

ReqMemBench 的标注分为三个主要阶段：先从项目聊天中识别 Requirement 及其生命周期 Event，再将 Event 回放为 Requirement State Graph，最后以 Client 消息为 Task 生成任务前后的 Gold State。

```text
项目聊天与元数据
        |
        v
Stage 1：Requirement / Event 标注
        |
        v
Stage 2.1：Requirement State Graph 构建
        |
        v
Stage 2.2：Task 选择与 Gold State 生成
```

## Stage 1：Requirement 与 Event 标注

Stage 1 的目标是从完整项目对话中建立 Requirement 体系，并为每个 Requirement 标出按时间排序的生命周期 Event 和执行 Event。当前输出格式为 annotation `v0.6`。

### Stage 1 Pipeline

```text
Datasets/<project_id>/：项目聊天 + 项目元数据
        |
        v
[0. 确定性预处理]
        |
        +--> normalized_project.json
        +--> pipeline_config.json
        |
        v
[1. EVIDENCE_SCAN]
按聊天分块扫描候选证据
        |
        +--> evidence_chunks/chunk_*.json
        +--> evidence_scan.json
        |
        v
[2. REQUIREMENT_DISCOVERY]
建立 Session / Family / 原子 Requirement inventory
        |
        +--> requirement_discovery.json
        |
        v
[3. EVENT_EXTRACTION]
每个 Requirement 独立提取按时间排序的 provisional Events
        |
        +--> events/<requirement_id>.json
        +--> event_extraction_findings.json
        |
        v
[4. CONSISTENCY_AUDIT]
全项目检查 Requirement 边界、重复/漏标、Event 类型和路由
        |
        +--> 应用高置信度 patch
        +--> 边界变化：重新提取受影响 Requirement 的 Events
        +--> audited_state.json
        |
        v
[5. CROSS_REQUIREMENT_IMPACT_AUDIT：verification 前]
回放实质性 MODIFY / REMOVE，检查对其他 Requirement 的连带影响
        |
        +--> ADD_EVENT / EDIT_EVENT / NO_IMPACT / HUMAN_REVIEW
        +--> impact_audited_state.json
        |
        v
[Lifecycle retention：默认保留所有 Requirement，包括 0–2 个 Event]
        |
        v
[6. EVENT_VERIFICATION]
逐 Requirement 验证全部 Event；重点复核 INTRODUCE，尤其是 MODIFY
        |
        +--> 每个 Event：KEEP / EDIT / DELETE
        +--> verification/<requirement_id>.json
        |
        v
verification 是否改变了 MODIFY / REMOVE 的实质语义？
        |
        +-- 否 ---------------------------------------------------+
        |                                                         |
        +-- 是 --> [CROSS_REQUIREMENT_IMPACT_AUDIT：verification 后] |
                         |                                       |
                         +--> 若产生 patch，重新验证受影响 Requirement
                         +--> 若仍有实质变化，写入最终人工复核提醒
                                                                  |
        +---------------------------------------------------------+
        |
        v
[最终 Lifecycle filter]
        |
        v
[7. 确定性组装与严格校验]
        |
        +--> verified_events.json
        +--> human_review.json
        +--> final/<project_id>_stage1_annotation.json
        +--> outputs/stage1_annotations/<project_id>_stage1_annotation.json
```

Extraction 后不会立即删除短 Requirement。它会一直保留到第一次跨 Requirement 影响审计结束，以便只有两个 Event 的 Requirement 仍有机会接收到第三个必要的连带 `MODIFY`。随后在 verification 前和 verification 后分别执行生命周期长度过滤。

### 0. 数据规范化

先对项目和消息做确定性预处理：统一项目与消息 ID，识别 Client/Freelancer，并原样保留说话人、文本、时间和消息顺序，形成 `normalized_project.json`。后续每个 Event 的 `message_id`、`speaker` 和 `text` 都必须与该文件中的原始消息完全一致。

### 1. 证据扫描（`EVIDENCE_SCAN`）

完整聊天按块交给模型扫描，找出可能涉及以下信息的消息：

- Requirement 的提出、变更、暂停、恢复或移除；
- Requirement 的 Value 或 Scope；
- 需要 Client 决策的歧义；
- 实现声明、运行失败或运行成功证据。

候选证据记录 message ID、证据标签、主题提示、上下文 message IDs 和置信度，再合并成项目级 Evidence Index。这一步只做高召回的证据索引，不创建正式 Requirement 或 Event。

### 2. Requirement 发现（`REQUIREMENT_DISCOVERY`）

模型从项目全局建立 Requirement ontology，标注：

- Sessions；
- 可选的 Requirement Families；
- 独立且可持续演化的原子 Requirement；
- 每个 Requirement 的 anchor message、初始 scope、边界说明和置信度；
- 暂时无法确定归属的候选项。

拆分依据是“能否独立变化、失败、修复或移除”。多个能独立演化的功能不能合并为一个宽泛 Requirement；同一目标的普通属性也不应被过度拆成多个 Requirement。此阶段结束后冻结初始 Requirement inventory，后续 Extraction 只能为 inventory 中已有的 Requirement 提取 Event。

### 3. Event 提取（`EVENT_EXTRACTION`）

每次只处理一个目标 Requirement。模型读取该 Requirement、必要的 Family siblings、候选证据及局部上下文，然后提取它的完整 chronological lifecycle/execution Events。

允许的 Event 类型及标法如下：

| Event | 标注含义 |
|---|---|
| `INTRODUCE` | Requirement 首次在可见聊天中被明确建立，至少标出 value 或 scope。 |
| `MODIFY` | 已有 Requirement 的 Value 或 Scope 发生变化，只记录本次变化，不重复整个旧状态。 |
| `DEFER` | Requirement 仍有效，但当前阶段暂不执行，生命周期进入 `DEFERRED`。 |
| `RESUME` | Requirement 从 `DEFERRED` 或 `CLARIFY` 回到 `ACTIVE`，该 Event 本身不承载 Value/Scope 修改。 |
| `REMOVE` | Client 明确不再需要整个 Requirement，不能用于普通属性变更或实现失败。 |
| `AMBIGUOUS` | 存在会实质影响下一步行动的未解决冲突，标注歧义维度 `VALUE`、`SCOPE` 或 `LIFECYCLE`。 |
| `IMPLEMENTATION_CLAIM` | Freelancer 明确声称目标功能已实现或修复，但该消息没有独立运行验证。 |
| `RUNTIME_FAILURE` | 实际测试或运行结果明确表明实现不符合该 Requirement。 |
| `RUNTIME_VERIFICATION` | 实际执行结果和可观察成功标准明确证明该 Requirement 正常工作。 |

每个 Event 都必须归属到正确的 Requirement，并以能够直接支持该语义的原始消息作为 `source_message`。局部上下文只能帮助解析指代，不能替代主消息承担 Event 语义。模型不得改写证据文本，也不得为了增加 lifecycle 长度而编造、重复或错误路由 Event。

`MODIFY` 的 payload 由三部分组成：

- `value_removals`：删除本次变更后已经失效的顶层属性；
- `value_updates`：新增或更新本次消息明确建立的属性；
- `scope_updates`：只更新发生变化的 scope 维度，维度值为 `null` 表示该维度本次未变化。

同一个 key 不能在一次 `MODIFY` 中同时被删除和更新。无法归入现有 Requirement 的证据只作为候选，交给后续全局审计。

### 4. 全局一致性审计（`CONSISTENCY_AUDIT`）

这一阶段同时查看完整 Requirement inventory 和全部 provisional Events，检查：

- Requirement 是否重复、重叠、过宽、过度拆分或漏标；
- Event 是否归错 Requirement、类型错误或 source evidence 错位；
- Client/Freelancer 权限是否使用正确；
- 执行类 Event 是否被过度标注或重复标注；
- Family 和 Session 是否合理。

审计通过 patch 修正结果，包括新增、合并、拆分、删除 Requirement，以及新增、编辑、删除、移动 Event。只有高置信度且结构合法的 patch 自动应用；低置信度、明确要求人工判断或应用失败的 patch 写入 `human_review.json`。如果 Requirement 边界发生变化，Pipeline 会重新提取受影响 Requirement 的 Events。

### 5. 跨 Requirement 影响审计（`CROSS_REQUIREMENT_IMPACT_AUDIT`）

对每个实质性的 `MODIFY` 或 `REMOVE`，程序先回放 source Requirement 变化前后的状态，再从所有 Requirement 的标题、当前属性、scope、历史、Family 和共享实体中检索可能受影响的候选项。模型逐个判断：

- `ADD_EVENT`：另一 Requirement 必然受到影响，但还没有对应 Event；
- `EDIT_EVENT`：已有同消息 Event，但缺少必要的更新、删除或 scope 变化；
- `NO_IMPACT`：只是历史或词面关联，另一 Requirement 状态不变；
- `HUMAN_REVIEW`：存在多种合理解释，无法自动传播。

自动传播只能生成或补全 `MODIFY`，必须使用同一条 Client source message，并且只应用高置信度决定。

### 6. Event 验证（`EVENT_VERIFICATION`）

对审计后保留的每个 Requirement 单独执行验证，并为其中每个 provisional Event 返回 `KEEP`、`EDIT` 或 `DELETE`。它会重新检查 source 是否支持 Event、是否属于目标 Requirement、Event 类型和 payload 是否正确，以及执行证据是否具体、独立且带来新的状态信息。

#### `MODIFY` 是否会被再次重点审核？

会。`EVENT_VERIFICATION` 不是只检查执行类 Event，它审核全部 Event，并对 `INTRODUCE`、尤其是每一个 `MODIFY` 设置了更严格的逐属性审核：

1. 分别检查 `value_updates`、`value_removals` 和 `scope_updates` 中的每一项是否有原始证据。
2. 判断每个属性是否真正影响软件行为、业务逻辑、UI/UX、数据/API/schema、认证授权、配置、基础设施、运行行为或验收条件。
3. 删除交付期限、排期、会议、人力、预算、账单、milestone 管理、工作量估计和交接安排等项目管理信息；系统控制的 timeout、expiration、retention 等时间规则仍可保留。
4. 回放 `MODIFY` 前的状态，确认 `value_removals` 中的 key 当时确实存在、删除项与更新项不重叠，并检查 provider/mode/entity/count/trigger 等替换是否遗留冲突的旧属性。
5. 若整个 `MODIFY` 都与实现无关，返回 `DELETE`；若混有有效和无效属性，返回 `EDIT` 并只保留有效项；清理后 payload 为空时也返回 `DELETE`。
6. 保留或编辑后的 `MODIFY` 必须保持 `ambiguity: null`、`execution: null`；状态回放时会重置 execution。

因此，`MODIFY` 至少经过 Extraction、全局 Consistency Audit、verification 前 Cross-Requirement Impact Audit 和 Event Verification 四层检查。若 Event Verification 的 `EDIT/DELETE` 改变了任一 `MODIFY/REMOVE` 的实质语义，Pipeline 还会再执行一次 verification 后 Cross-Requirement Impact Audit；如果该审计又修改了其他 Requirement，则只对受影响的 Requirement 再做一次 Event Verification。若最后一次复核仍改变实质语义，则不继续自动循环，而是写入最终人工复核提醒。

Verification 发现的 missing Event candidate 不会直接加入结果，而是进入人工复核，避免在最后阶段绕过 Requirement 路由与全局审计。

### 7. 生命周期保留、最终组装与校验

第一次跨 Requirement 影响审计后，以及 Event Verification 闭环结束后，Pipeline 都会执行 lifecycle retention 处理。默认 `--min-requirement-events 0`，因此不会按 Event 数量删除 Requirement，0、1、2 个 Event 的 Requirement 也会进入最终结果。少于两个成员的 Family 仍会被移除，其 Requirement 作为独立 Requirement 保留。

最后由确定性代码：

1. 按原始消息顺序稳定排列 Event，包括同一消息中的多个有序 Event；
2. 为每个 Requirement 生成连续的 `<requirement_id>_E001`、`E002` 等 Event ID；
3. 移除只供中间推理使用的字段，保留 canonical v0.6 Event 字段；
4. 校验 Session、Family、Requirement 和 Event ID 的唯一性及引用关系；
5. 校验 Event 时间顺序、source message、speaker、原文和 payload；
6. 生成最终 Stage 1 annotation、`verified_events.json` 和 `human_review.json`。

## Stage 2.1：Requirement State Graph

这一阶段不再进行模型标注，而是按 Stage 1 Event 的既定顺序确定性回放。每个 Requirement 形成一条线性状态链：

- Node 表示某一时点完整的 Requirement State；
- Edge 表示触发状态变化的 Event，并连接 `from_state_id` 与 `to_state_id`；
- lifecycle、ambiguity 和 execution 作为彼此独立的状态维度；
- 每个 Stage 1 Requirement 都进入 State Graph；没有 `INTRODUCE` 时从首个可见 Event 建立不完整的观测基线，未知状态保持为空或 `null`，不会伪造完整初始实现；
- `MODIFY` 先执行 `value_removals`，再应用 value 和 scope 更新，并将 execution 重置为空；
- 不产生实际状态变化的重复转换不生成新 Node/Edge；
- `supporting_event_ids` 只保留直接支撑当前状态的最小 Event 集合。

无法安全回放的转换会直接报一致性错误，不进行猜测或自动修补。输出为 `requirement_state_graph.json`。

## Stage 2.2：LLM 选择目标时间与 Gold State

Stage 2.2 不再按 Event priority、时间段比例和随机种子抽样 Task，而是把目标时间选择与 Gold replay 分成两个边界清晰的过程：

```text
规则生成 Candidate
        |
        v
构建 Candidate 前的相关 Requirement State 与历史证据
        |
        v
LLM 逐 Candidate 判断 Requirement Memory benchmark value
        |
        +--> 默认：coverage / deduplication --> 人工 ACCEPT / REJECT / ADD_BACK
        |
        +--> --auto-accept-ai：0-10 分数线以上全部直接接受
        |
        v
selected_target_times.json
        |
        v
State Graph 确定性回放 Pre/Post Gold
```

一个 Candidate 对应一条 Client message；同一消息触发的全部 Requirement Events 必须合并。主要候选包括 `MODIFY`、`REMOVE`、`DEFER`、`RESUME`、`AMBIGUOUS`，以及通过 `resolves_ambiguity_event_ids` 表达的 ambiguity resolution。当前 Stage 1 没有独立 `CLARIFY` / `RESOLVE` Event，Stage 2 只为 coverage 派生标签，不改写 Event schema。

LLM 每次只看到一个 Candidate Packet：当前 Task、triggered Events、受影响 Requirements 的 Pre-task States、此前 Event history 和对应原始 evidence messages。LLM 只判断历史依赖、Requirement 演化、重建风险、歧义决策价值、多 Requirement 价值和 history-sensitive error risk；它不重新标注 Requirement、不修改 State Graph，也不生成 Gold。

`history_turn_count` 定义为 Candidate 前的有效消息数量，从 `normalized_project.messages` 的规范化顺序计算。它会一直保留到最终 target 和 Gold，但不参与 LLM 评分、coverage、去重或排序。

默认模式中只有人工复核后的 target 才进入 Gold builder。显式使用 `--auto-accept-ai --score-threshold N` 时，程序按五个 `LOW/MEDIUM/HIGH` 维度确定性计算 0–10 分，并直接接受所有同时有效、history-sensitive、被 AI 推荐且达到分数线的时间点，不再要求 ACCEPT 文件。对每个 target，`Pre-task Gold` 是该消息发生前的完整项目 Requirement snapshot，`Post-task Gold` 是该消息中全部 Events 应用后的完整 snapshot；affected / preserved、INTRODUCE / REMOVE、same-message final State 和 future leakage 仍由确定性代码严格校验。

新版 Pipeline 已在 `gold_state.py` 和 `stage2_generate_gold_state.py` 中实现。实现契约见 [`DESIGN_stage2_target_time_selection.md`](DESIGN_stage2_target_time_selection.md)，准备 Candidate、运行 LLM、人工复核、AI 自动接受与 finalize 命令见 [`README_stage2_gold_state.md`](README_stage2_gold_state.md)。
