# Codex 完成报告

> 工单 ID：W-CONFIG-ENDPOINT-001  
> 完成时间：2026-06-01  
> 执行者：Cursor Agent

---

## 1. 修改摘要

修复 ISSUE-039：`PUT /api/config` 保存全局 `api_endpoint` 时复用 `is_valid_endpoint`，无 `http://` / `https://` 的地址在持久化前抛出 `config.error_api_endpoint_invalid`，与自定义模型校验一致，避免 httpx「missing protocol」类错误进入运行态与 `error_reports`。

## 2. 修改的文件

- `app/model_selection.py`
- `app/translations.py`
- `tests/test_model_selection.py`

## 3. 未修改的关键区域

- 未修改 `web/`：是
- 未修改 `main.py`：是
- 未修改 `app/application/config_service.py`（校验在 `validate_web_config_patch` 统一入口）：是

## 4. 运行的命令

```bash
python -m pytest tests/test_bundle_paths.py tests/test_model_selection.py tests/test_supabase_static.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest | 通过 | 26 passed（含 `test_validate_web_config_patch_rejects_invalid_endpoint`） |
| boundary_guard | 未运行 | 未改主链路 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| Web 助手设置保存 `ark.cn-beijing...`（无协议） | Toast/错误，配置不落库 | 待负责人 | — |
| 保存 `https://ark...` | 成功 | 待负责人 | — |

## 7. 风险与注意事项

- 仅在校验路径包含 `api_endpoint` 时触发；空字符串仍由后续逻辑处理。

## 8. 发现但未处理的问题

无（本工单范围内）。

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)

## 10. 建议下一个工单

W-ERROR-REPORT-004（ISSUE-037 诊断上下文）或 W-ERROR-REPORT-005（ISSUE-038 HTTP 摘要）。
