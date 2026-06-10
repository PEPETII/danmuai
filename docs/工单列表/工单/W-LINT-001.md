# W-LINT-001 — 一次性修复 9 处历史 ruff I001/F401

> **来源**：W-NICKNAME-001 完成报告 §8（发现但未处理，登记 ISSUE-041）  
> **执行者**：Codex / Cursor Agent  
> **优先级**：低（不影响功能；仅代码风格与死代码清理）  
> **预计工时**：5–10 分钟（`ruff check --fix` 自动 + 1 处 untracked 脚本决策）

---

## 工单 ID

`W-LINT-001`

## 工单标题

一次性修复 9 处历史 ruff I001/F401 警告并落地临时脚本（`scripts/rebalance_t008_tests2.py`）

## 背景

- 本仓库 `pyproject.toml` 启用了 ruff `select = ["E", "F", "I", "W"]`，`ruff check app main.py tests scripts` 报 **9 处**历史遗留警告（混合 `I001 import-order` 与 `F401 unused-import`）。
- 9 处分布在 8 个已跟踪文件 + 1 个 untracked 临时脚本。
- 历史 `d82f3f5 style: fix ruff import order and unused imports for CI`（2026-05-31）一次修了 16 个文件，但**漏了**本工单涉及的 8 个。
- 2026-05-30 之后多个工单（`W-LAYOUT-OVERLAY-002` / `W-AUDIT-FIX-001` / `W-DANMU-TTS-001/002/003` / `W-PROVIDER-ADAPTER-001` / `W-CAPTURE-REGION-*`）新增 import 后**未续跑** ruff，因此退步。
- ruff **未纳入 CI**（`.github/workflows/ci.yml` 不跑 ruff），导致退步不会被自动拦截。
- W-NICKNAME-001 工单内 ruff 100% 干净（本工单不会"借机"改未碰文件）。

### 根因汇总

| 根因 | 涉及文件数 | 触发工单族 |
|------|----------|----------|
| 2026-05-31 后新 import 未续跑 ruff | 8/9 | W-LAYOUT-OVERLAY-002 / W-AUDIT-FIX-001 / W-DANMU-TTS-001-003 / W-PROVIDER-ADAPTER-001 / W-CAPTURE-REGION-* |
| 临时调试脚本未清理 | 1/9 | W-008 验收期间手工"rebalance" 一次性脚本 |

## 目标

完成后：

1. `python -m ruff check app main.py tests scripts` 返回 0 错误。
2. `python -m pytest tests/ -q` 全量通过（基线 906+ 不退步）。
3. `python scripts/boundary_guard.py` 仍 PASS（确认本工单未越界）。
4. 8 个已跟踪文件全部被纳入下一次回归；1 个 untracked 脚本去留由负责人决策并落地。

## 依赖项

- 仓库根目录 `pyproject.toml` 已配置 ruff 规则（无需改）。
- W-NICKNAME-001 已完成（提交后无业务代码冲突）。
- 建议紧随本工单立项 `W-CI-LINT-001`（CI 加 ruff check 防退步），但**不在本工单范围**。

## 允许修改的区域

- `app/live_freshness.py`
- `app/region_selector.py`
- `tests/test_ai_pipeline.py`
- `tests/test_config_changed_init.py`
- `tests/test_danmu_display_cap.py`
- `tests/test_danmu_tts.py`
- `tests/test_model_providers.py`
- `scripts/rebalance_t008_tests2.py`（决策点：删 / 移走 / 收编）
- `docs/workflow/当前仓库状态.md`
- `docs/已知问题与后续事项.md`
- `docs/templates/Codex完成报告/W-LINT-001-完成报告.md`（新建）

## 禁止修改的区域

- `main.py`（本工单不涉及）
- `app/ai_client.py`、`app/overlay.py`、`app/danmu_engine.py`、`app/danmu_pool.py`、`app/persona_contract.py`、`app/personae.py` 等所有未列入"允许修改区域"的 `app/` 文件
- `app/application/`（除可能因 import 自动 isort 而需轻动外，**禁止功能改动**）
- `web/`、`tests/conftest.py`、`tests/fakes.py`、`requirements.txt`、CI 配置文件、锁文件
- `docs/workflow/工单列表.md`（已登记 W-LINT-001，**不再改动**）
- `docs/WEB_CONSOLE.md`、`docs/ARCHITECTURE.md` 等其他文档

## 需求

1. **死 import 删除**（3 处 `F401`）：
   - `app/live_freshness.py:14` — 删 `import time`（已确认文件全文未引用 `time.*`）。
   - `app/region_selector.py:195` — 删函数体内 `from app.snipper import resolve_screen_index`（函数实际走参数 `resolve_screen_index_fn`，已 grep 全文验证）。
   - `tests/test_ai_pipeline.py:13` — 删 `from tests.fakes import FakeConfig`（已 grep 全文仅此 1 处出现）。
   - `tests/test_danmu_display_cap.py:3` — 删 `import pytest`（已 grep 全文无 `pytest.*` 装饰器或 fixture）。
