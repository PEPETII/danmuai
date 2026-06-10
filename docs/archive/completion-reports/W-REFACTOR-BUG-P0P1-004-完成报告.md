# Codex 完成报告

> 工单 ID：W-REFACTOR-BUG-P0P1-004  
> 完成时间：2026-06-01  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

修复 **BUG-005**：`mic_audio_supported_for_config` / `model_supports_mic_audio` 不再仅依赖 endpoint host marker 推断 MiMo，改为在 OpenAI-compat transport 下以 `mimo-v2.5` 模型 ID 作为开麦能力锚点。自定义 MiMo proxy endpoint 不再被误判为 unsupported。同步在 `app/ai_client.py` 的 `_request_openai` 使用 `get_openai_adapter_for_model` / `get_capabilities_for_model`，使 probe gating、运行时请求体（`input_audio`）与 MiMo adapter 语义一致。豆包 Responses 开麦路径未改。

## 2. 修改的文件

- `app/model_providers.py`
- `app/ai_client.py`
- `tests/test_model_providers.py`
- `tests/test_mic_test_send.py`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-REFACTOR-BUG-P0P1-004-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `web/static/`：是
- 未修改 `community-site/`：是
- 未修改 `app/web_api/`、`app/web_console.py`：是
- 未修改 `app/mic_capture.py`、`app/danmu_read*.py`：是
- 未修改 `app/providers/`：是
- 未修改 `docs/refactor/**`：是

## 4. 运行的命令

```bash
python -m pytest tests/test_model_providers.py tests/test_mic_test_send.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest（工单指定子集） | 通过 | 30 passed |
| boundary_guard | 未运行 | 本票未触达 main 编排 / 新线程 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 自定义 MiMo endpoint/proxy + `mimo-v2.5` → mic test-send 不报 `unsupported_model` | 待负责人 | 待负责人 |
| 2 | 普通 OpenAI 兼容 endpoint + 非音频模型 → 仍被拦截 | 单元测试覆盖负例 | 是（自动化） |

## 7. 风险与注意事项

- `mimo-v2.5` 配在非 MiMo 的 OpenAI 兼容 endpoint 会被放行（工单目标行为）；真实 API 可能 4xx，非本票范围。
- `_stream_openai` 仍用 endpoint-only 选 adapter/caps 做 usage 归一化；与 `_request_openai` 请求体构建路径分离，对 openai 风格 usage 无功能影响。
- `app/providers/registry.py` host 推断未改；仅 mic/MiMo 请求语义经 model_id 旁路。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| — | 无 | — |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 本完成报告

## 10. 建议下一个工单

- `W-REFACTOR-BUG-P0P1-001`（BUG-001 首装 UI 引导）或 refactor 路线上下一项开放 P0 bug 票。
