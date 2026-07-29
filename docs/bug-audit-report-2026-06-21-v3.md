# DanmuAI 周期性 Bug 审计报告

> **历史审计快照（v3）**：结论只对文中 commit 与检查时间有效。文中 `docs/core/MAIN_PIPELINE.md`、`docs/features/WEB_CONSOLE.md`、`app/config_store.py` 等读取目标已迁移或未保留；现行入口是 [docs/README.md](README.md) 与 [.local-ai/workorders/当前仓库状态.md](../.local-ai/workorders/当前仓库状态.md)。

## 1. 本次审计范围
- 当前分支：`main`
- 当前 commit：`6d253af35379c38d4b91ab8d6d1c5f79e30d769d`
- 检查时间：`2026-06-21 11:10:05 +08:00`
- 已读取的关键文件：
  - 项目说明与边界：`README.md`、`CONTRIBUTING.md`、`AGENTS.md`、`docs/README.md`、`docs/core/MAIN_PIPELINE.md`、`docs/features/WEB_CONSOLE.md`
  - 启动与生命周期：`main.py`、`app/web_console.py`、`app/webview_shell.py`、`app/single_instance.py`、`app/tray.py`
  - 配置与本地数据：`app/config_store.py`
  - 更新与发布：`DanmuAI.spec`、`app/web_api/update.py`、`app/release_channels.py`、`app/supabase_config.py`、`app/supabase_app_updates.py`、`app/update_service.py`、`scripts/build_exe.ps1`、`scripts/publish_windows_release.ps1`、`scripts/upload_r2_release.ps1`、`scripts/run_acceptance_gates.py`
  - 前端与 Supabase：`web/static/supabase-config.js`、`web/static/modules/app-update-banner.js`
  - 关键测试：`tests/test_acceptance_gates.py`、`tests/test_update_api.py`、`tests/test_release_channels.py`、`tests/test_web_launch.py`、`tests/test_web_server.py`、`tests/test_webview_shell.py`、`tests/test_main_single_instance.py`、`tests/test_config_store.py`
- 已运行的命令：
  - `git branch --show-current`
  - `git rev-parse HEAD`
  - `git status --short`
  - `python scripts/run_acceptance_gates.py`
  - `python -m pytest tests/test_webview_shell.py -q -x`
  - `python -m pytest tests/test_web_launch.py -q -x`
  - `python -m pytest tests/test_web_server.py -q -x`
  - `python -m pytest tests/test_main_single_instance.py -q -x`
  - `python -m pytest tests/test_update_service.py tests/test_update_api.py tests/test_release_channels.py tests/test_velopack_runtime.py -q -x`
  - `python -m pytest tests/test_config_store.py tests/test_p1_sqlite_concurrency.py tests/test_danmu_pool.py tests/test_danmu_pool_api.py -q -x`
  - `python -m pytest tests/test_supabase_app_updates.py tests/test_supabase_static.py tests/test_supabase_config.py -q -x`
  - `python -m pytest tests/test_update_api.py tests/test_web_bridge.py -q -x`
- 未能运行的命令及原因：
  - 合并执行的启动相关测试批次首次超时，后续已拆分逐个执行确认。
  - 未运行本地全量 `pytest`，原因是仓库规则明确禁止。
  - 未运行真实 frozen EXE/Velopack/升级回滚真机验收，本轮为代码与脚本审计。

## 2. 结论总览
按严重程度列出：
- P0：`BUG-001` 已提交的 `web/static/supabase-config.js` 暴露真实 Supabase URL 与 anon key，且服务端默认读取该文件。
- P1：`BUG-002` 当前发布链被同一凭据文件硬阻塞，`scripts/publish_windows_release.ps1` 在当前仓库状态下会直接中止。
- P1：`BUG-003` `scripts/run_acceptance_gates.py` 引用了已不存在的测试文件，导致验收门禁稳定失败，发布前验证失真。
- P2：`BUG-004` `invoke_on_main` 504 超时返回结构与文档契约、现有测试不一致，机器可读错误码丢失。
- P3：`tests/test_release_channels.py` 与 `tests/test_web_launch.py` 都存在明显测试老化，不能直接拿它们的失败当产品 bug。

## 3. 已确认 Bug

### BUG-001：Supabase 凭据文件已入库，且服务端默认会读取它
- 严重等级：P0
- 影响功能：社区后端访问、更新元数据读取、反馈/公告相关安全边界
- 证据文件：
  - `web/static/supabase-config.js:1-5`
  - `app/supabase_config.py:35-47`
  - `.gitignore:30-31`
