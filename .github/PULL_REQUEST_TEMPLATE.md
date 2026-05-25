## 变更说明

简要描述本 PR 的目的和改动内容。

## 关联 Issue

Closes #

## 变更类型

- [ ] Bug 修复
- [ ] 新功能
- [ ] 文档更新
- [ ] 重构

## 自检清单

- [ ] 已运行 `python -m pytest tests/ -q`，测试通过
- [ ] 未引入 API Key、日志、截图等敏感文件
- [ ] **Web 默认路径**：`python -m pytest tests/test_web_console.py tests/test_web_persona_api.py tests/test_web_custom_models.py tests/test_image_compress.py tests/test_ui_mode.py -q`（若触及 Web/API/UI）
- [ ] 如涉及 Web UI 变更，已对照 `prototype/Qwen_html_*.html`
- [ ] 已更新 `README.md` 或 `docs/CHANGELOG.md`（如需要）；若面向国际贡献者，可同步 `README.en.md`

## 截图/录屏

如涉及 UI 变更，请附截图。请勿包含敏感内容。
