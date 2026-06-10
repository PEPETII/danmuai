# W-ANTISLOP-SCAN-001-REPORT-FIX-002 — 报告 §11 配置对齐完成报告

> **类型**：报告修订（非业务代码工单）  
> **来源**：`W-ANTISLOP-SCAN-001-REPORT-FIX-001` 用户反馈："§11.1 的 `backend-doctor.config.json` 没有包含 `community-site/**`，但 §11.2 预期 `community-site/` 桶 32 条 → 0，二选一"  
> **本工单选择**：**方案 A**（推荐）—— 在 §11.1 的 `ignore.files` 中加入 `community-site/**`；保留 §11.2 中"`community-site/` 桶 32 条 → 0"的预期  
> **执行者**：Codex / Cursor Agent  
> **完成时间**：2026-06-08  
> **结论**：本工单**仅**修订 4 个 `docs/` 文件；**不**修改业务代码、**不**落盘 `backend-doctor.config.json`、**不**动 CI、**不**动依赖。

---

## 1. 修改摘要

按用户 3 点要求逐条落实：

| # | 用户要求 | 本工单落实 |
|---|----------|------------|
| 1 | §11.1 增补 `community-site/**`（方案 A） | 已在 [backend-doctor-scan-report.md §11.1](../../backend-doctor-scan-report.md) 的 `ignore.files` 加入 `"community-site/**"`（位置：`.npmcache/**` 之后、`web/static/tailwindcdn.js` 之前）；与 §11.2 预期 "`community-site/` 桶 32 条 → 0" 严格对齐 |
| 2 | 保持 3 桶独立统计口径 | §1.3 / §4 / §4.1 / §4.2 / §7.2 / §11.2 均维持原"项目自身 / community-site / venv 缓存"3 桶独立；§11.2 已显式说明"在主仓扫描中静默 32 条 ≠ 取消 `community-site/` 应有独立扫描" |
| 3 | `community-site/**` 是否纳入 `W-DOCTOR-IGNORE-001` 的 ignore 范围 | **是**（方案 A）：`community-site/**` 已纳入 `W-DOCTOR-IGNORE-001` 的 `ignore.files`；**与 §7.2「`community-site/` 应有独立扫描」不冲突**——主仓静默 ≠ 取消独立扫描；独立 `backend-doctor.config.json` 由 **`W-DOCTOR-DEPENDENCY-001`** 立项时按需建立 |

---

## 2. 修改的文件列表（完整路径）

### 2.1 修订（已存在文件）

| 文件 | 修改内容 |
|------|----------|
| `docs/backend-doctor-scan-report.md` | §11.1 的 `ignore.files` 数组增补 `"community-site/**"`；§11.2 第 2 项 bullet 追加"与 §7.2 不冲突"说明 + 段末新增 `> ` blockquote 显式标注 "`community-site/**` 已纳入 `W-DOCTOR-IGNORE-001` 的 `ignore.files` 范围"；§12「已更新的文档」追加 REPORT-FIX-002 完成报告条目；§13 元数据追加 REPORT-FIX-002 修订时间线与"§11 配置修正（REPORT-FIX-002）"项 |
| `docs/工单列表/工单/W-DOCTOR-IGNORE-001.md` | §需求 1 的 JSON `ignore.files` 数组增补 `"community-site/**"`；§验收标准 `ignore.files` 至少包含列表增补 `"community-site/**"`；§风险点 1 由 "**不要**把 `community-site/**` 写进 `ignore.files`" 改为 "`community-site/**` 已纳入 `ignore.files`（方案 A）…独立扫描由 `W-DOCTOR-DEPENDENCY-001` 立项时按需建立" |
| `docs/工单列表.md` | 顶部"最后更新"行更新；W-ANTISLOP-SCAN-001 行允许修改文件列表追加 `W-ANTISLOP-SCAN-001-REPORT-FIX-002-完成报告.md`；备注中显式标注 "`ignore.files` 已含 `community-site/**`，方案 A" |
| `docs/当前仓库状态.md` | 顶部"最后更新"行更新；新增「最近变更（W-ANTISLOP-SCAN-001-REPORT-FIX-002）」节，明确"`community-site/**` 已纳入 `W-DOCTOR-IGNORE-001` 的 ignore 范围（项目根 `backend-doctor.config.json`）" |

### 2.2 新建（仅 docs/ 下）

- `docs/templates/Codex完成报告/W-ANTISLOP-SCAN-001-REPORT-FIX-002-完成报告.md` — **本文档**

### 2.3 清理（临时）

