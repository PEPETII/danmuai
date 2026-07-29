# DanmuAI 周期性 Bug 审计报告

> **日期化审计快照（2026-07-11）**：这是当前目录中较新的审计，但仍只证明文中工作树和已执行门禁。2026-07-12 之后的缺陷、修复与发布状态以 [.local-ai/workorders/当前仓库状态.md](../.local-ai/workorders/当前仓库状态.md) 和 [已知问题台账](../.local-ai/workorders/已知问题与后续事项.md) 为准。
>
> **审计日期**：2026-07-11  
> **修复同步**：2026-07-11（BUG-001 / BUG-002 / BUG-004 / BUG-005 已落地，见 §2 各条「修复状态」与附录 D）
> **审计范围**：当前工作区（`main` 分支，本地相对 `origin/main` **落后 3 个提交**；存在大量未提交改动，结论以**当前磁盘源码**为准）  
> **审计环境**：Windows；本地 Python **3.14**（README/CI 推荐 **3.12**）  
> **执行方式**：源码走读 + 分批 pytest（`-q -x`）+ `python scripts/boundary_guard.py` + `scripts/check_release_endpoints.ps1`（只读 HTTP）

---

## 1. 结论总览

| 严重度 | 数量 | 摘要 |
|--------|------|------|
| **P0** | 0 | 未发现可证实的「无法启动 / 数据丢失 / 密钥入包 / 发布源不可用」问题 |
| **P1** | 0 | 未发现可证实的核心链路（启动→弹幕→模型）单点阻断 Bug |
| **P2** | 2（开放） | **已修复 3**：测试投影漂移、`FakeConfig` canonical 化、boundary_guard 诊断路由规则缺文件容错；**仍开放**：`ConfigStore.get()` 关闭后静默读缓存；Python 3.14 本地子进程 GBK 解码告警 |
| **P3** | 2（开放） | **已修复 1**：`SECURITY.md` 自定义模型加密描述；**仍开放**：`final-architecture-baseline.md` mixin 数量过时；未签名安装包 SmartScreen（已文档化） |

**发布链路（已确认）**：R2 Feed / Setup / Portable / GitHub API 均 HTTP 200；Feed 最新 Full 版本 **0.3.9**，与 `app/version.py::__version__` 一致。

**门控（已确认）**：`boundary_guard.py` → PASS；`run_acceptance_gates.py` → **PASS**（2026-07-11 复测）；审计期失败用例 **BUG-001 / BUG-002 / BUG-005 已修复**（见附录 D）；**BUG-003** 仍开放。

---

## 2. 已确认 Bug

### BUG-001：`/api/status` 相关单测未适配 `GenerationPipelineState.from_app` 新投影

- **修复状态**：✅ **已修复**（2026-07-11）  
- **严重等级**：P2
- **影响功能**：CI/本地回归（非生产运行时）；`build_status_snapshot` 在极简 mock 上会抛 `AttributeError`  
- **证据文件**：`app/application/generation_pipeline_state.py`、`tests/test_overlay_topmost_health.py`  
- **证据代码**：

```37:44:app/application/generation_pipeline_state.py
    @classmethod
    def from_app(cls, app: "DanmuApp") -> "GenerationPipelineState":
        return cls(
            latest_displayed_round=app.latest_displayed_round,
            latest_requested_screenshot_id=app.latest_requested_screenshot_id,
            latest_queued_screenshot_id=app.latest_queued_screenshot_id,
            latest_displayed_screenshot_id=app.latest_displayed_screenshot_id,
        )
```

```332:358:tests/test_overlay_topmost_health.py
def test_status_includes_overlay_compat_warning(monkeypatch):
    ...
    app = SimpleNamespace(
        config=FakeConfig({}),
        engine=engine,
        ...
    )
    ...
    status = DanmuApp.build_status_snapshot(app)
```

- **复现路径**：

```powershell
python -m pytest tests/test_overlay_topmost_health.py::test_status_includes_overlay_compat_warning -q -x
```

  实测：`AttributeError: 'types.SimpleNamespace' object has no attribute 'latest_displayed_round'`（Python 3.14，2026-07-11）。

