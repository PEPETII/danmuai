# Roadmap

**当前默认 UI（2025+）**

- 主路径：Web 控制台（`web/static/` + `app/web_console.py` + `app/web_api/`），默认 `python main.py`
- 核心运行：Qt Overlay（`app/overlay.py` + `app/danmu_engine.py`）与托盘始终启用
- ~~Qt 主窗（`--qt-ui`）~~ 已移除（2026-05）；历史见 `docs/archive/qt6_ui_redesign_plan.md`

## 已完成

- 许可证整理（MIT → GPL-3.0+）
- 发布前隐私与忽略规则补齐
- 固定 5 条弹幕输出约束
- 过期回复丢弃和连续失败退避
- 退出流程中的线程池等待与客户端清理
- **Web 控制台成为默认 UI**（FastAPI + pywebview + `web/static/`）
- 人格工坊、自定义模型 CRUD、图像压缩预览、日志多选过滤迁入 Web
- `app/web_api/` 服务层；Web 成为唯一控制台 UI
- **公式化弹幕库** Web 页：内置/自定义库开关、同屏补足、`/api/danmu-pool/*`（见 [WEB_CONSOLE.md](WEB_CONSOLE.md)）
- **移除实时弹幕模式**：仅普通模式（固定识图间隔 + `normal_reply_count`）；历史见 [archive/planning/DANMU_DISPLAY_MODE_PLAN.md](archive/planning/DANMU_DISPLAY_MODE_PLAN.md)
- ~~场景记忆 / `scene_brief`~~（`memory_mode`、`app/memory/`）已于 2026-06 移除（`W-SCENEBRIEF-REMOVE-*`）；历史见 [CHANGELOG.md](CHANGELOG.md#unreleased)
- 人格工坊内置人格扩展（傲娇/腹黑/中二等 7 种）；前台窗口活动感知（`window_info` + `activity`）
- 架构文档治理、`app/application/` 运行态拆分、Boundary Guard / 验收脚本（见 [CHANGELOG.md](CHANGELOG.md#2026-05-27)）

## 下一步

- 增加可视化截图框选器，替代纯坐标配置（`region_*` 真正参与裁剪）
- Web 控制台英文/i18n（暂缓）
- 补充更多 AI 服务端兼容测试
- 优化 Overlay 动画和高 DPI 边界
- ~~移除 `--qt-ui` 与 Qt 主窗~~ 已完成

## 暂不计划

- Web 英文界面（短期）
- 账号系统
- 云端同步
- 复杂后台服务