2. **import 排序**（5 处 `I001`，可用 `ruff check --fix` 一键修复）：
   - `tests/test_config_changed_init.py:3`（预期分组：stdlib / 第三方 pytest / 第三方 PyQt6 / 本地 `app.*`）
   - `tests/test_danmu_display_cap.py:1`（预期分组：pytest / `app.*`）
   - `tests/test_danmu_tts.py:1`（预期字母序：`app.danmu_read_service` → `app.danmu_tts` → `app.danmu_tts_playback` → `app.tts_providers`）
   - `tests/test_model_providers.py:1`（括号内名字按字母序重排）
   - `tests/test_ai_pipeline.py:1`（预期分组：stdlib / PyQt6 / `app.*` / `main` / `tests.*`）
3. **untracked 脚本落地**：`scripts/rebalance_t008_tests2.py` 决策二选一：
   - **方案 A（推荐）**：删除（确认 `git grep rebalance_t008_tests2` 在仓库所有已跟踪文件内无引用）。
   - **方案 B**：若团队希望保留，将其移入 `scripts/_local/` 子目录并在仓库根 `.gitignore` 追加 `scripts/_local/`，明示其非交付物。
4. **可选 isort 自动应用**：执行 `python -m ruff check --fix app/live_freshness.py app/region_selector.py tests/test_ai_pipeline.py tests/test_config_changed_init.py tests/test_danmu_display_cap.py tests/test_danmu_tts.py tests/test_model_providers.py` —— `--fix` 会同时处理 `F401` 自动删除与 `I001` 自动 isort。

## 非目标

- 不实现新功能。
- 不重构相关业务模块。
- 不修改 `pyproject.toml` 的 ruff 规则。
- 不把 ruff 接入 CI（属 `W-CI-LINT-001`）。
- 不顺手修复 `app/` 内任何与 import 无关的代码（包括 `app/live_freshness.py` 的注释 / 函数体逻辑）。
- 不补 `app/region_selector.py` 内的任何业务注释。
- 不动 `scripts/boundary_guard.py`、`scripts/extract_danmu_pool.py` 等其它脚本。

## 验收标准

- [ ] `python -m ruff check app main.py tests scripts` 输出 `All checks passed!`（0 错误）。
- [ ] `python -m pytest tests/ -q` 全量通过（基线 906+ 不退步；本工单只动 8 个测试文件中的 4 个，应 100% 兼容）。
- [ ] `python scripts/boundary_guard.py` PASS。
- [ ] `git diff --stat` 仅显示允许修改区内的 8 个文件 + 可能的 `scripts/rebalance_t008_tests2.py` 删除/移动。
- [ ] `untracked` 脚本的去留决定已写入完成报告（删 → 报告 §6 注明；留 → 报告 §6 注明新路径与 .gitignore 行）。
- [ ] 完成报告已写至 `docs/templates/Codex完成报告/W-LINT-001-完成报告.md`。
- [ ] [docs/workflow/当前仓库状态.md](../../workflow/当前仓库状态.md) 追加 W-LINT-001 最近变更段。
- [ ] [docs/已知问题与后续事项.md](../../workflow/已知问题与后续事项.md) 中 ISSUE-041 状态由「待处理」改为「**已修复**」并指明新工单。

## 手动验证步骤

1. 拉取本工单分支后执行：
   ```bash
   python -m ruff check app main.py tests scripts
   ```
   预期：`All checks passed!`（修复前 9 errors）。
2. 执行全量测试：
   ```bash
   python -m pytest tests/ -q
   ```
   预期：906 passed, 5 skipped（基线 906）。
3. 边界检查：
   ```bash
   python scripts/boundary_guard.py
   ```
   预期：`Boundary Guard: PASS`。
4. 对照 4 个被改的测试文件：
   - `tests/test_ai_pipeline.py` — 确认 `FakeConfig` 已无引用（若需要，搜全文确认）。
   - `tests/test_danmu_display_cap.py` — 确认 `pytest` 已无引用。
   - `tests/test_danmu_tts.py` — 确认 4 个 `app.*` 仍按字母序排列。
   - `tests/test_model_providers.py` — 确认括号内名字按字母序（`apply_provider_to_form` 紧随 `DEFAULT_PROVIDER_ID` 等）。
5. 对照 2 个被改的 `app/` 文件：
   - `app/live_freshness.py` — 确认 `import time` 已删，且 `SLOW_REQUEST_SEC` / `SLOW_RTT_P90_SEC` 等常量行为未变。
   - `app/region_selector.py` — 确认第 195 行 `from app.snipper import resolve_screen_index` 已删，且 `start_capture_region_overlay` 函数对外行为未变（已验证函数体用参数 `resolve_screen_index_fn`）。
