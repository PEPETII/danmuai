# W-MODEL-CN-VISION-PROVIDERS-001 完成报告

## 1. 修改摘要

- 修复目录模型被当成保存白名单的问题：有 catalog 的平台现在允许手动输入未收录的新模型 ID，只保留“已知目录模型放到另一个已知平台”这类明确跨平台误配拦截。
- 修复完整模型配置档案已设为默认后，再保存助手设置会被“档案保留 ID”拦截的问题。
- 扩展中国/中国相关视觉模型目录：火山方舟、阿里云百炼、硅基流动、Z.AI/智谱。
- 新增 Z.AI / 智谱服务商预设，使用 OpenAI-compatible endpoint。
- 目录模型新增 `modality`、`supports_vision`、`main_flow_recommended`、`price.currency` 字段；前端价格提示按币种显示。

## 2. 修改的文件列表

- `E:/test/danmu/app/model_catalog.py`
- `E:/test/danmu/app/model_selection.py`
- `E:/test/danmu/app/model_providers.py`
- `E:/test/danmu/app/providers/capabilities.py`
- `E:/test/danmu/web/static/modules/settings-model-catalog.js`
- `E:/test/danmu/tests/test_model_catalog.py`
- `E:/test/danmu/tests/test_model_selection.py`
- `E:/test/danmu/tests/test_model_providers.py`
- `E:/test/danmu/tests/test_provider_adapters.py`
- `E:/test/danmu/tests/test_web_server.py`

## 3. 未修改的关键区域

- 未修改 `main.py`、视觉主链路、截图调度、回复队列、Overlay 渲染。
- 未修改 `app/ai_client.py`、`app/ai_client_requests.py` 的请求体生成。
- 未修改 `app/web_api/routes.py` 的路由注册和线程桥接。
- 未新增依赖、未修改锁文件、未执行 git commit / push。

## 4. 核验结论

### 已确认存在并修复

1. **目录模型被当作保存白名单**
   - 真实存在：`validate_global_model_selection()` 对有目录的平台强制 `model_id in catalog`。
   - 影响：火山方舟、百炼、硅基流动、MiMo 等平台无法手动输入新模型/接入点 ID。
   - 修复：改为只拦截“该模型 ID 已在其他 provider catalog 中明确出现”的跨平台误配；未知 freeform ID 允许保存。

2. **完整模型配置档案设为默认后，普通保存被拦截**
   - 真实存在：`validate_web_config_patch()` 即使识别到 active custom model，也继续调用全局模型校验。
   - 影响：用户通过“模型配置档案”设为默认后，再保存设置可能报“该模型 ID 已在模型配置档案中使用”。
   - 修复：active model 确认为完整自定义档案时跳过全局 endpoint/model 校验。

3. **目录模型缺少模态标注**
   - 真实存在：目录只返回价格和 mic 标记，无法表达“图片输入 + 文本输入 → 文本输出”。
   - 修复：目录 API 为每个模型返回 `modality`、`supports_vision`、`main_flow_recommended`。

4. **价格币种假设固定为人民币**
   - 真实存在：前端固定展示“元 / M tokens”。
   - 影响：Z.AI 等以 USD 标价的平台会误导用户。
   - 修复：`ModelPrice` 增加 `currency`，前端按 `CNY`/`USD` 显示。

### 已补充的视觉目录

- 火山方舟：新增 `doubao-seed-2-0-pro-260428`、`doubao-seed-1-6-vision-250615`。
- 阿里云百炼：新增 `qwen3-vl-plus`、`qwen3-vl-max`、`qwen3.7-plus`、`qwen3.6-plus`、`qwen3.5-omni-plus`。
- 硅基流动：新增 `Qwen/Qwen3-VL-235B-A22B-Instruct`、`zai-org/GLM-4.6V`。
- Z.AI / 智谱：新增 provider preset 和视觉目录 `glm-4.6v`、`glm-4.5v`。

### 未加入或无需修复

- DeepSeek、MiniMax、Moonshot/Kimi：当前按用户补充要求不加入，原因是本工单不需要纯文本平台；未确认适合截图主流程的模型不进入视觉默认推荐。
- OpenAI、Anthropic、Google、AWS、Groq、OpenRouter 等海外平台：明确不在本工单范围。

## 5. 运行的命令

- `python -m pytest tests/test_model_catalog.py tests/test_model_selection.py tests/test_model_providers.py tests/test_provider_adapters.py -q -x`
- `python -m pytest tests/test_web_server.py -q -x -k "model_catalog_api_payload or providers_excludes_deepseek or provider_rules"`
- `python -m pytest tests/test_web_auth.py -q -x -k "export_config_mismatched_model_still_loads or export_config_includes_catalog_display_name"`
- `python scripts/boundary_guard.py`

## 6. 构建/测试结果

- 模型目录/选择/provider 单测：`90 passed`
- Web catalog/provider 契约子集：`4 passed, 38 deselected`
- Web config 导出状态子集：`2 passed, 18 deselected`
- Boundary Guard：`PASS`

## 7. 手动验证步骤与结果

- 函数级复现已覆盖：
  - 火山方舟 endpoint + `ep-20260618-custom-vision` freeform ID 允许保存。
  - DashScope endpoint + Doubao catalog ID 仍被识别为跨平台误配并拒绝。
  - 完整模型配置档案作为 active default 时，普通配置保存不再被保留 ID 拦截。
- 未启动真实 `python main.py`；未使用真实 API Key 做外部模型调用。

## 8. 风险与注意事项

- 新增目录价格仅用于 UI 预估提示，不参与计费；上线前建议负责人用各平台官网价格页复核一次。
- 新增模型均标记为视觉主流程推荐；实际可用性仍依赖用户账号权限、区域、endpoint 与模型开通情况。
- `qwen3.5-omni-plus` 是多模态理解模型，但当前未声明 `supports_mic`，避免把百炼 Omni 误接到现有麦克风音频协议。

## 9. 已更新的文档

- `E:/test/danmu/.local-ai/workorders/当前仓库状态.md`
- `E:/test/danmu/reports/W-MODEL-CN-VISION-PROVIDERS-001-report.md`

## 10. 建议下一个工单

- 使用真实 API Key 对新增视觉目录逐个平台做 live probe，确认账号开通、endpoint、图像输入格式和返回解析。
