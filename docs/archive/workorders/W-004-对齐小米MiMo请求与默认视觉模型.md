# W-004：对齐小米 MiMo OpenAI 请求并修正默认视觉模型

## 背景

小米 MiMo（`mimo-v2-omni` / `mimo-v2.5`）在 Web 切换预设后默认选最便宜项 `mimo-v2-omni`，与 README 推荐的截图模型 `mimo-v2.5` 不一致；OpenAI 兼容请求体与官方文档（`max_completion_tokens`、图先文后、`thinking: disabled`）存在偏差，可能导致「AI 返回为空」。

## 目标

- MiMo endpoint 请求对齐官方格式；默认视觉模型为 `mimo-v2.5`。
- 流式仅 reasoning、无正文时打 `reason=mimo_reasoning_only` 日志。

## 允许修改的区域

- `app/ai_client.py`、`app/model_catalog.py`、`app/api_probe.py`
- `tests/test_ai_client.py`、`tests/test_model_catalog.py`
- `docs/工单列表.md`、`docs/当前仓库状态.md`、`docs/已知问题与后续事项.md`

## 禁止修改的区域

- `main.py`、`web/static/`、`app/web_api/`、`app/overlay.py`、`requirements.txt`

## 验收标准

- [x] `pytest tests/test_ai_client.py tests/test_model_catalog.py -q` 通过
- [x] `pytest tests/ -q` 全量通过
- [ ] 手动：MiMo + `mimo-v2.5` + 有效 Key → 至少一次 AI 弹幕入屏

## 手动验证步骤

1. Web → 小米 MiMo → 填 Key → 确认模型 `mimo-v2.5` → 保存。
2. `python main.py` → 开始弹幕 → 无连续「AI 返回为空」。
3. `python -m pytest tests/ -q`
