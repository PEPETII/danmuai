# Codex 完成报告

> 工单 ID：W-APP-UPDATE-001  
> 完成时间：2026-05-29  
> 执行者：Cursor Agent

---

## 1. 修改摘要

实现 Web 控制台侧栏左下角版本展示与 Supabase 驱动的更新提醒：本地版本来自 `app/version.py`（`GET /api/version`）；远程 `public.app_updates` 由前端 PostgREST 读取；数字段语义比较（非字符串比较）；有新版本时启动弹窗，「否」将 `dismissedLatestVersion` 持久化至 `config.db`；Supabase/网络失败仅显示「检查失败」，不阻塞 `init()`。

## 2. 修改的文件

- app/version.py
- app/version_compare.py
- app/web_api/routes.py
- web/static/index.html
- web/static/app.js
- web/static/supabase-client.js
- web/static/warm-tokens.css
- supabase/migrations/003_app_updates.sql
- supabase/README.md
- tests/test_version_compare.py
- tests/test_version_api.py
- tests/test_supabase_static.py
- docs/WEB_CONSOLE.md
- docs/工单列表.md
- docs/当前仓库状态.md
- docs/已知问题与后续事项.md
- docs/templates/Codex完成报告/W-APP-UPDATE-001-完成报告.md

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 Overlay / `app/overlay.py`、`app/danmu_engine.py`：是
- 未修改 `app/ai_client.py`、截图/回复队列主链路：是
- 未修改 `QTimer` / `QThreadPool` 调度：是
- 未新增 `requirements.txt` 依赖：是

## 4. 运行的命令

```bash
python -m pytest tests/test_version_compare.py tests/test_version_api.py tests/test_supabase_static.py -q
python scripts/boundary_guard.py
python -m pytest tests/ -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest（版本相关） | 通过 | 14 passed |
| boundary_guard | 通过 | Boundary Guard: PASS |
| pytest 全量 | 通过 | 700 passed, 1 skipped |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | Supabase `latest_version` = `app/version.py` | 需负责人在 Dashboard 配置后验证 | 待负责人 |
| 2 | `latest_version` 更大时启动弹窗 | 需真实环境 | 待负责人 |
| 3 | 点「是」打开 GitHub Releases | 需真实环境 | 待负责人 |
| 4 | 点「否」同版本不再弹 | 需真实环境 | 待负责人 |
| 5 | 断网/无 Supabase 配置时正常启动、左下「检查失败」 | 逻辑已 try/catch | 待负责人 |

## 7. 风险与注意事项

- 生产 Supabase 须执行 `003_app_updates.sql` 并插入 `enabled=true` 行，否则客户端显示「检查失败」（见 ISSUE-019）。
- 每次发布须同步更新 `app/version.py` 与 Git tag / `docs/release/`。
- `window.open` 在部分环境可能被拦截，已实现剪贴板回退 toast。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| ISSUE-019 | 生产 Supabase 可能尚未 apply `003_app_updates` | 是 |

## 9. 已更新的文档

- [x] docs/当前仓库状态.md
- [x] docs/工单列表.md
- [x] docs/WEB_CONSOLE.md
- [x] docs/已知问题与后续事项.md

## 10. 建议下一个工单

- 发布流程 checklist：GitHub Release → 更新 Supabase `app_updates` 行（可与 CI 文档工单合并）