- 证据代码：
  ```js
  window.DANMU_SUPABASE = {
    url: 'https://tzqhlazolpsnkbysubnk.supabase.co',
    anonKey: '...真实 anon key...',
  };
  ```
  ```python
  config_path = resource_path("web", "static", "supabase-config.js")
  if not config_path.is_file():
      return None
  return _parse_supabase_config_js(config_path.read_text(encoding="utf-8"))
  ```
- 复现路径：
  1. 查看仓库中的 `web/static/supabase-config.js`。
  2. 不设置 `DANMU_SUPABASE_URL` / `DANMU_SUPABASE_ANON_KEY`。
  3. 服务端会回退读取这个文件。
- 根因分析：
  - `.gitignore` 已声明该文件不应入库，但它已经被 Git 跟踪。
  - 该文件不是纯示例，而是运行时正式 fallback 输入。
- 最小修复建议：
  - 从版本库移除 `web/static/supabase-config.js`。
  - 轮换当前 Supabase anon key，并复核其权限边界。
  - 本地开发改用 `supabase-config.example.js` 或环境变量。
- 是否建议本次自动修复：否
- 需要补充的测试：
  - 增加仓库卫生测试，断言 `web/static/supabase-config.js` 不在 `git ls-files` 中。

### BUG-002：当前发布脚本会被已跟踪的 Supabase 凭据文件直接阻断
- 严重等级：P1
- 影响功能：打包发布、Velopack 产物生成、R2/GitHub 发布链
- 证据文件：
  - `scripts/publish_windows_release.ps1:13-17`
  - `scripts/build_exe.ps1:59-67`
  - `web/static/supabase-config.js:1-5`
- 证据代码：
  ```powershell
  if (Test-Path $supabaseConfigPath) {
      Write-Error "ABORT: web/static/supabase-config.js exists ..."
  }
  ```
  ```powershell
  if (Test-Path $leakedConfig) {
      Write-Error "Credential leak detected: ..."
  }
  ```
- 复现路径：
  1. 保持当前仓库状态不变。
  2. 运行 `scripts/publish_windows_release.ps1`。
  3. 脚本在真正打包前即终止。
- 根因分析：
  - 构建/发布脚本的安全护栏是正确的。
  - 当前仓库状态违反了这个护栏，因此发布链不可执行。
- 最小修复建议：
  - 先修复 `BUG-001`，再跑完整发布冒烟。
- 是否建议本次自动修复：否
- 需要补充的测试：
  - 为发布前检查增加“敏感 Supabase 文件不得存在”的自动化断言。

### BUG-003：验收门禁脚本引用了已删除/改名的测试文件，导致稳定失败
- 严重等级：P1
- 影响功能：测试与验收、发布前门禁、回归可信度
- 证据文件：
  - `scripts/run_acceptance_gates.py:9-19`
  - `tests/test_acceptance_gates.py:10-13`
  - 实际命令输出：`tests/test_boundary_guard.py`、`tests/test_diagnostics.py` 均 `file or directory not found`
- 证据代码：
  ```python
  COMMANDS = [
      ("test_boundary_guard", [sys.executable, "-m", "pytest", "tests/test_boundary_guard.py", "-q"]),
      ("test_diagnostics", [sys.executable, "-m", "pytest", "tests/test_diagnostics.py", "-q"]),
  ]
  ```
- 复现路径：
  1. 运行 `python scripts/run_acceptance_gates.py`。
  2. `boundary_guard` 本身通过。
  3. 后续两个 pytest 子步骤直接以退出码 4 失败。
- 根因分析：
  - 门禁脚本仍指向旧测试文件名。
  - 仓库现有入口已经迁移，但脚本未同步。
- 最小修复建议：
  - 把 `COMMANDS` 中的旧测试路径替换为现存文件。
- 是否建议本次自动修复：是
- 需要补充的测试：
  - 增加一个 smoke test，断言 `run_acceptance_gates.py` 不出现 `file or directory not found`。

### BUG-004：`invoke_on_main` 超时的 504 返回结构与文档契约不一致
- 严重等级：P2
- 影响功能：Web API 错误契约、自动化调用、前后端调试
- 证据文件：
  - `docs/features/WEB_CONSOLE.md:161-168`
  - `app/web_api/routes.py:153-161`
  - `tests/test_web_server.py:943-961`
- 证据代码：
  ```md
  504 -> {"detail": {"ok": false, "error": "main_thread_timeout", "detail": "..."}}
  ```
  ```python
  raise HTTPException(
      status_code=504,
      detail="主线程操作超时，请稍后重试。",
  )
  ```
- 复现路径：
  1. 运行 `python -m pytest tests/test_web_server.py -q -x`
  2. `test_invoke_main_route_timeout_returns_504` 失败。
  3. 实际返回是字符串 `detail`，而测试与文档都期待结构化对象。