- **根因分析**：`RuntimeState.from_app` 链路新增 `GenerationPipelineState.from_app`，要求 `app` 具备 `latest_displayed_*` 属性；真实 `DanmuApp` 经 `main_state_mixin` 提供 `@property`（缺字段时回退 0），但测试仍用 `SimpleNamespace` 未补齐字段。  
- **最小修复建议**：在失败用例的 `SimpleNamespace` 上补齐 4 个属性（或改用 `bind_minimal_danmu_app`）；可选：在 `GenerationPipelineState.from_app` 对非 `DanmuApp` 使用 `getattr(app, ..., 0)` 增强容错（需评估是否掩盖真实集成缺陷）。  
- **是否建议本次自动修复**：是（仅改测试，范围 <10 行）  
- **需要补充的测试**：无（修复后原断言即可覆盖）  
- **修复摘要**：`tests/test_overlay_topmost_health.py` 中 `test_status_includes_overlay_compat_warning` 与 `test_status_clears_overlay_compat_warning_when_stopped` 的 `SimpleNamespace` mock 补齐 `latest_displayed_round` / `latest_requested_screenshot_id` / `latest_queued_screenshot_id` / `latest_displayed_screenshot_id`。  
- **修复验证**：`python -m pytest tests/test_overlay_topmost_health.py::test_status_includes_overlay_compat_warning tests/test_overlay_topmost_health.py::test_status_clears_overlay_compat_warning_when_stopped -q` → **2 passed**（2026-07-11）

---

### BUG-002：`FakeConfig` 未 canonical 化 `custom_models`，导致配置补丁单测误失败

- **修复状态**：✅ **已修复**（2026-07-11）  
- **严重等级**：P2
- **影响功能**：Web 配置保存回归测试；**生产 `ConfigStore.get_custom_models()` 会 canonical 化，用户路径不受影响**  
- **证据文件**：`app/model_selection.py`、`app/model_providers.py`、`tests/fakes.py`、`tests/test_web_auth.py`  
- **证据代码**：

```95:104:app/model_selection.py
def _uses_complete_custom_model(config, model_id: str) -> bool:
    ...
    custom = _custom_model_by_id(_custom_models_list(config), mid)
    return custom is not None and is_model_config_complete(custom)
```

```599:620:app/model_providers.py
    model_ids = data.get("model_ids")
    if isinstance(model_ids, list):
        ...
    else:
        errors.append("custom_model.error_model_id")
```

```157:158:tests/fakes.py
    def get_custom_models(self):
        return list(self.values.get("custom_models", []))
```

```113:150:tests/test_web_auth.py
    config.set_custom_models([{"modelId": "gpt-4o", ...}])  # 无 model_ids
    apply_config_patch(app, {"model": "gpt-4o", ...})
    # 期望通过 validate_web_config_patch
```

  对比生产读路径（会补全 `model_ids`）：

```275:275:app/config_store/storage_models.py
    return [canonicalize_custom_model_profile(dict(m)) for m in store._custom_models_cache]
```

- **复现路径**：

```powershell
python -m pytest tests/test_web_auth.py::test_apply_config_patch_updates_batch_and_ignores_visual_api_key -q -x
```

  实测：`ValueError: 请填写视觉模型 ID`（Python 3.14，2026-07-11）。

- **根因分析**：`W-ARCH-MODEL-PROFILE-CANONICAL-004` 后 `validate_model_config` 强制要求 `model_ids`；`FakeConfig.get_custom_models` 返回原始 dict，未调用 `canonicalize_custom_model_profile`。  
- **最小修复建议**：`FakeConfig.get_custom_models` 返回前对每个 entry 调用 `canonicalize_custom_model_profile`；或更新该测试 fixture 为含 `model_ids` 的 canonical shape。  
- **是否建议本次自动修复**：是（改 `tests/fakes.py` 或单测 fixture）  
- **需要补充的测试**：`tests/test_web_custom_models.py` 已覆盖 canonical CRUD（55 passed）；可加 1 条「legacy `modelId` 经 `get_custom_models` 仍可通过 `validate_web_config_patch`」集成测（`ConfigStore` 真库）  
- **修复摘要**：`tests/fakes.py::FakeConfig.get_custom_models` 返回前对每个 entry 调用 `canonicalize_custom_model_profile`，与 `ConfigStore.get_custom_models()` 读路径对齐。  
- **修复验证**：`python -m pytest tests/test_web_auth.py::test_apply_config_patch_updates_batch_and_ignores_visual_api_key -q` → **1 passed**（2026-07-11）

---

