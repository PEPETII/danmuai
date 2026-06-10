# Codex 完成报告 — W-DOCS-REORG-001

> 工单 ID：W-DOCS-REORG-001  
> 完成时间：2026-06-10  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

按审查结论整理约 230 个 Markdown 文件：`docs/templates/` 瘦身（完成报告/历史工单迁出）、新建 `core/features/agent/operations` 子目录、协作活文档迁入 `docs/workflow/`、153 份完成报告与 26 份历史工单统一归档至 `docs/archive/`；`docs/reports/` 清空 completion-report 后专用于审查/审计类报告。已更新 `AGENTS.md` 与文档索引链接；`boundary_guard` 与分批测试通过。

## 2. 修改的文件

### 新建目录

- `docs/core/`
- `docs/features/`
- `docs/agent/`
- `docs/operations/`
- `docs/archive/completion-reports/`（153 个 `.md`）
- `docs/archive/workorders/`（26 个 `.md`）

### 根目录移动（2）

- `THIRD_PARTY_NOTICES.md` → `docs/core/THIRD_PARTY_NOTICES.md`
- `README.en.md` → `docs/operations/README.en.md`

### docs/ 顶层移动（20）

- → `docs/core/`：`ARCHITECTURE.md`、`MAIN_PIPELINE.md`、`RUNTIME_STATE.md`、`BOUNDARY_GUARD.md`、`OPEN_SOURCE_AUDIT.md`、`PRIVACY.md`
- → `docs/features/`：`WEB_CONSOLE.md`、`CAPTURE_AND_DANMAKU_REFERENCE.md`
- → `docs/agent/`：`ai-project-context.md`、`Codex提示词手册.md`、`Codex工单交接模板.md`、`提示词上下文包.md`、`手动验收指南.md`
- → `docs/operations/`：`CHANGELOG.md`、`PACKAGING_WINDOWS.md`、`ROADMAP.md`、`RELEASE_CHECKLIST.md`
- → `docs/workflow/`：`当前仓库状态.md`、`工单列表.md`、`已知问题与后续事项.md`、`设计更新说明.md`

### 自 templates 归档（147 完成报告 + 21 历史工单）

- `docs/templates/Codex完成报告/*`（保留 `Codex完成报告模板.md`）→ `docs/archive/completion-reports/`
- `docs/templates/工单/*`（保留 `工单模板.md`）→ `docs/archive/workorders/`

### 自活跃区归档（8）

- `docs/工单列表/工单/W-FONT-001~003-完成报告.md` → `docs/archive/completion-reports/`
- `docs/工单列表/工单/W-FP-001~005.md` → `docs/archive/workorders/`
- `docs/reports/*-completion-report.md`（3）→ `docs/archive/completion-reports/`

### 链接与索引更新

- `AGENTS.md`
- `docs/README.md`
- `docs/workflow/README.md`
- `docs/workflow/当前仓库状态.md`
- `docs/workflow/工单列表.md`
- `docs/workflow/设计更新说明.md`
- `docs/workflow/已知问题与后续事项.md`
- `docs/operations/PACKAGING_WINDOWS.md`
- `docs/operations/RELEASE_CHECKLIST.md`
- `docs/templates/工单/工单模板.md`
- `docs/templates/Codex完成报告/Codex完成报告模板.md`
- `docs/templates/` 下其余模板（workflow 路径）
- `docs/工单列表/工单/` 下全部活跃工单（相对链接）
- `.gitignore`（允许 `docs/archive/completion-reports/`、`workorders/` 跟踪；更新 maintainer 文档路径）

### 未移动（硬编码 / 工单禁止）

- `docs/runtime-state-map.md`、`docs/main-pipeline-sequence.md`、`docs/final-architecture-baseline.md`
- `docs/CONTRIBUTING_ARCHITECTURE.md`、`docs/DANMAKU_FORMULA.md`

## 3. 未修改的关键区域

- 未修改 `app/`：**是**（工作区内存在与本次工单无关的既有未提交改动，见 §7）
- 未修改 `web/`：**是**
- 未修改 `main.py`：**是**
- 未修改 `tests/`：**是**
- 未修改 `scripts/`：**是**
- 未修改 `docs/architecture-governance/`：**是**

## 4. 运行的命令

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_boundary_guard_runtime_rules.py -q -x
python -m pytest tests/test_boundary_guard_web_rules.py -q -x
python -m pytest tests/test_boundary_guard_diagnostics_rules.py -q -x
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 分批测试 | 通过 | 7 + 8 + 5 = 20 passed |
| boundary_guard | 通过 | `Boundary Guard: PASS` |
| 结构验收 | 通过 | templates CR=1、WO=1；archive CR=153、WO=26；docs 顶层 6；根目录 md 5 |

### 5.1 分批测试报告

- **未执行全量** `python -m pytest tests/`（遵守 IDE Agent 规则）
- 批次 1：`test_boundary_guard_runtime_rules.py` — 7 passed
- 批次 2：`test_boundary_guard_web_rules.py` — 8 passed
- 批次 3：`test_boundary_guard_diagnostics_rules.py` — 5 passed

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 模板目录瘦身 | Codex完成报告 ≤3、工单仅模板 | CR=1、WO=1 | 是 |
| 归档完整 | CR≥150、WO≥26 | CR=153、WO=26 | 是 |
| docs 顶层 | ≤6（含 DANMAKU_FORMULA） | 6 个文件 | 是 |
| 根目录 md | 5 个 | AGENTS/README/CONTRIBUTING/CODE_OF_CONDUCT/SECURITY | 是 |
| boundary_guard | PASS | PASS | 是 |
| boundary_guard 测试 | 3 批 PASS | 20 passed | 是 |

## 7. 风险与注意事项

- 历史归档文件内交叉链接**未**批量修复（只读档案）
- 根 `README.md`、`CONTRIBUTING.md`、`main.py` 注释仍指向旧 docs 顶层路径（已记 ISSUE-054/055）
- 工作区在工单开始前已有 `app/main_launch_mixin.py` 等未提交改动，与本次文档整理无关

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| ISSUE-054 | 根 README/CONTRIBUTING 旧 docs 路径 | 是 |
| ISSUE-055 | main.py / app/providers/constants.py 旧 docs 路径 | 是 |
| ISSUE-056 | docs/IDE_AGENT_RULES.md 不存在但被 AGENTS 引用 | 是 |

## 9. 已更新的文档

- [x] [docs/workflow/当前仓库状态.md](../../workflow/当前仓库状态.md)
- [x] [docs/workflow/工单列表.md](../../workflow/工单列表.md)
- [x] [docs/workflow/设计更新说明.md](../../workflow/设计更新说明.md)
- [x] [docs/README.md](../../README.md)
- [x] [docs/workflow/已知问题与后续事项.md](../../workflow/已知问题与后续事项.md)

## 10. 建议下一个工单

- W-DOCS-LINKS-002：统一修复根 README、CONTRIBUTING、main.py 内文档路径
- W-IDE-AGENT-RULES-001：补齐或重定向 `docs/IDE_AGENT_RULES.md`
