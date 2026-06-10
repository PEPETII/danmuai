# Codex 完成报告

> 工单 ID：W-LIVE-TOPIC-001
> 完成时间：2026-06-06
> 执行者：Cursor Agent

---

## 1. 修改摘要

在「人格工坊」顶部（昵称上方）新增「提示内容」textarea 与「保存主题」按钮，直播主题经 `PUT /api/config` 持久化到 `config.db`（新键 `live_topic`，上限 200 字）；AI 生成弹幕时由 `append_live_topic_to_system_pt` 在 `main.py` 两处 `system_pt` 拼接点、于 `append_nickname_to_system_pt` 之后追加单行主题上下文（中英自动切换）。空主题下助手函数原样返回原 `system_pt`，主链路行为零变化。完全复用 `WEB_CONFIG_KEYS` / `ConfigService` / `ConfigStore` 既有体系。

## 2. 修改的文件

- [app/persona_contract.py](../../app/persona_contract.py)
- [app/personae.py](../../app/personae.py)
- [app/config_defaults.py](../../app/config_defaults.py)
- [app/application/config_service.py](../../app/application/config_service.py)
- [main.py](../../main.py)
- [web/static/index.html](../../web/static/index.html)
- [web/static/app.js](../../web/static/app.js)
- [tests/test_reply_contract.py](../../tests/test_reply_contract.py)
- [tests/test_web_persona_api.py](../../tests/test_web_persona_api.py)
- [docs/WEB_CONSOLE.md](../../WEB_CONSOLE.md)
- [docs/CHANGELOG.md](../../CHANGELOG.md)
- [docs/当前仓库状态.md](../../当前仓库状态.md)
- [docs/工单列表.md](../../工单列表.md)

## 3. 未修改的关键区域

- 未修改 `app/persona_manager.py`、`app/persona_builtin.py`、`app/persona_version_history.py`：（是）
- 未修改 `app/ai_client.py`、`app/overlay.py`、`app/danmu_engine.py`：（是）
- 未修改 `app/mic_*.py`、`app/memory/`：（是）
- 未修改 `app/danmu_pool.py`、`app/danmu_read_service.py`、`app/danmu_tts*.py`：（是）
- 未修改 `app/web_api/` 全部：（是，复用既有 `PUT/GET /api/config`）
- 未修改 `web/static/modules/`：（是）
- 未修改 `scripts/boundary_guard.py`、`requirements.txt`、CI 配置：（是）
- 未绕过 `RequestScheduler` / `RequestTimingService`：（是）

## 4. 运行的命令

```bash
python -m pytest tests/test_web_persona_api.py tests/test_reply_contract.py -q
python -m pytest tests/ -q
python scripts/boundary_guard.py
python -m ruff check app/persona_contract.py app/personae.py app/config_defaults.py app/application/config_service.py main.py tests/test_web_persona_api.py tests/test_reply_contract.py
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest（test_web_persona_api + test_reply_contract） | 通过 | 46 passed |
| pytest（全量） | 通过 | 947 passed, 5 skipped |
| boundary_guard | 通过 | PASS |
| ruff（本工单触碰文件） | 通过 | All checks passed! |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 打开人格工坊 | 「提示内容」在昵称上方 | `index.html` card 顶部已插入 | 是 |
| 2 填入主题并保存 | toast「主题已保存~」、DB 有值 | 自动化：`test_put_config_persists_live_topic` | 是 |
| 3 离开再回来 | textarea 内容仍在 | 自动化：`export_config` 含 `live_topic` | 是 |
| 4 运行时注入 | system_pt 含 `[本次直播主题：…]` | 自动化：`test_append_live_topic_basic_injection_zh` | 是 |
| 5 清空并保存 | system_pt 零变化 | 自动化：`test_append_live_topic_empty_returns_unchanged` | 是 |
| 6 跨人格 | 所有人格同一主题行 | 设计保证（全局 config，非人格字段） | 是 |
| 7 多语言 en | 英文模板 | 自动化：`test_append_live_topic_basic_injection_en` | 是 |

## 7. 风险与注意事项

- **恢复默认副作用**：`live_topic` 已加入 `WEB_CONFIG_KEYS`，助手设置「恢复默认」会清空直播主题，与 `user_nickname` 行为一致，属有意设计。
- **两处注入**：`main.py` 视觉 API 路径与麦克风插入路径均已追加 `append_live_topic_to_system_pt`，遗漏任一处会导致部分请求不带主题。
- **零侵入**：`live_topic.strip() == ""` 时严格返回原 `system_pt`，不追加换行。
- **与 `topic_hint` 独立**：`app/window_info.py` 的窗口标题推断与用户主动填写的 `live_topic` 不合并。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| — | 无 | — |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/WEB_CONSOLE.md](../../WEB_CONSOLE.md)
- [x] [docs/CHANGELOG.md](../../CHANGELOG.md)

## 10. 建议下一个工单

- **W-LIVE-TOPIC-002**（可选）：多主题并存与切换 UI。
- **W-LIVE-TOPIC-003**（可选）：`{topic}` 占位符在 user_pt 模板层替换。
