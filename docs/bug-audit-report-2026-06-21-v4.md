# DanmuAI 周期性 Bug 审计报告

> **历史审计快照（v4）**：结论只对文中 commit 与检查时间有效。文中旧 `docs/core/`、`docs/features/` 与 `app/config_store.py` 路径不代表当前目录结构；现行问题状态见 [.local-ai/workorders/已知问题与后续事项.md](../.local-ai/workorders/已知问题与后续事项.md)。

## 1. 本次审计范围
- 当前分支：`main`
- 当前 commit：`6d253af35379c38d4b91ab8d6d1c5f79e30d769d`
- 检查时间：`2026-06-21 11:00:37 +08:00`
- 已读取的关键文件：
  - 项目说明与协作边界：`README.md`、`CONTRIBUTING.md`、`AGENTS.md`、`docs/README.md`、`docs/core/MAIN_PIPELINE.md`、`docs/features/WEB_CONSOLE.md`
  - 启动与生命周期：`main.py`、`app/web_console.py`、`app/webview_shell.py`、`app/single_instance.py`、`app/tray.py`
  - 配置与本地数据：`app/config_store.py`
  - 更新与发布：`DanmuAI.spec`、`app/web_api/update.py`、`app/release_channels.py`、`app/supabase_config.py`、`app/supabase_app_updates.py`、`app/update_service.py`、`scripts/build_exe.ps1`、`scripts/publish_windows_release.ps1`、`scripts/upload_r2_release.ps1`、`scripts/run_acceptance_gates.py`
  - Supabase 与静态前端：`web/static/supabase-config.js`、`web/static/modules/app-update-banner.js`
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
  - 首次合并执行的启动相关批次超时：`python -m pytest tests/test_webview_shell.py tests/test_web_launch.py tests/test_web_server.py tests/test_main_single_instance.py -q -x`，后续已拆分逐个执行。
  - 未运行本地全量 `pytest`：仓库规则明确禁止在当前环境直接跑全量套件。
  - 未运行真实 frozen EXE 启动、Velopack 安装/更新真机验收：本轮为只读审计，且这类检查需要完整桌面/安装环境。

