# 工单 W-001：清除 realtime/节奏模式主链路遗留

> **执行者**：Codex / IDE Agent  
> **状态**：已完成  
> **模板来源**：[工单模板.md](工单模板.md)

---

## 执行前必读（P0）

1. 先读 [AGENTS.md](../../../AGENTS.md) §1–§10、[docs/ai-project-context.md](../../ai-project-context.md)、[docs/当前仓库状态.md](../../当前仓库状态.md)。
2. **只执行本工单 W-001**，不得顺手做 ROADMAP、Overlay 重构或 Web i18n。
3. **术语区分（避免误删）**：
   - **要清除的「节奏模式 / realtime 显示模式」**：已废弃的 `danmu_display_mode=realtime`、200ms `_rhythm_check_timer`、`_check_rhythm_trigger`、库存驱动预截图等（见 [docs/archive/planning/DANMU_DISPLAY_MODE_PLAN.md](../../archive/planning/DANMU_DISPLAY_MODE_PLAN.md)）。
   - **保留且勿当节奏模式删除**：
     - `_scene_rhythm_pause_until` / `_rhythm_cooldown_left_ms`：场景切换后短暂 API 门禁（`app/live_freshness.py` 中 `SCENE_RHYTHM_PAUSE_SEC`），**普通模式仍在用**。
     - Web `REALTIME` 对象、`#realtimeConnStatus`：日志/状态 **WebSocket 连接**，与弹幕显示模式无关。
     - 弹幕池/人格文案里的「节奏可以」等：**内容用语**，非模式开关。
     - `app/api_schedule.py`：普通模式下调试日志与锚点时间计算，可**改注释/模块说明**，勿删 `time_to_anchor_boundary` 等仍在用的逻辑。
4. **必须保留**：旧库 `danmu_display_mode=realtime` → `normal` 的规范化（`main.py` 启动、`app/application/config_service.py`、`tests/test_web_console.py` 相关测试）。
5. **禁止**在 HTTP 线程直接改 Qt；**禁止**恢复 `_check_rhythm_trigger`（`scripts/boundary_guard.py` 已将其列为 forbidden call）。
6. 触达 `main.py` 主链路后必须跑：`python -m pytest tests/ -q` 与 `python scripts/boundary_guard.py`。
7. 范围外问题只记入 [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)，使用 [已知问题记录模板.md](../已知问题记录/已知问题记录模板.md)。

---

## 工单 ID

**W-001**

## 工单标题

清除 realtime/节奏模式主链路遗留死代码，并同步维护者文档与误导性注释

## 背景

- 产品已移除**实时弹幕显示模式**（`danmu_display_mode=realtime`），仅保留普通模式（固定识图间隔 + `normal_reply_count`），见 [docs/ROADMAP.md](../../ROADMAP.md)、[docs/CHANGELOG.md](../../CHANGELOG.md)。
- `main.py` 仍保留 `BatchTracker`（类注释写「节奏模式」）、`_maybe_schedule_screenshot`（空实现且 docstring 引用已删的 `_rhythm_check_timer`）、`_maybe_adjust_timer`（无调用方）、多个 `*_legacy` 空桩，以及 `next_generation_triggered` 等未使用字段。
- [docs/runtime-state-map.md](../../runtime-state-map.md) 将 `STAGGER_INTERVAL`、部分 Batch 字段标为遗留；[tests/test_p0_main_flow.py](../../../tests/test_p0_main_flow.py) 测试 docstring 仍写「节奏模式」。
- 与 [ISSUE-001](../../已知问题与后续事项.md)（`docs/archive/` 易误导 Agent）相关，但本工单**以代码与维护者文档为准**，不全面改写 `docs/archive/`。

## 目标

完成后应满足：

1. 仓库内**无**对已删除符号的活跃引用（`_rhythm_check_timer`、`_check_rhythm_trigger`、`_trigger_api_call_if_ready` 等），grep 仅允许出现在 archive/CHANGELOG/「已移除」说明中。
2. `main.py` 中确认为无调用方的节奏模式遗留（空桩、无 op 方法、未使用字段）已删除或合并，**普通模式截图 → API → 出队上屏**行为不变。
3. `BatchTracker` 若仍保留，类/字段/docstring 改为描述**当前**用途（批次锚点 + 可选 debug 的 `next_generation_time`），不再写「供 _check_rhythm_trigger 预加载」。
4. `app/personae.py` 中恒为 `True` 的 `is_normal_display_mode()`：删除或改为无误导的文档说明（须 grep 调用方后决定，无调用方则删）。
5. [docs/runtime-state-map.md](../../runtime-state-map.md)、[docs/main-pipeline-sequence.md](../../main-pipeline-sequence.md) 与代码一致；若删除 `STAGGER_INTERVAL` 等字段，登记表同步更新。
6. 全量 `pytest` 与 `boundary_guard` 通过。

## 依赖项

- 无前置工单；本地已 `pip install -r requirements.txt`。
- 无需 API Key（不跑真实 AI）。
- 建议在 `main` 或当前开发分支上执行。

