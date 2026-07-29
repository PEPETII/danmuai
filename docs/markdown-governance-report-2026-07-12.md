# Markdown 文档治理报告（2026-07-12）

> 工单：`W-DOCS-MARKDOWN-GOVERNANCE-002`  
> 基线 commit：`52f1c8ae626f0ea75af39c60b8225b94708bc074`  
> 状态：执行中；历史文档保留原始结论，仅规范可安全解析的链接。最终数字以重新生成的全量索引和门禁结果为准。

## 1. 范围与方法

### 纳入范围

- 根级项目文档、`.github/` 模板、`.agents/` 技能说明
- `docs/`、`.local-ai/`、`reports/`、`project-prompts/`
- `community/docs/`、`data/`、`prototype/`、`scripts/`、`supabase/`、`tools/` 中的项目 Markdown

### 排除范围

- 依赖与缓存：`.venv*`、`node_modules/`、`build/`、`dist/`、各类 cache
- 第三方/生成内容：`references/`、`.trae/`、`community/site/`、`website/`
- 旧发布产物与训练生成物：`release/`、`gepa_danmu_prompt_training_20260707/`

排除依据是 `.gitignore` 的目录语义和项目所有权，不是因为这些文件不存在。它们不应被 DanmuAI 文档治理任务改写。

### 扫描方式

每个纳入文件均解析：

1. 行数和完整 ATX 标题顺序
2. H1 数量、标题跳级和 800 行风险
3. 本地 Markdown 链接及目标存在性
4. 长段落精确重复组
5. `TODO`、`TBD`、待补建和待确认标记

逐文件结果见 [全量结构索引](../.local-ai/reports/markdown-structure-inventory/README.md)。

## 2. 基线结果

| 指标 | 已确认基线 |
|------|------------|
| 项目自有 Markdown | 863 个（编辑前） |
| 总行数 | 106,975 |
| 本地链接 | 2,661 |
| 失效本地链接 | 1,715 |
| 无 H1/无 ATX 标题 | 32 |
| 多 H1 | 7 |
| 标题跳级 | 1 |
| 完全重复文件 | 0 组 |
| 跨文件精确重复长段落 | 35 组 |
| 待补建/待确认类行 | 173 |

现行入口、模板和活动工单组成的 279 文件子集有 312 个失效本地链接。历史归档是断链大户，但核心入口本身也有真实错误：`AGENTS.md` 34 个、工单工作流 README 8 个、模板 README 9 个。

## 3. 文档层级与逻辑关系

```text
源码事实（main.py / app/）
└─ Boundary Guard 三登记表
   ├─ docs/final-architecture-baseline.md
   ├─ docs/main-pipeline-sequence.md
   └─ docs/runtime-state-map.md
      └─ AGENTS.md（协作与不可违反边界）
         └─ .local-ai/prompts/ai-project-context.md（技术导览）
            ├─ .local-ai/workorders/当前仓库状态.md
            ├─ .local-ai/workorders/工单列表.md
            └─ 当前工单正文
               └─ 完成报告、日期化审计与历史归档
```

### 目录关系

| 区域 | 主要内容 | 当前事实资格 | 处理策略 |
|------|----------|--------------|----------|
| 根级 README/CONTRIBUTING/SECURITY | 用户与贡献入口 | 是 | 修断链和明确流程 |
| `docs/` 三登记表 | 架构守卫输入 | 是 | 必须与源码同步 |
| `docs/` 日期化报告 | 审计快照 | 否 | 保留日期与 successor |
| `.local-ai/prompts/` | Agent 规则、上下文、验收 | 是 | 收口链接和测试规则 |
| `.local-ai/workorders/` 根级 | 当前状态与 backlog | 是 | 控制历史堆积 |
| `active/` | 活动/历史混合 | 需查台账 | 后续归档工单处理 |
| `.local-ai/reports/`、`reports/` | 交付证据 | 仅对应工单 | 不改写历史结果 |
| `scratch/`、`reviews/` | 草稿和审计 | 否 | 只索引，不作当前依据 |

## 4. 已确认的关键冲突

### 4.1 Mixin 数量

- **已确认**：`main.py:98-111` 装配 13 个 Mixin。
- **冲突**：`docs/final-architecture-baseline.md` 和 2026-07-02 架构报告仍写 8 个。
- **处理**：架构基线改为 13；旧六件套标为历史快照，不删除历史分析。

### 4.2 视觉回复过期门控

- **已确认**：`main.py:657` 调用 `_visual_reply_stale_reason()`。
- **已确认**：`app/main_request_context_mixin.py:70-75` 对落后代际返回 `scene_generation_lagged`。
- **冲突**：README FAQ 曾写普通模式不做 `scene_generation` 检查。
- **处理**：改为“不做截图 hash 场景判断，但仍做代际过期门控”。

### 4.3 测试规则

- **已确认**：`AGENTS.md` 与 `IDE_AGENT_RULES.md` 禁止 Agent 本地全量 pytest。
- **冲突**：手动验收指南和状态模板要求 `python -m pytest tests/ -q`。
- **处理**：统一为工单相关文件分批 `-q -x`；全量只允许 CI 或维护者明确执行。