### BUG-003：`ConfigStore.get()` 在 `close()` 后仍返回缓存值且无错误

- **严重等级**：P2（边界/关停竞态）  
- **影响功能**：应用退出或 `close()` 与并发读配置；可能让关停期逻辑读到**已关闭连接对应的旧缓存**  
- **证据文件**：`app/config_store/storage.py`  
- **证据代码**：

```313:316:app/config_store/storage.py
    def get(self, key: str, default: str = "") -> str:
        if self._closed:
            logger.warning("ConfigStore.get(%s) called after close(), returning cached value", key)
        return self._cache.get(key, default)
```

  写路径对比（`set` 会抛错）：

```320:322:app/config_store/storage.py
        if self._closed:
            raise RuntimeError(f"ConfigStore.set({key!r}) called after close()")
```

- **复现路径**：在单测中 `store.close()` 后调用 `store.get("model")` → 返回关闭前缓存，仅 warning 日志。  
- **根因分析**：读路径刻意宽松（避免关停期崩溃），但与写路径不对称；关停窗口内若有线程仍读配置，无法区分「有效读」与「陈旧读」。  
- **最小修复建议**：文档化契约；或在 debug 构建对 `get` after close 抛 `RuntimeError`（与 `set` 对称）；或返回带版本戳的只读快照。  
- **是否建议本次自动修复**：否（行为契约变更，需产品确认）  
- **需要补充的测试**：`tests/test_config_store.py` 增加 `test_get_after_close_raises_or_marks_stale`

---

### BUG-004：`SECURITY.md` 声称自定义模型 `apiKey` 明文存 SQLite，与实现不符

- **修复状态**：✅ **已修复**（2026-07-11）  
- **严重等级**：P3（文档/安全评审误导）
- **影响功能**：安全政策、合规说明；不影响运行时加密  
- **证据文件**：`SECURITY.md`、`app/config_store/storage_models.py`  
- **证据代码**：

```15:15:SECURITY.md
（审计时原文，已更正）
- **自定义模型**的 `apiKey` 以 JSON 明文存入 SQLite；...
```

修复后正文：

```15:15:SECURITY.md
- **自定义模型**的 `apiKey` 以 Fernet 密文写入 `custom_models` JSON（与全局 `api_key_encrypted` 共用 `.key`）；读取时解密，legacy 明文会在读路径自动升级；`GET /api/config` 与 `GET /api/custom-models` 返回掩码值 `********`。
```

```186:200:app/config_store/storage_models.py
def _encode_custom_models_json(store: ConfigStore, models: list) -> str:
    ...
        if plain_key:
            ...
                entry["apiKey"] = _encrypt_custom_model_api_key(store, plain_key)
```

  单测佐证：`tests/test_web_custom_models.py::test_custom_model_api_key_encrypted_at_rest_in_sqlite`（本次审计 55 passed）。

- **复现路径**：阅读 `SECURITY.md` 与 `storage_models.py` 对比；或跑上述单测。  
- **根因分析**：`W-ARCH` 系列工单已引入 Fernet 内联加密，安全文档未同步。  
- **最小修复建议**：更新 `SECURITY.md` 为「自定义模型 `apiKey` 以 Fernet 密文存入 `custom_models` JSON；读时解密；legacy 明文读时自动升级」。  
- **是否建议本次自动修复**：是（纯文档，1 段）  
- **需要补充的测试**：已有；无需新增  
- **修复摘要**：更新 `SECURITY.md`「项目当前安全边界」中自定义模型 `apiKey` 存储说明，与 `app/config_store/storage_models.py::_encode_custom_models_json` 行为一致。

---

### BUG-005：`check_web_diagnostics_route_boundary` 在单测临时仓库读取不存在的 `diagnostics_routes.py` 抛 `FileNotFoundError`

- **修复状态**：✅ **已修复**（2026-07-11）  
- **严重等级**：P2（验收门控 / CI 回归）  
- **影响功能**：`run_acceptance_gates.py` 的 `test_boundary_guard_rules` 批次；**生产仓库** `boundary_guard.py` 本身一直 PASS，不影响运行时  
- **证据文件**：`scripts/boundary_guard/rules/web.py`、`tests/boundary_guard_helpers.py`、`.acceptance_gates_report.txt`  
- **证据代码**：

