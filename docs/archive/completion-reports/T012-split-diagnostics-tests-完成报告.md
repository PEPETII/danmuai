# Codex 完成报告

> 工单 ID：T012-split-diagnostics-tests  
> 完成时间：2026-06-03  
> 执行者：Codex

---

## 1. 修改摘要

本票继续执行第二轮架构合理化拆分的 Phase 4 测试体量治理，只处理超阈值的 `tests/test_diagnostics.py`。我将原来的 711 行单文件按行为域拆成快照/API、SSE 端点、DiagnosticsHub 三个测试文件，并抽出共享构造与 SSE 读取 helper；断言语义、`skip` 策略和被测业务代码都保持不变。

## 2. 修改的文件

- `tests/diagnostics_helpers.py`
- `tests/test_diagnostics_snapshot.py`
- `tests/test_diagnostics_sse.py`
- `tests/test_diagnostics_hub.py`
- `tests/test_diagnostics.py`（删除）
- `docs/refactor/TEST-MAPPING.md`
- `docs/bug-audit/TEST-GAPS.md`
- `docs/architecture-governance/00-overview/CURRENT_MODULE_MAP.md`
- `docs/architecture-governance/05-validation/RELEASE_CHECKLIST.md`
- `docs/ai-project-context.md`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/T012-split-diagnostics-tests-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `app/`：是
- 未修改 `web/`：是
- 未修改 `main.py`：是
- 其他：未修改 `community-site/**`、`supabase/**`、`scripts/**`

## 4. 运行的命令

```bash
python -m pytest tests/test_diagnostics_snapshot.py tests/test_diagnostics_sse.py tests/test_diagnostics_hub.py -q
python -m pytest tests/test_diagnostics_snapshot.py tests/test_diagnostics_sse.py tests/test_diagnostics_hub.py tests/test_request_scheduling.py -q
python -m ruff check tests/diagnostics_helpers.py tests/test_diagnostics_snapshot.py tests/test_diagnostics_sse.py tests/test_diagnostics_hub.py
python scripts/boundary_guard.py
python -m ruff check app main.py tests scripts
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest | 通过 | 定向 diagnostics：`13 passed, 4 skipped`；加 `tests/test_request_scheduling.py` 联跑：`28 passed, 4 skipped` |
| boundary_guard | 通过 | `Boundary Guard: PASS` |
| ruff | 部分通过 | 新增/拆分测试文件通过；全仓 `ruff check app main.py tests scripts` 仍有 2 个范围外既有问题（`app/region_selector.py` 未使用 import、`scripts/rebalance_t008_tests2.py` import 排序） |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 运行拆分后的 diagnostics 测试套件 | `13 passed, 4 skipped` | 是 |
| 2 | 检查拆分后单文件体量回落到治理阈值内 | `314 / 234 / 105 / 68` 行 | 是 |
| 3 | 检查当前入口文档不再把 `tests/test_diagnostics.py` 当成现行套件 | 已同步到三文件套件 | 是 |

## 7. 风险与注意事项

- 本票只治理测试文件体量，没有改业务代码；如果后续 diagnostics 行为继续扩张，应优先往现有三类文件内增量落点，而不是重新堆回单文件。
- SSE 相关 4 个用例仍保持 `skip`，因为 `Sync TestClient` 对无限 SSE 的阻塞限制没有变化；这和拆分前一致。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| 无 | 无 | 是 |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/refactor/TEST-MAPPING.md](../../refactor/TEST-MAPPING.md)
- [x] [docs/bug-audit/TEST-GAPS.md](../../bug-audit/TEST-GAPS.md)
- [x] [docs/ai-project-context.md](../../ai-project-context.md)
- [x] [docs/architecture-governance/00-overview/CURRENT_MODULE_MAP.md](../../architecture-governance/00-overview/CURRENT_MODULE_MAP.md)
- [x] [docs/architecture-governance/05-validation/RELEASE_CHECKLIST.md](../../architecture-governance/05-validation/RELEASE_CHECKLIST.md)

## 10. 建议下一个工单

- 继续 Phase 4，可优先治理 `app/webview_shell.py`（703 行）或 `docs/bug-audit/P3-LOW.md`（1244 行），但都应先登记为独立小票。
