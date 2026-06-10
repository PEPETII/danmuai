# W-TEST-BUG-035-001 完成报告

## 1. 修改摘要

闭合 BUG-035 与 [TEST-GAPS.md](../../bug-audit/TEST-GAPS.md) §3：`LiveOverlayHub` 将同线程突发的多条 `broadcast_item` 先入 `_pending`，仅调度 **一次** `loop.call_soon_threadsafe(self._flush_pending)`；flush 回调在事件循环线程内对所有订阅 queue 批量 `put_nowait`。保留 `danmu_item` 单条 payload（含 per-item `y`）、`recent_items()` 回放与 `QueueFull` 丢最旧语义。未改 `main.py` / SSE 路由 / 前端协议。

## 2. 修改的文件列表

- `E:/test/danmu/app/live_overlay_hub.py`
- `E:/test/danmu/tests/test_live_overlay.py`
- `E:/test/danmu/docs/bug-audit/TEST-GAPS.md`
- `E:/test/danmu/docs/当前仓库状态.md`
- `E:/test/danmu/docs/工单列表.md`
- `E:/test/danmu/docs/templates/Codex完成报告/W-TEST-BUG-035-001-完成报告.md`

## 3. 未修改的关键区域

- `E:/test/danmu/main.py`：是（`_broadcast_live_overlay_item` 仍单条调用 hub）
- `E:/test/danmu/web/static/**`：是
- `E:/test/danmu/community-site/**`：是
- `E:/test/danmu/supabase/**`：是
- `E:/test/danmu/app/web_api/**`、`app/web_console.py`：是
- `E:/test/danmu/docs/refactor/**`：是
- Qt Overlay / 主链路截图·AI·回复队列：是

## 4. 运行的命令

```bash
python -m pytest tests/test_live_overlay.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest `tests/test_live_overlay.py` | 通过 | **12 passed** |
| boundary_guard | 未跑 | 未触达 DanmuApp / Web API 边界 |

## 6. 手动验证步骤与结果

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | `python main.py`，OBS/浏览器打开 `/live-overlay` | 待负责人 | 待负责人 |
| 2 | `POST /api/live-overlay/test` 20+ 行，网页层全部出现 | 待负责人 | 待负责人 |
| 3 | 正常启停生成，AI 弹幕 Y 与桌面 Overlay 对齐 | 待负责人 | 待负责人 |

## 7. 风险与注意事项

- 稳态每 tick 单条上屏仍为 1 次 flush/条；跨 tick 50ms 主线程合并未做（审计备选，需另票 touching `main.py`）。
- `last_batch_size` 现为 flush 批内条数（突发 100 条时为 100），与单条上屏时仍为 1。
- `broadcast_batch` 仍循环 `broadcast_item`，但共享同一 pending flush。

## 8. 发现但未处理的问题

| 问题 | 说明 | 已记录 |
|------|------|--------|
| BUG-037 `live-overlay.js` pickRandom 无防抖 | 非本票 | 否 |
| `BUGS-OVERVIEW.md` 仍标 BUG-035 待修复 | 本票未改审计总表 | 否 |
| `_build_batch_payload` 未用于 AI 旁路 | 设计保留；非回归 | 否 |

## 9. 已更新的文档

- [x] `E:/test/danmu/docs/bug-audit/TEST-GAPS.md`
- [x] `E:/test/danmu/docs/当前仓库状态.md`
- [x] `E:/test/danmu/docs/工单列表.md`
- [x] 本完成报告

## 10. scoped diff 结论

本票逻辑变更限于 `app/live_overlay_hub.py`、`tests/test_live_overlay.py` 与列出的 docs；未触达 `main.py`、`web/static`、`community-site`、主链路。