## 允许修改的区域

- `main.py`
- `app/personae.py`（仅 `is_normal_display_mode` 及直接相关引用）
- `app/api_schedule.py`（仅模块/函数注释，不改行为）
- `app/live_freshness.py`（仅注释：区分「场景切换暂停」与已删「节奏模式」）
- `app/reply_queue.py`（仅误导性注释，若存在「节奏模式插入」等表述）
- `tests/test_p0_main_flow.py`
- `tests/test_mic_insert.py`
- `tests/test_danmu_smoothness.py`（仅与 `main._maybe_schedule_screenshot` 生产行为相关的说明/断言；**勿**删除对 `PipelineSimulator` 库存调度仿真的有效覆盖，除非证明与产品无关）
- `tests/conftest.py`（仅因删除字段而调整 `bind_minimal_danmu_app` 默认值）
- `docs/runtime-state-map.md`
- `docs/main-pipeline-sequence.md`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`

## 禁止修改的区域

- `web/static/`（含 `REALTIME`、Tab 文案「节奏与截图策略」——另开工单）
- `app/web_api/`、`app/web_console.py`
- `app/overlay.py`、`app/danmu_engine.py`
- `app/application/config_service.py` 中 **realtime→normal 规范化逻辑**（可改注释，不可删行为）
- `requirements.txt`、锁文件、CI、`scripts/boundary_guard.py` 规则本身（除非删除符号后测试仍绿且无需改 guard）
- `docs/archive/` 正文（最多在已知问题文档记 ISSUE）
- `data/danmu_pool_zh.json`、`README.md` 用户面向「节奏与截图」操作说明（非本工单）
- 大规模架构拆分（`GenerationPipelineState` 等）
- `AGENTS.md` 附录（除非负责人另开文档工单）

## 需求

### A. 执行前审计（必须先做，结果写入完成报告）

```bash
rg -n "_rhythm_check_timer|_check_rhythm_trigger|_trigger_api_call_if_ready|节奏模式|rhythm mode|DEPRECATED \(rhythm" --glob "!docs/archive/**"
rg -n "_maybe_schedule_screenshot|_maybe_adjust_timer|_screenshot_loop_legacy|_on_ai_reply_legacy|_maybe_schedule_screenshot_legacy" main.py tests/
rg -n "next_generation_triggered|STAGGER_INTERVAL" main.py tests/
rg -n "is_normal_display_mode" app/ main.py tests/
```

### B. main.py 清理（在确认无调用方后）

1. 删除或内联确认为 **无调用方** 的遗留：
   - `_maybe_schedule_screenshot`（当前 `pass`）
   - `_maybe_adjust_timer`（若无引用）
   - `_screenshot_loop_legacy`、`_on_ai_reply_legacy`、`_maybe_schedule_screenshot_legacy`（空桩）
2. 精简 `BatchTracker`：
   - 删除未使用字段（如 `next_generation_triggered`，若 grep 确认无引用）
   - 更新类与 `DanmuApp` 类 docstring，移除对已删 `_check_rhythm_trigger` / `_rhythm_check_timer` 的引用
   - `_consume_reply_queue` docstring 改为描述**当前**锚点用途（debug/批次元数据），勿写 rhythm 预触发
3. 评估 `STAGGER_INTERVAL`：若全仓库无读取分支，从 `DanmuApp` 删除并在 `runtime-state-map.md` 移除登记；若有测试仅赋值无断言，一并清理。
4. **保留**：`danmu_display_mode=realtime` → `normal` 启动规范化；`_scene_rhythm_pause_until` 及 `_rhythm_cooldown_left_ms`（重命名属非目标，除非零行为变更且测试全绿）。
5. `start()` 等 docstring 中「按模式启动截图与节奏定时器」改为准确描述（仅 `screenshot_timer` + `reply_timer`）。

### C. 测试调整

1. 删除或改写仅断言 `_maybe_schedule_screenshot()` 无效果的「节奏模式」用例（`tests/test_p0_main_flow.py` 约 529–546 行一带）。
2. 更新 `tests/test_mic_insert.py` 等对 `BatchTracker` 的用法，与精简后的字段一致。
3. 保留并通过：`test_apply_config_patch_normalizes_legacy_realtime_display_mode` 等 **legacy 配置迁移** 测试。
4. `tests/test_danmu_smoothness.py` 顶部 NOTE 改为明确：生产路径无库存驱动 `_maybe_schedule_screenshot`；Simulator 测的是历史仿真逻辑。

### D. 维护者文档

1. `docs/runtime-state-map.md`：删除已不存在的字段/定时器行；`BatchTracker`/`_current_batch` 描述与代码一致。
2. `docs/main-pipeline-sequence.md`：确认「已移除」列表与当前主链路一致，无矛盾步骤。

### E. 交付文档

1. 按 [Codex完成报告模板.md](../Codex完成报告/Codex完成报告模板.md) 提交完成报告。
2. 更新 [docs/当前仓库状态.md](../../当前仓库状态.md)、[docs/工单列表.md](../../工单列表.md) 将 W-001 标为已完成。

## 非目标

- 不实现新模式、不恢复 realtime 显示模式、不新增定时器。
- 不重命名 Web `REALTIME`、不改 `web/static/index.html` Tab「节奏与截图策略」文案。
- 不删除 `danmu_display_mode` 数据库字段的迁移/规范化逻辑。
- 不重命名 `_scene_rhythm_pause_until`（避免大范围 diff；可记 ISSUE 后续做）。
- 不修改 `docs/archive/` 全文、不清理弹幕池里「节奏可以」等内容句。
- 不做 `GenerationPipelineState` / 主链路架构重构。

## 验收标准

- [ ] 审计命令（需求 A）中，**活跃代码**（排除 `docs/archive/`、`CHANGELOG` 历史条目）不再出现 `_rhythm_check_timer`、`_check_rhythm_trigger`、`_trigger_api_call_if_ready`。
- [ ] `main.py` 无空实现的 `_maybe_schedule_screenshot` / 无调用的 `_maybe_adjust_timer` / 无 `*_legacy` 空桩（或完成报告说明保留理由）。
- [ ] `BatchTracker` 与 `_consume_reply_queue` 注释不再引用已删除 rhythm 预触发链路。
- [ ] `python -m pytest tests/ -q` 全部通过。
- [ ] `python scripts/boundary_guard.py` 通过。
- [ ] `docs/runtime-state-map.md`、`docs/main-pipeline-sequence.md` 与代码一致。
- [ ] `docs/当前仓库状态.md`、`docs/工单列表.md` 已更新；完成报告已提交。

## 手动验证步骤

> 完整表格可复制 [手动验收模板.md](../手动验收/手动验收模板.md)。

1. `pip install -r requirements.txt`
2. `python -m pytest tests/ -q`
3. `python scripts/boundary_guard.py`
4. 运行需求 A 中的审计命令，确认无违规命中
5. （可选，约 3 分钟）`python main.py` → Web 控制台启动弹幕 → 观察普通模式仍按间隔截图、弹幕正常上屏

| # | 检查项 | 操作 | 预期结果 |
|---|--------|------|----------|
| 1 | 单元测试 | `pytest tests/ -q` | 0 failed |
| 2 | 边界守卫 | `python scripts/boundary_guard.py` | exit 0 |
| 3 | 死代码审计 | `rg` 见需求 A | 无活跃 rhythm 定时器引用 |
| 4 | 配置迁移 | `pytest tests/test_web_console.py -k legacy_realtime -q` | 通过 |
| 5 | 运行冒烟 | 启动应用并开弹幕 | 截图/弹幕/控制台正常，无新异常日志 |

**预期结果**：普通模式行为与清理前一致；代码与维护者文档不再误导为「仍存在节奏模式」。

## 风险点

| 风险 | 缓解 |
|------|------|
| 误删 `_scene_rhythm_pause_until` 导致场景切换 API 连打 | 禁止删除；仅改注释；跑 `tests/test_scene_freshness.py` |
| 误删 `BatchTracker` 导致 mic 插入/批次测试失败 | 保留批次 ID 与必要字段；跑 `tests/test_mic_insert.py` |
| 删除字段未同步 `bind_minimal_danmu_app` | 改 `tests/conftest.py` 并全量 pytest |
| main.py 改动触发 boundary_guard | 必跑 guard；勿在 `GenerationPipelineState` 内调用 forbidden APIs |

**回滚**：`git revert` 本工单单次提交。

## 完成后必须更新的文档

- [ ] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [ ] [docs/工单列表.md](../../工单列表.md)（标为已完成）
- [ ] Codex 完成报告（见下）

## Codex 完成报告要求

- 使用 [Codex完成报告模板.md](../Codex完成报告/Codex完成报告模板.md)
- 必须列出**全部**修改文件路径
- 范围外问题写入 [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)，不得顺手修复

## 建议后续工单（不得在本工单实现）

| 工单 ID | 标题 | 说明 |
|---------|------|------|
| W-002 | Web 文案去「节奏模式」歧义 | `web/static/` Tab 文案、`REALTIME` 常量命名 |
| W-003 | archive / ISSUE-001 文档警示 | 加强 `docs/archive/README.md` 等 |

## 范围外问题记录（发现时写入已知问题文档）

| 字段 | 建议 |
|------|------|
| 问题 ID | ISSUE-002 |
| 所属模块 | `web/static/` |
| 问题描述 | Tab「节奏与截图策略」与 JS `REALTIME` 易与已移除的 realtime 显示模式混淆 |
| 是否阻塞 | 否 |
| 建议后续工单 | W-002 |

---

**范围说明（负责人）**：按 AGENTS.md「一次一个小工单」，W-001 仅覆盖主程序 + 测试 + 维护者文档。若 diff 过大，先交付 B+C+D，Web/archive/重命名拆 W-002/W-003，并在完成报告 §10 写明。
