# Boundary Guard

`Boundary Guard` 是 DanmuAI 的架构边界回归检查器。它不是通用 linter，而是专门检查本仓库在**当前架构下不允许回退的边界**。

脚本入口：`scripts/boundary_guard.py`

---

## 1. 运行方式

```bash
python scripts/boundary_guard.py
```

成功：

- `Boundary Guard: PASS`

失败：

- `Boundary Guard: FAIL`
- 输出具体文件、行号、规则来源

---

## 2. 它当前主要检查什么

| 类别 | 当前保护点 |
|------|------------|
| Web / API | 禁止直接读 `danmu_app._*` / `app._*` / `ai_worker._*` |
| Status | `DanmuApp.build_status_snapshot()` 必须继续委托 `StatusSnapshotBuilder` |
| Config | `DanmuApp.apply_web_config_payload()` 必须继续委托 `ConfigService` |
| Runtime | 新运行态字段需登记到 `runtime-state-map.md` |
| Thread / Timer | 新 `QTimer` / `QThreadPool` / `threading.Thread` / `asyncio.create_task` 需要同步 `main-pipeline-sequence.md` |
| Request | `RequestScheduler` / `RequestTimingService` 的所有权与只读边界 |
| Diagnostics | `/api/diagnostics` 必须走 `DiagnosticSnapshotBuilder` |
| Baseline | `final-architecture-baseline.md` 必须存在 |

---

## 3. 它不是什么

它**不会**替代：

- 全量架构评审
- 用户可见行为验证
- 手动验收
- 全量 pytest

所以 `Boundary Guard: PASS` 不等于“功能一定没回归”。

---

## 4. 当前使用建议

以下改动应默认运行 Boundary Guard：

- `main.py`
- `app/main_*mixin.py`
- `app/web_console.py`
- `app/web_api/*`
- `app/application/*`
- 任意涉及线程 / 定时器 / runtime field / snapshot builder 的改动

---

## 5. 与文档的关系

Boundary Guard 依赖这些文档作为维护者登记表：

- `docs/runtime-state-map.md`
- `docs/main-pipeline-sequence.md`
- `docs/final-architecture-baseline.md`

如果你改了：

- 运行态字段
- 线程 / 定时器入口
- 关键边界说明

那就不只是改代码，还要同步这些文档。

---

## 6. 当前限制

Boundary Guard 只检查它已编码的规则，不会自动理解所有架构语义。  
因此：

- 文档必须保持准确
- 维护者不能把它当成“通过就万事大吉”
- 遇到边界重构时，应先更新设计文档，再更新规则实现

---

## 7. 推荐联合验证

本地请 **分批** 验证，不要跑全量 `python -m pytest tests/`（内存占用高、易卡顿）。全量仅 CI 或维护者专用环境。

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_request_scheduling.py tests/test_boundary_guard_web_rules.py tests/test_boundary_guard_runtime_rules.py tests/test_boundary_guard_request_rules.py tests/test_boundary_guard_diagnostics_rules.py -q -x
```

其他与本次改动相关的 `tests/test_*.py` 另起批次（每批 `-q -x`）。分批策略见仓库内 `.local-ai/prompts/IDE_AGENT_RULES.md` §10。

---

## 8. 一句话结论

`Boundary Guard` 的价值不是“证明一切正确”，而是尽早阻止我们把 DanmuAI 已经收紧的边界重新改回散乱状态。
