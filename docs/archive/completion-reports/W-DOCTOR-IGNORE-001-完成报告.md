# Codex 完成报告

> 工单 ID：W-DOCTOR-IGNORE-001  
> 完成时间：2026-06-08  
> 执行者：Cursor Agent

---

## 1. 修改摘要

落地 `backend-doctor v0.1.0` 实际支持的忽略配置：项目根新增 `.backend-doctor.toml`（TOML），`disabled-rules` 禁用 `security/hardcoded-secret` 与 `node/dead-export` 两条已确认 C/D 类规则。

**schema 修正**：原报告 §11.1 规划的 `backend-doctor.config.json` + `ignore.files`/`ignore.rules` **不被 v0.1.0 消费**；经 `npx @zypherhq/backend-doctor init --yes` 实测，工具仅生成 TOML + `disabled-rules`。已按工单 §风险点同步修正工单正文与报告 §11。

复测 finding 从 **15,663 降至 240**（两目标规则归零）；`caps` 已清空（无 `raw secret` cap）。`--score` 仍为 **0**（security/correctness/maintainability 分类分仍为 0）。venv / community-site / tailwindcdn.js 桶仍有残留（37 / 14 / 19），因 v0.1.0 **不支持文件级 ignore**。

## 2. 修改的文件

- `.backend-doctor.toml`（**新建**，项目根）
- `docs/backend-doctor-scan-report.md`（§11 替换为 TOML 实际内容；新增 §11.4 工具限制、§11.5 复测对照表）
- `docs/工单列表/工单/W-DOCTOR-IGNORE-001.md`（§需求 1 / §验收标准 / §风险点按 TOML schema 修正）
- `docs/工单列表.md`（W-DOCTOR-IGNORE-001 标为已完成）
- `docs/当前仓库状态.md`（追加「最近变更（W-DOCTOR-IGNORE-001）」节）
- `reports/backend-doctor.json`（覆盖复测产物，6,570,196 字节）
- `reports/backend-doctor.sarif`（覆盖复测产物，191,013 字节）
- `docs/templates/Codex完成报告/W-DOCTOR-IGNORE-001-完成报告.md`（本文件）

## 3. 未修改的关键区域

- 未修改 `app/`：**是**
- 未修改 `web/`：**是**
- 未修改 `main.py`：**是**
- 未修改 `tests/`：**是**
- 未修改 `scripts/`：**是**
- 未修改 `.github/workflows/ci.yml`：**是**
- 未修改 `requirements*.txt`、`AGENTS.md`、`.gitignore`：**是**
- 未修改任何 git 跟踪的 Python / JS / CSS / HTML 业务源文件：**是**

## 4. 运行的命令

```bash
# schema 探测
npx --yes @zypherhq/backend-doctor init --yes   # → 生成 .backend-doctor.toml（TOML，非 JSON）

# 复测（有 .backend-doctor.toml）
npx --yes @zypherhq/backend-doctor . --score
# → 0

npx --yes @zypherhq/backend-doctor . \
  --json-out reports/backend-doctor.json \
  --sarif reports/backend-doctor.sarif
# → 240 issues across 62 files in 32.2s

# 指标解析
python -c "..."  # 见 §5
```

**未执行**：`--fix-safe --yes` / `--fix-guided --yes` / `--ci` / `--min-score` / `pytest` / `ruff` / `boundary_guard`

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest | 未运行 | 工单明确不要求 |
| boundary_guard | 未运行 | 工单明确不要求 |
| backend-doctor --score | 0 | `caps=[]`（cap 已解除）；label=Critical |
| backend-doctor 复测 | **240 finding** | 首扫 15,663；降幅 98.5% |
| `security/hardcoded-secret` | **0** | 目标达成 ✓ |
| `node/dead-export` | **0** | 目标达成 ✓ |
| venv 桶 | **37** | 未达成（工具不支持文件级 ignore） |
| `community-site/` 桶 | **14** | 未达成 |
| `tailwindcdn.js` | **19** | 未达成 |
| 项目自身桶 | **170** | 可行动范围 |
| 扫描耗时 | 32.2s | 首扫 149.8s |
| JSON 大小 | 6,570,196 B | 首扫 25,886,127 B |
| SARIF 大小 | 191,013 B | 首扫 12,291,311 B |

