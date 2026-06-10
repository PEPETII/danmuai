# 工单 ID

W-PROVIDER-ADAPTER-001

# 工单标题

引入 Provider 适配层，收口多服务商差异，避免 ai_client.py 继续堆厂商特例

# 硬约束

本工单是「小步架构收口」，不是「大重构」。宁可少改，也不要动主链路。

# 背景

当前 DanmuAI 已具备多服务商雏形（`ProviderSpec` / `PROVIDERS`、`resolve_api_transport`、`guess_provider_from_endpoint`、`api_probe`），但厂商差异散落在 `ai_client.py` 与 `model_providers.py` 多份 host 表中。本工单学习 LiteLLM 的注册表 + 适配器思路，**不引入 litellm 库**。

# 目标

建立最小 Provider 适配层，使后续新增服务商主要改注册表 + capabilities + adapter + 测试。

# 允许修改区域

- `app/model_providers.py`
- `app/ai_client.py`
- `app/api_probe.py`
- `app/providers/`（新建）
- `tests/`
- `docs/architecture/provider-adapter.md`、工单/状态/完成报告

# 禁止修改区域

- `main.py` 主链路（`_on_screenshot_timer` / `_trigger_api_call` / `_consume_reply_queue`）
- Qt 线程模型、`app/overlay.py`、`app/web_api/*`（无必要不改）
- 不引入 `litellm`、不大拆 `ai_client.py`

# 验收标准

见计划文档与完成报告；`boundary_guard` + `test_model_providers` + `test_ai_client` + `test_api_probe` + `test_provider_adapters` 通过。

# 非目标

- 不修复 ISSUE-005（MiMo 探测无识图）
- 不接入大量新厂商
- 不改变用户配置字段语义
