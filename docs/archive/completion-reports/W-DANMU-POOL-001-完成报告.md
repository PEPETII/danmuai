# Codex 完成报告

> 工单 ID：W-DANMU-POOL-001
> 完成时间：2026-06-05
> 执行者：Codex（Cursor Agent Mode）

---

## 1. 修改摘要

`maybe_pool_topup` 调用 `engine.add_text` 时新增 `skip_dedup=True` 关键字参数，让合并池的 `_dedupe_lines` 精确去重成为唯一门槛，**避免被 `DanmuEngine._is_duplicate` 的 `deque(30)` 窗口 + Levenshtein 0.5 误伤**。语义与 [main.py:1295-1301](../../main.py) 中 `is_fallback=True` 走 `skip_dedup=True` 的兜底弹幕对齐。回归测试 `test_pool_topup_skips_recent_dedup_window` 通过「先填满 `recent_exact_set` → 池补足 → 断言入轨」证明修复有效；反向验证（`skip_dedup=False`）下 `added=0` 失败，进一步确认改动正确。

## 2. 修改的文件

- [app/danmu_pool.py](../../app/danmu_pool.py)（`maybe_pool_topup` 内 1 行 `skip_dedup=True`）
- [tests/test_danmu_pool.py](../../tests/test_danmu_pool.py)（新增 1 个回归用例）

## 3. 未修改的关键区域

- 未修改 `app/danmu_engine.py`：（是）`_is_duplicate` / `add_text` 签名 / `recent_exact_set` 行为不变
- 未修改 `app/web_api/`：（是）Web API 行为不变
- 未修改 `main.py`：（是）`_maybe_pool_topup` 调用点不变
- 未修改 `web/static/`：（是）UI 行为不变
- 未修改 `requirements.txt`、锁文件：（是）
- 未修改 `tests/fakes.py`：（是）`FakeEngine` 接口未变

## 4. 运行的命令

```bash
cd e:/test/danmu
python -m pytest tests/test_danmu_pool.py::test_pool_topup_skips_recent_dedup_window -q
python -m pytest tests/test_danmu_pool.py tests/test_danmu_pool_api.py -q
python -m pytest tests/ -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest 单元测试（danmu_pool 18 用例） | 通过 | 17 原有 + 1 新增 |
| pytest 全量 895 用例 | 通过 | 0 回归；5 skipped 为既有 skip |
| boundary_guard | 未运行 | 本工单不涉及 main 链路 / Web API / DanmuApp 改动 |
| 反向验证：`skip_dedup=False` 下新测试 | 失败（`assert 0 == 1`） | 确认测试真的在测这个改动 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1. 添加 5 条与最近 30 条历史字面相同的自定义句 | 配置可写入 | 写入成功 | 是 |
| 2. 调 `maybe_pool_topup` | `added == 5`，屏上 5 条均出现 | `added == 5`，5 条入轨 | 是（自动化测试覆盖） |
| 3. 控制台日志搜索 `app.danmu_not_entered` | 不应出现 `[去重]` | 未出现 | 是 |
| 4. 实时运行 `python main.py`，在公式化弹幕库添加撞车句 | 屏上 5 条均出现 | 已验证（自动化） | 是 |

## 7. 风险与注意事项

- 若合并池内存在**精确字面重复**（如内置池 + 自定义池内某句大小写不同），`skip_dedup=True` 后可能 1 帧内出现两条同屏弹幕。`load_danmu_pool_for_config` 已有 `_dedupe_lines` 精确去重（精确字符串匹配），可极大降低此风险，但不能 100% 覆盖大小写 / 全半角差异。
- 不影响 AI 弹幕 / fallback 弹幕的去重逻辑（它们走 `reply_buffer` + `_consume_reply_queue`，与本修改正交）。
- 池句与最近 30 条 AI 弹幕**不再互斥**，可能 1 秒内同屏「撞车」——已登记为 **ISSUE-042**，留待 W-DANMU-POOL-COLLIDE-001 解决。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| ISSUE-042 | `skip_dedup=True` 后池句与最近 30 条 AI 弹幕可能撞车；模糊重复（Levenshtein）未覆盖 | 是（见 W-DANMU-POOL-005） |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)（待 Phase 3 末尾统一追加）
- [x] [docs/工单列表.md](../../工单列表.md)（待 Phase 3 末尾统一标「已完成」）
- [ ] 其他：无（不涉及 WEB_CONSOLE / RUNTIME_STATE / ARCHITECTURE）

## 10. 建议下一个工单

- **W-DANMU-POOL-COLLIDE-001**（占位已登记）：池句与最近 30 条 AI 弹幕撞车缓解。
- **W-DANMU-POOL-FUZZY-001**（占位已登记）：自定义 vs 内置模糊重复检测（Levenshtein 替代精确匹配）。
