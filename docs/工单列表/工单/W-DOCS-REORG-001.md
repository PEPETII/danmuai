# W-DOCS-REORG-001 — Markdown 文档分布整理（基于审查报告）

> **来源**：项目负责人发起"文档分布合理性审查"，审查报告见后文。  
> **执行者**：Codex / IDE Agent  
> **优先级**：中（不影响功能；纯文档整理）  
> **预计工时**：15–20 分钟（文件移动 + 引用更新 + 验证）

---

## 工单 ID

`W-DOCS-REORG-001`

## 工单标题

整理约 230+ 个散落文档：瘦身模板目录、统一完成报告/历史工单落点、docs/ 顶层按类型归入子目录

## 背景

审查发现项目共 402 个 `.md` 文件，存在以下核心问题：

1. **`docs/templates/Codex完成报告/` 塞了 148 个历史完成报告**，把模板目录变成了存档目录（AGENTS.md 明确要求"模板目录复制填空，勿直接当正式状态用"）；
2. **完成报告分三处存放**：`docs/archive/completion-reports/`（2）、`docs/工单列表/工单/`（3）、`docs/templates/Codex完成报告/`（148）；
3. **工单正文分两处存放**：`docs/工单列表/工单/`（16，含 5 个已过时 W-FP） + `docs/templates/工单/`（22）；
4. **`docs/` 顶层 27 个文件扁平化**：核心架构、Agent 规则、协作流程、运维文档、功能规范全混在一起；
5. **根目录 7 个文件**：其中 `THIRD_PARTY_NOTICES.md` 和 `README.en.md` 可移入 `docs/`。

详细审查见 `docs/工单列表/工单/../审查报告上下文`（本轮审查输出）。

## 目标

完成后：

1. `docs/templates/Codex完成报告/` 仅剩模板文件（≤3 个）
2. `docs/templates/工单/` 仅剩 `工单模板.md`（1 个）
3. 所有历史完成报告统一在 `docs/archive/completion-reports/`
4. 所有历史工单统一在 `docs/archive/workorders/`
5. `docs/` 顶层仅保留**强制性不动文件**（≤5 个：runtime-state-map.md, main-pipeline-sequence.md, final-architecture-baseline.md, CONTRIBUTING_ARCHITECTURE.md, README.md）
6. 新增子目录：`docs/core/`, `docs/features/`, `docs/agent/`, `docs/operations/`
7. 根目录 `.md` 从 7 减少到 5（移走 `THIRD_PARTY_NOTICES.md` 和 `README.en.md`）
8. `AGENTS.md` 和 `docs/README.md` 中所有内部链接有效
9. `python scripts/boundary_guard.py` 通过
10. 分批测试全部通过

## 依赖项

- 无前置工单
- 无 API Key 需求
- 建议在干净分支上执行（`git checkout -b docs/reorg-001`）

## 允许修改的区域

### 批量移动（约 200 个文件）

- `docs/templates/Codex完成报告/*.md` — 除 `Codex完成报告模板.md` 外全部移走
- `docs/templates/工单/*.md` — 除 `工单模板.md` 外全部移走
- `docs/工单列表/工单/W-FP-001.md` ~ `W-FP-005.md` — 5 个已过时工单
- `docs/工单列表/工单/W-FONT-001-完成报告.md` ~ `W-FONT-003-完成报告.md` — 3 个完成报告

### 单文件移动（约 22 个文件）

