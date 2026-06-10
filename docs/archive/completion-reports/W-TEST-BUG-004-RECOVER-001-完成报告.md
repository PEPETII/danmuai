# W-TEST-BUG-004-RECOVER-001 完成报告

## 1. 修改摘要

闭合 [TEST-GAPS.md](../../bug-audit/TEST-GAPS.md) §1 BUG-004 子场景：**慢启动 / 延迟 HTTP 就绪**时 `_open_web_console_when_ready` 在重试窗口内恢复（attach pywebview + 清除 attach 错误条）。另补 **bind 失败**负向用例，明确真·端口占用（`EADDRINUSE` → `_bind_failed`）**无进程内恢复**，须释放端口后重启。未改 `main.py` / `app/`。

## 2. 修改的文件列表

- `E:/test/danmu/tests/test_p0_main_flow.py`
- `E:/test/danmu/tests/test_web_console.py`
- `E:/test/danmu/docs/bug-audit/TEST-GAPS.md`
- `E:/test/danmu/docs/当前仓库状态.md`
- `E:/test/danmu/docs/工单列表.md`
- `E:/test/danmu/docs/templates/Codex完成报告/W-TEST-BUG-004-RECOVER-001-完成报告.md`

## 3. 未修改的关键区域

- `E:/test/danmu/main.py`：是
- `E:/test/danmu/app/**`：是
- `E:/test/danmu/app/webview_shell.py`：是
- `E:/test/danmu/web/static/**`：是
- `E:/test/danmu/community-site/**`：是
- `E:/test/danmu/supabase/**`：是
- `E:/test/danmu/docs/refactor/**`：是

## 4. 运行的命令

```bash
python -m pytest tests/test_p0_main_flow.py tests/test_web_console.py -q -k "recover or delayed_server or bind_failed or attach_status_timer"
python -m pytest tests/test_p0_main_flow.py tests/test_web_console.py -q
```

未跑 `boundary_guard.py`（本票未触达 `main.py` / `app/`）。

## 5. 构建 / 测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest（本票 `-k` 子集） | 通过 | **5 passed** |
| pytest（两文件全量） | 140 passed | 后续已修 `notify_web_console_failure` 延迟回调与 `test_config_change_updates_overlay_font` 串扰 |

## 6. 手动验证步骤与结果

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 慢启动：`python main.py` → 警告后桌面壳打开、无持久 ERROR | 本票纯测试，待负责人 | 待负责人 |
| 2 | 真占端口：`http.server 18765` → 单次失败；结束占用后**重启** DanmuAI → 正常 | 本票纯测试，待负责人 | 待负责人 |

## 7. 风险与注意事项

- 自动化覆盖的是 **`classify=slow`** + `wait_for_http_server` 延迟就绪，**不是**真实 socket 占端口 20s。
- 重试耗尽（约 20s）后 server 才 ready 时，现行代码可能仍不自动 attach；托盘再次打开或重启为兜底（本票未扩 scope 修）。

## 8. 发现但未处理的问题

| 问题 | 说明 | 已记录 |
|------|------|--------|
| P0-CRITICAL BUG-004 文案 | 审计写「30s 占端口后进程内 bind 成功」；当前实现 bind 失败即 terminal，须**重启** | 本报告 + TEST-GAPS 注释 |
| ~~`test_config_change_updates_overlay_font` Qt 串扰~~ | 已修：`_tray_icon_for_notify` + bind-failed 测试 mock `notify` | 是（`app/webview_shell.py`、测试夹具） |
| 重试耗尽后晚就绪 | 无 `web_status_timer` 触发 `_schedule_webview_attach` | 否（范围外） |

## 9. 已更新的文档

- [x] `E:/test/danmu/docs/bug-audit/TEST-GAPS.md`
- [x] `E:/test/danmu/docs/当前仓库状态.md`
- [x] `E:/test/danmu/docs/工单列表.md`
- [x] 本完成报告

## 10. 建议下一个工单

- 负责人补签 P0P1-003 手动步骤 1–2（占端口 / 释放后重启），或登记「重试耗尽后晚就绪自动 attach」产品票（若需进程内完全自愈）。
