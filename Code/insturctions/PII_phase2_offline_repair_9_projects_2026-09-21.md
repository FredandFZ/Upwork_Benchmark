# 9 个项目 Phase 2 离线修复记录（2026-09-21）

## 修复范围

本次修复以下项目首次 Phase 2 实体分片失败、没有可复用 checkpoint 的问题：

- `37923084`
- `43796672`
- `43804272`
- `43948285`
- `44159104`
- `44159601`
- `44184953`
- `44186585`
- `44190396`

修复全程未调用 LLM API。Agent 根据已通过校验的 Phase 0B、1A、1B 本地结果，离线重建完整 Phase 2 计划。

## 结果

| 项目 | 实体决策 | slot 决策 | 实体分片 | slot 分组 | Phase 2 校验 |
| --- | ---: | ---: | ---: | ---: | --- |
| `37923084` | 48 | 133 | 1 | 3 | PASS |
| `43796672` | 10 | 18 | 1 | 1 | PASS |
| `43804272` | 34 | 63 | 1 | 1 | PASS |
| `43948285` | 38 | 26 | 1 | 2 | PASS |
| `44159104` | 46 | 51 | 1 | 1 | PASS |
| `44159601` | 16 | 25 | 1 | 1 | PASS |
| `44184953` | 20 | 14 | 1 | 1 | PASS |
| `44186585` | 57 | 60 | 1 | 1 | PASS |
| `44190396` | 24 | 17 | 1 | 1 | PASS |

合计：293 个实体决策、407 个 slot 决策。两个 SUM 关系均按新值重新满足。

每个项目生成并安装了：

- `outputs/pii_runs/<项目ID>/agent_repairs/phase2_plan.json`
- `outputs/pii_runs/<项目ID>/agent_repairs/phase2_repair_result.json`
- `outputs/pii_runs/<项目ID>/phase2_transformation_plan/plan.json`
- 对应实体分片、slot 分组和 Phase 2 输出 checkpoint

安装后 9 个项目均为 `unresolved: 0`，下一步为普通续跑 Phase 3–6。

## 代码修改

1. 新增 `Code/pii_prepare_phase2_offline_repairs.py`
   - 只允许本次审计确认的 9 个项目。
   - 离线生成 hash 绑定的完整实体和 slot 决策。
   - 同一身份组统一使用保留域 `.example`。
   - 公共服务链接保留服务端点；用户自定义托管站点改用私有合成域名。
   - slot 按出现位置生成替换值；裸数字仍为 `SEMANTIC_ONLY`，不进行全局字符串替换。
   - 写文件前执行生产版实体、slot、关系和整份计划校验。

2. 修改 `Code/pii_apply_offline_plan_repair.py`
   - 当字面出现是历史值的拼写变体时，按该 ordinal 的有效历史状态绑定计划值。
   - 安装成功后清除已解决的 Phase 2 ledger 记录并把状态更新为可从 Phase 3 续跑。
   - 记录重建后的 Phase 0B registry hash，使重复安装保持幂等，同时继续拒绝无关 registry 变化。

3. 修改 `Code/PII/phase2_plan.py`
   - `*.webflow.io`、`*.netlify.app`、`*.lovable.app` 的首级子域属于客户私有身份，不能因为平台品牌是公共实体就原样保留。

4. 修改 `Code/tests/test_pii_plan.py`
   - 增加公共托管平台私有子域回归测试。

## 验证

- 9 份离线计划均通过生产版 `validate_entity_chunk`、`validate_slot_cluster` 和 `validate_plan`。
- 安装结果中的实体和 slot 数与各自 `plan.json` 完全一致。
- `Code.tests.test_pii_plan`：135/135 通过。
- 全部 PII 回归测试：264/264 通过。
- `pii_clean.py --status`：9 个项目均为 `unresolved: 0`，下一步为 `resume`。

## 后续命令

以下命令会恢复 Phase 0A–2 checkpoint，并从 Phase 3 开始调用 LLM API：

```powershell
python .\Code\pii_clean.py `
  --project-id 37923084 --project-id 43796672 --project-id 43804272 `
  --project-id 43948285 --project-id 44159104 --project-id 44159601 `
  --project-id 44184953 --project-id 44186585 --project-id 44190396 `
  --insecure
```

不要添加 `--force-phase PHASE_2_TRANSFORMATION_PLAN`，否则会删除已经安装的离线 Phase 2 checkpoint，并重新调用 Phase 2 API。
