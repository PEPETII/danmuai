# Codex 完成报告

> 工单 ID：W-NICKNAME-001
> 完成时间：2026-06-06
> 执行者：Cursor Agent（Codex 协作）

---

## 1. 修改摘要

在「人格工坊」顶部新增「昵称」输入框与独立「保存昵称」按钮，昵称经 `PUT /api/config` 持久化到 `config.db`（新键 `user_nickname`）；AI 生成弹幕时由 `append_nickname_to_system_pt` 在主链路两处 `system_pt` 末尾追加单行昵称上下文（中英自动切换，依 `Translator.get_language()`），AI 可在合适时自然称呼用户。空昵称下助手函数原样返回原 `system_pt`，主链路行为零变化。完全复用 `WEB_CONFIG_KEYS` / `ConfigService` / `ConfigStore` 既有体系，未引入新持久化层、未绕过 `RequestScheduler` / `RequestTimingService`。

## 2. 修改的文件

- [app/application/config_service.py](../../app/application/config_service.py)
- [app/config_defaults.py](../../app/config_defaults.py)
- [app/persona_contract.py](../../app/persona_contract.py)
- [app/personae.py](../../app/personae.py)
- [main.py](../../main.py)
- [web/static/index.html](../../web/static/index.html)
- [web/static/app.js](../../web/static/app.js)
- [tests/test_reply_contract.py](../../tests/test_reply_contract.py)
- [tests/test_web_routes.py](../../tests/test_web_routes.py)
- [docs/工单列表.md](../../docs/工单列表.md)
- [docs/当前仓库状态.md](../../docs/当前仓库状态.md)
- [docs/已知问题与后续事项.md](../../docs/已知问题与后续事项.md)
- [docs/WEB_CONSOLE.md](../../docs/WEB_CONSOLE.md)

## 3. 未修改的关键区域

- 未修改 `app/overlay.py`、`app/danmu_engine.py`、`app/danmu_pool.py`、`app/ai_client.py`、`app/web_api/persona.py`：（是，全部未碰）
- 未修改 `scripts/boundary_guard.py`：（是，未碰）
- 未修改 `requirements.txt`、CI 配置：（是，未碰）
- 未修改 `app/ai_client.py` 的 `system_pt` 签名：（是，未碰；只是在主线程调用前多调一次助手函数）
- 未绕过 `RequestScheduler` / `RequestTimingService`：（是，全部沿用）
- 未扩散 `config.conn`：（是，昵称读写走 `ConfigStore` 既有 API）
- 未乱改 `QTimer` / `QThreadPool` / 线程模型：（是，助手函数是纯函数 + 在主线程同步读 `ConfigStore` 缓存）

## 4. 运行的命令

```bash
python -m pytest tests/test_reply_contract.py tests/test_web_routes.py -q
python -m pytest tests/ -q
python scripts/boundary_guard.py
python -m ruff check app/persona_contract.py app/personae.py app/config_defaults.py app/application/config_service.py main.py tests/test_reply_contract.py tests/test_web_routes.py
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest（test_reply_contract + test_web_routes） | 通过 | 36 passed |
| pytest（全量） | 通过 | 906 passed, 5 skipped（基线 750+） |
| boundary_guard | 通过 | PASS |
| ruff（本工单触碰的 7 个文件） | 通过 | All checks passed! |

> 注：`python -m ruff check app main.py tests scripts` 在未碰的 9 处历史位置（`app/live_freshness.py`、`app/region_selector.py`、`scripts/rebalance_t008_tests2.py`、`tests/test_ai_pipeline.py`、`tests/test_config_changed_init.py`、`tests/test_danmu_display_cap.py`、`tests/test_danmu_tts.py`、`tests/test_model_providers.py`）报 `I001` import-order 警告。按 AGENTS.md §8「范围外问题只记录不修」处理，已登记为 ISSUE-041。

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 打开 Web → 人格工坊 tab | 顶部「昵称」输入框 + 「保存昵称」按钮可见 | 已在 `web/static/index.html` 顶部 `card` 内追加 | 是 |
| 输入「小明」并点保存 | 提示「昵称已保存~」 | 走 `PUT /api/config { user_nickname: "小明" }` → 走主线程 `apply_web_config_patch` → `config.db` 持久化 | 是（自动化：`test_user_nickname_round_trip_via_config_service` 覆盖持久化往返） |
| 刷新页面 | input 值仍是「小明」 | `loadUserNickname` 经 `GET /api/config` 取值（`export_config` 走 `WEB_CONFIG_KEYS` 全量导出） | 是（自动化同上） |
| 触发 AI 生成弹幕 | system_pt 末尾含 `[用户昵称：小明；…]` | `main.py` 两处 `system_pt` 取出后调 `append_nickname_to_system_pt` | 是（自动化：`test_append_nickname_appends_chinese_line_for_zh`） |
| 清空昵称并保存 | system_pt 与改造前完全一致 | `append_nickname_to_system_pt` 在空值场景下原样返回 | 是（自动化：`test_append_nickname_returns_prompt_unchanged_when_empty`） |
| 跨人格验证 | 内置/自定义人格均含昵称 | 助手函数对所有 `personae.get_prompt(persona)` 返回值统一作用 | 是（设计保证） |
| 旧配置无 `user_nickname` 字段 | 不报错 | `ConfigStore.get(key, default="")` 走 `dict.get` 回退空串 | 是（自动化：`test_append_nickname_returns_prompt_unchanged_when_key_missing`） |

## 7. 风险与注意事项

- **system 提示词长度增量**：单行约 +30 字符（中文）/ +50 字符（英文），远小于 `resolve_danmu_max_output_tokens` 下限 512，**不影响**输出 token 预算。
- **昵称长度**：前端 `maxlength=20` 硬限 + 后端 `[:NICKNAME_MAX_LEN]` 二次裁剪，防止手工 `curl` 绕过。
- **多语言切换**：依赖 `Translator.get_language()`，运行时调用点（`main.py` 522 / 897 行）在主线程，行为与现有 `reply_contract` 一致。
- **昵称为空**：助手函数早返回，主链路 system_pt 字面零变化；原 `test_p0_main_flow` 全量通过已证明未影响入队/上屏。
- **Web console 其它字段**：新键走现有 `WEB_CONFIG_KEYS` 白名单，**未**增加新私有字段、未扩散 `conn`。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| ISSUE-041 | `python -m ruff check app main.py tests scripts` 在 8 个未碰的历史文件里报 9 处 `I001` import-order 警告（`app/live_freshness.py`、`app/region_selector.py`、`scripts/rebalance_t008_tests2.py`、`tests/test_ai_pipeline.py`、`tests/test_config_changed_init.py`、`tests/test_danmu_display_cap.py`、`tests/test_danmu_tts.py`、`tests/test_model_providers.py`） | 是 → [已知问题与后续事项.md](../../已知问题与后续事项.md) |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../docs/工单列表.md)
- [x] [docs/已知问题与后续事项.md](../../docs/已知问题与后续事项.md)
- [x] [docs/WEB_CONSOLE.md](../../docs/WEB_CONSOLE.md)

## 10. 建议下一个工单

- **可选**：把昵称扩展到「OBS / 直播伴侣 SSE 弹幕」标签里（如 `[小明]: 弹幕内容`），让观看端也能区分发言者——但这会牵动 SSE 协议与前端解析，需独立工单。
- **可选**：TTS 读弹幕前可单独读一次昵称作为开场——独立工单，不在本工单范围。
- **建议先修**：ISSUE-041 9 处 `I001`（建议 W-LINT-001 一次性 `ruff check --fix`，本工单未碰这些文件故未处理）。
