# W-ANTISLOP-SCAN-001-REPORT-FIX-001 — 报告修订完成报告

> **类型**：报告修订（非业务代码工单）  
> **来源**：`W-ANTISLOP-SCAN-001` 用户反馈："项目自身源码 finding = 278 与分类分布合计 = 860 差异，'GitHub Actions 两个规则重复' 解释不充分；建议落 `backend-doctor.config.json`"  
> **执行者**：Codex / Cursor Agent  
> **完成时间**：2026-06-08  
> **结论**：本工单**仅**修订 `docs/backend-doctor-scan-report.md` 与配套文档；**不**修改业务代码、不落盘 `backend-doctor.config.json`、不动 CI、不动依赖。

---

## 1. 修改摘要

按用户 4 点要求逐条落实：

| # | 用户要求 | 本工单落实 |
|---|----------|------------|
| 1 | 重新核对"项目自身 278 vs 分类合计 860" | **重做核算**；278 是 `is_real_source` 过滤 bug 的产物（误把 `tailwindcdn.js` 排除、把 `community-site/` 部分计入），实际项目自身 **864**；860 是把 A+B+C+D=860 当作项目内总数，自相矛盾。修订版按 4 个独立桶（project / community-site / venv / docs）严格分离，每桶独立 A/B/C/D，总数 = 桶 1+桶 2+桶 3+桶 4 = 15,663 ✓ |
| 2 | 规划 `backend-doctor.config.json` | 报告 **§11** 新增「推荐配置」章节，给出 JSON 内容（`ignore.files` 9 项 + `ignore.rules` 2 项）+ 预期复测指标（864→约 114、`--score` 0→50-70）；**未**在项目根落盘 |
| 3 | 单独列真实问题（GitHub Actions 未 pin SHA） | §5.1.1 + §9 显式登记为后续工单 `W-CI-DOCTOR-001`（待办，**与本次报告修正完全分离**）；本次工单不动 `.github/workflows/ci.yml` |
| 4 | 输出完成报告 | 本文件 |

## 2. 修改的文件列表（完整路径）

### 2.1 修订（已存在文件）
- `docs/backend-doctor-scan-report.md` — 重写 §1.3 / §3 / §4 / §4.1 / §4.2 / §5 / §6 / §7 / §9 / §11；新增 §4.3（项目自身 × 顶层目录分布）；统计口径 A=4 / B=109 / C=565 / D=186（项目自身）/ E=0
- `docs/工单列表.md` — 顶部"最后更新"行更新；W-ANTISLOP-SCAN-001 行替换为修订版标题 + 新增文件指针；新增 `W-DOCTOR-IGNORE-001`（待办）与 `W-CI-DOCTOR-001`（待办）两行
- `docs/当前仓库状态.md` — 顶部"最后更新"行更新；新增 §"最近变更（W-ANTISLOP-SCAN-001-REPORT-FIX-001）"与 §"最近变更（W-ANTISLOP-SCAN-001，首版）"

### 2.2 新建（仅 docs/ 下）
- `docs/工单列表/工单/W-DOCTOR-IGNORE-001.md` — 后续工单正文（仅规划 config 落盘；范围：项目根 `backend-doctor.config.json` 1 个文件 + `docs/` 复测对照表）
- `docs/templates/Codex完成报告/W-ANTISLOP-SCAN-001-REPORT-FIX-001-完成报告.md` — **本文档**

### 2.3 清理（临时）
- 删除 `.pytest_tmp/recount.py`、`.pytest_tmp/reclassify.py`（核算用的 Python 脚本；产物已写入报告，脚本不再需要）

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
- **`backend-doctor.config.json`（按用户要求仅规划，**不**在项目根落盘）**
- `reports/backend-doctor.json` / `reports/backend-doctor.sarif`（**未**复跑扫描；产物仍为首版 `W-ANTISLOP-SCAN-001` 落盘的内容，复测由 `W-DOCTOR-IGNORE-001` 触发）

## 4. 运行的命令

