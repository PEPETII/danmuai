# Codex 完成报告

> 工单 ID：W-ERROR-REPORT-004  
> 完成时间：2026-06-01  
> 执行者：Cursor Agent

---

## 1. 修改摘要

修复 ISSUE-037：`/api/diagnostics` 快照增加只读 `config_context`（`active_model_id`、`provider_id`、`api_endpoint_host`、`api_mode`），并同步 Python/Web 诊断文本，便于 `error_reports.diagnostics_json` 运维关联配置。

## 2. 修改的文件

- `app/application/diagnostic_snapshot.py`
- `web/static/app.js`
- `tests/test_diagnostics.py`
- `tests/fakes.py`（`FakeConfig.get_custom_models`）

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `/api/status` 载荷结构：是（`config_context` 仅在 diagnostics）

## 4. 运行的命令

```bash
python -m pytest tests/test_diagnostics.py tests/test_ai_client.py tests/test_bundle_paths.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest | 通过 | 55 passed |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| Web 诊断页 / 错误反馈提交 | diagnostics 段含 model/provider/host | 待负责人 | — |

## 7. 风险与注意事项

- 仅暴露 endpoint 主机名，不含 path/Key。

## 8. 发现但未处理的问题

无。

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)

## 10. 建议下一个工单

无（P1 批次内其余项为 005/006）。
