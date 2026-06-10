# W-TEST-BUG-027-001 完成报告

## 1. 修改摘要

闭合 BUG-027 与 [TEST-GAPS.md](../../bug-audit/TEST-GAPS.md) §4：在**不改动** `_is_reply_stale` 恒为不丢弃的产品策略下，用回归测试锁定 dormant 管线 `_log_reply_drop` → `_stale_drop_count` → `LiveStatusSnapshot.stale_drops` → `/api/status.live_stale_drops`，并静态记录 `applyStatus` 仅写 `#liveStatusLine` 来自 `st.live_message`、未读 `live_stale_drops`。

## 2. 修改的文件列表

- `E:/test/danmu/tests/test_live_freshness.py`
- `E:/test/danmu/tests/test_web_console.py`
- `E:/test/danmu/tests/test_bundle_paths.py`
- `E:/test/danmu/docs/bug-audit/TEST-GAPS.md`
- `E:/test/danmu/docs/当前仓库状态.md`
- `E:/test/danmu/docs/工单列表.md`
- `E:/test/danmu/docs/templates/Codex完成报告/W-TEST-BUG-027-001-完成报告.md`

## 3. 未修改的关键区域

- `E:/test/danmu/main.py`
- `E:/test/danmu/app/**`
- `E:/test/danmu/web/static/**`
- `E:/test/danmu/community-site/**`
- `E:/test/danmu/supabase/**`
- `docs/runtime-state-map.md`、`docs/main-pipeline-sequence.md`

## 4. 运行的命令

```bash
python -m pytest tests/test_live_freshness.py tests/test_web_console.py::test_build_status_snapshot_includes_dedup_profile_when_enabled tests/test_bundle_paths.py -q
python scripts/boundary_guard.py
```

## 5. 构建 / 测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| scoped pytest | 通过 | **27 passed** |
| boundary_guard | PASS | 未改 `app/` / `main.py` |

## 6. 手动验证步骤与结果

本票为测试维护票，无新增 GUI 手动验收步骤。负责人可选：启动应用 → DevTools `/api/status` 中 `live_stale_drops` 为 0；`#liveStatusLine` 无「旧回复丢弃」文案（与静态测试一致）。

## 7. 风险与注意事项

- 生产主链路仍不触发 `_log_reply_drop`；计数测试通过直接调用 dormant 入口模拟。
- P2 审计写「控制台副文案永远显示旧回复丢弃 0 条」——当前 `web/static` 未展示 `control.live_detail`；误导性在 API 字段 dormant + 前端未接线，非可见 DOM。

## 8. 发现但未处理的问题

| 问题 | 说明 | 已记录 |
|------|------|--------|
| BUG-027 P2「UI 与实际不一致」产品清理 | 删除 `live_stale_drops` / `detail_message` 或接线 UI | 否，属后续产品票 |
| BUG-043 `_log_reply_drop` 无锁 | 本票仅主线程单测路径 | 否 |
| `startConfigNotices` 等 TEST-GAPS §4 其余项 | 非本票 | 否 |
| `BUGS-OVERVIEW.md` 仍标 BUG-027 待修复 | 本票未改审计总表 | 否 |

## 9. 已更新的文档

- [x] `E:/test/danmu/docs/bug-audit/TEST-GAPS.md`
- [x] `E:/test/danmu/docs/当前仓库状态.md`
- [x] `E:/test/danmu/docs/工单列表.md`
- [x] 本完成报告

## 10. scoped diff 结论

本票限于 `tests/test_live_freshness.py`、`tests/test_web_console.py`、`tests/test_bundle_paths.py` 与列出的 docs；未触达 `main.py`、`app/`、`web/static/`。
