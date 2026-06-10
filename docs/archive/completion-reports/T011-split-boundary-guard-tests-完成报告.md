# Codex 完成报告

> 工单 ID：T011-split-boundary-guard-tests  
> 完成时间：2026-06-03  
> 执行者：Codex / GPT-5

---

## 1. 修改摘要

将超出测试文件硬警戒的 `tests/test_boundary_guard.py`（972 行）按规则域拆分为 4 个测试文件，并抽出共享的临时 git 仓库构造 helper。拆分只改变测试文件边界，不改变 `scripts/boundary_guard.py` 的规则实现和原有断言语义；同时同步更新当前入口文档里对旧测试文件名的引用。

## 2. 修改的文件

- `tests/boundary_guard_helpers.py`
- `tests/test_boundary_guard_web_rules.py`
- `tests/test_boundary_guard_runtime_rules.py`
- `tests/test_boundary_guard_request_rules.py`
- `tests/test_boundary_guard_diagnostics_rules.py`
- `tests/test_boundary_guard.py`（删除）
- `docs/BOUNDARY_GUARD.md`
- `docs/CONTRIBUTING_ARCHITECTURE.md`
- `docs/ai-project-context.md`
- `docs/architecture-governance/00-overview/CURRENT_MODULE_MAP.md`
- `docs/architecture-governance/01-rules/REFACTORING_RULES.md`
- `docs/architecture-governance/05-validation/BOUNDARY_GUARD_GUIDE.md`
- `docs/bug-audit/TEST-GAPS.md`
- `docs/refactor/REFACTOR-TASKS.md`
- `docs/refactor/TEST-MAPPING.md`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/T011-split-boundary-guard-tests-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `app/**`：是
- 未修改 `main.py`：是
- 未修改 `web/static/**`：是
- 未修改 `community-site/**`：是
- 未修改 `supabase/**`：是
- 未修改 `scripts/boundary_guard.py` 规则实现：是

## 4. 运行的命令

```bash
python -m pytest tests/test_boundary_guard_web_rules.py tests/test_boundary_guard_runtime_rules.py tests/test_boundary_guard_request_rules.py tests/test_boundary_guard_diagnostics_rules.py -q
python -m ruff check tests/boundary_guard_helpers.py tests/test_boundary_guard_web_rules.py tests/test_boundary_guard_runtime_rules.py tests/test_boundary_guard_request_rules.py tests/test_boundary_guard_diagnostics_rules.py
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest | 通过 | `33 passed` |
| ruff | 通过 | 新增/拆分测试文件 `All checks passed!` |
| boundary_guard CLI | 未运行 | 本票未修改 guard 规则实现，仅拆测试文件 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1. 检查拆分后文件体量 | 每个测试文件不再超过 800 行 | 181 / 243 / 295 / 117 行，helper 159 行 | 是 |
| 2. 运行 Boundary Guard pytest 套件 | 所有旧断言域仍通过 | `33 passed` | 是 |
| 3. 检查当前入口文档 | 不再引用已删除的 `tests/test_boundary_guard.py` | 已同步到 4 文件套件 | 是 |

## 7. 风险与注意事项

- 历史完成报告、历史审计快照仍保留 `tests/test_boundary_guard.py` 的旧文件名，这属于历史事实，不应改写。
- 本票只做测试文件治理，没有补改 `scripts/boundary_guard.py` 或业务代码；若后续继续拆 `tests/test_diagnostics.py`，应沿用“按规则域/行为域”拆分，而不是按行数硬切。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| 无 | 本票未新增范围外问题 | 是 |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/BOUNDARY_GUARD.md](../../BOUNDARY_GUARD.md)
- [x] [docs/CONTRIBUTING_ARCHITECTURE.md](../../CONTRIBUTING_ARCHITECTURE.md)
- [x] [docs/ai-project-context.md](../../ai-project-context.md)
- [x] [docs/refactor/REFACTOR-TASKS.md](../../refactor/REFACTOR-TASKS.md)
- [x] [docs/refactor/TEST-MAPPING.md](../../refactor/TEST-MAPPING.md)

## 10. 建议下一个工单

- 继续 Phase 4，可优先治理 `tests/test_diagnostics.py`（711 行）或超 1000 行的 bug 审计文档，但都应先登记为独立小票。
