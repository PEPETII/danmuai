# Contributing

## 开发原则

- 默认 UI 为 **Web 控制台**（`web/static/` + `app/web_console.py` + `app/web_api/`），PyQt6 仅用于 Overlay/托盘。
- 优先修复稳定性、隐私和发布质量问题，再考虑新功能。
- 修改 Web UI 前对照 [`prototype/Qwen_html_20260524_481u8vlmv.html`](prototype/Qwen_html_20260524_481u8vlmv.html) 与 `web/static/warm-tokens.css`。

## 本地开发

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
python main.py
```

配置目录默认为 `%APPDATA%/DanmuAI/`。在非 Windows 且未设置 `APPDATA` 时，会落在当前工作目录下的 `./DanmuAI/`。

## 提交前检查

本地 **不要** 跑全量 `python -m pytest tests/`：套件 700+ 条，内存占用高，易导致机器卡顿。请按改动范围 **分批** 执行（每批 `-q -x`）；全量仅 CI 或资源充足的维护者环境执行。细则见 `.local-ai/prompts/IDE_AGENT_RULES.md` §10。

```bash
pip install -r requirements-dev.txt
ruff check app main.py tests scripts
# 批次 1（失败即停）
python -m pytest tests/test_reply_parser.py tests/test_p0_main_flow.py tests/test_danmu_engine.py tests/test_config_store.py tests/test_ai_client.py -q -x
# 批次 2 — 若改动涉及 Web / UI
python -m pytest tests/test_web_console.py tests/test_web_persona_api.py tests/test_web_custom_models.py tests/test_image_compress.py tests/test_ui_mode.py -q -x
# 触达主链路 / Web API 时
python scripts/boundary_guard.py
```

与改动相关的其他 `tests/test_*.py` 请单独成批追加；**禁止**无文件参数的 `pytest` / `python -m pytest tests/`。

请遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 提交规范

- 不要提交 API Key、日志、截图、`%APPDATA%/DanmuAI/` 下的本地数据库或 `.key` 文件。
- 不要把调试截图、缓存目录、`.coverage`、`__pycache__`、`.pytest_cache` 带入版本库。
- 新功能或行为变化需要同步更新 `README.md`、`docs/WEB_CONSOLE.md`（若涉及 Web API/UI）和 `docs/CHANGELOG.md`。
- 修改文档时，请同步更新 `docs/CHANGELOG.md` 与相关 docs 页面。

## Issue 与 PR

- Bug 报告请附最小复现步骤、实际行为、期望行为和日志摘要。
- 涉及隐私、凭据或安全边界的问题，请不要公开贴出原始截图和密钥，改走 [SECURITY.md](SECURITY.md) 中的私下反馈流程。