- 无（本次工单无 Python 脚本）

---

## 3. 未修改的关键区域（证明未越界）

按 [AGENTS.md §4](../../AGENTS.md) 边界 + 本工单「禁止修改的区域」，**本工单未触碰**：

- `app/`（含 `app/main_*mixin.py`、`app/overlay.py`、`app/danmu_engine.py`、`app/ai_client.py`、`app/web_api/*`、`app/config_store.py`、`app/danmu_pool*.py`、`app/pet/*` 等）
- `web/`（含 `web/static/**`、`web/static/index.html`）
- `main.py`
- `tests/`
- `scripts/`（含 `scripts/boundary_guard*`）
- `requirements.txt`、`requirements-dev.txt`、`pyproject.toml`、`package.json`、`package-lock.json`、`pytest.ini`、`DanmuAI.spec`
- `.github/`（含 `.github/workflows/ci.yml`）
- `.gitignore`、`AGENTS.md`、`README.md`、`README.en.md`、`SECURITY.md`、`THIRD_PARTY_NOTICES.md`
- 所有 git 跟踪的 Python / JS / CSS / HTML 业务源文件
- **`backend-doctor.config.json`（按用户要求仅规划，**不**在项目根落盘；本工单再次明确）**
- `reports/backend-doctor.json` / `reports/backend-doctor.sarif`（**未**复跑扫描；产物仍为 REPORT-FIX-001 落盘的内容）
- `community-site/`（**未**新建其 `backend-doctor.config.json`，留给 `W-DOCTOR-DEPENDENCY-001`）

---

## 4. 运行的命令

```bash
# 仅文档 diff 检查（无 Python 脚本、无 backend-doctor 重跑）
git diff -- docs/backend-doctor-scan-report.md docs/工单列表.md docs/当前仓库状态.md docs/工单列表/工单/W-DOCTOR-IGNORE-001.md
```

**未运行**：
- `backend-doctor`（重扫 / 任何 `--fix-*` / `--ci` / `--min-score`）
- `pytest` / `ruff` / `boundary_guard`（纯文档工单）
- `node --version` / `npm --version`（无新依赖）
- `python` 任何脚本（无核算需求）

---

## 5. §11 修订前后对比

### 5.1 修订前（REPORT-FIX-001 版，自相矛盾）

```jsonc
{
  "ignore": {
    "files": [
      ".venv-build/**", ".venv-build-312/**", "node_modules/**",
      "build/**", "dist/**", ".pytest_tmp/**", ".ruff_cache/**",
      ".npmcache/**",
      "web/static/tailwindcdn.js"   // ← 漏 community-site/**
    ],
    "rules": ["security/hardcoded-secret", "node/dead-export"]
  }
}
```

**问题**：§11.1 的 `ignore.files` 没有 `community-site/**`，但 §11.2 仍写"community-site/ 桶 32 条 → 0"——自相矛盾。

### 5.2 修订后（REPORT-FIX-002 版，方案 A）

```jsonc
{
  "ignore": {
    "files": [
      ".venv-build/**", ".venv-build-312/**", "node_modules/**",
      "build/**", "dist/**", ".pytest_tmp/**", ".ruff_cache/**",
      ".npmcache/**",
      "community-site/**",         // ← 增补
      "web/static/tailwindcdn.js"
    ],
    "rules": ["security/hardcoded-secret", "node/dead-export"]
  }
}
```

§11.2 第 2 项 bullet 现为：

> `community-site/` 桶 32 条 → 0（`ignore.files` 排除 `community-site/**`；**与 §7.2「`community-site/` 应有独立扫描」不冲突**——此处仅在 DanmuAI 主仓扫描中静默，`W-DOCTOR-DEPENDENCY-001` 仍需为 `community-site/` 单独起一份 `backend-doctor` 扫描）

§11.2 段末新增 `> ` blockquote：

> **`community-site/**` 已纳入 `W-DOCTOR-IGNORE-001` 的 `ignore.files` 范围**（见 §11.1）。本工单**不**为 `community-site/` 单独规划配置；其独立 `backend-doctor.config.json` 由 `W-DOCTOR-DEPENDENCY-001` 立项时按需建立。

---

## 6. 风险与注意事项

