# 架构债务波次状态（2026-07-10）

> **历史收官快照**：本页记录波次 0-9 在 2026-07-10 的结案状态，不替代三份现行 Boundary Guard 登记表。后续状态以 [.local-ai/workorders/当前仓库状态.md](../.local-ai/workorders/当前仓库状态.md) 为准。
>
> 性能节由 T2 Profiler 工单（W-PERF-PROFILER-T2-001）更新。

---

## 性能基线（P1–P7）

| ID | 项 | 静态结论（波次初稿） | Profiler 状态（2026-07-10） |
|----|-----|----------------------|----------------------------|
| P1 | `MAX_IN_FLIGHT=1` | **Keep** | 未测（本工单禁止改动） |
| P2 | 主线程解析/分发 | 风险仍成立 | **部分已 profile** — 离线 harness：`normalize_reply_batch` ~26% cumtime；真机 Overlay 竞争待补 |
| P3 | Levenshtein 去重回退 | 风险仍成立 | **已 profile** — C 扩展路径通过；纯 Python 回退边界通过（500 次排水 2.6s） |
| P4 | `invoke_on_main` 同步 10s | **Keep** | 未测 |
| P5 | （波次内其他项） | — | — |
| P6 | 主线程瓶颈推断 | 未 profiler 确认 | **部分待真机** — 场景 1 Overlay `dt_ms`、场景 3 `invoke_timeout_count` 未采样 |
| P7 | `TOPMOST_HEALTH_INTERVAL_MS=1500` | **Keep** | 未测 |

### T2 Profiler 实测报告

完整场景结论、Top 热点与子工单建议见：

**[.local-ai/workorders/T2-profiler-实测报告-2026-07-10.md](../.local-ai/workorders/T2-profiler-实测报告-2026-07-10.md)**

产物（cProfile / 指标 JSON）：**[.local-ai/profiles/](../.local-ai/profiles/)**

### 性能节摘要（2026-07-10）

- **P2**：离线 200 轮 `handle_reply_parsed` 总耗时 ~0.16s；`parse_ai_reply_payload` 轻量（~5% cumtime）。**暂不启动** W-PERF-GP-PARSE/DISPATCH 子工单，待真机 Overlay 同屏 profile。
- **P3**：`python-Levenshtein` 可用时 `avg_is_duplicate_us` ≈ 65 μs；回退路径 `avg_similarity_us` ≈ 85 μs。**建议低优登记** W-PERF-DEDUP-FALLBACK-001（依赖护栏），非紧急算法优化。
- **P6**：场景 3（Web 写配置 vs 主线程）**待真机**；使用 `scripts/profile_cpu_baseline.ps1 -Scenario B`。

---

## 其他波次项

### T4 ConfigStore / routes 拆分（W-T4-SPLIT-000）

| 子域 | 状态（2026-07-10） | 行数 |
|------|-------------------|------|
| `routes.py` 聚合器 | **已完成**（W-T4-ROUTES-001/002/003） | 148 行（≤250） |
| `storage.py` 主体 | **已完成**（W-T4-CS-001/002/003 外提 meme/models/legacy） | 789 行（≤800） |

**母工单 W-T4-SPLIT-000：已结案。**

### T5 GenerationPipeline Host Façade（W-T5-BOUNDARY-000）

| 项 | 状态（2026-07-10） | 度量 |
|----|-------------------|------|
| GP 内 `app._*` 私有写回 | **已完成**（W-T5-GP-002/003/004/005） | **66 → 0** |
| Host Façade 公开方法 | **已完成** | 18 个（`main_web_facade_mixin.py`） |
| `reply_timer` / `reply_buffer` | **Phase 4 冻结** | GP 内 34 处；所有权仍属 `DanmuApp` |

**母工单 W-T5-BOUNDARY-000：GP façade 阶段完成。**

---

## 执行收官（波次 0–9）

| 波次 | 主题 | 完成日期 | 状态 |
|------|------|----------|------|
| 0 | T0 文档与工单草案 | 2026-07-10 | ✅ |
| 1 | T1.1 re-export 垫片收敛 | 2026-07-08 | ✅ |
| 2 | T1.1 `danmu_tts` 拆除 | 2026-07-10 | ✅ |
| 3 | T1.1 `personae` 拆分 | 2026-07-10 | ✅ |
| 4 | T2 Profiler（离线） | 2026-07-10 | ✅（场景 1/3 真机待补） |
| 5 | T3 AI 客户端瘦身 | 2026-07-08 | ✅ |
| 6 | T4 ConfigStore 外提（一） | 2026-07-10 | ✅ |
| 7 | T4 routes 外提 + CS 收尾 | 2026-07-10 | ✅ |
| 8 | T5 GP Host Façade | 2026-07-10 | ✅ |
| 9 | 预存测试修复 | 2026-07-05 ~ 2026-07-10 | ✅ |

**波次 1–9 收官日期：2026-07-10**

**总完成报告**：[.local-ai/workorders/架构债执行总完成报告-2026-07-10.md](../.local-ai/workorders/架构债执行总完成报告-2026-07-10.md)

**仍开放（不阻塞收官）**：T2 真机场景 1/3 · `W-PERF-DEDUP-FALLBACK-001` · R4 `web_console` 导入收敛 · `reply_timer` 所有权冻结

---

*最后更新：2026-07-10 · 架构债波次 0–9 收官；总报告已固化*
