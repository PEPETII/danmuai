# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.9] - 2026-07-07

### Changed
- 样式生成器「消息内容」更名为「弹幕用户名」。
- 样式生成器「背景与透明度」更名为「弹幕气泡背景」，辅助说明改为「弹幕气泡颜色、气泡透明度」；原「描边」「阴影」「边框」三个折叠面板合并为「描边、阴影、边框」。
- 样式生成器「消息颜色」更名为「弹幕字体」，并将原「消息内容」中的弹幕字号/粗细/行间距，以及原「字体与间距」全部设置项合并入该面板；字段标签改为更易懂的「弹幕字号」「文字粗细」「行间距」。
- Windows release package built from the current release-readiness branch state.

---

## [0.3.7] - Unreleased

### Changed
- 弹幕样式「从下到上模式」基础风格由按钮组改为下拉菜单，默认选中「仿微信」。
- 修复弹幕样式页冷启动读取旧版无气泡配置时，预览与「仿微信」基础风格按钮不一致；启动时自动恢复为气泡堆叠预设。

### Added
- AI platform reference data system with custom models schema and web UI model selector.
- Per-model thinking level selector in advanced model configuration (off/low/medium/high).
- Equivalent bottom-up floating-panel animation controls and live preview: entry fade/slide, stack push timing, and exit fade/none behavior are now carried through the WebView and Qt fallback renderers.
- Bottom-up floating-panel display-area adjustment mode: the user-facing toggle temporarily enables dragging, shows an inline guide/border, and automatically persists the final position for the next launch.
- Pet barrage system (`app/pet/pet_barrage.py`) for desktop companion overlay comments.
- Live overlay setup assistant for streamers.
- Diagnostics hub and SSE-based diagnostics snapshot API (`/api/diagnostics`).
- Feedback context image handling for user reports.
- Full persona prompt preview in web console.
- Track layout exposure in `/api/status` with font settings visualization.

### Changed
- Web settings: removed the danmu style preview block from **Danmu display** tab; horizontal preview remains on **Danmu Style → Horizontal mode**.

- Improved startup trace and stream performance.
- Restructured web settings UI for mic, TTS, and persona panels.
- Refined builtin persona prompts and reply contract wording.

### Fixed
- Fixed microphone logs returning `http_404` with Doubao by using the existing Responses audio-input path instead of the OpenAI transcription route.
- Removed `_Y_OFFSET` ghost offset so top danmu aligns to track origin.
- Bottom-to-top floating-panel usernames now use each message's persona display name, matching horizontal mode; legacy no-persona calls retain their configured fallback.
- Batch fixes for tray restore, bililive-dm plugin bridge, and engine bugs.
- Security, threading safety, and test coverage improvements.
- PyInstaller spec updated for PyInstaller 6.16 compatibility.
- Restored supabase/migrations/ to fix CI test failures.

### Removed
- Deprecated scene brief memory support and related configuration keys.

---

## [0.3.6]

> Early release; not recorded under this changelog format.

---

## [0.3.5]

> Version number was not used; skipped.

---

## [0.3.4]

> Early release; not recorded under this changelog format.

---

## [0.3.3] and earlier

> Early releases; not recorded under this changelog format.
