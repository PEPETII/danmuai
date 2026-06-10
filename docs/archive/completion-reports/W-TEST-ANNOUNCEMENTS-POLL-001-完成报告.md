# W-TEST-ANNOUNCEMENTS-POLL-001 完成报告

## 1. 修改摘要

闭合 BUG-042 与 [TEST-GAPS.md](../../bug-audit/TEST-GAPS.md) §4：公告未读 badge 的 5min `setInterval` 在「公告」页停止（避免多余 Supabase 请求），切到其他页恢复轮询；`init` 在 `#announcements` 已激活时不启动定时器。新增 `stopAnnouncementsBadgePolling` 与静态回归测试。

## 2. 修改的文件列表

- `E:/test/danmu/web/static/modules/content-pages.js`
- `E:/test/danmu/web/static/app.js`
- `E:/test/danmu/tests/test_bundle_paths.py`
- `E:/test/danmu/docs/bug-audit/TEST-GAPS.md`
- `E:/test/danmu/docs/当前仓库状态.md`
- `E:/test/danmu/docs/工单列表.md`
- `E:/test/danmu/docs/templates/Codex完成报告/W-TEST-ANNOUNCEMENTS-POLL-001-完成报告.md`

## 3. 未修改的关键区域

- `E:/test/danmu/main.py`、`app/**`：是
- `E:/test/danmu/community-site/**`、`supabase/**`：是
- `E:/test/danmu/docs/refactor/**`：是
- 主链路 / Overlay / AI：是

## 4. 运行的命令

```bash
python -m pytest tests/test_bundle_paths.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest `tests/test_bundle_paths.py` | 通过 | **13 passed** |
| boundary_guard | 未跑 | 仅 `web/static` + 测试 |

## 6. 手动验证步骤与结果

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 非公告页 5min 内有 Supabase announcements 轮询 | 待负责人 | 待负责人 |
| 2 | 停留在公告页无周期性轮询（除首次 load） | 待负责人 | 待负责人 |
| 3 | 离开公告页后轮询恢复 | 待负责人 | 待负责人 |

## 7. 风险与注意事项

- 用户长时间停在公告页不会后台刷新列表；再次进入会 `loadAnnouncementsPage` 全量加载。
- 审计文档行号指向旧 `app.js` 位置；实现以 `content-pages.js` + 当前 `app.js` 为准。

## 8. 发现但未处理的问题

| 问题 | 说明 | 已记录 |
|------|------|--------|
| `BUGS-OVERVIEW.md` 仍标 BUG-042 待修复 | 本票未改审计总表 | 否 |
| §4 其他 UI 缺口（BUG-027、startConfigNotices 等） | 非本票 | 否 |

## 9. 已更新的文档

- [x] `E:/test/danmu/docs/bug-audit/TEST-GAPS.md`
- [x] `E:/test/danmu/docs/当前仓库状态.md`
- [x] `E:/test/danmu/docs/工单列表.md`
- [x] 本完成报告

## 10. scoped diff 结论

本票限于 `web/static/modules/content-pages.js`、`web/static/app.js`、`tests/test_bundle_paths.py` 与列出的 docs；未触达 Python 主程序与 Supabase 迁移。
