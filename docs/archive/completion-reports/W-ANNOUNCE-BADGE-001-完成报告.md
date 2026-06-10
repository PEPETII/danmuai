# Codex 完成报告

> 工单 ID：W-ANNOUNCE-BADGE-001  
> 完成时间：2026-05-29  
> 执行者：Cursor Agent

---

## 1. 修改摘要

修复 Web 控制台侧栏「公告」红点：用户进入公告页阅读后，**完全退出应用再启动**仍显示红点的问题。根因是未读判定仅依赖 `localStorage` 中的 `created_at` ISO 时间戳比较（格式/精度微差或 WebView2 未持久化时恒为未读）。改为按 Supabase 公告 **`id` 集合**判定未读，并通过 `GET/PUT /api/announcements-read-state` 写入本机 `config.db`（键 `announcements_read_state`），与 `localStorage` 双写合并；启动时先加载已读状态再请求 Supabase；进入公告页立即隐藏红点；一次性迁移旧键 `danmu_announcements_last_seen_at`。

## 2. 修改的文件

- `app/web_api/routes.py`
- `web/static/app.js`
- `tests/test_web_console.py`
- `docs/WEB_CONSOLE.md`
- `docs/工单列表.md`
- `docs/当前仓库状态.md`
- `docs/templates/Codex完成报告/W-ANNOUNCE-BADGE-001-完成报告.md`
- `docs/templates/已知问题记录/ISSUE-008-公告侧栏红点重启后仍显示.md`
- `docs/已知问题与后续事项.md`

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `app/config_store.py`（结构）：是（仅运行时经 `get_json`/`set_json` 读写新键）
- 未修改 `web/static/index.html`：是
- 未修改 Supabase 迁移 / RLS：是
- 未修改 `requirements.txt`、锁文件、CI 配置：是

## 4. 运行的命令

```bash
python -m pytest tests/test_web_console.py -q -k announcements_read_state --tb=short
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest | 通过 | `3 passed`（`announcements_read_state` 相关） |
| boundary_guard | 未运行 | 未改主链路 / `main.py` |
| 全量 pytest | 未运行 | 建议提交前 `python -m pytest tests/ -q` |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 配置 `supabase-config.js`，有一条已发布公告 | — | 待负责人 |
| 2 | 启动后进入公告页，加载完成红点消失 | — | 待负责人 |
| 3 | 托盘完全退出后重启，侧栏无红点 | — | 待负责人 |
| 4 | Supabase 新发公告（新 `id`）重启后出现红点，进入公告页后消失 | — | 待负责人（可选） |

## 7. 风险与注意事项

- `readIds` 上限 200，公告量极小时无影响。
- 已读状态按**本机** `config.db` 存储，多机不同步符合桌面单用户预期。
- `PUT` 需 Bearer；若仅 localStorage 成功而 PUT 失败，下次 GET 会合并，一般可自愈。
- 未配置 Supabase 时不显示红点（与改前一致）。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| ISSUE-007 | Supabase 不可达时公告加载失败、Console 报错 | 是（既有，未在本工单修） |
| ISSUE-008 | 原「重启后公告红点仍显示」 | 是（本工单已修复，见模板记录） |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/WEB_CONSOLE.md](../../WEB_CONSOLE.md)
- [x] [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)
- [x] [docs/templates/已知问题记录/ISSUE-008-公告侧栏红点重启后仍显示.md](../已知问题记录/ISSUE-008-公告侧栏红点重启后仍显示.md)

## 10. 建议下一个工单

- 可选：ISSUE-007 公告加载失败时 UI 静默降级，减少 Console 噪音。
- ISSUE-006 Tailwind CDN 本地化。
