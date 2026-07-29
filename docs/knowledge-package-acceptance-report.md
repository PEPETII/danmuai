# 知识包功能验收报告（Wave 5）

| 字段 | 值 |
|------|-----|
| 日期 | 2026-07-23 |
| Git SHA | `0260597`（完整 `02605979d4c373cdbf24656b9ed2ba93663a7897`） |
| 结论 | **有条件通过** |

---

## 1. 测试环境

| 项 | 值 |
|----|-----|
| OS | Windows（win32） |
| Python | 3.14.0 |
| 工作目录 | `E:\test\danmu` |
| 真实 UI / 主程序手测 | **未执行**（本波次以自动化为主） |
| 真实 LLM / 外网抓取 | **未执行**（import 路径 mock `organize_chunk`） |

---

## 2. 变更范围（Waves 1–5 摘要）

### Wave 1 — 真实场景上下文
- `app/knowledge/runtime_service.py`：`build_knowledge_scene_context`、禁止 `round=`/`screenshot=` 占位
- `app/knowledge/models.py`：`KnowledgeSceneContext`、`KnowledgeInjectionResult`
- `app/main_request_context_mixin.py`：`_build_knowledge_scene_context` / `_inject_knowledge_prompt` 走真实语义；注入即 `mark_items_used`
- `tests/test_knowledge_scene_context.py`、pipeline 集成扩展

### Wave 2 — TXT/MD base64 导入与校验
- import / extractor / API 对 `txt` / `markdown` + `content_base64` 的校验与创建 source 前检查
- 相关：`import_service`、`source_extractors`、`test_knowledge_api` / extractors

### Wave 3 — Job 状态与 UI 刷新映射
- 任务状态流转与 source status 映射（控制台轮询/刷新路径；自动化覆盖 API job 状态）

### Wave 4 — 跨导入去重、livestream_chat、package scope
- `app/knowledge/deduplicator.py`、`chunker.py`（`livestream_chat`）
- `app/knowledge/retriever.py`：`package_scope_allows` / tagged scope 过滤
- repository `content_kind` 归一化

### Wave 5 — 生产路径 E2E + 验收报告（本波）
- **新增** `tests/test_knowledge_e2e_production.py`（调用 `DanmuApp._build_visual_prompts` + API 导入全链路）
- **修复** 与当前实现漂移的 2 个单测：
  - `test_knowledge_database.py`：content 上限按模型 `max_length=500` 断言
  - `test_knowledge_ai_organizer.py`：`max_output_tokens` 与 `_ORGANIZE_MAX_OUTPUT_TOKENS=8192` 对齐
- **新增** 本报告 `docs/knowledge-package-acceptance-report.md`

### 核心生产文件（知识包子系统，历波累计）

```
app/knowledge/{__init__,models,database,migrations,repository,chunker,
  normalizer,validator,deduplicator,ai_organizer,import_service,
  source_extractors,retriever,prompt_builder,runtime_service}.py
app/main_request_context_mixin.py   # 注入入口
main.py                             # _build_visual_prompts 调用注入
app/web_api/knowledge*.py           # REST
```

---

## 3. 自动化测试结果

### 3.1 知识包全量相关（Wave 5 门控）

命令：

```text
python -m pytest tests/test_knowledge_pipeline_integration.py tests/test_knowledge_scene_context.py tests/test_knowledge_api.py tests/test_knowledge_import_service.py tests/test_knowledge_deduplicator.py tests/test_knowledge_chunker.py tests/test_knowledge_retriever.py tests/test_knowledge_extractors.py tests/test_knowledge_diagnostics.py tests/test_knowledge_integration.py tests/test_knowledge_validator.py tests/test_knowledge_database.py tests/test_knowledge_ai_organizer.py tests/test_knowledge_e2e_production.py -q --tb=line
```

结果：

```text
396 passed in 34.82s
```

### 3.2 Wave 5 生产路径 E2E（单独）

命令：

```text
python -m pytest tests/test_knowledge_e2e_production.py -q --tb=short
```

结果（与修复用例一并验证时）：`8 passed`（含 6 个 E2E + 2 个修复回归）。

E2E 覆盖：

| # | 场景 | 入口 | 结果 |
|---|------|------|------|
| 1 | live_topic 含 boss 词 → system 含知识 | `_build_visual_prompts` | 自动化通过 |
| 2 | 注入即 `use_count+1`，无 knowledge_used | `_build_visual_prompts` | 自动化通过 |
| 3 | 空语义不检索、无 `round=` 占位 | `_build_visual_prompts` + spy retrieve | 自动化通过 |
| 4a | tagged scope 不匹配 → 不注入 | `_build_visual_prompts` | 自动化通过 |
| 4b | tagged scope 匹配 → 注入 | `_build_visual_prompts` | 自动化通过 |
| 5 | create → import pasted_text → poll job → list items | Web API + mock organizer | 自动化通过 |

### 3.3 Boundary Guard

```text
python scripts/boundary_guard.py
→ Boundary Guard: PASS
```

### 3.4 未运行

- **禁止** 的本地全量 `pytest tests/`（AGENTS.md / IDE_AGENT_RULES）
- 真实豆包/OpenAI 整理与真实网页抓取
- 桌面 Web 控制台点击路径、托盘/Overlay 联调

---

## 4. 手动验收清单

