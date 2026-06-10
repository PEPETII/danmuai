# Codex 完成报告

> 工单 ID：T005-clean-api-boundary  
> 完成时间：2026-06-03  
> 执行者：Codex / IDE Agent

---

## 1. 修改摘要

将 `app/web_api/routes.py` 中的三个内联 helper（`_danmu()`、`_read_api()`、`_mic_test_response()`）下沉到对应的领域模块，保持 `routes.py` 为薄适配层。`_invoke_main()` 保持原位，因为它是 `bridge.invoke_on_main` 的薄包装，属于路由适配职责。

## 2. 修改的文件

- `app/web_api/routes.py`
- `app/web_api/danmu_read.py`
- `app/web_api/mic_test.py`（新建）
- `tests/test_web_console.py`

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `app/danmu_engine.py`：是
- 未修改 `app/overlay.py`：是
- 未修改 `app/ai_client.py`：是
- 未顺手重构无关代码：是

## 4. 运行的命令

```bash
python -m pytest tests/test_web_console.py tests/test_web_persona_api.py tests/test_web_custom_models.py -q
python scripts/boundary_guard.py
ruff check app/web_api/routes.py app/web_api/danmu_read.py app/web_api/mic_test.py tests/test_web_console.py
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest | 通过 | 96 passed |
| boundary_guard | 通过 | PASS |
| ruff | 通过 | All checks passed! |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1. 打开 `routes.py`，搜索 `def _` | 无内联 helper | 仅剩 `_invoke_main` | 是 |
| 2. 运行 Web 测试 | 全部通过 | 96 passed | 是 |

## 7. 风险与注意事项

- 低风险：仅 helper 移动，不影响业务逻辑。
- `tests/test_web_console.py` 中的 mic test 断言已同步更新，以匹配新的 `invoke_on_main` 调用签名（传入 `run_mic_test` 函数对象和 `bridge.danmu_app` 实例，而非直接传入 `bridge.danmu_app.run_mic_test`）。

## 8. 发现但未处理的问题

无。

## 9. 已更新的文档

- [x] `docs/当前仓库状态.md`
- [x] `docs/templates/Codex完成报告/T005-clean-api-boundary-完成报告.md`

## 10. 建议下一个工单

无。
