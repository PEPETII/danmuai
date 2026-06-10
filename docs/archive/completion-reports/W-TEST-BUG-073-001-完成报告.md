# Codex 完成报告

> 工单 ID：W-TEST-BUG-073-001  
> 完成时间：2026-06-03  
> 执行者：Codex

---

## 1. 修改摘要

闭合 [TEST-GAPS.md](../../bug-audit/TEST-GAPS.md) §6 BUG-073：在 CI 可跑范围内补充 `reply_request_id` 整数域网格唯一性回归，以及 `_pending_request_meta` 在 8 线程 × 50 条唯一 triple 下的并发 register/pop 压测（`threading.Barrier` 同步起跑）。本票**仅**测试与文档；未将 dict 键改为 `tuple`。

## 2. 修改的文件

- `tests/test_request_scheduling.py`
- `docs/bug-audit/TEST-GAPS.md`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-TEST-BUG-073-001-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `app/**`：是
- 未修改 `web/static/**`：是
- 未修改 `community-site/**`：是
- 未修改 `supabase/**`：是

## 4. 运行的命令

```bash
python -m pytest tests/test_request_scheduling.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| scoped pytest | 通过 | **15 passed** in ~1.5s |
| boundary_guard | 未跑 | 纯 `tests/` + 文档，未触达 Web/API 边界 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | scoped pytest 单文件 | 全部通过 | **15 passed** | 是 |
| 2 | `git diff --name-only` 无 `main.py` / `app/` | 仅 tests + docs | 是 | 是 |
| 3 | 重复跑并发用例 3 次无 flake | 待负责人可选 | — | — |

## 7. 风险与注意事项

- 并发测试模拟「若未来从工作线程触达 `_pending_request_meta`」的最坏情况；生产路径仍为主线程登记/弹出（与 BUG-080 审计一致）。
- `test_reply_request_id_injective_across_ranges` 扫描约 137 万组 triple，CI 约 1s；非生产 SLA。
- GIL 下 dict 单操作原子性不等于业务层无竞态；本票不引入生产侧锁。

## 8. 发现但未处理的问题

| 问题 | 说明 | 已记录 |
|------|------|--------|
| BUG-073 tuple 键迁移 | 审计建议改 `tuple` 键；本票 test-only | 否 |
| `BUGS-OVERVIEW` / `P3-LOW` 仍标 BUG-073 待修复 | 测试已覆盖并发缺口；overview 未改 | 否 |
| RISK-002 `mic_in_flight` 并发 | TEST-GAPS §6 剩余项 | 否 |
| BUG-072 `invoke_on_main` 负载 | TEST-GAPS §6 剩余项 | 否 |

## 9. scoped diff 结论

本票改动路径：

- `tests/test_request_scheduling.py`
- `docs/bug-audit/TEST-GAPS.md`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-TEST-BUG-073-001-完成报告.md`

未触及 `app/**`、`main.py`、`web/static/**`、`community-site/**`、`supabase/**`。

## 10. 已更新的文档

- [x] [docs/bug-audit/TEST-GAPS.md](../../bug-audit/TEST-GAPS.md)
- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 本完成报告

## 11. 建议下一个工单

- TEST-GAPS §6 剩余：RISK-002 `mic_in_flight` 并发、`BUG-072` invoke_on_main 负载等。
- 若需闭合 BUG-073 生产键型：另开 `W-BUG-073-TUPLE-*` 触达 `main.py` / `app/main_helpers.py` / `RequestTimingService`。