```91:102:scripts/boundary_guard/rules/web.py
def check_web_diagnostics_route_boundary(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    ...
    for rel_path in _diagnostics_route_paths():
        abs_path = repo_root / rel_path
        if abs_path.is_file():
            lines.extend(_read_lines(abs_path))
```

  修复前：`routes.py` 出现在 `changed` 时无条件 `_read_lines(diagnostics_routes.py)`，而 `_baseline_repo()` 未创建该文件 → 6 例单测 `FileNotFoundError`。

- **复现路径**（修复前）：

```powershell
python -m pytest tests/test_boundary_guard_web_rules.py::test_boundary_guard_detects_web_private_access -q
python scripts/run_acceptance_gates.py
```

  实测：`test_boundary_guard_rules` → 6 failed / 31 passed；`ACCEPTANCE_GATES: FAIL`。

- **根因分析**：Web API 拆出 `diagnostics_routes.py` 后，boundary guard 规则改为扫描双文件，但未对「文件不存在」做 `is_file()` 守卫；单测最小仓库仅含 `routes.py`。  
- **最小修复建议**：读取前判断 `abs_path.is_file()`；可选同步在 `_baseline_repo` 补 stub `diagnostics_routes.py`（非必须）。  
- **是否建议本次自动修复**：是  
- **需要补充的测试**：已有 `tests/test_boundary_guard_*_rules.py` 覆盖；修复后 37 passed  
- **修复验证**：

```text
python -m pytest tests/test_boundary_guard_web_rules.py tests/test_boundary_guard_request_rules.py tests/test_boundary_guard_diagnostics_rules.py -q
  → 30 passed
python scripts/run_acceptance_gates.py
  → ACCEPTANCE_GATES: PASS（test_boundary_guard_rules: 37 passed）
```

---

## 3. 高风险但未确认问题

| ID | 标题 | 为何未确认 | 建议人工验证 |
|----|------|------------|--------------|
| RISK-001 | 单实例启动竞态可能导致双实例 | `single_instance.py` 模块文档承认 QLocalServer 未就绪窗口；`main()` 有 3 次重试，但极端慢启动机未在本机双开压测 | 冷启动 EXE 后 500ms 内连点第二次快捷方式；观察是否出现两个托盘 |
| RISK-002 | 独占全屏游戏内 Overlay 置顶失效 | 已有 `SetWindowPos` 连续失败计数与 `overlay_compat_warning`（BUG-004），属 Win32 层级限制 | 全屏 DX/Vulkan 游戏 + 弹幕开启，观察 `/api/status.overlay_compat_warning` 与托盘提示 |
| RISK-003 | pywebview 冷启动 >25s 时用户仅见托盘 | `webview_shell.py` 握手超时与浏览器回退逻辑存在，慢机未实测 | WebView2 未预热机器首次启动，记录 `%APPDATA%\DanmuAI\startup.log` 时间线 |
| RISK-004 | Supabase `app_updates` 与 R2 版本漂移 | `check_release_endpoints.ps1` 仅验证 Feed=0.3.9；脚本提示 Supabase 需人工核对 | 配置 `DANMU_SUPABASE_*` 后 `GET http://127.0.0.1:18765/api/update/channels`，比对 `latest_version` / `release_url` |
| RISK-005 | 本地 `web/static/supabase-config.js` 误提交 | 文件含真实 anon key（已 `.gitignore`）；`publish_windows_release.ps1` 与 `DanmuAI.spec` 有 default-deny 护栏 | 发版前跑 `publish_windows_release.ps1 -DryRun`；检查产物 `web/static` 无 `supabase-config.js` |
| RISK-006 | `is_stored_custom_pool_text` 在缺 `custom_danmu_contains_text` 时全表加载 | 代码路径 `getter()` → `get_custom_danmu_pool()` 可触发 2 万条加载；`ConfigStore` 已实现 `custom_danmu_contains_text`，仅 mock/旧适配器可能踩中 | 用 2 万条库 + 高频去重路径 profiling |

---

## 4. 性能与卡顿风险

