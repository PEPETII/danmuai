# Codex 完成报告

> 工单 ID：W-GUI-RETEST-011-001  
> 完成时间：2026-06-02  
> 执行者：Codex

---

## 1. 修改摘要

为 `W-REFACTOR-BUG-P0P1-011` 增加确定性复测入口：新增受 token 保护的 `POST /api/test/danmu`，主线程复用既有 `reply -> overlay -> history` 链路注入测试弹幕，并返回 `expected_texts` / `active_texts`。用该入口复测 `LONG-VERIFY-ABCDE12345`，在 `danmu_max_chars=5` 下得到 `LONG-...`，关闭 011 随机 AI 路径无法稳定复现的缺口。

## 2. 修改的文件

- `main.py`
- `app/web_api/routes.py`
- `tests/test_p0_main_flow.py`
- `tests/test_web_console.py`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-REFACTOR-BUG-P0P1-011-完成报告.md`
- `docs/templates/Codex完成报告/W-GUI-RETEST-011-001-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `community-site/**`：是
- 未修改 `web/static/**`：是
- 未修改 `app/web_console.py`：是
- 未修改 `app/overlay.py`：是
- 未修改 `supabase/**`：是

## 4. 运行的命令

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_p0_main_flow.py -q -k "history_enqueue_matches_display_truncation or inject_test_danmu_batch"
python -m pytest tests/test_web_console.py -q -k "test_danmu_route_uses_public_app_entry"
python -m pytest tests/test_p0_main_flow.py tests/test_web_console.py -q
python main.py --web-browser
```

运行态复测期间调用：

```bash
GET  /api/session
PUT  /api/config               # danmu_max_chars=5, font_size=48
POST /api/test/danmu          # LONG-VERIFY-ABCDE12345
POST /api/stop
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| boundary_guard | 通过 | `Boundary Guard: PASS` |
| 针对性 pytest | 通过 | `3 passed` + `1 passed` |
| 扩展 pytest 子集 | 未全绿 | `tests/test_web_console.py` 内两条既有 `quit()` 用例因 `_pool_topup_timer` fixture 漏配失败；与本票新增入口无关 |
| 运行态复测 | 通过 | `expected_texts=["LONG-..."]`，`active_texts=["LONG-..."]` |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 注入一条超过 `danmu_max_chars` 的长弹幕 | 返回截断后的 `...` 文本 | `LONG-VERIFY-ABCDE12345` 在 `danmu_max_chars=5` 下返回 `expected_texts=["LONG-..."]` | 是 |
| 2 | 注入后的轨道文本与预期一致 | `active_texts` 含同一截断文案 | 返回 `active_texts=["LONG-..."]` | 是 |
| 3 | 历史落库与上屏文案一致 | 复用既有 BUG-015 回归 | `test_history_enqueue_matches_display_truncation` 通过 | 是 |

说明：Windows 分层透明窗口截图未稳定捕获 Qt Overlay，本票以运行态轨道文本作为确定性 GUI 复测证据。

## 7. 风险与注意事项

- `POST /api/test/danmu` 为验证入口，需 Bearer token，且设计为本机控制台使用，不用于业务流程。
- 该入口不会绕过现有截断/去重/历史链路；若轨道过载，`active_texts` 不保证立刻包含新文案。
- `tests/test_web_console.py` 当前仍有两条与 `quit()` 相关的既有失败，需独立工单处理。

## 8. 发现但未处理的问题

- `tests/test_web_console.py::test_quit_stops_web_status_timer_before_server_shutdown`
- `tests/test_web_console.py::test_quit_logs_warning_when_thread_pool_does_not_finish`

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/templates/Codex完成报告/W-REFACTOR-BUG-P0P1-011-完成报告.md](W-REFACTOR-BUG-P0P1-011-完成报告.md)
- [x] 本完成报告

## 10. 建议下一个工单

- `W-GUI-RETEST-012-001`：在英文 locale 首装环境复测默认语言种子。