| 场景 | 说明 | 覆盖状态 |
|------|------|----------|
| 游戏攻略包 | 导入攻略 → live_topic/场景相关词 → 视觉 prompt 含要点 | **自动化**：E2E #1–2 + pipeline；**需手测**：真实模型弹幕质量 |
| 直播烂梗包 | livestream_chat 分块 + 检索 | **自动化**：chunker / retriever / integration；**需手测**：真实聊天日志导入 UI |
| TXT 导入 | base64 / 文件选择 | **自动化**：API `txt` base64；**需手测**：控制台选文件 |
| MD 导入 | base64 / 文件选择 | **自动化**：API markdown base64；**需手测**：控制台选文件 |
| 网页导入 | URL 抓取 + 整理 | **自动化**：extractor mock / API webpage mock；**需手测**：真实 URL 与 SSL |
| 重复导入 / 去重 | 同内容再导不重复堆条目 | **自动化**：deduplicator + import；**需手测**：UI 提示 |
| 包 scope（tagged） | 标签不匹配不注入 / 匹配注入 | **自动化**：E2E #4 + retriever；**需手测**：设置页改 scope 后开播 |
| 重启 / 中断 job | 进程退出后 job 状态 interrupted 等 | **部分自动化**：cancel / status；**需手测**：杀进程再启动 |
| Job 状态 UI 自动刷新 | 导入进度条/状态文案 | **需手测**（Wave 3 主目标；API 状态有测） |
| 空主题不注入 | 无 live_topic / 无弹幕上下文 | **自动化**：E2E #3 + scene_context |

---

## 5. 性能说明

| 项 | 状态 | 说明 |
|----|------|------|
| 注入字符预算 | 实现已约束 | `max_chars=360`，硬上限 600（`retriever` / `prompt_builder` / runtime） |
| 额外视觉 LLM | 无 | 检索为本地 FTS/LIKE，不另开视觉请求 |
| 失败降级 | 实现已隔离 | runtime / inject 异常 → 原样 system_pt，主链路不中断 |
| 检索耗时 soak | **N/A** | 本波未做压测；无编造 ms 数字 |
| 导入吞吐 | **N/A** | 仅 mock organizer；真实 LLM 耗时依赖模型与网络 |

定性：单测路径下检索与注入为内存/SQLite 本地操作，未观察到阻塞主链路的设计（主线程注入调用应保持轻量；大库场景未 soak）。

---

## 6. 已修复问题（本波及历波相关）

1. **占位查询**：禁止用 `round=` / `screenshot=` 作为检索文本（Wave 1）。
2. **注入统计**：方案 A — 注入成功即 `mark_items_used` / `use_count`，不依赖模型 `knowledge_used`（Wave 1）。
3. **文件导入**：TXT/MD base64 校验后再 `create_source`（Wave 2）。
4. **包范围**：`scope_mode=tagged` 按 `scene_tags ∩ scope_tags` 过滤（Wave 4）。
5. **content_kind**：历史 `livestream` → `livestream_chat` 归一化（Wave 4）。
6. **测试漂移（Wave 5）**：
   - `KnowledgeItemCandidate.content` 上限 500 与单测对齐
   - organizer `max_output_tokens` 8192 与单测对齐
7. **生产路径 E2E 缺口（Wave 5）**：新增 `_build_visual_prompts` 与 API 导入轮询用例。

---

## 7. 未关闭 / 开放问题

1. **完整 Web UI 手测未做**：控制台导入向导、进度刷新、错误 toast 等需负责人在真实环境点验。
2. **真实 LLM 整理质量**：mock 路径无法保证条目质量、JSON 稳定性与 token 成本。
3. **真实网页抓取**：依赖外网、编码与反爬；仅 mock/单测覆盖。
4. **进程中断后恢复策略**：interrupted job 的用户可操作性需产品确认。
5. **大库检索延迟**：无 soak 数据；条目量上万时 FTS/评分是否影响主线程待观察。
6. **与浮动面板等并行改动**：工作区另有 floating_panel 未提交修改，与本知识包门控无关；合并时注意勿混提交。

---

## 8. 回归风险

| 风险 | 级别 | 缓解 |
|------|------|------|
| `_build_visual_prompts` 注入异常拖垮视觉请求 | 低 | 异常隔离 + 单测 |
| use_count 在每次注入递增导致过度惩罚 | 中 | 有 recent_use / last_injected 惩罚；需观察实播多样性 |
| tagged scope 过严导致「有库不注入」 | 中 | E2E 覆盖匹配/不匹配；UI 需提示 scope 配置 |
| 导入后台线程与 SQLite 并发 | 中 | API 测试已轮询 job；生产注意单写连接约定 |
| content 字段放宽至 500 字 | 低 | 与 prompt 预算独立；上屏仍走既有弹幕长度契约 |

---

## 9. 结论

**有条件通过。**

依据：

- 知识相关自动化 **396 passed**（含 Wave 5 生产路径 E2E）。
- `boundary_guard` **PASS**。
- 生产入口 `DanmuApp._build_visual_prompts` 与 API 导入闭环有自动化证据。
- **未**完成真实 UI / 真实 LLM / 外网抓取手测，故不能标「通过」。

建议负责人补做 §4 中标记「需手测」项后，可将结论升为 **通过**。