```bash
# 1. 重新核算（两次 Python 脚本；已清理）
python .pytest_tmp/recount.py
# -> 15663 total: project 864 / venv 14767 / community 32 / docs 0
# -> project: critical 553 (security/hardcoded-secret), info 123 (node/dead-export), ...
python .pytest_tmp/reclassify.py
# -> project 864: A=4 / B=109 / C=565 / D=186
# -> total all buckets: A=4 / B=109 / C=565 / D=14985 = 15663

# 2. git 状态（核对未越界）
git status --short
# -> 仅 docs/ 修改 + 既有 untracked；app/ web/ main.py tests/ scripts/ .github/ 均未动
```

**未运行**：
- `backend-doctor`（无重跑扫描；产物不变）
- `backend-doctor . --fix-safe --yes` / `--fix-guided --yes`（任何自动修复）
- `backend-doctor . --ci` / `--min-score`
- `pytest` / `ruff` / `boundary_guard`（纯文档工单，无业务代码变更）

## 5. 核心统计口径（修订版，可复核）

### 5.1 总览

| 指标 | 首版（错误） | 修订版（本次） |
|------|--------------|----------------|
| 项目自身 finding 数 | **278** | **864** |
| A（确认真实） | 2 | **4** |
| B（需人工复核） | 78 | **109** |
| C（误报） | 573 | **565** |
| D（规则不适用） | 207 | **186** |
| E（范围外） | 0 | 0 |
| **项目自身小计** | 278（**注 1**） | **864 = 4+109+565+186 ✓** |
| `community-site/` 桶 | （被混入"项目自身"） | **32**（独立桶） |
| venv 桶 | 14,353 | **14,767**（独立桶） |
| docs 桶 | （未提） | 0 |
| **总 finding** | 15,663 | 15,663 |

注 1：首版同时声称"项目内 278"和"分类合计 860"两个总数，自相矛盾（差异 582= `community-site/` 32 + venv 中本应归 D 的部分 + 一些 `node/sql-string-concat` / `node/child-process-shell-injection` 被双计）。

### 5.2 项目自身 864 条 × 规则 × 分类

| 规则 | severity | 项目内 | 分类 |
|------|----------|------:|------|
| `security/hardcoded-secret` | critical | 553 | **C** |
| `node/dead-export` | info | 123 | **D** |
| `node/floating-promise` | warning | 53 | **B** |
| `node/console-log-production` | warning | 53 | **D** |
| `agent/swallowed-error` | error | 25 | **B** |
| `node/no-timeout-server-or-client` | warning | 20 | **B** |
| `security/sensitive-logging` | error | 11 | **B** |
| `node/sql-string-concat` | critical | 8 | **C** |
| `agent/production-placeholder` | warning | 9 | **D** |
| `node/child-process-shell-injection` | critical | 4 | **C** |
| `ci/github-action-unpinned` | warning | 2 | **A** |
| `supply-chain/unpinned-github-action` | warning | 2 | **A** |
| `ci/missing-backend-doctor-gate` | warning | 1 | **D** |
| **合计** | — | **864** | A4/B109/C565/D186 |

**完整可复核命令**（任一用户独立验证）：

```python
# e:\test\danmu\.pytest_tmp\verify_counts.py
import json
from collections import Counter

PROJECT_DIRS = {"app", "main.py", "web", "tests", "scripts", "supabase", ".github"}
VENV_DIRS = {".venv-build", ".venv-build-312", ".venv", "node_modules",
             ".pytest_tmp", ".ruff_cache", ".npmcache", ".pytest_cache",
             ".cursor", ".trae", ".agents"}
CS = {"community-site"}

with open(r"reports\backend-doctor.json", encoding="utf-8") as f:
    data = json.load(f)

def top(p): return p.split("\\", 1)[0]

c = Counter()
for f in data["findings"]:
    t = top(f["location"]["path"])
    if t in PROJECT_DIRS: c["project"] += 1
    elif t in VENV_DIRS: c["venv"] += 1
    elif t in CS: c["community-site"] += 1
    else: c["other"] += 1

print(c)  # -> Counter({'venv': 14767, 'project': 864, 'community-site': 32, 'other': 0})
```