- 根因分析：
  - 文档和测试仍维护旧的结构化契约。
  - 实现层后来被简化成纯字符串，三者未同步。
- 最小修复建议：
  - 恢复结构化 504 返回，或统一改文档与测试。
  - 从自动化可用性看，恢复结构化对象更稳妥。
- 是否建议本次自动修复：是
- 需要补充的测试：
  - 保留并修正 `tests/test_web_server.py::test_invoke_main_route_timeout_returns_504` 作为契约回归测试。

## 4. 高风险但未确认问题
- `tests/test_web_launch.py::test_tray_uninstall_keeps_user_data_without_second_delete_confirm` 当前失败，但从 [`app/tray.py`](../app/tray.py#L174) 可以看到卸载交互已经改成单个自定义按钮的 `QMessageBox` 流程。测试仍假设旧的 `QMessageBox.question` 双确认路径，更像测试老化，不足以直接判为产品 bug。
- `tests/test_release_channels.py::test_release_channels_api_route` 当前失败，但新实现 [`app/web_api/update.py`](../app/web_api/update.py#L28) 已改为走 `fetch_app_update_result()`，而 `tests/test_update_api.py` 中对应新契约批次已通过。该失败更像老测试 patch 旧入口，不足以直接判为运行时 bug。
- 启动慢、双击 EXE 后托盘先起但窗口慢开，这轮没有做 frozen EXE 真机复现，仍需人工确认。

## 5. 性能与卡顿风险
- 启动链路源码和测试层面没有新的明显死锁证据：`tests/test_webview_shell.py`、`tests/test_main_single_instance.py` 通过。
- 配置、SQLite、自定义弹幕库相关批次 105 项通过，本轮没有发现新的锁竞争或配置丢失回归。
- 当前更现实的风险是“验收脚本假红”和“错误返回契约漂移”降低排障效率，而不是已经确认的主线程死锁。
- Overlay、桌宠、多实例、长时间麦克风、真实游戏置顶等体验问题，本轮没有做人工真机验收，不能宣称已通过。

## 6. 发布与更新风险
- 当前最大的发布风险是 `BUG-002`：只要 `web/static/supabase-config.js` 还在仓库里，发布脚本就会直接中止。
- `BUG-003` 使得发布前门禁失真，脚本失败与产品回归被混在一起。
- 更新 API 主路径整体并不显示新的明显崩溃：`tests/test_update_api.py`、`tests/test_update_service.py` 主要断言通过。
- 本轮没有执行 Velopack 真机安装、升级、卸载，因此不能据此声称“当前版本可安全发布”。

## 7. 安全与隐私风险
- `BUG-001` 是本轮唯一确认的 P0，属于已发生的配置泄露，而不是“未来可能泄露”。
- 仅依赖 `.gitignore` 已经无法修复这个问题，因为文件已被 Git 跟踪。
- 本轮未发现新的 `/api/session` 绕过证据；已有相关鉴权测试仍通过。
- Supabase RLS、Vercel 管理端、Cloudflare R2 线上权限边界，本轮未做联网实测，仍需人工复核。

## 8. 建议新增的测试
- `tests/test_repo_security.py`
  - 测试目标：仓库敏感配置不得被跟踪。
  - 断言内容：`web/static/supabase-config.js` 不存在，或不在 `git ls-files` 输出中。
- `tests/test_run_acceptance_gates.py`
  - 测试目标：验收门禁脚本引用的测试文件必须与仓库现状一致。
  - 断言内容：`scripts/run_acceptance_gates.py` 中每个 pytest 目标路径都实际存在。
- `tests/test_web_server.py`
  - 测试目标：固定 504 超时返回契约。
  - 断言内容：`invoke_on_main` 超时时返回结构化对象，或明确断言为字符串并同步文档。
- `tests/test_build_release_hygiene.py`
  - 测试目标：发布输入中不得包含敏感 Supabase 配置。
  - 断言内容：发布脚本运行前若存在 `web/static/supabase-config.js`，测试直接失败。

## 9. 本次可自动修复项
- `BUG-003`：修正 `scripts/run_acceptance_gates.py` 中过期的测试文件路径。
- `BUG-004`：统一 `invoke_on_main` 504 返回契约，实现、文档、测试三者对齐。

## 10. 最终建议
1. 先处理 `BUG-001`。真实 Supabase 凭据已经在受版本控制文件里，优先级高于其他工程性问题。
2. 再处理 `BUG-003`。当前门禁脚本持续假红，会直接削弱后续所有审计和发布检查的可信度。
3. 最后处理 `BUG-004` 并补一次真实 Windows 发布/启动验收。把错误契约和发布输入修正后，再做 frozen EXE + WebView2 + Velopack 的人工验收，才有意义。