### 4.4 Windows 发布入口

- **已确认**：`docs/operations/PACKAGING_WINDOWS.md:3-5` 是权威入口，并声明四份旧文档已删除。
- **冲突**：项目上下文和 IDE 规则仍把已删除文档列为必读。
- **处理**：保留四个现行入口：打包、IDE 构建、线上验证回滚、周期监控。

## 5. 冗余内容决策

### 已合并

1. `.local-ai/README.md`、工单 README 和模板 README 的目录说明改为单一权威地图。
2. 模板目录不再同时宣称“全是空白模板”又把已填报告当模板；历史示例明确标注。
3. Windows 发布提示文档不再重复已删除契约，统一链接 `PACKAGING_WINDOWS.md`。
4. 测试命令只在 IDE 规则中定义完整约束，其他文档引用该规则并给最小示例。

### 有意保留

- 工单中的固定字段重复：属于可执行契约，不做 DRY 式删除。
- 完成报告中的测试、范围、风险段：属于审计证据，不合并成外部引用。
- 日期化 Bug 审计：保留原始快照，仅在索引标注最新 successor。
- `AGENTS.md` §1-§10 与方法论细化的部分重复：当前属于用户提供的强制规则，本轮不做大段删除。

### 后续应拆分但本轮不物理移动

- `docs/architecture-workorders/workorders.md`（1,588 行）
- `docs/bug-audit-report-2026-06-21.md`（1,467 行）
- `.local-ai/reviews/bug-audit/P3-LOW.md`（1,244 行）
- `active/` 中混放的 22 个完成报告

## 6. 深入补全结果

| 文件/区域 | 缺口 | 本轮动作 |
|-----------|------|----------|
| `AGENTS.md` | 根级/旧目录断链 | 改向 `.local-ai/prompts/` 和 `docs/` 当前文件 |
| `ai-project-context.md` | 8 Mixin、DisplayMixin、memory、旧发布文档 | 对齐当前源码和现行发布入口 |
| 手动验收指南 | 全量 pytest 冲突、缺记录格式 | 改为定向批次并补证据表 |
| 工单/完成报告模板 | 缺基线、证据状态、delta、回滚、消费者 | 新增必填字段 |
| 架构基线 | 8 Mixin、acceptance gates 权限不清 | 改 13 Mixin并说明执行权限 |
| 主链路登记表 | 缺成功/丢弃/退出流程和术语 | 增加流程与 glossary 链接 |
| 运行态映射 | 缺 owner/线程/消费者/示例 | 增加补充表、JSON 示例和维护清单 |
| README | stale 门控错误、缺失法律/英文文件链接 | 修事实；移除不存在链接 |

## 7. 未处理问题

1. 历史路径迁移造成的大量断链仍存在；逐条修复会改写历史证据，应按目录分批开单。
2. 179 个活动工作文件中仅 117 个具备完整模板字段；已完成旧工单不应机械补造当时信息。
3. `SECURITY.md` 缺少可执行私下披露渠道和响应时限，但该文件开工前已有用户改动，本轮不触碰。
4. 根级不存在 `README.en.md` 和 `THIRD_PARTY_NOTICES.md`；本轮移除断链，不编造译文或法律清单。
5. `active/` 与完成报告归档语义混杂，需要独立迁移工单和回滚清单。

## 8. 复核方式

```powershell
# 纯文档范围
git diff --name-only -- "*.md" ":(glob)**/*.md"

# 检查核心断链（本工单使用同一解析逻辑复跑）
python -c "# 见完成报告中的审计命令"
```

完成报告必须记录最终文件数、断链数、结构异常数及相对基线 delta；不能只写“已优化”。

## 9. 完成结果

| 指标（原始 863 文件同口径） | 基线 | 完成后 | Delta |
|-----------------------------|-----:|-------:|------:|
| 总行数 | 106,975 | 106,591 | -384 |
| 本地链接 | 2,661 | 2,576 | -85 |
| 失效本地链接 | 1,715 | 1,244 | -471 |
| 无 H1/无 ATX 标题 | 32 | 26 | -6 |
| 多 H1 | 7 | 7 | 0 |
| 标题跳级 | 1 | 1 | 0 |
| 精确重复长段落组 | 35 | 32 | -3 |

现行入口、5 份权威工单根文档、模板、活动工单和现行发布文档组成的 286 文件子集：**0 个失效本地链接**。`active/` 206 个 Markdown 单独复核同样为 **0**。

说明：早期“279 文件 / 312 断链”子集未正确纳入中文文件名的权威台账，不能作为 286 文件口径的可靠基线；本报告只保留可比较的全量 863 文件 delta 与 `active/` 专项 delta。

`python scripts/boundary_guard.py` 已执行，退出码 0，结果 `Boundary Guard: PASS`。未运行 pytest：本工单未修改业务代码，且仓库禁止 Agent 全量测试。