1. **`community-site/**` 静默 ≠ 取消独立扫描**：`W-DOCTOR-DEPENDENCY-001`（待办，低优）仍需立项为 `community-site/` 建立独立 `backend-doctor.config.json`，不能因本工单在主仓静默而认为该问题已闭环。
2. **`backend-doctor.config.json` schema 不在 v0.1.0 公开文档中**：报告 §11.1 给出的是基于惯例的 JSON 形状；`W-DOCTOR-IGNORE-001` 落地前**必须**先用 `npx @zypherhq/backend-doctor init` 看一眼默认输出对齐字段名（**特别**是 `ignore` 还是 `excludes` / `rules` 还是 `disabledRules`）。如字段名不同，**改工单正文与报告 §11.1**，不强行落盘。
3. **不应**为追求"更干净分数"而**扩大** `ignore.files` 范围（如把 `tests/**`、`scripts/**` 整体排除）；`W-DOCTOR-IGNORE-001` §风险点已强调 B 类规则与 B 类文件需人工 review，不应一刀切忽略。
4. **未落盘 `backend-doctor.config.json`**：本工单同样**仅**修订文档，**不**在项目根落盘；落盘由 `W-DOCTOR-IGNORE-001` 单独授权。
5. **A 类（4 条 finding）`actions/checkout@v4` / `actions/setup-python@v5` 未 pin SHA 仍属真实问题**：登记为 `W-CI-DOCTOR-001`（待办，中优），**不**在本次工单修改。
6. **§11.2 的 114 条目标值不变**：增补 `community-site/**` 后，剩余 finding 仍 = 4（A 类）+ 109（B 类）+ 1（D 类 `ci/missing-backend-doctor-gate`）= 114；`--score` 预期 0→50-70 不变。

---

## 7. 发现但未处理的问题（应已写入已知问题文档）

**无 E 类（范围外）问题**。本工单未发现新 ISSUE；所有修正均落在 `docs/` 内部。

REPORT-FIX-001 版报告的"§11.1 与 §11.2 不一致"问题已**通过本工单**纠正，**不**作为 ISSUE 留存（属于本工单链路的内部修正）。

---

## 8. 已更新的文档

- [x] [docs/backend-doctor-scan-report.md](../../backend-doctor-scan-report.md) — §11.1 `ignore.files` 增补 `community-site/**`；§11.2 增补"与 §7.2 不冲突"说明与 `> ` blockquote；§12 追加 REPORT-FIX-002 完成报告条目；§13 元数据追加 REPORT-FIX-002 修订时间线
- [x] [docs/工单列表/工单/W-DOCTOR-IGNORE-001.md](../../工单列表/工单/W-DOCTOR-IGNORE-001.md) — §需求 1 JSON `ignore.files` 增补 `community-site/**`；§验收标准列表增补 `community-site/**`；§风险点 1 措辞由"不要把 `community-site/**` 写进 `ignore.files`"改为"`community-site/**` 已纳入 `ignore.files`（方案 A），与 §7.2 独立扫描不冲突"
- [x] [docs/工单列表.md](../../工单列表.md) — 顶部"最后更新"行；W-ANTISLOP-SCAN-001 行允许修改文件列表追加 REPORT-FIX-002 完成报告；备注显式标注"`ignore.files` 已含 `community-site/**`，方案 A"
- [x] [docs/当前仓库状态.md](../../当前仓库状态.md) — 顶部"最后更新"行；新增「最近变更（W-ANTISLOP-SCAN-001-REPORT-FIX-002）」节
- [x] [docs/templates/Codex完成报告/W-ANTISLOP-SCAN-001-REPORT-FIX-002-完成报告.md](../../templates/Codex完成报告/W-ANTISLOP-SCAN-001-REPORT-FIX-002-完成报告.md) — **本文档**

`docs/已知问题与后续事项.md` **不修改**（本工单无 E 类问题）。

---

## 9. 建议下一个工单

| 工单 ID | 标题 | 优先级 | 范围 | 状态 |
|---------|------|--------|------|------|
| **`W-DOCTOR-IGNORE-001`** | 落地 `backend-doctor.config.json` 忽略配置（含 `community-site/**`） | **高** | 仅 `backend-doctor.config.json` 1 个新文件 + `docs/` 复测对照表 | 待办 |
| `W-DOCTOR-DEPENDENCY-001` | `community-site/` 独立扫描（独立 `backend-doctor.config.json`） | 低 | 仅 `community-site/` | 待办 |
| `W-CI-DOCTOR-001` | `.github/workflows/ci.yml` pin GitHub Actions 到 SHA | 中 | 仅 `.github/workflows/ci.yml`（**前置**：`W-DOCTOR-IGNORE-001`） | 待办 |
| `W-DOCTOR-REVIEW-001` | 复核 B 类 109 条 finding | 低 | 仅 `docs/`（按需追加 `app/`、`web/` 子工单） | 待办 |