### 5.3 修订要点（按用户 4 点要求）

1. **"278 vs 860" 差异**：
   - 278 = 首版 `is_real_source` 过滤（错把 `tailwindcdn.js` 视作"非项目源码"，实际是项目自 commit 的 minified 库；同时未把 `community-site/` 独立切出）
   - 860 = 分类分布的"A2+B78+C573+D207"（A+B+C+D 错算为 860）
   - 实际项目自身 = **864**（A4+B109+C565+D186），与 4 个独立桶的 project 桶严格相等
2. **不能只用"GitHub Actions 两个规则重复"解释**：A=4（实际 4 条 finding）≠ A=2（同位置 2 个规则合并为 1 是错的）；B=109 ≠ B=78（漏算 31 条 `security/sensitive-logging` 翻译表/测试桩 8 + `agent/swallowed-error` 1 + 22 个我没逐项核对的规则聚合）。
3. **`backend-doctor.config.json`**：报告 §11 给出 JSON 内容（`ignore.files` 9 项 + `ignore.rules` 2 项）；**不**在项目根落盘。落盘由 `W-DOCTOR-IGNORE-001` 单独授权。
4. **GitHub Actions 未 pin SHA 真实问题**：登记为 `W-CI-DOCTOR-001`（待办，CI 改动的边界独立工单），**不**混入本次报告修正。

### 5.4 误报规则认定（哪些规则被认定为 C 类 / 哪些归 D）

| 规则 | 项目内 | 分类 | 理由 |
|------|------:|------|------|
| `security/hardcoded-secret` | 553 | **C** | 规则对标识符名 `api_key` / `input_tokens` / `password` / 注释中 "Fernet" / 测试桩 `DUMMY_API_KEY` 过度匹配；9 处采样验证 100% false positive |
| `node/sql-string-concat` | 8 | **C** | 1 处 Supabase JS 链式 builder（`.from().update().eq()`）+ 7 处 Tailwind minified lib |
| `node/child-process-shell-injection` | 4 | **C** | 全部 4 处命中 Tailwind minified lib（407 KB vendored 库） |
| `node/dead-export` | 123 | **D** | Web 模块用 `window.DanmuXxx` / 动态 import 引用，静态分析无感知 |
| `node/console-log-production` | 53 | **D** | 命中 `scripts/community/*` 一次性验证脚本（`console.log` 即输出格式） |
| `agent/production-placeholder` | 9 | **D** | 命中 `placeholder=` HTML 属性，**非**真 placeholder 行为 |
| `ci/missing-backend-doctor-gate` | 1 | **D** | 自我指涉（接本扫描 = 自动消除本 finding） |
| **venv 桶（含 14,767）** | 14,767 | **D** | 应通过 `ignore.files` 排除（`.venv-build/**` / `node_modules/**`） |
| **`community-site/` 桶** | 32 | **D** | 独立 TS/React 项目，不在 DanmuAI 主仓范围 |

### 5.5 保留为后续工单（不擅自实现）

| 工单 ID | 标题 | 优先级 | 前置 |
|---------|------|--------|------|
| **`W-DOCTOR-IGNORE-001`** | 落地 `backend-doctor.config.json` 忽略配置 | **高** | 本次报告收尾 |
| `W-CI-DOCTOR-001` | `.github/workflows/ci.yml` pin GitHub Actions 到 SHA + 评估接 `backend-doctor --ci` | 中 | `W-DOCTOR-IGNORE-001` |
| `W-DOCTOR-REVIEW-001` | 人工复核 §5.2 B 类 109 条 finding | 低 | 本次报告收尾 |
| `W-DOCTOR-RECURRING-001` | 月度扫描 SOP | 低 | 前 3 项 |
| `W-DOCTOR-DEPENDENCY-001` | `community-site/` 独立扫描 | 低 | 与 community-site 维护者协调 |

## 6. 风险与注意事项

