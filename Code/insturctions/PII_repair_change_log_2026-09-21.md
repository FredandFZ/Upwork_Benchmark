# PII 离线修复记录（2026-09-21）

## 本次范围

- 文本级 Agent 修复：`44036410`、`44166278`、`44039904`
- Phase 2 离线计划修复：`43214420`、`44133873`

## 项目结果

| 项目 | 结果 | 说明 |
| --- | --- | --- |
| `44036410` | 已发布 | 3 条文本由 Agent 离线修复；最终审计 0 问题；发布 101 条消息 |
| `44166278` | 已发布 | 3 条文本由 Agent 离线修复；最终审计 0 问题；发布 147 条消息 |
| `44039904` | 已发布 | 9 条文本由 Agent 离线修复；最终审计 0 问题；发布 346 条消息 |
| `43214420` | Phase 2 已通过 | 49 个实体决定、516 个 slot 决定全部通过；停在 `STOPPED_EARLY`，可进入 Phase 3 |
| `44133873` | Phase 2 已通过 | 44 个实体决定、108 个 slot 决定全部通过；停在 `STOPPED_EARLY`，可进入 Phase 3 |

## 代码修改

1. `Code/pii_apply_preserved_slot_repair.py`
   - Phase 2 恢复不再依赖旧、新 cluster 文件名完全相同；先汇总旧决定，再按当前 cluster 重新分组并校验。
   - 实体 canonical form 和 alias 都可约束相同原文的 slot 决定。
   - 同一短别名在不同消息代表不同实体时，按 ordinal 和出现位置选择实体替换值。
   - 短别名只用于精确出现位置，不用于全文搜索，避免普通短词误替换。
   - 支持 hash 绑定的 Agent slot override，以及明确授权后的缺失 slot 离线生成。
   - 离线生成仍经过正式 `validate_entity_chunk`、`validate_slot_cluster` 和项目组装校验。

2. `Code/PII/phase2_plan.py`
   - `IDENTIFIER` 可以从纯数字代码变为字母数字合成代码；其他数量类 slot 仍必须保留数值精度。

3. `Code/pii_prepare_offline_text_repairs.py`
   - 同一位置、同一映射被多个关系闭包 slot 重复记录时先去重，避免第二次应用时报“位置失效”。

4. `Code/pii_refresh_text_tasks.py`
   - 新增离线工具：计划修复后，按当前 Phase 2 plan 重新生成 TEXT Agent task 的 plan slice 和 hash，防止沿用旧计划任务。

5. `Code/tests/test_pii_plan.py`
   - 增加短别名、按 ordinal 消歧、重复 slot 出现、离线数值生成、保留术语文件名和数字标识符等回归测试。

## 项目专用修复凭据

- `outputs/pii_runs/44133873/agent_repairs/phase2_slot_overrides.json`
  - hash 绑定到当前语义 registry，只覆盖一个无效文件名 slot。
- `outputs/pii_runs/43214420/agent_repairs/phase2_missing_slot_generation.json`
  - hash 绑定到当前语义 registry，明确授权补齐历史 API 多次失败后仍缺失的 slot 决定。

这些文件只保存合成值、slot ID 和 hash，不记录原始消息正文。

## 验证

- 完整相关回归：`205/205` 通过。
- `43214420`：10 个 Phase 2 slot cluster 全部恢复，0 unresolved。
- `44133873`：2 个 Phase 2 slot cluster 全部恢复，0 unresolved。
- 三个已发布项目均先执行 `pii_finalize.py --validate-only`，确认审计为 0 后才正式提交。

## API 说明

修复本身均为离线操作。第一次对 `43214420` 做停止于 Phase 2 的恢复检查时，旧工具未识别新增 cluster，流水线尝试请求缺失 cluster；该请求传输失败，没有产生或提交模型结果。随后已改为按当前 cluster 离线重组，最终验证没有再次调用 API。

## 后续续跑命令

以下命令会从 Phase 3 继续，因此会调用已配置的 LLM API：

```powershell
python .\Code\pii_clean.py --project-id 43214420 --project-id 44133873 --insecure
```

## 第二批 8 项目 Agent 修复

以下项目已经完成离线 Agent 修复，并统一通过 `pii_finalize.py --validate-only`：

| 项目 | 接受的 Agent 修复 | Phase 6 审计 |
| --- | ---: | --- |
| `41829618` | 1 | 0 问题 |
| `43214420` | 1 | 0 问题 |
| `43255761` | 3 | 0 问题 |
| `43772711` | 4 | 0 问题 |
| `44099875` | 4 | 0 问题 |
| `44102153` | 3 | 0 问题 |
| `44133873` | 1 | 0 问题 |
| `44177602` | 6 | 0 问题 |

合计 23 条。其中 `43255761` 的第 3 条来自 Agent 文本通过后发现的 Phase 6 全项目凭据形状审计问题。

本批新增修正：

- slot 出现位置嵌套时优先应用外层安全编辑，内层目标值交给闭集补全，避免坐标被第一次编辑破坏。
- 实体移除优先级覆盖全部保留词来源，包括全局保留词和公共 allowlist；包含完整私有实体的更长保留短语也会被排除。
- `pii_refresh_text_tasks.py` 支持把 Phase 6 审计发现的 ordinal 添加为正式 TEXT Agent 任务。
- 完整相关回归测试更新为 `208/208` 通过。
