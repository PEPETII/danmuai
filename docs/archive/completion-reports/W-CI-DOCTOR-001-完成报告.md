# Codex 完成报告

> 工单 ID：W-CI-DOCTOR-001  
> 完成时间：2026-06-08  
> 执行者：Cursor Agent

---

## 1. 修改摘要

将 [.github/workflows/ci.yml](../../../.github/workflows/ci.yml) 中两个 GitHub Actions 从浮动 major tag（`@v4` / `@v5`）改为 `git ls-remote` 解析的 **40 位完整 commit SHA**，消除 W-DOCTOR-REVIEW-001 复核的 **4 条 A 类** pin finding（`ci/github-action-unpinned` ×2 + `supply-chain/unpinned-github-action` ×2）。

**未接** `backend-doctor --ci` gate（`ci/missing-backend-doctor-gate` 按工单要求保留）。

## 2. 修改的文件

- `.github/workflows/ci.yml`（pin 两行 `uses:`）
- `reports/backend-doctor.json`（复测覆盖）
- `reports/backend-doctor.sarif`（复测覆盖）
- `docs/工单列表.md`（W-CI-DOCTOR-001 标为已完成）
- `docs/当前仓库状态.md`（追加最近变更）
- `docs/templates/Codex完成报告/W-CI-DOCTOR-001-完成报告.md`（本文件）

## 3. 未修改的关键区域

- 未修改 `app/`：**是**
- 未修改 `web/`：**是**
- 未修改 `main.py`：**是**
- 未修改 `tests/`：**是**
- 未修改 `scripts/`：**是**
- 未修改 `requirements*.txt`：**是**
- 未修改 `.backend-doctor.toml`：**是**
- 未新增 backend-doctor CI step：**是**

## 4. 运行的命令

```bash
# 解析 tag → 完整 SHA
git ls-remote https://github.com/actions/checkout.git refs/tags/v4
git ls-remote https://github.com/actions/setup-python.git refs/tags/v5

# 复测
npx --yes @zypherhq/backend-doctor . \
  --json-out reports/backend-doctor.json \
  --sarif reports/backend-doctor.sarif
```

**未执行**：`pytest` / `boundary_guard` / `ruff` / `backend-doctor --ci`

## 5. 构建/测试结果

### Pin 使用的完整 SHA

| Action | 原 tag | 完整 SHA（40 字符） |
|--------|--------|---------------------|
| `actions/checkout` | `v4` | `34e114876b0b11c390a56381ad16ebd13914f8d5` |
| `actions/setup-python` | `v5` | `a26af69be951a213d495a4c3e4e4022e16d87065` |

### backend-doctor 复测（native 规则，与 W-DOCTOR-IGNORE-001 口径一致）

| 检查项 | 修前（W-DOCTOR-IGNORE-001） | 修后 | 目标 |
|--------|---------------------------|------|------|
| native finding 总数 | 240 | **236** | 236 ✓ |
| `ci/github-action-unpinned` | 2 | **0** | 0 ✓ |
| `supply-chain/unpinned-github-action` | 2 | **0** | 0 ✓ |
| `ci/missing-backend-doctor-gate` | 1 | **1** | 仍保留 ✓ |
| A 类（人工复核口径） | 6 | **2** | 2 ✓ |

A 类剩余 2 条：`scripts/community/probe_vercel_bundle.mjs` 外部 fetch 无 timeout（`node/no-timeout-server-or-client` ×2），非本工单范围。

### 全量 JSON 说明

复测 JSON 共 **476** 条 finding（含 **240** 条 `security/codeql/*` 镜像规则，为 v0.1.0 新增输出层）。**native 层** 240→236 与工单预期一致。`security/codeql/ci/github-action-unpinned` 与 `security/codeql/supply-chain/unpinned-github-action` 各仍报 2 条（`ci.yml:15`、`:18`），snippet 已 redacted，疑似镜像层误报；**工单验收以 native `ruleId` 为准**，两项均已归零。

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest | 未运行 | 工单未要求 |
| boundary_guard | 未运行 | 工单未要求 |
| backend-doctor 扫描耗时 | 178.3s | 62 文件 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| `ci.yml` 两行 `uses:` 为 40 位 SHA | 无 `@v4`/`@v5` | 已 pin | 是 |
| native `ci/github-action-unpinned` | 0 | 0 | 是 |
| native `supply-chain/unpinned-github-action` | 0 | 0 | 是 |
| native `ci/missing-backend-doctor-gate` | 1 | 1 | 是 |
| A 类 6→2 | 仅剩 probe timeout | native probe ×2 | 是 |
| 未改 workflow 其它逻辑 | 仅两行 `uses:` | 是 | 是 |

## 7. 风险与注意事项

- **Tag 升级**：`v4`/`v5` 为浮动 major tag；日后升级需重新 `git ls-remote` 并开后续工单。
- **镜像误报**：`security/codeql/*` 层可能对已 pin SHA 仍报 unpinned；后续接 CI gate 时需与负责人确认是否忽略镜像层或等工具修复。
- **Scope 收窄**：工单列表标题含「评估接 `backend-doctor --ci`」；本次按指令仅 pin SHA，gate 留待未来工单。

## 8. 发现但未处理的问题

| 问题 | 简述 | 已记录 |
|------|------|--------|
| — | `probe_vercel_bundle.mjs` timeout ×2（A 类剩余） | 见 W-DOCTOR-REVIEW-001 |
| — | `security/codeql/*` 镜像层 pin 误报 ×4 | 本报告 §5 |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 本完成报告

已检查限制 / 边界入口文件、AGENTS.md、README.md 和相关项目说明文件，本次无需更新。

## 10. 建议下一个工单

- **W-PROBE-TIMEOUT-001**（建议）— `probe_vercel_bundle.mjs` 加 `AbortSignal.timeout(5000)`（A 类剩余 ×2）
- **W-CI-DOCTOR-002**（建议）— 评估接 `backend-doctor --ci` gate 与 `--min-score` 阈值
