# Codex 完成报告

> 工单 ID：W-STARTUP-001、W-STARTUP-002  
> 完成时间：2026-05-30  
> 执行者：Cursor Agent

---

## 1. 修改摘要

为 exe 冷启动增加 `app/startup_trace.py` 分阶段耗时埋点（frozen 写入 `%APPDATA%\DanmuAI\startup.log`，开发环境 `logger.info`）。缩短主线程阻塞：`attach_web_console` 的 `wait_ready` 由 frozen 30s 降为 5s；`_ensure_server_ready` 在 `startup_ok` 时短路；pywebview 握手改为 `QTimer` 轮询，不再在回调中同步 `queue.get` 阻塞事件循环；托盘 `show()` 后 `processEvents()`；frozen 桌面壳延迟由 2000ms 降为 300ms（服务已就绪时）。

## 2. 修改的文件

- `app/startup_trace.py`（新增）
- `app/web_console.py`
- `app/webview_shell.py`
- `main.py`
- `tests/test_startup_trace.py`（新增）
- `tests/test_webview_shell.py`
- `docs/main-pipeline-sequence.md`
- `DanmuAI.spec`
- `docs/templates/Codex完成报告/W-STARTUP-001-002-完成报告.md`
- `docs/templates/已知问题记录/ISSUE-020-frozen冷启动import未懒加载.md`
- `docs/工单列表.md`
- `docs/当前仓库状态.md`
- `docs/已知问题与后续事项.md`

## 3. 未修改的关键区域

- 未改主链路：`_on_screenshot_timer` → `_trigger_api_call` → `_consume_reply_queue` 等：**是**
- 未改 `app/overlay.py` / `app/danmu_engine.py` / `app/ai_client.py` 主路径：**是**
- 未改 `web/static/`：**是**
- 未改 Web API 路由语义 / `DanmuApp` 私有字段直读：**是**
- `WebConsoleBridge` 仍为唯一 Web→Qt 写入口：**是**

## 4. 运行的命令

```bash
python -m pytest tests/ -q --tb=line
python scripts/boundary_guard.py
python -m pytest tests/test_startup_trace.py tests/test_webview_shell.py tests/test_acceptance_gates.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest 全量 | 通过 | 706 passed, 1 skipped（`test_single_instance` 环境 Qt 导入警告，非本工单引入） |
| boundary_guard | 通过 | 已同步 `docs/main-pipeline-sequence.md` Bootstrap 表 |
| 打包 exe 冷启动 | 未在本机执行 | 需负责人本地 `dist\DanmuAI\DanmuAI.exe` 对比 `startup.log` |

## 6. 手动验证步骤与结果

1. `python main.py`：控制台应出现 `[startup]` 日志行；托盘应在数秒内可见；Web 窗或浏览器 fallback 应在 uvicorn 就绪后出现。  
2. 设置 `DANMU_STARTUP_TRACE=1` 后启动：应写入 `%APPDATA%\DanmuAI\startup.log`。  
3. 打包 exe 冷启动 3 次：对比 `main.begin` → `danmu_app.init.end` → `pywebview.loaded` 毫秒差（**待负责人填写实测**）。

## 7. 风险与注意事项

- `wait_ready` 5s 超时后仍会继续启动后台 uvicorn；pywebview 依赖 HTTP 探测与浏览器 fallback。  
- 握手改为 50ms `QTimer` 轮询；极端慢机器可能先见托盘后见桌面窗。  
- 回滚：恢复 `web_console_ready_timeout()` 为 30s 与同步 `shell.start()` 即可。

## 8. 发现但未处理的问题

- **ISSUE-020**：frozen 下 `main.py` 顶层重 import 与 PyInstaller 全量 `uvicorn` 子模块仍可能占大头耗时；见 `docs/templates/已知问题记录/ISSUE-020-frozen冷启动import未懒加载.md`。

## 9. 已更新的文档

- [docs/main-pipeline-sequence.md](../../main-pipeline-sequence.md)
- [docs/工单列表.md](../../工单列表.md)
- [docs/当前仓库状态.md](../../当前仓库状态.md)
- [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)

## 10. 建议下一个工单

- 根据 `startup.log` 若 `uvicorn.import.done` 仍 >10s：W-STARTUP-003 懒加载 FastAPI/uvicorn 或缩减 `hiddenimports`。  
- 可选：启动中托盘 `showMessage`「正在打开控制台…」。
