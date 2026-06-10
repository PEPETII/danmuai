# W-021：修复测试连接非流式请求误带 stream_options（百炼 400）

## 工单 ID

W-021

## 工单标题

修复测试连接非流式请求误带 stream_options（百炼 400）

## 背景

W-PROVIDER-ADAPTER-001 后 `api_probe` 的 OpenAI 路径经 `DefaultOpenAIAdapter.patch_probe_body` 打补丁。百炼/DashScope（`capabilities` 中 `stream_usage_in_final_chunk=True`）会在**非流式**探测体上仍注入 `stream_options.include_usage`，上游 compatible-mode 常返回 HTTP 400。主链路 `_request_openai` 为 `stream: true`，故出现「测试连接失败、弹幕仍可能正常」的误导。

## 目标

- 百炼内置模型 + 有效 Key：Web「测试连接」返回 `ok: true`
- 主链路流式 OpenAI 请求仍带 `stream_options.include_usage`（DashScope usage 统计）

## 依赖项

W-PROVIDER-ADAPTER-001（已完成）

## 允许修改的区域

- `app/providers/adapters/default_openai.py`
- `tests/test_provider_adapters.py`
- `tests/test_api_probe.py`
- `docs/architecture/provider-adapter.md`
- `docs/工单列表.md`
- `docs/当前仓库状态.md`
- `docs/已知问题与后续事项.md`
- `docs/templates/已知问题记录/ISSUE-015-api_probe非流式stream_options.md`
- `docs/templates/Codex完成报告/W-021-完成报告.md`

## 禁止修改的区域

- `main.py`
- `web/static/`
- `app/ai_client.py`（主链路 HTTP/SSE）
- `requirements.txt`、锁文件

## 需求

1. `patch_openai_chat_body` 仅在 `data.get("stream")` 为真时设置 `stream_options`
2. 单测覆盖 dashscope probe 体无 `stream_options`、流式体仍有
3. `test_api_probe` 回归 dashscope endpoint 请求 JSON
4. 登记 ISSUE-015 并标为 W-021 已修复
5. 输出完成报告并更新工单列表、当前仓库状态

## 非目标

- ISSUE-005（MiMo 探测无识图）
- 将探测改为流式
- 修改百炼 `capabilities` 默认值

## 验收标准

- [x] pytest 新增/更新用例通过
- [x] `patch_probe_body` + `stream: false` + dashscope：无 `stream_options`
- [x] `patch_openai_chat_body` + `stream: true`：仍有 `stream_options`
- [x] 现有 `test_ai_client` 流式用例仍绿

## 手动验证步骤

1. Web 助手设置 → 阿里云百炼预设 + 目录模型 + 有效 Key → 测试连接 → 成功 Toast
2. （可选）开始弹幕后确认仍有 AI 弹幕

## 风险点

- 流式主链路行为不变（已有 `test_ai_client` 覆盖）
- `openai_compatible_request_extensions` 无 `stream` 键时不再误加 `stream_options`（更符合 shim 语义）

## 完成后必须更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)

## Codex 完成报告要求

见 [W-021-完成报告.md](../Codex完成报告/W-021-完成报告.md)
