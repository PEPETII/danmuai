# Codex 完成报告

> 工单 ID：W-MIC-AUDIT-002  
> 完成时间：2026-06-08  
> 执行者：Cursor Agent

---

## 1. 修改摘要

修复 bug-audit「问题 2：麦克风模式」。统一 `model_supports_mic_audio` 能力门控（豆包启发式 + catalog + `ProviderCapabilities` + 自定义模型 `supportsMic` 声明）；不支持时返回「未声明 mic_audio 支持」标准文案；麦克风测试录音改用 `QEventLoop` 等待避免冻结主线程；`MicService` 补齐 `try_snapshot_pcm_ms` 门面；Web 麦克风标签增加开麦凭据来源 banner 与自定义模型「支持麦克风」勾选。

## 2. 修改的文件

- `app/model_providers.py`
- `app/model_catalog.py`
- `app/mic_service.py`
- `app/mic_orchestrator.py`
- `app/mic_test.py`
- `app/mic_test_send.py`
- `app/ai_client_requests.py`
- `app/web_api/custom_models.py`
- `web/static/modules/settings.js`
- `web/static/modules/settings-core.js`
- `web/static/modules/settings-custom-models.js`
- `web/static/modules/settings-model-catalog.js`
- `web/static/partials/settings.html`
- `web/static/partials/modals.html`
- `web/static/index.html`（经 `build_index_html.py` 生成）
- `tests/test_model_providers.py`
- `tests/test_model_catalog.py`
- `tests/test_mic_test_send.py`
- `tests/test_mic_test.py`
- `tests/test_web_custom_models.py`
- `docs/工单列表/工单/W-MIC-AUDIT-002.md`
- `docs/工单列表.md`
- `docs/当前仓库状态.md`
- `docs/WEB_CONSOLE.md`
- `docs/templates/Codex完成报告/W-MIC-AUDIT-002-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `app/main_*mixin.py`：是
- 未修改 `app/overlay.py`、`app/danmu_engine.py`：是
- 未修改读弹幕/TTS 模块：是
- 未改编排主链路顺序：是

## 4. 运行的命令

```bash
python web/static/build_index_html.py
python -m pytest tests/test_model_providers.py tests/test_model_catalog.py tests/test_mic_test_send.py tests/test_mic_mode.py tests/test_mic_test.py tests/test_web_custom_models.py -q
python -m pytest tests/ -q
python scripts/boundary_guard.py
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 定向 pytest | 通过 | 79 passed（含新增 mic/catalog 回归） |
| 全量 pytest | 1030 passed，2 failed（范围外） | `test_danmu_tts`、`test_live_overlay` 既有失败 |
| boundary_guard | PASS | |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1. 豆包 + 与识图相同 + 开麦 | mic insert 可触发 | 单元/门控测试覆盖 | 是（测试） |
| 2. OpenRouter 自定义模型 supportsMic | 未勾选拦截；勾选可 probe | `test_send_mic_probe_allows_declared_custom_openai` | 是（测试） |
| 3. 测试麦克风等待 | 主线程 QTimer 可触发 | `test_capture_mic_sample_does_not_block_main_thread` | 是（测试） |
| 4. 独立 mic 配置 banner | 显示独立来源 | DOM + `updateMicActiveSourceBanner` 已接线 | 待负责人 UI 点验 |

## 7. 风险与注意事项

- OpenRouter 等网关勾选 `supportsMic` 后仅消除本地拦截；上游是否真支持 `input_audio` 仍取决于模型与网关。
- 豆包路径仍由 `_mic_audio_supported` 前置 gate，行为与改前一致。

## 8. 发现但未处理的问题

- 全量 pytest 中 `test_danmu_tts::test_playback_busy_flag`、`test_live_overlay::test_broadcast_failure_does_not_break_enqueue` 仍失败（范围外，未在本工单修复）。

## 9. 已更新的文档

- `docs/工单列表.md`、`docs/工单列表/工单/W-MIC-AUDIT-002.md`
- `docs/当前仓库状态.md`
- `docs/WEB_CONSOLE.md`（custom-models `supportsMic` 字段）

## 10. 建议下一个工单

- bug-audit 问题 3：读弹幕/TTS 模型误配提示与门控（单独工单）