| 区域 | 结论 | 证据 |
|------|------|------|
| **启动** | 托盘先显、Web 控制台异步就绪（BUG-007 已避免 `__init__` 阻塞 `wait_ready`） | `app/web_console.py:623-640`；`main_lifecycle_mixin._init_startup_services` 延迟迁移 |
| **截图/压缩** | 主线程抓屏 + worker 压缩；`MAX_IN_FLIGHT=1` 限制并发成本 | `main.py` 注释；`app/main_helpers.py` |
| **Overlay/轨道** | 去重纯 Python fallback 有 O(m×n) 截断（BUG-009）；轨道加权随机非确定性 | `app/danmu_engine_dedup.py:20-25` |
| **SQLite 自定义库** | `set_custom_danmu_pool` diff 路径；1.5 万条替换 <2s（单测门槛） | `tests/test_custom_danmu_pool_large_diff_performance.py`（112 passed 批次含此文件） |
| **自定义库全量读** | `get_custom_danmu_pool_for_store` 仍迭代全表；**元数据 API 已用 `custom_danmu_count`** | `app/danmu_pool.py:645-647`、`app/web_api/danmu_pool.py:43-58` |
| **外部接口** | 烂梗 AI 选梗走独立 `meme_ai_pool`（BUG-G05），不占用视觉 `MAX_IN_FLIGHT` | `app/worker_pools.py` |
| **模型请求** | httpx 30s 超时；in-flight 48s 强制恢复（`inflight_watchdog_recover`） | `app/ai_client.py:99`；`app/main_request_context_mixin.py:107-147` |

---

## 5. 兼容性与环境风险

| 项 | 说明 |
|----|------|
| **Python 版本** | 本地 **3.14** 跑 pytest 时大量 `subprocess._readerthread` `UnicodeDecodeError`（GBK 字节 0xd2）；README 声明 3.12 推荐。CI 使用 3.12，**不代表 3.14 受支持**。 |
| **PowerShell 编码** | 审计中部分带 `(cd ...; cmd)` 包装命令解析失败；直接 `python -m pytest` 正常。脚本已设 `$OutputEncoding = UTF8`（如 `publish_windows_release.ps1:11`）。 |
| **中文路径** | 未在本轮对含中文的 `%APPDATA%` 或工程路径做专项压测（待确认）。 |
| **显卡/窗口层级** | Overlay 使用 `Tool \| BypassWindowManagerHint` + Win32 layered/transparent；独占全屏场景依赖周期性 health tick 重断言置顶。 |

---

## 6. 发布与更新风险

| 检查项 | 状态 | 证据 |
|--------|------|------|
| PyInstaller spec 凭据护栏 | 已确认 | `DanmuAI.spec:44-57` default-deny `supabase-config*` |
| 发布脚本凭据护栏 | 已确认 | `scripts/publish_windows_release.ps1:18-36` |
| Velopack 外链 | 已确认可达 | `check_release_endpoints.ps1`：Feed/Setup/Portable/GitHub API 全 OK，FeedLatestFull=**0.3.9** |
| 版本一致性 | 已确认 | `app/version.py::__version__ = "0.3.9"` |
| MSI 主入口 | 已移除（历史） | release skill W-REL-CLEANUP-001；勿按旧 MSI 文档发版 |
| 代码签名 | 默认关闭 | SmartScreen「未知发布者」；见 `README.md` + `PACKAGING_WINDOWS.md` |
| CI 锁文件 | 未强制 | `PACKAGING_WINDOWS.md`：`DANMU_BUILD_USE_RELEASE_LOCK=1` 可选；CI 仍用范围依赖 |
| 用户数据保留 | 设计保留 | `uninstall_service.py` BUG-A06 限制删除范围在 `%APPDATA%` 父路径校验 |
| 本地树与远端 | **落后 3 commit** | `git status` 快照；发版审计应以即将发布的 commit 为准 |

---

## 7. 安全与隐私风险

| 项 | 等级 | 说明 |
|----|------|------|
| `/api/session` 零成本取 token | 已缓解 | `enforce_session_authorization`：无 Origin 的 curl 401（`app/web_console_session_auth.py`） |
| 本机只读 API 无 Bearer | 设计如此 | `GET /api/config`、`/api/logs/recent`、`/api/status` 等无 token（`SECURITY.md` 威胁模型：信任本机用户） |
| 自定义模型密钥存储 | 已确认 + 文档已同步 | BUG-004 已修复；DB 内 Fernet 密文，`SECURITY.md` 已更新 |
| 全局 API Key | Fernet + legacy base64 升级 | `storage_models.py:encrypted_get_for_store` |
| 日志脱敏 | 已实现 | `app/logger.py`：`sk-`、`Authorization`、`data:image` base64 等模式 |
| Supabase anon | 开发机本地 js 含 key | **gitignore**；打包排除；应用内仅 anon 权限 + RLS（`011_anon_table_grants.sql`） |
| 社区后端 | 不在本仓库 | `SECURITY.md` 指向 `community/` 子项目；本轮未审计其 RLS |

