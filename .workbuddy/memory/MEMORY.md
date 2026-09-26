# DanmuAI 项目长期记忆

## 测试与工具链（本机，必须遵守）

- **跑 pytest 只能用 `/c/Python314/python.exe`**（pytest 9.0.1，依赖齐全）。
  - 系统 py3.12 缺 `cryptography`/`apscheduler`/`PySide6`；托管 py3.13.12 无 `pytest`/`ruff` 模块。
  - 因此 `python -m pytest` / `python -m ruff` 在本机默认 PATH 下**都会失败**。
- **ruff 用 PATH 上的独立二进制**（当前 v0.15.15）：`ruff check app main.py tests scripts`。
- **boundary_guard**：`/c/Python314/python.exe scripts/boundary_guard.py`（exit 0 = PASS）。
- **前端测试**：`node --test tests/*.mjs`；仓库根无 `package.json`，`.mjs` 中
  `await import('../web/static/modules/*.js')` 为既有惯例，DOM 用 `globalThis` 手工打桩
  （参见 `tests/test_model_provider_picker.mjs`）。
- 并行跑测试时给每路设置独立 `TEMP`/`TMP`，避免 pytest 临时目录互相污染。

## 基线既有失败（`main @ 9a3edca`，非新引入）

以下用例在干净 HEAD 上就失败（已用 `git worktree add` 独立复现）。**属于范围外既有缺陷，
不要顺手修**，报告中如实标注即可：

1. `tests/test_custom_models_schema_migration.py::test_update_with_masked_key_preserves_api_key_via_adapter`
   （`_derive_profile_name()` 遮蔽显式 `name` 字段）
2. `tests/test_custom_model_key_encryption.py::test_custom_model_crud_roundtrip_encrypted`
   （陈旧用例仍传 legacy `modelId`，被 `_assert_canonical_http_payload()` 拒绝）
3. `tests/test_ai_pipeline.py::test_ai_error_releases_in_flight`

## 协作约定

- **本仓库存在多代理并行写入**：除本会话外，另有 Codex 会话用独立 worktree 跑 P2 工单，
  且其改动会出现在主工作区 `E:\test\danmu`。动手前先 `git worktree list` + `git status --short`
  判断是否存在外部写入，避免互相覆盖。
- 工单执行采用**波次串行**：共享文件（`app/web_api/custom_models*.py`、
  `app/main_lifecycle_mixin.py`、`web/static/modules/app-persona-topic-page.js`）必须串行。
- 证明"某失败是既有噪声"必须用干净 `HEAD` worktree 复现，禁止推测。
- 默认**不提交、不推送**，除非用户明确授权。
