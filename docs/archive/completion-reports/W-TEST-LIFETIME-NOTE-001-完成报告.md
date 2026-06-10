# W-TEST-LIFETIME-NOTE-001 完成报告

## 1. 修改摘要

- 补齐 lifetime 历史总 Token 与拆分输入/输出字段并存时的展示契约回归。
- 新增后端 `refresh_status` 回归，确认 `lifetime_total_tokens` 不会覆盖掉 legacy extra。
- 新增前端 `status.js` 静态回归，确认 `legacyExtra` note 仍按预期渲染。

## 2. 修改的文件列表

- `E:/test/danmu/tests/test_lifetime_stats.py`
- `E:/test/danmu/tests/test_bundle_paths.py`
- `E:/test/danmu/docs/bug-audit/TEST-GAPS.md`
- `E:/test/danmu/docs/当前仓库状态.md`
- `E:/test/danmu/docs/工单列表.md`
- `E:/test/danmu/docs/templates/Codex完成报告/W-TEST-LIFETIME-NOTE-001-完成报告.md`

## 3. 未修改的关键区域

- `E:/test/danmu/main.py`
- `E:/test/danmu/app/**`
- `E:/test/danmu/web/static/**`
- `E:/test/danmu/community-site/**`
- `E:/test/danmu/supabase/**`

## 4. 运行的命令

```bash
python -m pytest tests/test_lifetime_stats.py tests/test_bundle_paths.py -q
python scripts/boundary_guard.py
```

## 5. 构建 / 测试结果

- `python -m pytest tests/test_lifetime_stats.py tests/test_bundle_paths.py -q`：`20 passed`
- `python scripts/boundary_guard.py`：`PASS`

## 6. 手动验证步骤与结果

- 本票为测试维护票，无新增 GUI 手动验收步骤。
- 自动化覆盖：
  - `tests/test_lifetime_stats.py::test_refresh_status_preserves_legacy_lifetime_extra_alongside_split_fields`
  - `tests/test_bundle_paths.py::test_status_js_renders_legacy_lifetime_token_note`

## 7. 风险与注意事项

- 本票未改前端实现，只补了回归保护。
- `BUG-042` 的公告页轮询停止逻辑仍未补。

## 8. 发现但未处理的问题

- `announcementsBadgePollTimer` 离开公告页不停止（BUG-042）仍无测试。
- 端口占用恢复、BUG-086、完整 happy path 等后续债务仍在 `TEST-GAPS`。

## 9. 已更新的文档

- `E:/test/danmu/docs/bug-audit/TEST-GAPS.md`
- `E:/test/danmu/docs/当前仓库状态.md`
- `E:/test/danmu/docs/工单列表.md`
- `E:/test/danmu/docs/templates/Codex完成报告/W-TEST-LIFETIME-NOTE-001-完成报告.md`

## 10. 建议下一个工单

- `W-TEST-ANNOUNCEMENTS-POLL-001`：补公告 badge 轮询在离开公告页时停止的最小静态/行为回归，继续清理 `BUG-042`。