6. untracked 脚本：
   ```bash
   git grep rebalance_t008_tests2 || echo "no references in tracked files"
   ```
   预期：`no references in tracked files`。如选择删除则 `rm scripts/rebalance_t008_tests2.py`；如选择保留则 `mkdir -p scripts/_local && mv scripts/rebalance_t008_tests2.py scripts/_local/` 并在 `.gitignore` 追加 `scripts/_local/`。

## 风险点

- **`tests/test_danmu_tts.py` 与 `tests/test_danmu_display_cap.py`** 是 TTS / 弹幕显示限额回归测试，任何 import 错位可能导致 fixture 找不到。`ruff --fix` 是机械操作，但 Codex 仍应 diff 改动并执行 `pytest` 验收。
- **`app/region_selector.py` 第 195 行** 若误删其他 import 可能导致区域框选功能不可用。**已在需求中明确**：仅删 `from app.snipper import resolve_screen_index`，**保留** `from app.web_api.capture_region import SELECTION_SELECTING`。
- **`app/live_freshness.py` 删 `import time` 后** 应再 grep 一次全文（含注释）确认无遗漏引用。本文件实际是 `time` 模块的死导入，删除无副作用。
- **untracked 脚本若团队已记不清其用途**，保守起见选方案 B（移入 `scripts/_local/`），避免误删唯一遗留。
- **`ruff --fix` 同时启用 isort + 自动删 F401**：对于 5 个测试文件这是安全的；对于 2 个 `app/` 文件已**逐行**核对要保留的 import，确保 `--fix` 不会误删业务 import。
- **回滚方式**：本工单修改面小，1 commit 内可整体 `git revert`。

## 完成后必须更新的文档

- [x] [docs/workflow/当前仓库状态.md](../../workflow/当前仓库状态.md)（追加 W-LINT-001 最近变更段）
- [x] [docs/workflow/工单列表.md](../../workflow/工单列表.md)（将 W-LINT-001 从「待办工单」移入「已完成工单」）
- [x] [docs/已知问题与后续事项.md](../../workflow/已知问题与后续事项.md)（ISSUE-041 标为「**已修复**」并指向 W-LINT-001）
- [x] [docs/templates/Codex完成报告/W-LINT-001-完成报告.md](../../templates/Codex完成报告/W-LINT-001-完成报告.md)（新建）

## Codex 完成报告要求

- 使用 [Codex完成报告模板.md](../../templates/Codex完成报告/Codex完成报告模板.md)
- 必须列出**全部**修改文件路径（8 个文件 + untracked 脚本去留结果）
- 报告 §8「发现但未处理的问题」应明确指出：本工单**未**把 ruff 接入 CI（属 `W-CI-LINT-001` 后续工单）
- 报告 §10「建议下一个工单」应推 `W-CI-LINT-001`

---

## 附录 A：9 处具体改动清单（给 Codex 一次性 `ruff check --fix` 用）

```bash
python -m ruff check --fix \
    app/live_freshness.py \
    app/region_selector.py \
    tests/test_ai_pipeline.py \
    tests/test_config_changed_init.py \
    tests/test_danmu_display_cap.py \
    tests/test_danmu_tts.py \
    tests/test_model_providers.py
```

预期结果：
- 8 处自动修复（5 个 I001 isort + 3 个 F401 删死 import；`app/region_selector.py:195` 与 `app/live_freshness.py:14` 已被 `F401` 自动覆盖）。
- `tests/test_danmu_display_cap.py` 同时修 I001 + F401 → `pytest` 一并删除。

`scripts/rebalance_t008_tests2.py` 的 I001 不能靠 `--fix`（untracked + 不在 ruff 工作集？实测 ruff 仍会扫到）；如需可单独跑 `python -m ruff check --fix scripts/rebalance_t008_tests2.py`。

## 附录 B：参考 commit 风格

参考 `d82f3f5 style: fix ruff import order and unused imports for CI`（2026-05-31，PEPETII）：

```
style: fix ruff import order and unused imports (ISSUE-041)

Run ruff check --fix on app, main.py, tests, and scripts (I001, F401).
Replaces the manually-fixed subset from d82f3f5 with a complete pass.
Resolves ISSUE-041.
```

## 附录 C：与 W-CI-LINT-001 的边界

| 维度 | W-LINT-001（本工单） | W-CI-LINT-001（后续） |
|------|---------------------|---------------------|
| 范围 | 修复现有 9 处 + untracked 脚本 | 修改 `.github/workflows/ci.yml` 加 ruff check |
| 文件 | 8 个 `app/`/`tests/` + 1 个 `scripts/` | CI 配置 yaml |
| 风险 | 低（仅改 import） | 中（CI 改动可能阻塞 PR） |
| 建议顺序 | 先做本工单 | 本工单合并入主分支后再立项 |