---

## 8. 建议新增的测试

| 测试文件 | 测试目标 | 关键断言 |
|----------|----------|----------|
| `tests/test_status_snapshot_generation_pipeline.py` | `build_status_snapshot` 与 `GenerationPipelineState` 投影 | 极简 `bind_minimal_danmu_app` 调用 `build_status_snapshot` 不抛异常；`overlay_compat_warning` 字段可设置（**部分已由 BUG-001 修复覆盖**） |
| `tests/test_fake_config_canonical_models.py` | `FakeConfig` 与生产读路径一致 | `set_custom_models([{modelId:...}])` 后 `get_custom_models()[0]["model_ids"]` 非空且 `validate_web_config_patch` 通过（**核心行为已由 BUG-002 修复覆盖**；独立文件仍可选） |
| `tests/test_config_store_close_read.py` | 关闭后读语义 | `close()` 后 `get` 行为符合文档（抛错或显式 stale 标记） |
| `tests/test_release_endpoints_integration.py` | 发布冒烟脚本可导入 | 对 `check_release_endpoints.ps1` 的 `Normalize-Semver` / feed 解析做 Python 镜像测试（已有 `tests/test_check_release_endpoints_script.py` 可扩展 ExpectedVersion 参数） |
| `tests/test_subprocess_encoding_windows.py` | Windows GBK 子进程 | 触发带非 UTF-8 输出的 helper，断言 pytest 无 `UnicodeDecodeError` 线程告警（应用 `encoding=utf-8, errors=replace`） |

---

## 9. 本次可自动修复项

| 项 | 状态 | 说明 |
|----|------|------|
| **BUG-001** 测试补全 `latest_displayed_*` 字段 | ✅ 已完成 | `tests/test_overlay_topmost_health.py` |
| **BUG-002** `FakeConfig.get_custom_models` canonical 化 | ✅ 已完成 | `tests/fakes.py` |
| **BUG-004** 更新 `SECURITY.md` 自定义模型加密描述 | ✅ 已完成 | `SECURITY.md` |
| **BUG-005** boundary_guard 诊断路由缺文件容错 | ✅ 已完成 | `scripts/boundary_guard/rules/web.py` |
| **BUG-003** `get after close` 读语义 | ⏸ 未修复 | 契约变更需负责人确认 |

**仍开放自动修复**：无（除 BUG-003 外，审计建议项均已落地）。

---

## 10. 最终建议（Top 3）

1. **【P2 / 发版】发版前强制执行 `check_release_endpoints.ps1` + Supabase `app_updates` 人工核对（RISK-004）**  
   理由：R2 链路已自动验证 0.3.9；更新弹窗还依赖 Supabase 表，漂移会导致「Feed 已更新但 Web 公告仍指向旧版」的用户困惑。

2. **【P2 / 数据契约】决策 BUG-003：`ConfigStore.get()` after `close()` 是否改为抛错或返回显式 stale**  
   理由：写路径已 `RuntimeError`，读路径仍静默回缓存；关停竞态下可能误导后台线程。

3. **【P3 / 文档】校正 `docs/final-architecture-baseline.md` mixin 数量（8→13）**  
   理由：Boundary Guard 维护者登记表与 AGENTS.md 不一致；BUG-004（`SECURITY.md`）已于 2026-07-11 同步完成。

---

## 附录 A：必查模块打勾

| 模块 | 状态 | 备注 |
|------|------|------|
| A 启动与生命周期 | ✅ | 单实例/托盘/Web/pywebview 分工已读；未做双开压测 |
| B 弹幕显示链路 | ✅ | 截图→API→去重→轨道→Overlay 主路径已读；overlay status 相关单测 BUG-001 修复后已通过 |
| C 模型调用与成本 | ✅ | `MAX_IN_FLIGHT=1`、压缩、超时、in-flight 恢复已确认 |
| D 麦克风/读弹幕 | ✅ | `mic_insert_reply_count` 与普通条数一致；TTS 测试文件通过（未全跑 mic 批次） |
| E 桌宠 | ✅ | `pet_facade` 沙箱与 barrage 模式恢复逻辑已读；未做 GUI 手测 |
| F 配置/SQLite | ✅ | WAL/锁/close 语义/diff 池已读；config_store 112 passed |
| G 公式化弹幕库 | ✅ | 分页 API + diff 写入；全量读路径已标性能风险 |
| H 自动更新与发布 | ✅ | 脚本链 + 在线端点已验证 |
| I Web 社区与后端 | ⚠️ | 本仓库仅 Supabase 客户端/迁移；`community/` 未纳入 |
| J 测试与验收 | ✅ | 分批 pytest + boundary_guard；`run_acceptance_gates.py` **全量 PASS**（2026-07-11 复测） |

