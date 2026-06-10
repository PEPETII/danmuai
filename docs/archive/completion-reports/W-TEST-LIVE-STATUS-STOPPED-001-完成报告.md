# W-TEST-LIVE-STATUS-STOPPED-001 完成报告

## 1. 修改摘要

- 修正 `/api/status.live_message` 在 `running=False` 时仍可能沿用运行态文案的问题。
- `StatusSnapshotBuilder` 现统一在 stopped 态返回 `control.status_stopped_desc`。
- 新增 stopped 态状态快照回归测试，并回填 `TEST-GAPS` 与状态文档。

## 2. 修改的文件列表

- `E:/test/danmu/app/application/status_snapshot.py`
- `E:/test/danmu/tests/test_web_console.py`
- `E:/test/danmu/docs/bug-audit/TEST-GAPS.md`
- `E:/test/danmu/docs/当前仓库状态.md`
- `E:/test/danmu/docs/工单列表.md`
- `E:/test/danmu/docs/templates/Codex完成报告/W-TEST-LIVE-STATUS-STOPPED-001-完成报告.md`

## 3. 未修改的关键区域

- `E:/test/danmu/main.py`
- `E:/test/danmu/web/static/**`
- `E:/test/danmu/community-site/**`
- `E:/test/danmu/supabase/**`

## 4. 运行的命令

```bash
python -m pytest tests/test_web_console.py -q
python -m pytest tests/test_p0_main_flow.py -q
python scripts/boundary_guard.py
```

## 5. 构建 / 测试结果

- `python -m pytest tests/test_web_console.py -q`：`80 passed`
- `python -m pytest tests/test_p0_main_flow.py -q`：`57 passed`
- `python scripts/boundary_guard.py`：`PASS`

## 6. 手动验证步骤与结果

- 本票为后端状态快照修正，无新增 GUI 手动验收步骤。
- 自动化确认 stopped 态不再泄露运行中文案：
  - `tests/test_web_console.py::test_build_status_snapshot_uses_stopped_live_message_when_not_running`

## 7. 风险与注意事项

- 本票只调整 stopped 态 `live_message`，未修改前端 `applyStatus` 的其它逻辑。
- `BUG-041`、`BUG-042` 仍在 `TEST-GAPS`，本票未处理 lifetime note 与公告轮询。

## 8. 发现但未处理的问题

- 前端 `applyStatus` 中 lifetime 算式（BUG-041）仍无测试。
- `announcementsBadgePollTimer` 离开公告页不停止（BUG-042）仍无测试。
- 端口占用恢复、BUG-086、完整 happy path 等后续债务仍在 `TEST-GAPS`。

## 9. 已更新的文档

- `E:/test/danmu/docs/bug-audit/TEST-GAPS.md`
- `E:/test/danmu/docs/当前仓库状态.md`
- `E:/test/danmu/docs/工单列表.md`
- `E:/test/danmu/docs/templates/Codex完成报告/W-TEST-LIVE-STATUS-STOPPED-001-完成报告.md`

## 10. 建议下一个工单

- `W-TEST-LIFETIME-NOTE-001`：补前端 `applyStatus` 中 legacy lifetime token note 的最小测试，继续清理 `BUG-041`。
