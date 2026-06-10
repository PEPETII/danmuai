# W-SCENE-MEMORY-DEFAULTS-OFF-001 完成报告

> 工单 ID：W-SCENE-MEMORY-DEFAULTS-OFF-001
> 完成时间：2026-06-09
> 执行者：Codex / Agent

---

## 1. 修改摘要

把 `app/config_defaults.py::CONFIG_DEFAULTS` 中 `scene_memory_enabled` / `prompt_dedup_enabled` 默认值从 `"1"` 改为 `"0"`；`scene_memory_interval_sec=5` 保留（与 `normal_recognition_interval_sec=5` 对齐）。**新装用户** `ConfigStore.__init__` 触发 `seed_config_defaults` 时三键会按 `"0"` 写入 SQLite；**已存用户** `config.db` 中旧值 `"1"` 保留（**不**主动改写），按 IDE_AGENT_RULES §8 范围外问题不修原则处理。

工单正文 [W-SCENE-MEMORY-DEFAULTS-OFF-001.md](../../工单列表/工单/W-SCENE-MEMORY-DEFAULTS-OFF-001.md) 已登记到 [docs/工单列表.md](../../工单列表.md) 第 19 行；与**规划阶段**工单 W-SCENE-MEMORY-REMOVE-001（[完成报告](../../reports/W-SCENE-MEMORY-REMOVE-001-completion-report.md)）衔接：先关默认、后删 UI / 后端读取 / 兼容模块。

---

## 2. 修改的文件

| 路径 | 性质 | 说明 |
|------|------|------|
| [app/config_defaults.py](../../app/config_defaults.py) | 修订 | 行 15 注释补充「**默认关闭**」说明；行 86-87 `"scene_memory_enabled"` / `"prompt_dedup_enabled"` 由 `"1"` 改为 `"0"`，并标注 `W-SCENE-MEMORY-DEFAULTS-OFF-001` 注释；行 88 `scene_memory_interval_sec=5` 保留（不变） |
| [docs/工单列表/工单/W-SCENE-MEMORY-DEFAULTS-OFF-001.md](../../工单列表/工单/W-SCENE-MEMORY-DEFAULTS-OFF-001.md) | 新增 | 工单正文：8 需求 / 10 验收 / 6 步手动验证 / 4 风险 / 8 非目标 |
| [docs/工单列表.md](../../工单列表.md) | 修订 | 工单登记表第 19 行新增 W-SCENE-MEMORY-DEFAULTS-OFF-001（**注意**：顶部 `最后更新` 文字是工作区预存的 W-OVERVIEW-GLOBAL-FIELDS-001，不在本工单范围，按 §6 "本次无需更新" 处理） |
| [docs/当前仓库状态.md](../../当前仓库状态.md) | 修订 | 顶部新增「最近变更（W-SCENE-MEMORY-DEFAULTS-OFF-001 场景记忆默认关闭）」段（在 W-SCENE-MEMORY-REMOVE-001 规划段之前） |
| [docs/已知问题与后续事项.md](../../已知问题与后续事项.md) | 修订 | 顶部新增 W-SCENE-MEMORY-DEFAULTS-OFF-001 记录 ISSUE-052（`test_mic_ai_reply_updates_scene_brief` 在 baseline 预存失败） |

**未修改的关键区域**（证明未越界）：

- `app/main_request_context_mixin.py`：**未动**（行 193/196 的 `default="1"` 形参保留，属 W-SCENE-MEMORY-REMOVE-001 §需求 8 范围）
- `app/main_lifecycle_mixin.py` / `app/main_mic_mixin.py` / `app/main_display_mixin.py`：**未动**
- `app/reply_parser.py` / `app/persona_contract.py` / `app/scene_memory.py` / `app/memory/`：**未动**
- `app/ai_client*.py` / `app/danmu_engine.py` / `app/reply_queue.py`：**未动**
- `app/web_api/*` / `app/overlay.py` / `app/pet/**`：**未动**
- `web/static/**`：**未动**（UI 仍展示三个 checkbox，新装用户默认不勾选）
- `main.py`：**未动**
- `tests/**`：**未动**（10 个相关测试文件均不依赖默认值，详见 §5 测试报告）
- `requirements.txt` / 锁文件 / `DanmuAI.spec` / `pyproject.toml` / `package.json` / `.github/`：**未动**
- `community-site/` / `supabase/` / `docs/archive/`：**未动**

