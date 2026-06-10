# Codex 完成报告

> 工单 ID：W-SECURITY-001  
> 完成时间：2026-06-08  
> 执行者：Codex

---

## 1. 修改摘要

为 `/api/diagnostics` 和 `/api/diagnostics/events` 两个端点添加 Bearer Token 认证保护。之前这两个端点无需认证即可访问，虽然仅返回应用状态信息，但从安全最佳实践角度，所有 API 端点应统一认证机制。前端 SSE 连接已更新为通过 query 参数传递 Token。

## 2. 修改的文件

- `app/web_api/routes.py`
- `web/static/modules/diagnostics.js`
- `tests/test_diagnostics_snapshot.py`
- `tests/diagnostics_helpers.py`
- `docs/WEB_CONSOLE.md`

## 3. 未修改的关键区域

- 未修改 `app/application/diagnostic_snapshot.py`：是
- 未修改 `app/application/diagnostics_hub.py`：是
- 未修改 `main.py`：是
- 未修改 `web/static/` 中其他文件：是

## 4. 运行的命令

```bash
python -m pytest tests/test_diagnostics_snapshot.py -q
python scripts/boundary_guard.py
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest | 通过 | 11 passed |
| boundary_guard | 通过 | PASS |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 无 Token 访问 /api/diagnostics | 返回 401 | 需实机验证 | 待验证 |
| 有 Token 访问 /api/diagnostics | 返回 200 | 需实机验证 | 待验证 |
| SSE 连接带 Token | 正常接收事件 | 需实机验证 | 待验证 |

## 7. 风险与注意事项

- 前端错误报告功能依赖 `/api/diagnostics`，已确认 `apiFetch` 自动携带 Token
- SSE 端点使用 query 参数传递 Token（EventSource 不支持自定义 headers）
- 测试中使用 mock 的 `check_token` 函数，实际验证需在真实环境进行

## 8. 发现但未处理的问题

无

## 9. 已更新的文档

- [x] [docs/工单列表.md](../../工单列表.md)（状态改为已完成）
- [x] [docs/WEB_CONSOLE.md](../../WEB_CONSOLE.md)（标注需 Bearer Token）

## 10. 建议下一个工单

- W-SECURITY-002：WebSocket Token 传输方式改进
