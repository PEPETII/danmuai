# W-TEST-BUG-067-001 完成报告

## 1. 修改摘要

闭合 BUG-067 与 [TEST-GAPS.md](../../bug-audit/TEST-GAPS.md) §4：运行概览新增「显示/隐藏诊断面板」按钮；`setDiagnosticsPanelVisible` 切换 `#diagnosticsPanel` 的 `hidden`/`aria-hidden` 并触发既有 SSE 可见性门控；新增静态符号回归测试。

## 2. 修改的文件列表

- `E:/test/danmu/web/static/index.html`
- `E:/test/danmu/web/static/modules/diagnostics.js`
- `E:/test/danmu/tests/test_bundle_paths.py`
- `E:/test/danmu/docs/bug-audit/TEST-GAPS.md`
- `E:/test/danmu/docs/当前仓库状态.md`
- `E:/test/danmu/docs/工单列表.md`
- `E:/test/danmu/docs/templates/Codex完成报告/W-TEST-BUG-067-001-完成报告.md`

## 3. 未修改的关键区域

- `E:/test/danmu/main.py`、`app/**`、`app/web_api/**`：是
- `E:/test/danmu/community-site/**`、`supabase/**`：是
- `E:/test/danmu/web/static/app.js`：是（仍仅 `initDiagnosticsPanel` 导入）
- 主链路 / Overlay / AI：是

## 4. 运行的命令

```bash
python -m pytest tests/test_bundle_paths.py tests/test_diagnostics.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest `tests/test_bundle_paths.py` + `tests/test_diagnostics.py` | 通过 | 全文件 **通过**（含新用例与既有 panel/SSE 测试） |
| boundary_guard | 未跑 | 仅 `web/static` + 测试 |

## 6. 手动验证步骤与结果

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 运行概览默认不显示诊断指标卡片 | 待负责人 | 待负责人 |
| 2 | 点「显示诊断面板」→ 卡片出现且数据更新 | 待负责人 | 待负责人 |
| 3 | 点「隐藏诊断面板」→ 卡片隐藏；无 2.5s 轮询 `/api/diagnostics` | 待负责人 | 待负责人 |

## 7. 风险与注意事项

- `setDiagnosticsPanelVisible` 与 `MutationObserver` 可能双触发 `handlePanelVisibilityChange`；`connectDiagnosticsSSE` 有单例守卫，风险低。
- `docs/WEB_CONSOLE.md` L43「默认隐藏」与实现一致；`DOCS-CODE-MISMATCH-008` 中「始终轮询」描述已过时（SSE 由 `W-DIAGNOSTICS-SSE-001` 替代），未在本票改 audit 总表。

## 8. 发现但未处理的问题

| 问题 | 说明 | 已记录 |
|------|------|--------|
| `BUGS-OVERVIEW.md` / `P3-LOW.md` 仍标 BUG-067 待修复 | 本票未改审计总表 | 否 |
| `DOCS-CODE-MISMATCH-008` 轮询描述过时 | 待单独文档票 | 否 |
| TEST-GAPS §4 其他缺口（`startConfigNotices`、panel 切换等） | 非本票 | 否 |

## 9. 已更新的文档

- [x] `E:/test/danmu/docs/bug-audit/TEST-GAPS.md`
- [x] `E:/test/danmu/docs/当前仓库状态.md`
- [x] `E:/test/danmu/docs/工单列表.md`
- [x] 本完成报告

## 10. scoped diff 结论

本票限于 `web/static/index.html`、`web/static/modules/diagnostics.js`、`tests/test_bundle_paths.py` 与列出的 docs；未触达 Python 后端与 Supabase。
