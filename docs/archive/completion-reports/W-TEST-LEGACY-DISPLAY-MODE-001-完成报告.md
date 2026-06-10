# W-TEST-LEGACY-DISPLAY-MODE-001 完成报告

## 1. 修改摘要

- 收敛 `DanmuApp` 启动时对遗留 `danmu_display_mode=realtime` 的清理逻辑，改为复用 `app.application.config_service.normalize_legacy_display_mode`。
- 新增初始化入口回归测试，补齐 BUG-052 的第二条清理路径。
- 回填 `TEST-GAPS`、当前仓库状态与工单列表。

## 2. 修改的文件列表

- `E:/test/danmu/main.py`
- `E:/test/danmu/tests/test_p0_main_flow.py`
- `E:/test/danmu/docs/bug-audit/TEST-GAPS.md`
- `E:/test/danmu/docs/当前仓库状态.md`
- `E:/test/danmu/docs/工单列表.md`
- `E:/test/danmu/docs/templates/Codex完成报告/W-TEST-LEGACY-DISPLAY-MODE-001-完成报告.md`

## 3. 未修改的关键区域

- `E:/test/danmu/app/**`
- `E:/test/danmu/web/static/**`
- `E:/test/danmu/community-site/**`
- `E:/test/danmu/supabase/**`

## 4. 运行的命令

```bash
python -m pytest tests/test_p0_main_flow.py tests/test_web_console.py -q
python scripts/boundary_guard.py
```

## 5. 构建 / 测试结果

- `python -m pytest tests/test_p0_main_flow.py tests/test_web_console.py -q`：`136 passed`
- `python scripts/boundary_guard.py`：`PASS`

## 6. 手动验证步骤与结果

- 本票为代码 + 测试维护票，无新增 GUI 手动验收步骤。
- 通过双入口自动化回归确认 BUG-052：
  - Web patch 入口：`tests/test_web_console.py::test_apply_config_patch_normalizes_legacy_realtime_display_mode`
  - 初始化入口：`tests/test_p0_main_flow.py::test_init_normalizes_legacy_realtime_display_mode_config`

## 7. 风险与注意事项

- 本票未改变 `normal` 之外其他显示模式的行为，仅消除初始化入口与 Web patch 入口的重复实现。
- `DanmuApp.__init__` 仍未做全量构造异常路径测试，BUG-086 继续保留在 `TEST-GAPS`。

## 8. 发现但未处理的问题

- 端口占用 20s 后释放的恢复路径仍无测试，见 `docs/bug-audit/TEST-GAPS.md`。
- `DanmuApp.__init__` 任意子系统失败时的整体 try/except 行为仍无测试，见 `docs/bug-audit/TEST-GAPS.md`。

## 9. 已更新的文档

- `E:/test/danmu/docs/bug-audit/TEST-GAPS.md`
- `E:/test/danmu/docs/当前仓库状态.md`
- `E:/test/danmu/docs/工单列表.md`
- `E:/test/danmu/docs/templates/Codex完成报告/W-TEST-LEGACY-DISPLAY-MODE-001-完成报告.md`

## 10. 建议下一个工单

- `W-TEST-PORT-RECOVERY-001`：补端口占用后恢复路径的最小回归；若确认当前实现缺失，则再拆代码修复票。