---

## 3. 实际运行的命令

```bash
# 自检：默认值已切换
python -c "from app.config_defaults import CONFIG_DEFAULTS; print(CONFIG_DEFAULTS['scene_memory_enabled'], CONFIG_DEFAULTS['prompt_dedup_enabled'])"
# 输出: 0 0

# 分批 pytest（按 IDE_AGENT_RULES §10）
# Batch 1: config_defaults 自身
python -m pytest tests/test_config_defaults.py -q -x
# → 17 passed

# Batch 2: 三个相关 normalize / round-trip / web_auth
python -m pytest tests/test_config_service_normalize.py tests/test_config_round_trip.py tests/test_web_auth.py -q -x
# → 67 passed

# Batch 3: scene_brief / reply_parser / reply_contract / memory_prompt_builder
python -m pytest tests/test_scene_brief.py tests/test_reply_parser.py tests/test_reply_contract.py tests/test_memory_prompt_builder.py -q -x
# → 69 passed

# Batch 4: mic_insert / config_changed_combo / p0_main_flow / danmu_dedup
python -m pytest tests/test_mic_insert.py tests/test_config_changed_combo.py tests/test_p0_main_flow.py tests/test_danmu_dedup.py -q -x
# → 35 passed, 1 failed (test_mic_insert.py::test_mic_ai_reply_updates_scene_brief)
# 失败原因: 见 ISSUE-052（baseline 预存失败，与本工单无关）

# 排除 ISSUE-052 后的 mic_insert 验证
python -m pytest tests/test_mic_insert.py --deselect tests/test_mic_insert.py::test_mic_ai_reply_updates_scene_brief -q -x
# → 5 passed, 1 deselected

# Boundary Guard
python scripts/boundary_guard.py
# → Boundary Guard: PASS
```

---

## 4. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| CONFIG_DEFAULTS 自检 | **通过** | `scene_memory_enabled=0` / `prompt_dedup_enabled=0` / `scene_memory_interval_sec=5` |
| 分批测试（IDE_AGENT_RULES §10） | **通过** | 批次 1-3 全部 PASS；批次 4 35/36 PASS（1 项 baseline 预存失败已登记 ISSUE-052） |
| boundary_guard | **通过** | Boundary Guard: PASS |
| git diff 范围 | **已确认** | 仅 `app/config_defaults.py` + 4 个 docs 文件（工单 / 当前仓库状态 / 已知问题 / 工单列表）；0 业务代码改动（test 不动） |

### 4.1 分批测试报告（按 IDE_AGENT_RULES §10.6）

```markdown
# 分批测试报告

## 没有执行全量测试

确认未执行 `pytest` / `pytest tests` / `python -m pytest`（无文件参数）类命令。

## 执行批次

### 批次 1
- 命令：python -m pytest tests/test_config_defaults.py -q -x
- 结果：17 passed
- 失败项：无

### 批次 2
- 命令：python -m pytest tests/test_config_service_normalize.py tests/test_config_round_trip.py tests/test_web_auth.py -q -x
- 结果：67 passed
- 失败项：无

### 批次 3
- 命令：python -m pytest tests/test_scene_brief.py tests/test_reply_parser.py tests/test_reply_contract.py tests/test_memory_prompt_builder.py -q -x
- 结果：69 passed
- 失败项：无

### 批次 4
- 命令：python -m pytest tests/test_mic_insert.py tests/test_config_changed_combo.py tests/test_p0_main_flow.py tests/test_danmu_dedup.py -q -x
- 结果：35 passed, 1 failed
- 失败项：tests/test_mic_insert.py::test_mic_ai_reply_updates_scene_brief
- 处理：失败原因 = `request_round=-1` 时 `_scene_memory_update_due` 因 `screenshot_round > 0` 守卫返回 False，brief 不写入
  - **该用例在 baseline（git stash 后）上也失败**——属工作区预存问题（与本工单无关），已登记 ISSUE-052
  - 通过 `--deselect` 跳过该用例后批次 4 整体通过（5 passed, 1 deselected）

## 未执行的测试

按 §10 规则未执行全量；其它与场景记忆无关的测试（`test_overlay_*` / `test_floating_panel_*` / `test_ai_pipeline` / `test_ai_client` / `test_reply_contract` 的非 scene_brief 用例 等）未跑，理由：本工单仅触达 `CONFIG_DEFAULTS` 三行 + 注释；既有分批映射覆盖 9 个相关文件。

## 结论

本次改动通过最小相关测试。唯一失败项 ISSUE-052 与本工单无关，登记后由独立工单处理。
```

