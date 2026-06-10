# Codex 完成报告

> 工单 ID：（调试修复，无正式工单 ID）  
> 完成时间：2026-05-29  
> 执行者：Cursor Agent

---

## 1. 修改摘要

修复 Web 控制台 `/ws/status`、`/ws/logs` 无法连接（浏览器 Console 持续 `WebSocket close 1006`、后端升级 HTTP 403）的问题。根因：在 FastAPI 0.135 + Python 3.14 下，本项目路由规模内 `@app.websocket` 注册的 handler **从未被调用**；改为 Starlette `WebSocketRoute` 注册后 handler 正常执行。另：`ws_token` 统一从 `websocket.query_params` 读取；前端在 WS 关闭码 **1008**（令牌无效，常见于重启 `python main.py` 后未刷新页面）时自动 `refreshSession()` 再重连。

## 2. 修改的文件

- `app/web_console.py`
- `web/static/app.js`

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `app/web_api/routes.py`：是
- 未修改 `app/overlay.py`、`app/danmu_engine.py`：是
- 未修改 `requirements.txt`、CI 配置：是

## 4. 运行的命令

```bash
python .pytest_tmp/ws_probe.py
python -m pytest tests/test_web_console.py -q --tb=no
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| ws_probe | 通过（初验） | `session ok` + `ws ok, first msg keys: ['running', ...]`（`.pytest_tmp/ws_probe.py`，未入库） |
| pytest test_web_console | 通过 | 54 passed（W-006 复验；含 3 个 WS 回归） |
| pytest WS 回归（W-006） | 通过 | `test_ws_status_websocket_*` 3 passed |
| boundary_guard | 未运行（初验） | W-006 复验 PASS |
| 终端运行时日志 | 通过 | `[WebConsole] WebSocket /ws/status accepted`、`/ws/logs accepted`、`_broadcast_status consumers=1` |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | `python main.py` → 终端「Web 控制台 HTTP/WS 已监听 http://127.0.0.1:18765」 | 2026-05-29 实测有 | 是 |
| 2 | `python .pytest_tmp/ws_probe.py` → `ws ok` | 2026-05-29 实测通过 | 是 |
| 3 | 打开/硬刷新控制台 → Console 出现 `[realtime] status WS open`、无持续 1006 重连 | 终端已有 accepted 日志；浏览器 Console 待负责人复验 | 待负责人 |
| 4 | 重启 `python main.py` 后不刷新 → 旧 token 应 1008；刷新后恢复 | 前端已加 1008 自动 refreshSession | 待负责人 |

## 7. 风险与注意事项

- WebSocket 路由通过 `app.router.routes.insert(0, WebSocketRoute(...))` 注册，若未来新增更泛化的 WS 路由需注意匹配顺序。
- 关闭码 1008 仍会在**故意使用过期 token** 时出现；用户应刷新页面或依赖前端自动 refreshSession。
- 控制台仍依赖外网 CDN（Tailwind、Google Fonts）与 Supabase 公告；离线/受限网络见 ISSUE-006、ISSUE-007。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| ISSUE-006 | `index.html` 引用 Tailwind/Google Fonts CDN，外网不可达时 `tailwind is not defined` | 是 |
| ISSUE-007 | Supabase 公告 REST 请求失败时不影响核心控制台，Console 有网络错误 | 是 |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)（W-006 retroactive 验收，2026-05-29）
- [x] [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)
- [x] [docs/templates/已知问题记录/ISSUE-006-Web控制台CDN外网依赖.md](../已知问题记录/ISSUE-006-Web控制台CDN外网依赖.md)
- [x] [docs/templates/已知问题记录/ISSUE-007-Supabase公告外网不可用.md](../已知问题记录/ISSUE-007-Supabase公告外网不可用.md)

## 10. 建议下一个工单

- **Web 静态资源**：将 Tailwind 改为构建产物或本地 fallback，减少 CDN 依赖（ISSUE-006）。
- **已完成（W-006）**：为 `/ws/status` 增加 TestClient 回归测试（`tests/test_web_console.py`）。