**不**擅自实现上述工单。

---

## 10. 验收标准（按 Codex 流程 §6）

- [x] 修改摘要：见 §1
- [x] 修改的文件列表：见 §2（4 个 docs/ 文件修订 + 1 个完成报告新建）
- [x] 未修改的关键区域：见 §3（`app/`、`web/`、`main.py`、`tests/`、`scripts/`、`requirements*.txt`、`.github/`、`backend-doctor.config.json` 均未触碰）
- [x] 运行的命令：见 §4（**仅** `git diff`；**未**运行 `backend-doctor` / pytest / ruff / boundary_guard）
- [x] 构建/测试结果：N/A（**纯文档工单**，无构建/测试影响）
- [x] 手动验证步骤与结果：
  - §11.1 `ignore.files` 现含 10 项（venv × 2、node_modules、build × 2、pytest_tmp、ruff_cache、npmcache、community-site、tailwindcdn.js）
  - §11.2 `community-site/` 桶 32 → 0 预期现与 §11.1 严格对齐
  - §11.2 `> ` blockquote 显式标注 "`community-site/**` 已纳入 `W-DOCTOR-IGNORE-001` 的 `ignore.files` 范围"
  - 4 桶独立统计口径（project / community-site / venv / docs）未变：864 / 32 / 14,767 / 0 = 15,663 ✓
- [x] 风险与注意事项：见 §6（6 项）
- [x] 发现但未处理的问题：见 §7（无 E 类）
- [x] 已更新的文档：见 §8
- [x] 建议下一个工单：见 §9（**不**擅自实现）

---

## 11. 元数据

- **工单 ID**：`W-ANTISLOP-SCAN-001-REPORT-FIX-002`
- **来源工单**：`W-ANTISLOP-SCAN-001-REPORT-FIX-001`（已完成 2026-06-08）
- **类型**：报告修订（非业务代码工单）
- **执行时间**：2026-06-08（UTC+8）
- **完成时间**：2026-06-08（UTC+8）
- **执行者**：Codex / Cursor Agent
- **方法选择**：**方案 A**（在 §11.1 `ignore.files` 增补 `community-site/**`，保留 §11.2 预期）
- **未运行命令**：`backend-doctor`（重扫 / 任何 `--fix-*` / `--ci` / `--min-score`）、`pytest`、`ruff check`、`boundary_guard`、任何 Python 核算脚本
- **产物**：
  - `docs/backend-doctor-scan-report.md`（§11.1 / §11.2 / §12 / §13 修订）
  - `docs/工单列表/工单/W-DOCTOR-IGNORE-001.md`（§需求 1 / §验收标准 / §风险点 1 修订）
  - `docs/工单列表.md`（顶部"最后更新" + W-ANTISLOP-SCAN-001 行修订）
  - `docs/当前仓库状态.md`（顶部"最后更新" + 新增「最近变更（W-ANTISLOP-SCAN-001-REPORT-FIX-002）」节）
- **完成报告路径**：`docs/templates/Codex完成报告/W-ANTISLOP-SCAN-001-REPORT-FIX-002-完成报告.md`

---

## 附录 A. 报告修订链路（README 替代说明）

| 修订版 | 工单 | 核心变化 | 完成报告 |
|--------|------|----------|----------|
| 首版 | `W-ANTISLOP-SCAN-001` | 15,663 finding；首版分类 A2 / B78 / C573 / D207（项目自身 278 实际是 `is_real_source` 过滤 bug） | [W-ANTISLOP-SCAN-001-完成报告.md](W-ANTISLOP-SCAN-001-完成报告.md) |
| 修订版 1 | `W-ANTISLOP-SCAN-001-REPORT-FIX-001` | 桶分离（project 864 / community-site 32 / venv 14,767 / docs 0）；分类修正 A4 / B109 / C565 / D186（项目自身 864）；新增 §11 推荐 `backend-doctor.config.json`（漏 `community-site/**`） | [W-ANTISLOP-SCAN-001-REPORT-FIX-001-完成报告.md](W-ANTISLOP-SCAN-001-REPORT-FIX-001-完成报告.md) |
| 修订版 2 | `W-ANTISLOP-SCAN-001-REPORT-FIX-002` | §11.1 增补 `community-site/**`；与 §11.2 预期 32 → 0 严格对齐；与 §7.2 独立扫描不冲突；明确"已纳入 `W-DOCTOR-IGNORE-001` 的 ignore 范围" | **本文档** |