**根目录 → docs/**

- `THIRD_PARTY_NOTICES.md` → `docs/core/THIRD_PARTY_NOTICES.md`
- `README.en.md` → `docs/operations/README.en.md`

**docs/ 顶层 → docs/core/**（核心架构）

- `docs/ARCHITECTURE.md` → `docs/core/ARCHITECTURE.md`
- `docs/MAIN_PIPELINE.md` → `docs/core/MAIN_PIPELINE.md`
- `docs/RUNTIME_STATE.md` → `docs/core/RUNTIME_STATE.md`
- `docs/BOUNDARY_GUARD.md` → `docs/core/BOUNDARY_GUARD.md`
- `docs/OPEN_SOURCE_AUDIT.md` → `docs/core/OPEN_SOURCE_AUDIT.md`
- `docs/PRIVACY.md` → `docs/core/PRIVACY.md`

**docs/ 顶层 → docs/features/**（功能规范）

- `docs/WEB_CONSOLE.md` → `docs/features/WEB_CONSOLE.md`
- `docs/CAPTURE_AND_DANMAKU_REFERENCE.md` → `docs/features/CAPTURE_AND_DANMAKU_REFERENCE.md`
- **注意**：`docs/DANMAKU_FORMULA.md` 暂不移动（被 `scripts/write_formula_bootstrap.py` 硬编码引用）

**docs/ 顶层 → docs/agent/**（Agent 规则）

- `docs/ai-project-context.md` → `docs/agent/ai-project-context.md`
- `docs/Codex提示词手册.md` → `docs/agent/Codex提示词手册.md`
- `docs/Codex工单交接模板.md` → `docs/agent/Codex工单交接模板.md`
- `docs/提示词上下文包.md` → `docs/agent/提示词上下文包.md`
- `docs/手动验收指南.md` → `docs/agent/手动验收指南.md`

**docs/ 顶层 → docs/operations/**（运维/发布）

- `docs/CHANGELOG.md` → `docs/operations/CHANGELOG.md`
- `docs/PACKAGING_WINDOWS.md` → `docs/operations/PACKAGING_WINDOWS.md`
- `docs/ROADMAP.md` → `docs/operations/ROADMAP.md`
- `docs/RELEASE_CHECKLIST.md` → 移动到 `docs/operations/RELEASE_CHECKLIST.md`（与 `docs/architecture-governance/05-validation/RELEASE_CHECKLIST.md` 共存，不删除副本）

**docs/ 顶层 → docs/workflow/**（协作流程）

- `docs/workflow/当前仓库状态.md` → `docs/workflow/当前仓库状态.md`
- `docs/workflow/工单列表.md` → `docs/workflow/工单列表.md`
- `docs/已知问题与后续事项.md` → `docs/workflow/已知问题与后续事项.md`
- `docs/设计更新说明.md` → `docs/workflow/设计更新说明.md`

### 需要新建的目录

- `docs/core/`
- `docs/features/`
- `docs/agent/`
- `docs/operations/`
- `docs/archive/completion-reports/`
- `docs/archive/workorders/`

### 需要更新的文件

- `AGENTS.md` — 更新约 15 处内部 `.md` 路径引用
- `docs/README.md` — 重建文档索引
- `docs/workflow/README.md` — 更新工作流目录说明
- `docs/workflow/当前仓库状态.md` — 记录本次整理（移动后更新路径）
- `docs/workflow/工单列表.md` — 更新工单路径

## 禁止修改的区域

### 强制性不动（被代码硬编码引用）

- `docs/runtime-state-map.md` — `scripts/boundary_guard/constants.py:17` 硬编码
- `docs/main-pipeline-sequence.md` — `scripts/boundary_guard/constants.py:18` 硬编码
- `docs/final-architecture-baseline.md` — `scripts/boundary_guard/constants.py:19` 硬编码
- `docs/CONTRIBUTING_ARCHITECTURE.md` — `scripts/boundary_guard/` 多处引用
- `docs/DANMAKU_FORMULA.md` — `scripts/write_formula_bootstrap.py:2` 硬编码（本轮不动）

### 本轮不碰

- `app/`、`main.py`、`tests/`、`scripts/` — **禁止修改任何业务代码**
- `docs/architecture-governance/` — 本轮不动（结构良好）
- `docs/community/` — 本轮不动（独立子系统）
- `docs/archive/architecture-phases/` — 不删不改（仅新增子目录）
- `docs/archive/planning/` — 不删不改
- `docs/archive/qt6_ui_redesign_plan.md` — 不删不改
- `docs/bug-audit/` — 不删不改（乱码问题不在本工单范围）
- `docs/audits/` — 不删不改
- `docs/refactor/` — 本轮不动（与 architecture-governance 重叠问题后续单独处理）
- `docs/release/` — 不删不改
- `docs/templates/已知问题记录/` — 本轮不动（保留互补关系）
- `docs/test/` — 本轮不动（定位模糊问题后续单独处理）
- `docs/guides/` — 本轮不动
- `.github/` — 不动
- `prototype/` — 不动
- `data/`、`supabase/`、`scripts/README.md`、`community-site/` — 不动

## 需求

1. 新建 6 个目标目录（见"需要新建的目录"）
2. 从 `docs/templates/Codex完成报告/` 移动 147 个完成报告到 `docs/archive/completion-reports/`（保留 `Codex完成报告模板.md`）
3. 从 `docs/templates/工单/` 移动 21 个历史工单到 `docs/archive/workorders/`（保留 `工单模板.md`）
4. 从 `docs/工单列表/工单/` 移动 5 个 W-FP-001~005 到 `docs/archive/workorders/`
5. 从 `docs/工单列表/工单/` 移动 3 个完成报告到 `docs/archive/completion-reports/`
6. 移动 2 个根目录文件（THIRD_PARTY_NOTICES.md, README.en.md）
7. 移动 22 个 `docs/` 顶层文件到对应子目录（见"允许修改的区域"）
8. 更新 `AGENTS.md` 中所有受影响的内部链接
9. 更新 `docs/README.md` 文档索引
10. 更新 `docs/workflow/README.md`
11. 在 `docs/workflow/当前仓库状态.md` 中记录本次整理
12. 运行 `python scripts/boundary_guard.py` 确认通过
13. 分批运行 `tests/test_boundary_guard_*.py` 确认通过

## 非目标

- 不删除任何文件（全部用 git mv 保留历史）
- 不修改 `docs/architecture-governance/` 和 `docs/refactor/` 的重叠问题
- 不修复 `docs/bug-audit/danmuai_issue_md_files/` 的文件名乱码
- 不处理 `docs/test/`、`docs/guides/`、`docs/设计更新说明.md` 的定位模糊问题
- 不合并 RELEASE_CHECKLIST 两份副本
- 不更新 `DanmuAI.spec`、`.github/workflows/ci.yml`
- 不新增依赖或修改 `pyproject.toml`

## 验收标准

- [ ] `docs/templates/Codex完成报告/` 仅剩模板文件（≤3 个，含 `Codex完成报告模板.md`）
- [ ] `docs/templates/工单/` 仅剩 `工单模板.md`（1 个）
- [ ] `docs/archive/completion-reports/` 包含 ≥150 个完成报告（147 + 3）
- [ ] `docs/archive/workorders/` 包含 ≥26 个历史工单（21 + 5）
- [ ] `docs/` 顶层仅剩 ≤5 个强制性文件（不含子目录下的）
- [ ] 根目录 `.md` 文件仅剩 5 个（AGENTS.md, README.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md）
- [ ] `docs/core/`, `docs/features/`, `docs/agent/`, `docs/operations/` 四个新目录各有内容
- [ ] `python scripts/boundary_guard.py` PASS
- [ ] `python -m pytest tests/test_boundary_guard_runtime_rules.py tests/test_boundary_guard_web_rules.py tests/test_boundary_guard_diagnostics_rules.py -q -x` PASS
- [ ] 所有变更通过 `git diff --stat` 确认未触及 `app/`、`main.py`、`tests/conftest.py`

## 手动验证步骤

1. **检查模板目录瘦身**：`ls docs/templates/Codex完成报告/` 应仅 ≤3 个文件
2. **检查历史归档完整**：`ls docs/archive/completion-reports/ | wc -l` ≥ 150；`ls docs/archive/workorders/ | wc -l` ≥ 26
3. **检查 docs/ 顶层干净**：`ls docs/*.md` 应仅 5 个文件
4. **检查根目录干净**：`ls *.md` 应仅 5 个文件
5. **检查链接有效**：在 AGENTS.md 中 Ctrl+Click 任意内部链接应能打开对应文件
6. **运行 boundary_guard**：`python scripts/boundary_guard.py` → PASS
7. **运行测试**：分批 `pytest tests/test_boundary_guard_*.py -q -x` → PASS

## 风险点

| 风险 | 缓解措施 |
|------|---------|
| AGENTS.md 内部链接更新遗漏 | 移动前 `grep` 所有"docs/"引用，比对移动后路径 |
| Boundary Guard 测试因路径变更失败 | 3 个强制性文件（runtime-state-map 等）不允许移动 |
| `docs/RELEASE_CHECKLIST.md` 移动后与 architecture-governance 副本不一致 | 两份都保留，不在本轮合并 |
| pywebview 打包可能引用 .md 路径 | 检查 `DanmuAI.spec` 的 `datas` 列表 |
| 其它 IDE（Cursor/Trae）可能引用旧路径 | 仅更新 AGENTS.md，不移除旧引用（等 IDE 自行适配） |

## 回滚方案

```bash
git checkout -- .   # 或 git reset --hard HEAD~1
```

建议每个步骤单独 `git commit`，便于分步回滚。推荐提交顺序：
1. `mkdir` 新建目录
2. 批量移动完成报告
3. 批量移动历史工单
4. 逐个移动 docs/ 顶层文件
5. 移动根目录文件
6. 更新 AGENTS.md + docs/README.md
7. 最终验证 + boundary_guard

## 完成后必须更新的文档

- [x] [docs/workflow/当前仓库状态.md](../../workflow/当前仓库状态.md)
- [x] [docs/workflow/工单列表.md](../../workflow/工单列表.md)（标为已完成）
- [x] [docs/设计更新说明.md](../../workflow/设计更新说明.md)
- [x] [docs/README.md](../../README.md)（重建索引）

## Codex 完成报告要求

- 使用 [Codex完成报告模板.md](../../templates/Codex完成报告/Codex完成报告模板.md)
- 必须列出**全部**修改文件路径（含批量移动的 200+ 个文件）
- 必须提供 `git diff --stat` 输出摘要
- 范围外问题写入 [docs/已知问题与后续事项.md](../../workflow/已知问题与后续事项.md)，不得顺手修复

---

## 附录 A：审查报告摘要

审查结论：**C 级 — 明显散乱，需要集中整理**。

核心问题：
1. `docs/templates/Codex完成报告/` 有 148 个历史完成报告（模板目录当垃圾桶）
2. 完成报告分散在 3 处、工单分散在 2 处
3. `docs/` 顶层 27 个文件扁平化

## 附录 B：需要人工确认的遗留问题（不在本工单范围）

| 问题 | 说明 |
|------|------|
| `docs/DANMAKU_FORMULA.md` 移动 | 被 `scripts/write_formula_bootstrap.py` 硬编码引用，需单独工单 |
| `docs/RELEASE_CHECKLIST.md` 副本 | 与 `docs/architecture-governance/05-validation/RELEASE_CHECKLIST.md` 内容是否一致？ |
| `docs/设计更新说明.md` | 空白模板 — 删除还是保留？ |
| `docs/guides/README.md` | 空目录 — 删除还是填充？ |
| `docs/test/persona-项目1~4.md` | 测试数据还是测试文档？ |
| `docs/bug-audit/danmuai_issue_md_files/*.md` | 6 个文件名乱码 |
| `docs/templates/已知问题记录/` 36 个文件 | 保留在 templates 还是移入 workflow？ |
| `docs/refactor/` vs `docs/architecture-governance/` | 功能重叠 |