### 复测 top 规则（240 条）

| 规则 | finding 数 | 原分类 |
|------|----------:|--------|
| `node/floating-promise` | 58 | B |
| `node/console-log-production` | 58 | D |
| `agent/swallowed-error` | 30 | B |
| `agent/production-placeholder` | 26 | D |
| `node/no-timeout-server-or-client` | 22 | B |
| `security/sensitive-logging` | 20 | B |
| `node/sql-string-concat` | 8 | C |
| `node/child-process-shell-injection` | 4 | C |
| `ci/github-action-unpinned` + `supply-chain/unpinned-github-action` | 4 | A |
| `ci/missing-backend-doctor-gate` | 1 | D |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1. `Get-Content .backend-doctor.toml` | 含 `disabled-rules` 两项 | TOML 合法，两项规则 | 是 |
| 2. `npx @zypherhq/backend-doctor --version` | `0.1.0` | `0.1.0` | 是 |
| 3. `npx @zypherhq/backend-doctor . --score` | 数字 | `0`（caps 已清空） | 部分（分数未回升，但 cap 解除） |
| 4. `Test-Path reports\backend-doctor.json` | True | True（已覆盖） | 是 |
| 5. Python 解析 JSON | 两规则=0；总 finding 大幅下降 | 240 total；两规则=0 | 是 |
| 6. venv/community-site/tailwindcdn 桶 | 原规划=0 | 37/14/19 | 否（工具限制） |
| 7. 未跑 `--fix-safe`/`--ci` | 未执行 | 未执行 | 是 |

## 7. 风险与注意事项

1. **文件级 ignore 不可用**：venv（37）、community-site（14）、tailwindcdn.js（19）仍被报；接 CI 前须评审是否接受 240 finding 基线，或等上游工具升级。
2. **扫描模式变化**：有 `.backend-doctor.toml` 时 backend-doctor 走项目图模式（`monorepo: true`），总 finding 与首扫桶统计**不可直接横比**。
3. **`--score` 仍为 0**：虽 `caps` 已清空，但 security/correctness/maintainability 分类分仍为 0；**不建议**立刻 `--ci --min-score 80`。
4. **勿扩大 `disabled-rules`**：B 类 109 条（floating-promise、swallowed-error 等）须 `W-DOCTOR-REVIEW-001` 人工复核后再决定是否忽略。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| （待登记） | `backend-doctor v0.1.0` 不支持 `ignore.files` 文件级 glob 排除；venv/community-site/tailwindcdn 桶仍有残留 | 否（记入本报告；负责人可决定是否写入 `docs/已知问题与后续事项.md`） |
| （待登记） | 原规划「剩余 finding ≈ 114」基于 JSON `ignore.files` 假设，实际复测为 240 | 否（已在本报告与报告 §11.5 说明） |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/backend-doctor-scan-report.md](../../backend-doctor-scan-report.md)（§11.4/§11.5）
- [x] [docs/工单列表/工单/W-DOCTOR-IGNORE-001.md](../../工单列表/工单/W-DOCTOR-IGNORE-001.md)
- [x] [docs/templates/Codex完成报告/W-DOCTOR-IGNORE-001-完成报告.md](W-DOCTOR-IGNORE-001-完成报告.md)（本文件）

已检查限制 / 边界入口文件、AGENTS.md、README.md 和相关项目说明文件，本次无需更新（仅新增扫描工具配置 + 文档同步，不改变运行行为或 API）。

## 10. 建议下一个工单

- **`W-CI-DOCTOR-001`**：评审是否以 240 finding 为 CI 基线接入 `backend-doctor --ci`；须先 pin GitHub Actions SHA（A 类 4 条）
- **`W-DOCTOR-REVIEW-001`**：人工复核 B 类 finding（floating-promise ×58、swallowed-error ×30、sensitive-logging ×20、no-timeout ×22）
- **`W-DOCTOR-DEPENDENCY-001`**：`community-site/` 独立扫描与独立 `.backend-doctor.toml`
