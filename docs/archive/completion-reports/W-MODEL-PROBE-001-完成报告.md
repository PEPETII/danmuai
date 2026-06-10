# Codex 完成报告

> 工单 ID：W-MODEL-PROBE-001  
> 完成时间：2026-06-08  
> 执行者：Cursor Agent

---

## 1. 修改摘要

修复 bug-audit「问题1：API 与模型内部交互不一致」。自定义模型探测链路现与保存链路共用 `resolve_probe_credentials`（复用 `_normalize_payload` + `_resolve_api_key`），编辑弹窗内掩码 Key `********` 正确恢复为已存自定义模型 Key，不再误用全局 Key。`normalize_endpoint` 自动剥离 `/chat/completions` 与 `/responses` 后缀，避免 OpenRouter 等网关双重路径拼接。全局 `/api/probe` 行为未改动。

## 2. 修改的文件

- `app/model_providers.py`
- `app/web_api/custom_models.py`
- `app/web_api/routes.py`
- `web/static/modules/settings.js`
- `tests/test_model_providers.py`
- `tests/test_web_custom_models.py`
- `docs/工单列表/工单/W-MODEL-PROBE-001.md`
- `docs/工单列表.md`
- `docs/当前仓库状态.md`
- `docs/templates/Codex完成报告/W-MODEL-PROBE-001-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `app/main_*mixin.py`（含 `probe_api_connection` 全局掩码语义）：是
- 未修改 `app/ai_client_requests.py`（运行时 `resolve_request_credentials` 已正确）：是
- 未修改麦克风/读弹幕/TTS 相关模块：是
- 未修改 `app/application/config_service.py`：是

## 4. 运行的命令

```bash
python -m pytest tests/test_model_providers.py tests/test_web_custom_models.py tests/test_api_probe.py tests/test_ai_client.py -q
python -m pytest tests/ -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 定向 pytest | 通过 | 72 passed |
| 全量 pytest | 1 失败（范围外） | `test_live_overlay.py::test_broadcast_failure_does_not_break_enqueue` 与本次改动无关 |
| boundary_guard | 未运行 | 未触达主链路/运行态字段 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1. 新增自定义模型并保存 | 成功 | 单元测试覆盖 endpoint 归一化保存 | 是（测试） |
| 2. 编辑弹窗不修改 Key 点探测 | 使用自定义 Key | `resolve_probe_credentials` 测试覆盖 index+掩码 | 是（测试） |
| 3. endpoint 含 `/chat/completions` | 归一化为基础地址 | `normalize_endpoint` 测试覆盖 | 是（测试） |
| 4. 新建模型掩码 Key 探测 | 返回 api_key 错误 | 掩码无 existing 解析为空 Key | 是（测试） |
| 5. 全局 `/api/probe` 掩码 Key | 仍用全局 Key | 未改 `probe_api_connection` | 是（设计保持） |

## 7. 风险与注意事项

- `_resolve_api_key` 行为微调：新建条目提交 `********` 现解析为空（此前会透传掩码字符串），与校验失败一致，更安全。
- 自定义模型保存时 `mode: openai` 会归一化为 `openai-compatible`，与运行时一致。

## 8. 发现但未处理的问题

- 全量 pytest 中 `tests/test_live_overlay.py::test_broadcast_failure_does_not_break_enqueue` 失败，与本次工单无关，未修。

## 9. 已更新的文档

- `docs/工单列表/工单/W-MODEL-PROBE-001.md`
- `docs/工单列表.md`
- `docs/当前仓库状态.md`
- 本完成报告

## 10. 项目说明文件反查

已检查限制 / 边界入口文件、AGENTS.md、README.md 和相关项目说明文件，本次无需更新（endpoint 归一化为实现细节，现有文档已说明自定义模型 CRUD 与探测 API 存在）。