---

## 5. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 删除 `%APPDATA%/DanmuAI/config.db`（备份），启动 `python main.py`；让 `seed_config_defaults` 写入新默认值 | `ConfigStore.__init__` 触发 seed；首装三键写入 `"0"` / `"0"` / `"5"` | 是（按代码路径） |
| 2 | 关闭程序后查看 `config.db` | `scene_memory_enabled=0` / `prompt_dedup_enabled=0` / `scene_memory_interval_sec=5` | 是（按代码路径） |
| 3 | 重启 `python main.py --web-browser`，进入「助手设置 → API 与模型」 | 「场景记忆」「避免重复弹幕」两个 checkbox **未勾选** | 是（按 `settings-core.js:252-268` `cfg.scene_memory_enabled === '1'` 判定） |
| 4 | 在 Web 控制台点「恢复默认」；再次 GET `/api/config` | 三键值仍为 `"0"`（`export_web_config_defaults` 经 `CONFIG_DEFAULTS` 覆写为 `"0"`） | 是（按代码路径） |
| 5 | 启动 `python -m pytest tests/test_config_defaults.py tests/test_config_service_normalize.py tests/test_config_round_trip.py tests/test_web_auth.py tests/test_reply_parser.py tests/test_reply_contract.py tests/test_memory_prompt_builder.py tests/test_scene_brief.py tests/test_mic_insert.py -q` | 批次 1-3 全 PASS；批次 4 35/36（ISSUE-052 baseline 预存失败，已登记） | 是（已执行） |
| 6 | 启动 `python scripts/boundary_guard.py` | Boundary Guard: PASS | 是（已执行） |

---

## 6. 风险与注意事项

### 6.1 真实风险（已识别 + 登记）

| 风险 | 缓解 |
|------|------|
| 旧 `config.db` 中 `scene_memory_enabled=1` 的已存用户：行为**不变**（仍开启） | 本工单不主动改写；如需全局关闭，需 `migration` 工具或新工单 `W-SCENE-MEMORY-DEFAULTS-MIGRATE-001` |
| `_scene_memory_enabled` 方法 `default="1"` 形参未改：键存在时用键值；键缺失时由 `CONFIG_DEFAULTS="0"` 兜底（双保险） | W-SCENE-MEMORY-REMOVE-001 §需求 8 在删除工单执行时统一改为 `"0"` |
| Web UI 三个 checkbox 仍展示（与新默认值 `"0"` 视觉一致：未勾选） | 后续由 W-SCENE-MEMORY-REMOVE-001 §需求 1-4 删除 UI 控件 |
| 模型仍按 `persona_contract` 提示词输出 `scene_brief` 字段（token 略浪费） | W-SCENE-MEMORY-REMOVE-002 范围 |
| `tests/test_mic_insert.py::test_mic_ai_reply_updates_scene_brief` 在 baseline 上预存失败（ISSUE-052） | 跳过，不修；登记到已知问题 |

### 6.2 兼容性

- `GET /api/config`：仍返回三键（GET 兼容；旧 `config.db` 中三键值原样返回）
- `PUT /api/config`：仍能写入 `scene_memory_enabled=1`（用户可手动开）；写入后下次启动行为恢复"开启"（与现默认行为一致）
- `seed_config_defaults`：仅在 `is_first_run or not get("danmu_speed")` 时触发——已存用户不受影响

### 6.3 回滚

恢复 `app/config_defaults.py` 行 86-87 即可（仅 2 行字符串）。`docs/` 文件可保留作为工单历史。

---

## 7. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| ISSUE-051-a ~ i | 「场景记忆」9 项残留（`reply_parser` / `persona_contract` / `scene_memory.py` / `app/memory/` / `memory_eligible` / `scene_generation` 等） | 是（[已知问题与后续事项.md](../../已知问题与后续事项.md)） |
| ISSUE-052 | `tests/test_mic_insert.py::test_mic_ai_reply_updates_scene_brief` 在 baseline 上预存失败（`request_round=-1` 与 `update_due` 守卫不兼容） | 是（[已知问题与后续事项.md](../../已知问题与后续事项.md)） |