---

## 附录 B：本次运行的命令与结果

```text
python -m pytest tests/test_overlay_topmost_health.py -q -x
  → 13 passed, 1 failed (test_status_includes_overlay_compat_warning)

python -m pytest tests/test_config_store.py tests/test_danmu_pool.py tests/test_custom_danmu_pool_large_diff_performance.py -q -x
  → 112 passed

python -m pytest tests/test_web_console.py tests/test_p0_main_flow.py tests/test_ai_client.py -q -x
  → 25 passed, 1 skipped

python -m pytest tests/test_release_channels.py tests/test_packaging_executable_name.py tests/test_check_release_endpoints_script.py -q -x
  → 83 passed

python -m pytest tests/test_web_auth.py tests/test_danmu_tts.py tests/test_mic_insert.py -q -x
  → 5 passed, 1 failed (test_apply_config_patch_updates_batch_and_ignores_visual_api_key)

python -m pytest tests/test_web_custom_models.py tests/test_persona_model_bindings.py -q -x
  → 55 passed

python scripts/boundary_guard.py
  → Boundary Guard: PASS

powershell -File scripts/check_release_endpoints.ps1
  → All automated checks passed (FeedLatestFull=0.3.9)
```

---

## 附录 D：修复后复测（2026-07-11）

| 修复项 | 修改文件 | 验证命令 | 结果 |
|--------|----------|----------|------|
| BUG-001 | `tests/test_overlay_topmost_health.py` | `python -m pytest tests/test_overlay_topmost_health.py::test_status_includes_overlay_compat_warning tests/test_overlay_topmost_health.py::test_status_clears_overlay_compat_warning_when_stopped -q` | 2 passed |
| BUG-002 | `tests/fakes.py` | `python -m pytest tests/test_web_auth.py::test_apply_config_patch_updates_batch_and_ignores_visual_api_key -q` | 1 passed |
| BUG-004 | `SECURITY.md` | 人工 diff：自定义模型 `apiKey` 条目与 `storage_models.py` 一致 | 已对齐 |
| BUG-005 | `scripts/boundary_guard/rules/web.py` | `python -m pytest tests/test_boundary_guard_*_rules.py -q` | 37 passed |
| BUG-005 | 同上 | `python scripts/run_acceptance_gates.py` | **ACCEPTANCE_GATES: PASS** |
| 合并冒烟 | BUG-001/002 | `python -m pytest ... -q -x`（三条用例一次跑） | **3 passed** |

```text
# 合并冒烟（2026-07-11 实测）
python -m pytest tests/test_overlay_topmost_health.py::test_status_includes_overlay_compat_warning tests/test_overlay_topmost_health.py::test_status_clears_overlay_compat_warning_when_stopped tests/test_web_auth.py::test_apply_config_patch_updates_batch_and_ignores_visual_api_key -q -x
  → 3 passed in 0.76s
```

---

## 附录 C：自检评分（0~2）

| 维度 | 得分 | 说明 |
|------|------|------|
| 证据完整性 | 2 | 均含路径/代码/复现或命令输出 |
| 严重度准确性 | 2 | P0/P1 无证据不立案；测试问题标 P2 |
| 已确认 vs 待确认 | 2 | §2 与 §3 分离 |
| 发布更新链路 | 2 | 脚本 + 在线端点 + 版本号 |
| 可执行测试建议 | 2 | §8 含文件名与断言 |
| **总分** | **10/10** | 达输出门槛 |

---

*报告生成：自动化审计代理；手动验收（真实 EXE、游戏全屏、麦克风、桌宠拖动）未在本轮执行。*  
*修复同步：2026-07-11，BUG-001/002/004/005 已落地并复测通过（附录 D）；`run_acceptance_gates.py` 全量 PASS。*
