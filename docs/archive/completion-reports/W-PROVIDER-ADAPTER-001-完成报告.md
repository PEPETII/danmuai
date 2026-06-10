# Codex 完成报告

> 工单 ID：W-PROVIDER-ADAPTER-001  
> 完成时间：2026-05-29  
> 执行者：Cursor Agent

---

## 1. 现状审计结论（开工前 / 本工单依据）

| 区域 | 文件 | 函数 / 符号 |
|------|------|-------------|
| 预设与表单 | `app/model_providers.py` | `ProviderSpec`, `PROVIDERS`, `apply_provider_to_form` |
| 三份 host 数据（已合并） | `app/model_providers.py` | `_ENDPOINT_GUESSES`, `_OPENAI_HOST_MARKERS`, `_DOUBAO_HOST_MARKERS` |
| Transport | `app/model_providers.py` | `resolve_api_transport`, `guess_provider_from_endpoint` |
| 开麦启发式 | `app/model_providers.py` | `model_likely_supports_mic_audio` |
| MiMo / OpenAI-compat 特例（已迁 adapter） | `app/ai_client.py` | `is_mimo_endpoint`, `build_openai_vision_user_content`, `openai_compatible_request_extensions`, `_request_openai` 分支 |
| Usage | `app/ai_client.py` | `parse_stream_usage`, `_stream_openai` |
| 豆包 Responses | `app/ai_client.py` | `_request_doubao`, `_stream_doubao` |
| 探测 | `app/api_probe.py` | `probe_connection`, `_probe_openai`, `_probe_doubao` |
| 模型目录（未动） | `app/model_catalog.py` | 定价与默认模型 |

适合 **ProviderCapabilities**：transport、thinking、image 顺序、stream_usage、max_tokens 字段、usage 风格。  
适合 **ProviderAdapter**：OpenAI body 补丁、vision content、probe 补丁。  
**暂留**：httpx 池、SSE 循环、`main.py` 主链路、豆包 Responses 体。

## 2. 最小设计方案

- **Registry**：`app/providers/registry.py` 的 `HOST_ENTRIES` 从 `PROVIDERS[].default_endpoint` 派生；`guess_provider_from_endpoint` / `resolve_api_transport` 单表匹配。
- **Capabilities**：`app/providers/capabilities.py` 的 `ProviderCapabilities` + `get_capabilities` / `get_capabilities_for_endpoint`。
- **Adapters**：`DefaultOpenAIAdapter`、`MimoOpenAIAdapter`；`get_openai_adapter(endpoint, api_mode)` 选择实现。
- **兼容 shim**：`ai_client.is_mimo_endpoint` 等仍可用，内部委托 registry/adapter。

## 3. 修改的文件列表

- `app/providers/`（新建：`__init__.py`, `constants.py`, `capabilities.py`, `registry.py`, `adapters/*`）
- `app/model_providers.py` — 删除三份 host 元组，委托 registry
- `app/ai_client.py` — OpenAI 路径委托 adapter；`THINKING_DISABLED` 迁至 `providers.constants`
- `app/api_probe.py` — `_probe_openai` 委托 adapter
- `tests/test_provider_adapters.py`（新建）
- `docs/architecture/provider-adapter.md`（新建）
- `docs/templates/工单/W-PROVIDER-ADAPTER-001-引入Provider适配层.md`
- `docs/templates/Codex完成报告/W-PROVIDER-ADAPTER-001-完成报告.md`
- `docs/工单列表.md`
- `docs/当前仓库状态.md`

## 4. 行为兼容性说明

| 场景 | 结果 |
|------|------|
| 火山方舟 Ark | `resolve_api_transport` → `doubao`，`/responses` 不变 |
| 百炼 / 硅基等已知 host | → `openai` + `stream_options.include_usage` |
| MiMo | `thinking: disabled`、image-first、`max_completion_tokens`、无 `stream_options` |
| 自定义未知 host | 由 `api_mode` 决定 transport；默认 OpenAI adapter |
| 兼容函数 | `build_openai_vision_user_content` / `openai_compatible_request_extensions` 仍导出 |

## 5. 测试结果

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_model_providers.py tests/test_ai_client.py tests/test_api_probe.py tests/test_provider_adapters.py -q
python -m pytest tests/ -q
```

| 检查项 | 结果 |
|--------|------|
| boundary_guard | PASS |
| 工单相关 pytest（58） | 58 passed |
| 全量 pytest | **651 passed**（2026-05-29） |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 硅基流动截图弹幕 | 正常出字 | 未在真实环境复验 | 待负责人 |
| MiMo 截图弹幕 | 正常出字（W-004 行为保持） | 未在真实环境复验 | 待负责人 |
| Web 自定义模型探测 | 成功/失败信息正常 | 未在真实环境复验 | 待负责人 |

## 7. 风险与回滚

- **风险**：未知 OpenAI-compat 服务商若需 `thinking` 字段，默认 adapter 不会发送（与改前一致）。
- **回滚**：revert `app/providers/` 及 `model_providers` / `ai_client` / `api_probe` 本 PR；或临时恢复 `is_mimo_endpoint` 硬编码（不推荐）。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| ISSUE-005 | MiMo 连通性探测不含识图 | 是（既有记录，本工单非目标） |

## 9. 已更新的文档

- [x] `docs/当前仓库状态.md`
- [x] `docs/工单列表.md`
- [x] `docs/architecture/provider-adapter.md`

## 10. 建议下一个工单

- 按服务商拆「更多 AI 服务端兼容测试」小工单（ROADMAP）
- ISSUE-005：MiMo 探测增加最小 vision ping（单独工单）