## 2. 结论总览
按严重程度列出：
- P0：`BUG-001` 已提交的 `web/static/supabase-config.js` 暴露真实 Supabase URL 与 anon key，且服务端默认读取该文件。
- P1：`BUG-002` 当前发布链被同一凭据文件硬阻塞，`scripts/publish_windows_release.ps1` 在当前仓库状态下会直接中止。
- P1：`BUG-003` `scripts/run_acceptance_gates.py` 引用了已不存在的测试文件，导致验收门禁稳定失败，发布前验证失真。
- P2：`BUG-004` `invoke_on_main` 504 超时返回结构与文档契约、现有测试不一致，机器可读错误码丢失。
- P3：现有测试中还有两处明显老化：`tests/test_release_channels.py` 仍 patch 旧入口，`tests/test_web_launch.py` 仍假设旧的卸载交互。

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
  // web/static/supabase-config.js
  window.DANMU_SUPABASE = {
    url: 'https://tzqhlazolpsnkbysubnk.supabase.co',
    anonKey: '...真实 anon key...',
  };
  ```
  ```python
  # app/supabase_config.py
  config_path = resource_path("web", "static", "supabase-config.js")
  if not config_path.is_file():
      return None
  return _parse_supabase_config_js(config_path.read_text(encoding="utf-8"))
  ```
- 复现路径：
  1. 直接查看仓库中的 `web/static/supabase-config.js`。
  2. 不设置 `DANMU_SUPABASE_URL` / `DANMU_SUPABASE_ANON_KEY`。
  3. 代码会回退读取该本地文件。
- 根因分析：
  - `.gitignore` 已声明 `web/static/supabase-config.js` 不应入库，但该文件已经被 Git 跟踪。
  - 服务端凭据解析逻辑把该文件当成正式 fallback 来源，因此这不是单纯的样例残留，而是实际会被运行时消费的敏感配置。
- 最小修复建议：
  - 从版本库移除 `web/static/supabase-config.js`。
  - 轮换当前 Supabase anon key，并核对该 key 的 RLS/权限边界。
  - 本地开发改用 `web/static/supabase-config.example.js` 或环境变量。
- 是否建议本次自动修复：否
- 需要补充的测试：
  - 增加一个仓库卫生测试，断言 `web/static/supabase-config.js` 不在 Git 跟踪列表中。
  - 扩展 `tests/test_supabase_static.py`，在 CI 中对正式构建输入做存在性检查。

### BUG-002：当前发布脚本会被已跟踪的 Supabase 凭据文件直接阻断
- 严重等级：P1
- 影响功能：打包发布、Velopack 产物生成、R2/GitHub 发布链
- 证据文件：
  - `scripts/publish_windows_release.ps1:13-17`
  - `scripts/build_exe.ps1:59-67`
  - `web/static/supabase-config.js:1-5`
- 证据代码：
  ```powershell
  # scripts/publish_windows_release.ps1
  if (Test-Path $supabaseConfigPath) {
      Write-Error "ABORT: web/static/supabase-config.js exists ..."
  }
  ```
  ```powershell
  # scripts/build_exe.ps1
  if (Test-Path $leakedConfig) {
      Write-Error "Credential leak detected: ..."
  }
  ```
- 复现路径：
  1. 保持当前仓库状态不变。
  2. 运行 `scripts/publish_windows_release.ps1`。
  3. 脚本在真正打包前即因 `web/static/supabase-config.js` 存在而中止。
- 根因分析：
  - 发布脚本和构建脚本都正确地把 `supabase-config.js` 视为敏感文件。
  - 但仓库当前又实际跟踪了该文件，导致“安全护栏”和“当前仓库状态”互相冲突，发布链不可执行。
- 最小修复建议：
  - 优先处理 `BUG-001`，从仓库中移除该文件并改回安全配置路径。
  - 之后重新执行 `build_exe.ps1` / `publish_windows_release.ps1` 做一次完整发布冒烟。
- 是否建议本次自动修复：否
- 需要补充的测试：
  - 为发布前检查增加仓库输入校验，直接在测试中断言 `web/static/supabase-config.js` 不存在。

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
  ```python
  # 当前仓库实际存在的是
  def test_boundary_guard_passes_on_repository_root() -> None:
      findings = run_boundary_guard(repo_root)
  ```
- 复现路径：
  1. 运行 `python scripts/run_acceptance_gates.py`。
  2. 脚本先跑通 `boundary_guard`。
  3. 随后在 `test_boundary_guard`、`test_diagnostics` 两步直接以退出码 4 失败。
- 根因分析：
  - 门禁脚本仍指向旧测试文件名。
  - 仓库已经迁移为 `tests/test_acceptance_gates.py` 等新入口，但脚本未同步。
- 最小修复建议：
  - 把 `COMMANDS` 中的旧路径替换为现存测试文件。
  - 或者把这两个子步骤合并到 `tests/test_acceptance_gates.py` 的现有断言。
- 是否建议本次自动修复：是
- 需要补充的测试：
  - 给 `scripts/run_acceptance_gates.py` 增加“目标测试文件必须存在”的单测。
  - 或新增一个 smoke test，直接运行该脚本并断言不出现 `file or directory not found`。

### BUG-004：`invoke_on_main` 超时的 504 返回结构与文档契约不一致
- 严重等级：P2
- 影响功能：Web API 错误契约、自动化调用、前后端调试
- 证据文件：
  - `docs/features/WEB_CONSOLE.md:161-168`
  - `app/web_api/routes.py:153-161`
  - `tests/test_web_server.py:943-961`
- 证据代码：
  ```md
  # docs/features/WEB_CONSOLE.md
  504 -> {"detail": {"ok": false, "error": "main_thread_timeout", "detail": "..."}}
  ```
  ```python
  # app/web_api/routes.py
  raise HTTPException(
      status_code=504,
      detail="主线程操作超时，请稍后重试。",
  )
  ```
- 复现路径：
  1. 运行 `python -m pytest tests/test_web_server.py -q -x`
  2. `test_invoke_main_route_timeout_returns_504` 失败。
  3. 实际返回是字符串 detail，测试与文档都期待结构化对象。
- 根因分析：
  - 文档与测试都按“结构化错误对象”维护。
  - 实现层后来简化成纯字符串，但未同步文档和测试，也失去了机器可读的 `main_thread_timeout` 错误码。
- 最小修复建议：
  - 二选一统一：要么恢复结构化 504 响应；要么明确修改文档与测试为字符串契约。
  - 从可维护性看，保留结构化错误对象更稳妥。
- 是否建议本次自动修复：是
- 需要补充的测试：
  - 保留 `tests/test_web_server.py::test_invoke_main_route_timeout_returns_504`，作为契约回归测试。

## 4. 高风险但未确认问题
- `tests/test_web_launch.py::test_tray_uninstall_keeps_user_data_without_second_delete_confirm` 当前失败，但证据显示更可能是测试未跟上交互改版。实现已改成单个 `QMessageBox` 自定义按钮流，测试仍 monkeypatch 旧的 `QMessageBox.question` 双确认路径；需要人工点托盘“卸载应用”做真实交互验收，暂不判为产品 bug。
- `tests/test_release_channels.py::test_release_channels_api_route` 当前失败，但更新 API 的新路径 `app/web_api/update.py` 已改为走 `fetch_app_update_result()`，而 `tests/test_update_api.py` 中对应新契约 43 项全部通过。该失败更像老测试仍 patch `release_channels.fetch_app_update`，暂不判为运行时 bug。
- 启动慢、托盘已启动但窗口迟迟不出现的问题，本轮只做了源码与单测核查，尚未在 frozen EXE + WebView2 冷启动环境下做真机复测，仍需人工确认。

## 5. 性能与卡顿风险
- 启动链路方面，`tests/test_webview_shell.py` 28 项通过、`tests/test_main_single_instance.py` 3 项通过，说明当前源码层没有新的明显死锁回归；但这不能替代真实 Windows 双击 EXE 的冷启动验收。
- SQLite 与配置路径方面，`tests/test_config_store.py`、`tests/test_p1_sqlite_concurrency.py`、`tests/test_danmu_pool.py`、`tests/test_danmu_pool_api.py` 共 105 项通过，本轮未发现新的配置写锁或池数据并发退化。
- 更新与 Web 主线程桥接方面，`tests/test_update_api.py` 与 `tests/test_web_bridge.py` 共 43 项通过；当前更大的风险不是死锁，而是 `BUG-004` 这种超时错误契约漂移，会降低定位效率。
- 自定义弹幕库 20000 条、Overlay 长时间渲染、桌宠多实例、麦克风长时间录音，本轮没有跑压力型真机场景，因此只能给出“未确认”，不能宣称已通过真实卡顿验收。

## 6. 发布与更新风险
- `BUG-002` 是当前最直接的发布阻断项：只要仓库里还存在 `web/static/supabase-config.js`，`scripts/publish_windows_release.ps1` 就不会继续执行。
- `BUG-003` 会让发布前门禁报告持续报假红，导致“脚本失败”与“产品真回归”混在一起，削弱发布检查可信度。
- 更新 API 主路径本身相对稳定：`tests/test_update_api.py`、`tests/test_update_service.py` 绝大多数断言通过；当前失败主要来自旧测试入口未同步，不是新发现的更新逻辑崩溃。
- 本轮未做 R2、GitHub Releases、Velopack 安装/升级/卸载的真实联网验收，因此不能把当前代码状态视为“已具备发布条件”。

## 7. 安全与隐私风险
- `BUG-001` 是本轮唯一确认的 P0：真实 Supabase URL 与 anon key 已经出现在受版本控制文件中，而且服务端会默认读取它。
- 由于该文件已被跟踪，仅依赖 `.gitignore` 已经无效；这是“泄露已发生”，不是“未来可能泄露”。
- 本轮没有发现新的本地会话 token 绕过证据；`tests/test_web_server.py` 中 `/api/session` 鉴权相关用例仍通过。
- 本轮未进行线上 Supabase / Vercel / Cloudflare 权限实测，因此社区表 RLS、举报滥用、后台管理权限边界仍属于待人工联网验证项。

## 8. 建议新增的测试
- `tests/test_repo_security.py`
  - 测试目标：仓库敏感配置不得被跟踪。
  - 断言内容：`web/static/supabase-config.js` 不存在，或至少不在 `git ls-files` 输出中。
- `tests/test_acceptance_gates.py`
  - 测试目标：验收门禁脚本引用的测试文件必须与仓库现状一致。
  - 断言内容：`scripts/run_acceptance_gates.py` 中每个 `pytest` 目标路径都实际存在。
- `tests/test_web_server.py`
  - 测试目标：固定 504 超时返回契约。
  - 断言内容：`invoke_on_main` 超时时返回结构化对象，或明确断言为字符串并同步文档。
- `tests/test_build_release_hygiene.py`
  - 测试目标：发布输入中不得包含敏感 Supabase 配置。
  - 断言内容：发布脚本运行前若存在 `web/static/supabase-config.js`，测试直接失败并给出明确原因。

## 9. 本次可自动修复项
- `BUG-003`：修正 `scripts/run_acceptance_gates.py` 中过期的测试文件路径。
- `BUG-004`：统一 `invoke_on_main` 504 返回契约，实现、文档、测试三者对齐。

## 10. 最终建议
1. 先处理 `BUG-001`。这是已经发生的安全事件，不应继续让真实 Supabase 凭据留在受版本控制文件中；同时它也直接阻断当前发布链。
2. 再处理 `BUG-003`。当前验收门禁会稳定报假红，导致发布前无法可靠区分“脚本坏了”还是“产品坏了”。
3. 最后处理 `BUG-004` 并补一次真实 Windows 发布冒烟。把 504 错误契约对齐后，再做一次 frozen EXE + Velopack + WebView2 的人工验收，才能恢复对启动/更新链路的真实信心。
