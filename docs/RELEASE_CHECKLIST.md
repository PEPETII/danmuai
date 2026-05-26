# Release Checklist

发布新版本前的检查清单。

## 代码与测试

- [ ] 所有测试通过：`python -m pytest tests/ -q`
- [ ] `ruff check app main.py tests scripts` 通过
- [ ] 无硬编码的 API Key、Token 或敏感路径

## 文档

- [ ] `README.md` 中的环境要求、已知限制与代码一致
- [ ] `docs/CHANGELOG.md` 已更新本次变更
- [ ] `docs/ARCHITECTURE.md` 与实际代码结构一致（含场景指纹、`live_freshness` 时序）
- [ ] `docs/PRIVACY.md`、`SECURITY.md`、`docs/OPEN_SOURCE_AUDIT.md` 与 `screen_index` 截图行为一致
- [ ] `THIRD_PARTY_NOTICES.md` 与 `requirements.txt` 一致

## Web 控制台（默认）

- [ ] `python main.py` 可打开 `http://127.0.0.1:18765`（pywebview 或 `--web-browser`）
- [ ] Web 回归：`python -m pytest tests/test_web_console.py tests/test_web_persona_api.py tests/test_web_custom_models.py tests/test_image_compress.py tests/test_ui_mode.py tests/test_deprecated_launch_flags.py -q`
- [ ] Web 视觉对照：`prototype/Qwen_html_20260524_481u8vlmv.html` 与 `web/static/warm-tokens.css` 无严重偏差（若本次改 UI）

## Overlay / 弹幕核心（若本次改动相关）

- [ ] `python -m pytest tests/test_overlay_render.py tests/test_danmu_engine.py tests/test_danmu_motion.py -q`

## 许可证与合规

- [ ] `LICENSE` 文件正确
- [ ] 新增依赖已记录在 `THIRD_PARTY_NOTICES.md` 和 `docs/OPEN_SOURCE_AUDIT.md`
- [ ] 无许可证冲突

## 安全与隐私

- [ ] `.gitignore` 覆盖所有本地调试产物
- [ ] `git status` 中无日志、缓存、数据库、密钥文件
- [ ] 日志脱敏规则覆盖 API Key、Token、base64 图片

## Windows exe（可选）

- [ ] 按 [PACKAGING_WINDOWS.md](PACKAGING_WINDOWS.md) 在干净环境构建成功
- [ ] `.\scripts\build_exe.ps1` 成功，产物为 `dist\DanmuAI\` 整目录
- [ ] 在未装 Python 的机器上启动 `DanmuAI.exe`，pywebview 控制台与 Overlay 正常
- [ ] `%APPDATA%\DanmuAI\startup.log` 无 uvicorn/pywebview 崩溃栈
- [ ] WebView2 缺失时文档说明安装 Runtime 或 `--web-browser` 回退

## macOS app（可选）

- [ ] 按 [PACKAGING_MACOS.md](PACKAGING_MACOS.md) 在 macOS 构建成功
- [ ] `./scripts/build_macos.sh` 成功，产物为 `dist/DanmuAI.app`
- [ ] 首次启动能打开 pywebview Cocoa 控制台或 `--web-browser` 回退
- [ ] 授权屏幕录制后截图和 Overlay 正常；未授权时日志给出 macOS 权限提示
- [ ] `~/Library/Application Support/DanmuAI/startup.log` 无 uvicorn/pywebview 崩溃栈

## Git 与发布

- [ ] `git add -n .` 预演无意外文件
- [ ] Tag 格式：`vX.Y.Z`
- [ ] GitHub Release 描述包含变更摘要和已知问题
