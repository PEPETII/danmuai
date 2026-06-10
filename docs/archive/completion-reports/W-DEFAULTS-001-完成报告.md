# Codex 完成报告

> 工单 ID：W-DEFAULTS-001  
> 完成时间：2026-06-09  
> 执行者：Cursor Agent

---

## 1. 修改摘要

将首装 seed 与 Web「恢复默认」的视觉 API 预设改为自定义 OpenAI 兼容接口（`api_mode=openai`、空 endpoint/model）、温度 0.8；桌宠默认大小倍率改为 0.5。麦克风恢复默认仍使用火山方舟地址。对齐前端 `guessProviderIdFromEndpoint` 与 Python registry，避免首装时下拉显示「手动填写」。

## 2. 修改的文件

- `app/config_defaults.py`
- `app/ai_client_requests.py`
- `app/pet/pet_state.py`
- `app/application/config_service.py`
- `web/static/modules/settings-providers.js`
- `web/static/modules/app-pet-page.js`
- `web/static/partials/content-pages.html`
- `web/static/index.html`（rebuild）
- `tests/test_web_auth.py`
- `tests/test_config_store.py`
- `docs/工单列表/工单/W-DEFAULTS-001.md`
- `docs/工单列表.md`
- `docs/当前仓库状态.md`
- `docs/templates/Codex完成报告/W-DEFAULTS-001-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `app/main_*mixin.py`：是
- 未修改 `app/overlay.py`、`app/danmu_engine.py`：是
- 未修改 Boundary Guard 登记表：是
- 未修改麦克风默认 `mic_api_mode` / `mic_model`：是

## 4. 运行的命令

```bash
python web/static/build_index_html.py
python -m pytest tests/test_web_auth.py tests/test_config_defaults.py tests/test_config_store.py tests/test_model_providers.py -q
python -m pytest tests/test_web_console.py tests/test_pet_assets.py tests/test_bundle_paths.py tests/test_ai_client.py -q
python -m pytest tests/ -q  # 启动后长时间停在 ~56%，疑似既有慢测/挂起，未等待结束
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest（目标 + 相关） | 通过 | 77 + 87 = 164 passed |
| pytest（全量） | 未确认 | 进程在 ~56% 长时间无进展 |
| boundary_guard | 未运行 | 未触达主链路/编排 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 删除 config.db 后首装 | api_mode=openai、temperature=0.8、pet_scale=0.5 | 由单测 `test_first_run_seeds_config_defaults` 覆盖 | 是（单测） |
| Web 服务商预设 | 自定义 OpenAI 兼容接口 | 依赖 JS 修复 + 单测 export defaults | 待负责人 UI 确认 |
| 桌宠倍率 | 0.5 | HTML/JS/API fallback 已改 | 待负责人 UI 确认 |

## 7. 风险与注意事项

- 仅影响新装与「恢复默认」，已有 config.db 不变
- custom_openai 无目录模型，首装 model 为空属预期

## 8. 发现但未处理的问题

无

## 9. 已更新的文档

- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/工单列表/工单/W-DEFAULTS-001.md`

## 10. 项目说明文件检查

已检查限制 / 边界入口文件、AGENTS.md、README.md 和相关项目说明文件，本次无需更新（用户可见行为属默认值微调，无新 API/架构变更）。