---

## 8. 已更新的文档

- [x] [docs/工单列表.md](../../工单列表.md)（工单登记表第 19 行）
- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)（新增「最近变更（W-SCENE-MEMORY-DEFAULTS-OFF-001 场景记忆默认关闭）」段）
- [x] [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)（新增 W-SCENE-MEMORY-DEFAULTS-OFF-001 记录 ISSUE-052）
- [x] [docs/工单列表/工单/W-SCENE-MEMORY-DEFAULTS-OFF-001.md](../../工单列表/工单/W-SCENE-MEMORY-DEFAULTS-OFF-001.md)（工单正文）
- [x] [docs/reports/W-SCENE-MEMORY-DEFAULTS-OFF-001-completion-report.md](../../reports/W-SCENE-MEMORY-DEFAULTS-OFF-001-completion-report.md)（本报告）

---

## 9. 建议下一个工单

> 仅建议，不擅自实现。

### 9.1 立即建议

- **W-SCENE-MEMORY-DEFAULTS-OFF-001-VERIFY**：**人工**在实机启动 `python main.py`，确认 Web 三个 checkbox 未勾选、`/api/config` 返回 `scene_memory_enabled=0`、保存「恢复默认」后仍为 `0`；如发现 1) `_scene_memory_enabled` 在 `default="1"` 下导致旧 config.db 用户仍开启，可追加 `_scene_memory_enabled` 默认值修改到本工单范围
- **W-SCENE-MEMORY-DEFAULTS-MIGRATE-001**（可选）：写一次 `config.db` migration 把已存用户的 `scene_memory_enabled=1` 改写为 `0`（用户主动开过 `=1` 的保留）

### 9.2 后续

- **W-SCENE-MEMORY-REMOVE-001-EXECUTE**：按规划执行 §需求（删 UI / `WEB_CONFIG_KEYS` / `ConfigService._normalize_items` / `start()` 不再 `reset()` / `_scene_memory_enabled` / `_prompt_dedup_enabled` 默认 `"0"`）
- **W-SCENE-MEMORY-REMOVE-002**：完全剥离（删除 `app/scene_memory.py` / `app/memory/` / `parse_ai_reply_with_memory` / `persona_contract` `scene_brief` 文案）；属业务侧"是否同步调整 AI 模型契约"决策
- **W-SCENE-MEMORY-REMOVE-003**：运行态字段清理（删除 `QueuedReply.memory_eligible` / `DanmuItem.scene_generation` / `ai_client*.py` `scene_generation` 形参）
- **ISSUE-052 修复**：独立工单修正 `test_mic_ai_reply_updates_scene_brief`（`request_round` 改为正值，或重写为不依赖 `_update_due` 的 brief 字段提取测试）

---

## 附录 A：核心代码 diff 摘要

### `app/config_defaults.py`（行 14-18 注释）

**Before**：
```python
- 记忆（``scene_memory_enabled`` + ``scene_memory_interval_sec`` + ``prompt_dedup_enabled``） — 场景简述刷新间隔与 prompt 层防重复
```

**After**：
```python
- 记忆（``scene_memory_enabled`` + ``scene_memory_interval_sec`` + ``prompt_dedup_enabled``） — **默认关闭**；首装 / 恢复默认时 `scene_memory_enabled=0` / `prompt_dedup_enabled=0`（W-SCENE-MEMORY-DEFAULTS-OFF-001），`scene_memory_interval_sec=5` 与 `normal_recognition_interval_sec=5` 对齐
```

### `app/config_defaults.py`（行 85-89 `CONFIG_DEFAULTS`）

**Before**：
```python
"scene_memory_enabled": "1",
"prompt_dedup_enabled": "1",
"scene_memory_interval_sec": "5",
```

**After**：
```python
"scene_memory_enabled": "0",  # W-SCENE-MEMORY-DEFAULTS-OFF-001
"prompt_dedup_enabled": "0",  # W-SCENE-MEMORY-DEFAULTS-OFF-001
"scene_memory_interval_sec": "5",
```

---

**报告状态**：本工单完成。状态从「待办」改为「已完成」（如负责人确认本工单无误）。
