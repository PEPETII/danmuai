# Codex 完成报告

> 工单 ID：W-TEST-BUG-038-001  
> 完成时间：2026-06-03  
> 执行者：Codex

---

## 1. 修改摘要

闭合 [TEST-GAPS.md](../../bug-audit/TEST-GAPS.md) §6 BUG-038：`app/web_console.py` 为 `/ws/status`、`/ws/logs` 在 `accept` 前限制最多 10 个 consumer（超额 `close(1008, "连接数已满")`，不注册队列）。新增 `test_ws_status_max_connections_capped`（真实 `WebConsoleBridge` + `ExitStack` 保持 10 条连接后第 11 条被拒）；W-006 镜像 `_build_ws_status_test_app` 同步 cap 逻辑。

## 2. 修改的文件

- `app/web_console.py`
- `tests/test_web_console.py`
- `docs/bug-audit/TEST-GAPS.md`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-TEST-BUG-038-001-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `web/static/**`：是
- 未修改 `community-site/**`：是
- 未修改 `supabase/**`：是
- 未修改 `docs/bug-audit/BUGS-OVERVIEW.md`：是
- 未修改 `docs/runtime-state-map.md`：是（无新增 `DanmuApp` 字段）

## 4. 运行的命令

```bash
python -m pytest tests/test_web_console.py -k "ws_status_max_connections_capped or ws_status_websocket" -q
python scripts/boundary_guard.py
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| scoped pytest | 通过 | **4 passed**（~1.2s） |
| boundary_guard | **FAIL**（既有） | 因本票改动 `tests/test_web_console.py`，扫描到文件中既有 `threading.Thread`（BUG-072 用例 L1911+）与 `main-pipeline-sequence.md` 未同步；**非**本票新增调度点；`app/web_console.py` 无新增 Thread/Timer |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | scoped pytest 4 条 WS 用例 | 全部通过 | **4 passed** | 是 |
| 2 | `git diff --name-only` 无 `main.py` / `web/static` | 仅允许路径 | 待负责人 scoped diff | — |
| 3 | `python main.py` 多标签连 `/ws/status` | consumers≤10 | 待负责人 | — |

## 7. 风险与注意事项

- `len(_ws_*_queues)` 检查与 `accept` 非原子；极端并发可能短暂超出上限；本票 TestClient 顺序连接已覆盖主路径。
- 关闭码 `1008` 与无效 token 相同，前端可能触发 `refreshSession()`；多开页场景可接受。
- 未新增 `test_ws_logs_max_connections_capped`（TEST-GAPS 仅点名 status）；logs 端点已对称 cap。

## 8. 发现但未处理的问题

| 问题 | 说明 | 已记录 |
|------|------|--------|
| `BUGS-OVERVIEW` 仍标 BUG-038 待修复 | 本票未改审计总表 | 否 |
| RISK-002 `mic_in_flight` 并发 | TEST-GAPS §6 剩余 | 否 |
| 严格 asyncio 锁 / 单 token 单连接 | P2 备选方案 | 否 |

## 9. scoped diff 结论

本票改动路径：

- `app/web_console.py`
- `tests/test_web_console.py`
- `docs/bug-audit/TEST-GAPS.md`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-TEST-BUG-038-001-完成报告.md`

未触及 `main.py`、`web/static/**`、`community-site/**`、`supabase/**`。

## 10. 已更新的文档

- [x] [docs/bug-audit/TEST-GAPS.md](../../bug-audit/TEST-GAPS.md)
- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 本完成报告

## 11. 建议下一个工单

- TEST-GAPS §6 剩余：RISK-002 `mic_in_flight` 并发、RISK-013 视觉+mic 池监控等。
- 若需同步 `BUGS-OVERVIEW` BUG-038 状态：另开纯文档票。