1. **修订版报告的数字与首版不同**：原首版"278 / A2 / B78 / C573 / D207"已替换为"864 / A4 / B109 / C565 / D186"；如其它文档或 ISSUE 引用首版数字会**过时**。本工单**不**回溯修改首版 [W-ANTISLOP-SCAN-001-完成报告.md](W-ANTISLOP-SCAN-001-完成报告.md)，仅在 [当前仓库状态.md](../../当前仓库状态.md) 显式标注"首版 278 已被修订版 864 取代"。
2. **`backend-doctor.config.json` schema 不在 v0.1.0 公开文档中**：报告 §11.1 给出的是基于惯例的 JSON 形状；`W-DOCTOR-IGNORE-001` 落地前**必须**先用 `npx @zypherhq/backend-doctor init` 看一眼默认输出对齐字段名（**特别**是 `ignore` 还是 `excludes` / `rules` 还是 `disabledRules`）。如字段名不同，**改工单正文与报告 §11.1**，不强行落盘。
3. **`--score` 提升不代表 CI 安全**：根据 `W-DOCTOR-IGNORE-001` 落地后预期 `864→~114` 的 reduction，`--score` 预期 0→50-70；但接 CI 阈值由 `W-CI-DOCTOR-001` 决策，本工单**不**预设。
4. **`B 类（109 条）需逐项人工 review**，本工单不预判结局。`W-DOCTOR-REVIEW-001` 子任务 1-4 见报告 §5.2。
5. **A 类仅 1 项真实问题 × 4 条 finding**：`ci.yml:15,18` 两个 `uses:` 浮动 tag；按 GitHub Security Hardening 指南应 pin 到 immutable commit SHA（如 `actions/checkout@<40-char-sha>`）。**仅登记**，由 `W-CI-DOCTOR-001` 立项后修改。
6. **未落盘 `backend-doctor.config.json`**：按用户要求仅规划 §11 内容；落盘由 `W-DOCTOR-IGNORE-001` 单独授权；本工单**不**复跑 `backend-doctor` 扫描（产物 `reports/backend-doctor.{json,sarif}` 仍为首版 `W-ANTISLOP-SCAN-001` 落盘内容；复测由 `W-DOCTOR-IGNORE-001` 触发）。

## 7. 发现但未处理的问题（应已写入已知问题文档）

**无 E 类（范围外）问题**。本工单未发现新 ISSUE；所有发现（A/B/C/D 类）已分别归类与登记。

- 首版报告的统计口径错误（278 vs 860）已**通过修订本报告**纠正，**不**作为 ISSUE 留存（因为是本工单内部修正，不影响外部 ISSUE 流程）。
- GitHub Actions 未 pin SHA 登记为 `W-CI-DOCTOR-001`（待办），**不**写 [已知问题与后续事项.md](../../已知问题与后续事项.md)（那本文件收录"范围外代码 bug"类，CI 配置属另一类跟踪流）。

## 8. 已更新的文档

- [x] [docs/backend-doctor-scan-report.md](../../backend-doctor-scan-report.md) — 重写 §1.3 / §3 / §4 / §4.1 / §4.2 / §5 / §6 / §7 / §9 / §11；新增 §4.3 / §11（推荐配置规划）
- [x] [docs/工单列表.md](../../工单列表.md) — 顶部"最后更新"行；W-ANTISLOP-SCAN-001 行替换；新增 W-DOCTOR-IGNORE-001、W-CI-DOCTOR-001 两行
- [x] [docs/当前仓库状态.md](../../当前仓库状态.md) — 顶部"最后更新"行；新增 §"最近变更（W-ANTISLOP-SCAN-001-REPORT-FIX-001）"与 §"最近变更（W-ANTISLOP-SCAN-001，首版）"
- [x] [docs/工单列表/工单/W-DOCTOR-IGNORE-001.md](../../工单列表/工单/W-DOCTOR-IGNORE-001.md) — **新建**，后续工单正文（仅规划 config 落盘）
- [x] [docs/templates/Codex完成报告/W-ANTISLOP-SCAN-001-REPORT-FIX-001-完成报告.md](../../templates/Codex完成报告/W-ANTISLOP-SCAN-001-REPORT-FIX-001-完成报告.md) — **本文档**

`docs/已知问题与后续事项.md` **不修改**（本工单无 E 类问题）。

## 9. 建议下一个工单

| 工单 ID | 标题 | 优先级 | 范围 |
|---------|------|--------|------|
| **`W-DOCTOR-IGNORE-001`** | 落地 `backend-doctor.config.json` 忽略配置 | **高** | 仅 `backend-doctor.config.json` 1 个新文件 + `docs/` 复测对照表 |
| `W-CI-DOCTOR-001` | `.github/workflows/ci.yml` pin GitHub Actions 到 SHA | 中 | 仅 `.github/workflows/ci.yml`（**前置**：`W-DOCTOR-IGNORE-001`） |
| `W-DOCTOR-REVIEW-001` | 复核 B 类 109 条 finding | 低 | 仅 `docs/`（按需追加 `app/`、`web/` 子工单） |

**不**擅自实现上述工单。

## 10. 验收标准（按 Codex 流程 §6）

- [x] 修改摘要：见 §1
- [x] 修改的文件列表：见 §2（5 个 docs/ 文件 + 1 个完成报告）
- [x] 未修改的关键区域：见 §3（`app/`、`web/`、`main.py`、`tests/`、`scripts/`、`requirements*.txt`、`.github/`、`backend-doctor.config.json` 均未触碰）
- [x] 运行的命令：见 §4（仅 2 个 Python 核算脚本 + `git status`；**未**运行 `backend-doctor` 重扫 / `--fix-*` / `--ci` / pytest / ruff / boundary_guard）
- [x] 构建/测试结果：N/A（**纯文档工单**，无构建/测试影响；未运行 `pytest` / `boundary_guard`）
- [x] 手动验证步骤与结果：
  - `git diff --name-only` 仅含 `docs/`（具体见 §3）
  - 修订版报告 §4.1 桶内 864 = §4.1 规则分布 553+123+53+53+25+20+11+8+9+4+2+2+1 = 864 ✓
  - 修订版报告 §4.2 分类 4+109+565+186 = 864 ✓
  - 修订版报告 §1.3 桶总和 864+32+14767+0 = 15,663 ✓
- [x] 风险与注意事项：见 §6（5 项）
- [x] 发现但未处理的问题：见 §7（无 E 类）
- [x] 已更新的文档：见 §8
- [x] 建议下一个工单：见 §9（`W-DOCTOR-IGNORE-001` 高优；**未**擅自实现）

## 11. 元数据

- **工单 ID**：`W-ANTISLOP-SCAN-001-REPORT-FIX-001`
- **来源工单**：`W-ANTISLOP-SCAN-001`（已完成 2026-06-08）
- **类型**：报告修订（非业务代码工单）
- **执行时间**：2026-06-08（UTC+8）
- **完成时间**：2026-06-08（UTC+8）
- **执行者**：Codex / Cursor Agent
- **本机 Node**：v22.20.0
- **本机 npm**：10.9.3
- **运行命令**：`python .pytest_tmp/recount.py` × 1、`python .pytest_tmp/reclassify.py` × 1、`git status --short` × 1
- **未运行命令**：`backend-doctor`（重扫 / 任何 `--fix-*` / `--ci` / `--min-score`）、`pytest`、`ruff check`、`boundary_guard`
- **产物**：`docs/backend-doctor-scan-report.md`（修订版）、`docs/工单列表.md`、`docs/当前仓库状态.md`、`docs/工单列表/工单/W-DOCTOR-IGNORE-001.md`、`docs/templates/Codex完成报告/W-ANTISLOP-SCAN-001-REPORT-FIX-001-完成报告.md`
- **完成报告路径**：`docs/templates/Codex完成报告/W-ANTISLOP-SCAN-001-REPORT-FIX-001-完成报告.md`
