# Markdown 文档优化修改摘要（2026-06-24 历史记录）

> 本文件只记录 W-DOCS-MARKDOWN-OPT-001 当时的 15 文件抽查；其中“不存在文件”清单已过时，不得作为当前文档状态。最新全量治理见 [2026-07-12 Markdown 文档治理报告](markdown-governance-report-2026-07-12.md)。

**生成日期：** 2026-06-24  
**工单：** W-DOCS-MARKDOWN-OPT-001  
**范围：** 15 个关键 Markdown 文件（根级 6 + 子项目 8 + docs/ 1）

---

## 统计数据

| 指标 | 数量 |
|------|------|
| 纳入优化文件数 | 15 |
| 实际修改文件数 | 5 |
| 未修改文件数（已符合规范） | 10 |
| 新生成文件数 | 1（本摘要） |
| 代码块格式修复 | 4 处 |
| 标题层级修复 | 1 处 |
| 段落可读性优化 | 2 处 |
| 链接路径修复（绝对→相对） | 18 处 |
| 表格渲染修复 | 4 个表格 |
| 链接验证总数 | 40+ |
| 占位链接保留（不修改） | 15+ |
| 需人工判断链接（不存在的非占位链接） | 14 |

---

## 每文件变更摘要

### 1. `README.md` — 已修改

| 类别 | 变更 |
|------|------|
| 格式 | **修复关键 bug**：第 63-66 行 ```bash 代码块未闭合，且 `> 说明：...` 块引用误嵌于代码块内。现已在 `pip install -r requirements-dev.txt` 行后正确闭合代码块，`> 说明：...` 作为独立块引用置于代码块之后。 |
| 内容 | 无拼写/标点错误；技术术语、配置键名、命令行参数原文未改动。 |
| 可读性 | 无超长段落需拆分；标题层级无跳级。 |
| 链接 | 14 个指向不存在文件的链接（`docs/WEB_CONSOLE.md` 等）保留未改，标记为「需人工判断」。 |

### 2. `AGENTS.md` — 已修改

| 类别 | 变更 |
|------|------|
| 格式 | 代码块语言标注、标题层级、表格空行、列表缩进均无问题，未改。 |
| 内容 | 未增删任何技术内容（模块表、reason= 表、环境变量表、配置键名全部原样保留）。 |
| 可读性 | **§7 验证规则**：将一个超长段落（含 3 个要点）拆分为 3 个独立短段。**§9 item 8**：将「视觉请求看门狗」列表项拆分为主项 + 子项结构，与同节 item 1 模式一致。 |
| 链接 | 所有占位链接 100% 保留（`../workorders/...` 5 处、`templates/...` 4 处、6 个待根级协作文档、`../docs/...` 路径均未触碰）。 |

### 3. `CONTRIBUTING.md` — 未修改

格式、内容、链接均已符合规范，无需改动。

### 4. `CODE_OF_CONDUCT.md` — 未修改

标准 Contributor Covenant 2.1（英文），格式正确，无需改动。

### 5. `SECURITY.md` — 未修改

格式、表格、链接均已符合规范，无需改动。

### 6. `claude.md` — 未修改

操作指令文件，格式已最优（标题层级正确、列表一致、无代码块），无需改动。

### 7. [`scripts/README.md`](../scripts/README.md) — 未修改

代码块均带语言标注（bash/powershell），标题层级正确，无需改动。

### 8. `community/README.md` — 已修改

| 类别 | 变更 |
|------|------|
| 格式 | 目录结构代码块添加 `text` 语言标注（原为无标注的 ` ``` `）。 |

### 9. `data/README.md` — 未修改

文件简短且格式正确，无需改动。

### 10. `data/ATTRIBUTION.md` — 未修改

文件简短且格式正确，无需改动。

### 11. `prototype/README.md` — 未修改

格式正确，不存在的链接 `../docs/archive/qt6_ui_redesign_plan.md` 按规则保留。

### 12. `supabase/README.md` — 已修改（重大修复）

| 类别 | 变更 |
|------|------|
| 格式 | **修复表格渲染失败**：4 个表格的行之间被空行打断导致渲染失败，现移除空行使表格连续可渲染。 |
| 格式 | 移除列表项之间的多余空行（松散列表改为紧凑列表）。 |
| 格式 | 移除段落和标题之间的多余空行（原有多达 3 行连续空行）。 |
| 格式 | **标题层级修复**：`### 桌面端凭证配置` 改为 `## 桌面端凭证配置`（原从 `#` 跳级到 `###`）。 |
| 内容 | SQL 代码块内部的空行按规则保留不变。 |
| 链接 | 不存在的 `../docs/operations/RELEASE_CHECKLIST.md` 链接按规则保留。 |

### 13. `tools/bililive_dm_plugin_mock/README.md` — 已修改

| 类别 | 变更 |
|------|------|
| 格式 | 3 个目录树/路径代码块添加 `text` 语言标注（原为无标注的 ` ``` `）。 |

### 14. `tools/bililive_dm_plugin_mock/MODULE_OVERVIEW.md` — 已修改

| 类别 | 变更 |
|------|------|
| 链接 | **将 18 处机器特定绝对路径转换为相对路径**：`/E:/test/danmu/tools/bililive_dm_plugin_mock/src/DanmuAiMockPlugin.cs` → `src/DanmuAiMockPlugin.cs`；`/E:/test/danmu/app/web_api/bililive_dm_bridge.py` → `../../app/web_api/bililive_dm_bridge.py`；`/E:/test/danmu/main.py` → `../../main.py` 等。 |

### 15. `docs/DanmuAI性能优化分析报告.md` — 未修改

格式规范（代码块均带语言标注 python/javascript/html/bash），标题层级正确，技术数据未改动。

---

## 异常清单（需人工判断）

以下链接指向不存在的文件，且非 AGENTS.md 中标记的「待补建」占位链接。已保留原文未修改，建议人工判断是创建对应文件还是移除链接。

### README.md 中的失效链接（14 个）

| 链接路径 | 说明 |
|----------|------|
| `docs/WEB_CONSOLE.md` | Web 控制台文档，未创建 |
| `docs/ROADMAP.md` | 路线图文档，未创建 |
| `docs/ARCHITECTURE.md` | 架构总览文档，未创建 |
| `docs/CONTRIBUTING_ARCHITECTURE.md` | 贡献者架构边界文档，未创建 |
| `docs/MAIN_PIPELINE.md` | 主链路文档，未创建 |
| `docs/PRIVACY.md` | 隐私说明文档，未创建 |
| `docs/README.md` | 文档索引，未创建 |
| `docs/CHANGELOG.md` | 变更日志，未创建 |
| `docs/OPEN_SOURCE_AUDIT.md` | 开源审计文档，未创建 |
| `docs/operations/WINDOWS_CODE_SIGNING.md` | Windows 代码签名文档，未创建 |
| `docs/operations/PACKAGING_WINDOWS.md` | Windows 打包文档，未创建 |
| `docs/operations/RELEASE_CHECKLIST.md` | 发布检查清单，未创建 |
| `THIRD_PARTY_NOTICES.md` | 第三方组件许可证，未创建 |
| `README.en.md` | 英文概要，未创建 |

### 其他文件中的失效链接（3 个）

| 文件 | 链接路径 | 说明 |
|------|----------|------|
| `scripts/README.md` | `../docs/operations/PACKAGING_WINDOWS.md` | 同上，未创建 |
| `prototype/README.md` | `../docs/archive/qt6_ui_redesign_plan.md` | 归档目录未创建 |
| `supabase/README.md` | `../docs/operations/RELEASE_CHECKLIST.md` | 同上，未创建 |

### 结构性问题（2 个）

| 文件 | 问题 | 说明 |
|------|------|------|
| `tools/bililive_dm_plugin_mock/README.md` | §4 缺少 `### 4.1` 标题 | 第 4 节有 `### 4.2` 但无 `### 4.1`，原文结构问题，未添加标题（按「不增删技术内容」规则） |
| `README.md` | 目录树代码块内含 markdown 链接 | 第 229 行的 `text` 代码块曾写入 `scripts/README.md` 的 Markdown 链接语法；代码块内不会渲染，属呈现选择 |

---

## 占位链接清单（AGENTS.md，已知待补建，未修改）

以下链接在 AGENTS.md 中已明确标注为「待补建」，本次优化 100% 保留原文。

### 待 workorders/ 目录补建（5 处）

- `../workorders/README.md`
- `../workorders/工单列表.md`
- `../workorders/当前仓库状态.md`
- `../workorders/已知问题与后续事项.md`
- `../workorders/设计更新说明.md`

### 待 templates/ 目录补建（4 处）

- `templates/工单/工单模板.md`
- `templates/Codex完成报告/Codex完成报告模板.md`
- `templates/Codex执行提示词/Codex执行提示词模板.md`
- `templates/已知问题记录/已知问题记录模板.md`

### 待根级协作文档补建（6 处）

- `ai-project-context.md`
- `IDE_AGENT_RULES.md`
- `手动验收指南.md`
- `Codex提示词手册.md`
- `Codex工单交接模板.md`
- `提示词上下文包.md`

### 已知路径问题（AGENTS.md 顶部注脚已记录）

AGENTS.md 位于仓库根，但其中 `../docs/...` 路径实际指向仓库外（应为 `docs/...`）。此问题已在 AGENTS.md 顶部「链接与目录说明（2026-06-21 校正）」注脚中记录，本次优化未修正（注脚说明「Codex 可忽略其内容做无副作用阅读」）。

---

## 验证结果

### git diff 验证

`git diff --name-only` 显示 4 个已跟踪文件被修改（均为 Markdown）：

```
README.md
supabase/README.md
tools/bililive_dm_plugin_mock/MODULE_OVERVIEW.md
tools/bililive_dm_plugin_mock/README.md
```

另外 2 个已修改文件不在 git diff 中，原因：
- `AGENTS.md`：未被 git 跟踪（`git ls-files` 返回空），但磁盘文件已修改（§7 段落拆分、§9 item 8 主子项拆分已验证）。
- `community/README.md`：被 `.gitignore` 忽略（`git check-ignore` 确认），但磁盘文件已修改（代码块添加 `text` 语言标注已验证）。

新增 1 个未跟踪文件：`docs/markdown-optimization-summary.md`（本摘要）。

**结论**：仅 Markdown 文件被改动，未触及任何代码文件（`.py`、`.js`、`.html` 等）。

### 抽检验证

| 文件 | 验证点 | 结果 |
|------|--------|------|
| `README.md` | 第 63-66 行代码块闭合修复 | ✅ 代码块在 line 66 正确闭合，`> 说明：` 在 line 68 作为独立块引用 |
| `supabase/README.md` | 表格渲染修复 | ✅ 4 个表格行间空行已移除，表格连续可渲染；标题层级 `##` 修复 |
| `MODULE_OVERVIEW.md` | 绝对路径转相对路径 | ✅ `/E:/test/danmu/...` 已转为 `src/...`、`../../app/...` 等相对路径 |
| `AGENTS.md` | §7 段落拆分 + §9 item 8 主子项 | ✅ 3 段独立 + 主项/子项结构 |
| `community/README.md` | 代码块语言标注 | ✅ ```text 标注已添加 |

### 摘要文件完整性

✅ 本摘要包含：每文件变更分类、异常清单、占位链接清单、统计数据、验证结果。
