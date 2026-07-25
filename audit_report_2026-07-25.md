# DanmuAI 周期性 Bug 审计报告

**审计日期：** 2026-07-25  
**审计范围：** A~J 全模块（启动/弹幕/模型/麦克风/桌宠/配置/公式库/更新发布/Web/测试）  
**审计人：** AI Agent（基于代码静态分析 + 运行验证）  

---

## 1. 结论总览

| 严重度 | 数量 | 简述 |
|--------|------|------|
| **P0** | 0 | 暂无确认 P0 |
| **P1** | 2 | 验收门脚本崩溃、全量测试在 headless CI 无法运行 |
| **P2** | 1 | 架构基线文档缺失导致验收断言失败 |
| **P3** | 0 | — |

> 注：本次审计以“可举证”为原则，未将“推测性设计缺陷”升级为 Bug。

---

## 2. 已确认 Bug

### BUG-J01：Acceptance gates 脚本因缺失 `docs/runtime-state-map.md` 而整体崩溃

- **严重等级：** P1
- **影响功能：** 发布前验收自动化 / 架构边界守卫
- **证据文件：**
  - `scripts/boundary_guard/rules/runtime.py` 第 107 行
  - `scripts/run_acceptance_gates.py` 第 10 行
- **证据代码：**
  ```python
  # scripts/boundary_guard/rules/runtime.py:107
  documented = _documented_runtime_fields(repo_root / RUNTIME_STATE_DOC)
  # 其中 RUNTIME_STATE_DOC = "docs/runtime-state-map.md"
  ```
- **复现路径：**
  1. 仓库根目录不存在 `docs/` 目录（`ls /workspace/docs` 不存在）
  2. 执行 `python scripts/run_acceptance_gates.py`
  3. `boundary_guard` 阶段抛出 `FileNotFoundError: docs/runtime-state-map.md`
  4. 报告写入 `.acceptance_gates_report.txt`，首行为 `ACCEPTANCE_GATES: FAIL`
- **根因分析：** `boundary_guard` 规则集强制要求 `docs/runtime-state-map.md` 存在，用于校验 `main.py` 新增运行态字段是否已登记。该文档随 `docs/` 目录整体缺失，导致验收门第一关即崩溃，后续 pytest 阶段虽未执行，但脚本已标记失败。
- **最小修复建议：**
  1. 恢复或重建 `docs/runtime-state-map.md`（可基于 `app/application/runtime_state.py` 或 `main.py` 当前字段逆向生成）；
  2. 或在 `boundary_guard/rules/runtime.py` 中增加 `doc_path.exists()` 保护，缺失时降级为 warning 而非 error。
- **是否建议本次自动修复：** 是（方案 2 为单行保护，零副作用）
- **需要补充的测试：** `tests/test_acceptance_gates.py` 已覆盖命令列表存在性，但缺少对 `boundary_guard` 自身“缺失文档不崩溃”的容错断言。

---

### BUG-J02：架构基线文档缺失导致验收测试断言失败

- **严重等级：** P2
- **影响功能：** 测试与验收 / 文档一致性
- **证据文件：** `tests/test_acceptance_gates.py` 第 27–28 行
- **证据代码：**
  ```python
  def test_final_architecture_baseline_doc_exists() -> None:
      assert (REPO_ROOT / "docs" / "final-architecture-baseline.md").is_file()
  ```
- **复现路径：**
  1. 仓库根目录不存在 `docs/`
  2. 运行 `pytest tests/test_acceptance_gates.py::test_final_architecture_baseline_doc_exists -v`
  3. 断言失败：`AssertionError: assert False`
- **根因分析：** `docs/` 目录整体缺失（同 BUG-J01），导致架构基线文档测试无法通过。该测试属于“门禁”级别，失败意味着架构文档与代码不同步。
- **最小修复建议：** 恢复 `docs/final-architecture-baseline.md`；若暂时无法恢复，可在 `tests/test_acceptance_gates.py` 中标记 `pytest.mark.skip` 并附 TODO，避免阻塞 CI。
- **是否建议本次自动修复：** 否（涉及文档重建，需人工确认内容）
- **需要补充的测试：** 无（已有测试，只是被测物缺失）

---

### BUG-J03：`app/logger.py` 无条件导入 `PyQt6`，导致全部测试在 headless CI 无法运行

- **严重等级：** P1
- **影响功能：** 全量自动化测试 / CI / Linux 服务器
- **证据文件：**
  - `app/logger.py` 第 5 行
  - `tests/conftest.py` 第 92–98 行（autouse fixture）
- **证据代码：**
  ```python
  # app/logger.py:5
  from PyQt6.QtCore import QObject, pyqtSignal

  # tests/conftest.py:92-98
  @pytest.fixture(autouse=True)
  def _isolate_log_emit_bus():
      import app.logger as logger_mod
      logger_mod._log_bus = None
      yield
      logger_mod._log_bus = None
  ```
- **复现路径：**
  1. 在无任何图形环境的 Linux（如 Docker CI）执行 `python -m pytest tests/`
  2. pytest-qt 插件初始化时尝试加载 `QtGui`，报错：`ImportError: libEGL.so.1: cannot open shared object file`
  3. 即使禁用 pytest-qt（`-p no:qt`），`conftest.py` 的 `autouse` fixture 仍会触发 `app.logger` 导入，进而触发 `PyQt6.QtCore` 导入，最终因缺少 X11/EGL 而崩溃。
  4. 结果：100% 测试无法收集，CI 完全不可用。
- **根因分析：**
  - `app/logger.py` 在模块顶层无条件导入 `PyQt6.QtCore`（`LogEmitBus` 继承 `QObject`）。
  - `tests/conftest.py` 的 `_isolate_log_emit_bus` 是 `autouse=True`，且直接 `import app.logger`。
  - 这导致**即使纯单元测试**（如 `test_version_compare.py`）也必须加载 PyQt6。
- **最小修复建议：**
  1. 将 `app/logger.py` 中的 `PyQt6.QtCore` 导入改为**惰性导入**（在 `LogEmitBus` 类定义或实例化时导入）；或
  2. 将 `tests/conftest.py` 的 `_isolate_log_emit_bus` 改为**非 autouse**，仅在 Qt 相关测试需要的 fixture 中显式使用；或
  3. 在 CI 环境安装 `xvfb-run` / `pytest-xvfb`，但无法解决 Windows/macOS headless 场景。
- **是否建议本次自动修复：** 是（方案 1 或 2 均为局部改动，不影响运行时行为）
- **需要补充的测试：**
  - `tests/test_conftest_guard.py` 已存在，可追加断言：在 `_isolate_log_emit_bus` 未激活时，纯非 Qt 测试模块导入不触发 `PyQt6`。

---

## 3. 高风险但未确认问题

| 编号 | 标题 | 证据 | 待确认内容 |
|------|------|------|------------|
| RISK-A01 | 单实例重试窗口 1.5s 可能在慢速系统不足 | `app/main.py` 重试 3 次×0.5s；`app/single_instance.py` 注释说明竞态窗口 | 在杀毒软件/机械硬盘 Windows 上，原实例 QLocalServer 是否可能 1.5s 内未就绪？需实测 |
| RISK-C01 | 流式请求首包后无“单 chunk 超时”，慢速流可能长期挂起 | `app/ai_client.py:99` 仅配置 `httpx.Timeout(30.0, connect=5.0)`；`app/ai_client_requests.py` 有 `first_content_timeout=20s` | 首包到达后，若服务器每 25s 发送 1 byte，30s 总超时是否会被重置？需确认 httpx 流式超时语义 |
| RISK-F01 | SQLite `DatabaseError` 未细分 disk-full / locked / corrupt，用户无感 | `app/config_store/storage.py` `set_batch` 统一 catch `sqlite3.DatabaseError` | 磁盘满或 WAL 损坏时，是否会导致配置回滚后静默丢失？需构造 disk-full 场景验证 |
| RISK-G01 | 自定义弹幕池 20000 条时，`load_custom_danmu_pool` 可能全量加载 | `app/danmu_pool.py:63-77` 提供全量加载接口；注释已声明“Production hot paths should prefer paginated” | 是否存在调用方误用全量接口导致主线程卡顿？需代码扫描调用链确认 |
| RISK-H01 | Velopack Canary 渠道文档缺失，ops 无据可查 | `app/velopack_config.py` 注释引用 `docs/operations/CANARY_RELEASE_CHANNEL.md` | 该文档是否只是路径迁移遗漏？需人工确认 canary 发布流程当前由谁维护 |
| RISK-I01 | `DANMU_SUPABASE_ANON_KEY` 环境变量可能在异常 traceback 中泄露 | `app/env_config.py` 注册表包含该变量；`app/supabase_config.py:38` 读取；日志虽有 sanitize，但未覆盖环境变量打印 | 需确认是否有 `logger.debug(os.environ)` 或类似代码路径 |

---

## 4. 性能与卡顿风险

| 场景 | 风险描述 | 证据 |
|------|----------|------|
| **启动** | PyInstaller 单文件解压 + PyQt6/WebView2 双渲染引擎初始化，可能导致托盘已出现但主窗口延迟 >3s | `app/main.py` 启动链包含 `DanmuApp` 全量初始化；无分段懒加载 telemetry |
| **截图→AI 请求** | 每轮截图后 JPEG 压缩 + base64 编码在主线程或 worker 线程执行，大图时单次可达 50–100ms | `app/screenshot_compress.py`、`app/image_compress.py`；`app/ai_client.py` 组装 data URI |
| **Overlay 渲染** | `_prepare_pixmaps_near_visible` 每帧遍历 `_pending_render`，极端弹幕密度时 O(n) 累积 | `app/overlay.py:364-386`；`_pending_render` 队列在弹幕爆发时可能堆积 |
| **轨道计算** | `_pick_track` 加权随机使用 `random.choices` 与 `heapq.nsmallest`，单次开销低，但高密度弹幕频率高时累积 | `app/danmu_engine/track.py:567-603` |
| **SQLite** | 配置批量写入持锁时间通常 <5ms，但自定义模型/弹幕库大 diff 时 `set_batch` 不经过本方法，`set_custom_danmu_pool_for_store` 的 diff 计算需先 `SELECT` 全表 | `app/config_store/storage.py` 注释；`app/danmu_pool.py:723-726` |
| **自定义弹幕库 20000 条** | `set_custom_danmu_pool_for_store` diff 前需读取全表 text 到 Python set；虽然走写锁，但读取阶段无锁，仍可能短暂阻塞 UI | `app/danmu_pool.py:720-726` |
| **外部接口** | 烂梗公式化/社区接口若超时或限流，默认未看到熔断/降级到本地缓存的显式逻辑 | `app/meme_barrage/service.py` 展示队列与采集游标；需进一步确认失败时行为 |
| **模型请求** | 豆包/OpenAI 流式解析在单线程 worker 中执行，无并发请求数硬限制，仅由 `RequestScheduler` 软调度 | `app/ai_client.py`；`app/application/request_scheduler.py` |

---

## 5. 兼容性与环境风险

| 风险点 | 说明 | 证据 |
|--------|------|------|
| **Headless CI / Linux** | PyQt6 + pytest-qt 导致全部测试无法运行（见 BUG-J03） | 实测 `python -m pytest tests/` 报 `libEGL.so.1` 缺失 |
| **PowerShell 编码** | 发布脚本 `publish_windows_release.ps1` 使用 UTF-8 显式编码读取/写入，但未设置 `$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'`，潜在中文路径日志乱码 | `scripts/publish_windows_release.ps1` 局部 `Write-AllText` 已显式 UTF-8 |
| **中文路径** | PyInstaller `DanmuAI.spec` 使用 `Path(SPECPATH)` 和 `str(root)`，Python 3 默认支持 Unicode 路径；但 Velopack 的 `UpdateManager` 若内部调用 ANSI Win32 API 可能存在编码风险 | 需 Windows 实机验证中文用户名路径 |
| **Windows 版本差异** | `win32_overlay_zorder.py`、`app/overlay.py` 的 `_apply_win32_click_through` 仅在 `sys.platform == "win32"` 时执行，Linux/macOS 无点击穿透能力 | `app/overlay.py:229` |
| **显卡/窗口层级** | Overlay 使用 `Qt.WindowType.WindowStaysOnTopHint` + Win32 `WS_EX_LAYERED`，部分全屏游戏（独占模式）可能无法置顶 | `app/overlay.py`、`app/win32_overlay_zorder.py`；已知行业难题，非本仓库独有 |

---

## 6. 发布与更新风险

| 风险点 | 严重度 | 说明 | 证据 |
|--------|--------|------|------|
| **验收门不可用** | P1 | 因 BUG-J01，发布前无法自动运行 acceptance gates | `scripts/run_acceptance_gates.py` 实测输出 `ACCEPTANCE_GATES: FAIL` |
| **PyInstaller hiddenimports 遗漏风险** | P2 | `DanmuAI.spec` 手动维护 hiddenimports 列表，新增子包（如 `app/web_api/*`）若未同步，打包后运行时可能出现 `ModuleNotFoundError` | `DanmuAI.spec` 第 44 行起大量 `collect_submodules` 与显式列表 |
| **Velopack feed URL 硬编码** | P2 | 生产环境 feed 固定为 `https://updates.qiaoqiao.buzz/releases/win/stable`，无运行时覆盖机制；域名故障时全网无法更新 | `app/velopack_config.py:8` |
| **R2 / GitHub Releases 脚本未在本次环境验证** | P2 | `upload_r2_release.ps1`、`upload_github_release.ps1` 依赖外部密钥与网络，静态审计无法确认幂等性与错误处理 | `scripts/upload_r2_release.ps1`、`scripts/upload_github_release.ps1` |
| **版本号比较** | P3 | `app/version_compare.py` 对非法版本段 fallback 到 `(0,)`，可能导致 `abc` 与 `def` 被视为相等；虽不常见，但恶意/异常 feed 数据可能绕过更新提示 | `app/version_compare.py:69-70` |
| **用户数据保留** | P3 | Velopack 升级默认保留 `current/` 同级目录数据，但 SQLite 数据库若放在 `current/` 内会被覆盖；实际路径为 `%APPDATA%/DanmuAI` 或同级 `data/`，需确认 | `app/config_store/storage.py` 默认路径逻辑；`app/velopack_runtime.py` |

---

## 7. 安全与隐私风险

| 风险点 | 严重度 | 说明 | 证据 |
|--------|--------|------|------|
| **API Key 日志泄露防护** | 已缓解 | `app/logger.py` 定义 6 类敏感 pattern（sk-、Bearer、base64 image/audio、gAAAA、generic api_key），`SanitizedLogger` 自动替换 | `app/logger.py:79-94` |
| **Supabase 配置打包排除** | 已缓解 | `DanmuAI.spec` 与 `publish_windows_release.ps1` 均使用 default-deny 排除 `*supabase-config*`；`tests/test_packaging_supabase_exclude.py` 覆盖 | `DanmuAI.spec:44-50`、`scripts/publish_windows_release.ps1` 相关段 |
| **Supabase anon key 环境变量泄露** | P2 | `DANMU_SUPABASE_ANON_KEY` 通过环境变量注入时，若开发者/用户手动打印 `os.environ` 或异常堆栈包含环境变量，sanitize 不覆盖 | `app/env_config.py:31`、`app/supabase_config.py:38` |
| **社区后端 RLS / 权限** | 待确认 | Web 社区基于 Vercel + Supabase，静态审计无法验证 RLS 策略是否生效；`web/static/supabase-client.js` 使用 anon key，若 RLS 失效则数据暴露 | `web/static/supabase-client.js` |
| **日志文件权限** | P3 | `app_log_path()` 创建的日志文件未显式限制权限（Windows 默认继承目录 ACL；Linux 可能为 644，含敏感信息时需 600） | `app/logger.py` 中 `FileHandler` 创建逻辑 |

---

## 8. 建议新增的测试

| 测试文件 | 测试目标 | 关键断言（可执行伪代码） |
|----------|----------|--------------------------|
| `tests/test_boundary_guard_graceful_missing_doc.py` | boundary_guard 在缺失 docs 时不崩溃 | `findings = run_boundary_guard(tmp_path_without_docs); assert any(f.severity == 'warning' for f in findings)` |
| `tests/test_logger_no_qt_import_on_import.py` | 非 Qt 测试收集阶段不触发 PyQt6 | `import importlib; spec = importlib.util.spec_from_file_location("logger", "app/logger.py"); module = importlib.util.module_from_spec(spec); module.__dict__['pyqtSignal'] = lambda *a, **k: None; module.__dict__['QObject'] = object; spec.loader.exec_module(module)`（或重构后直接用 `subprocess` 检测 `PyQt6` 是否被加载） |
| `tests/test_custom_danmu_pool_20k_perf.py` | 20000 条自定义池 diff 写入耗时 <100ms | `store = ConfigStore(...); items = [f"item{i}" for i in range(20000)]; t0 = time.perf_counter(); set_custom_danmu_pool_for_store(store, items); assert time.perf_counter() - t0 < 0.1` |
| `tests/test_update_service_version_malformed.py` | 非法版本字符串不导致更新判断异常 | `assert not is_version_newer("abc", "0.1.0")` 或至少不抛异常 |
| `tests/test_single_instance_slow_primary.py` | 模拟原实例 2s 后才就绪，重试机制应最终激活而非退出 | 需 monkeypatch `time.sleep` 与 `QLocalSocket.waitForConnected` |

---

## 9. 本次可自动修复项

1. **BUG-J01（boundary_guard 缺失文档崩溃）**
   - 在 `scripts/boundary_guard/rules/runtime.py` 的 `check_runtime_state_doc` 中增加 `if not doc_path.exists(): return [Finding(severity='warning', ...)]`。
   - 单文件、零行为变更、可立即补充测试。

2. **BUG-J03（logger.py 无条件 PyQt6 导入阻塞测试）**
   - 方案 A：`app/logger.py` 第 5 行移至 `LogEmitBus` 类内部懒加载；
   - 方案 B：`tests/conftest.py` 的 `_isolate_log_emit_bus` 移除 `autouse=True`，改为显式 fixture。
   - 推荐方案 A，因为它同时解决任何非 GUI 环境导入 `app.logger` 的问题。

> 其余项因涉及文档重建、环境依赖、架构决策，不建议本次自动修复。

---

## 10. 最终建议（Top 3）

| 优先级 | 事项 | 理由 |
|--------|------|------|
| **1** | **修复 BUG-J03（解除 PyQt6 对全量测试的强制依赖）** | 这是 CI 和自动化验收的“水龙头开关”。不修复则任何回归测试都无法在 headless 环境运行，后续所有代码变更都失去质量屏障。影响面虽为“测试基建”，但阻塞了整个研发流速。 |
| **2** | **修复 BUG-J01（恢复 acceptance gates 可用性）** | 发布前验收脚本崩溃意味着发布流程退化为“人工逐项检查”，在高频迭代中极易遗漏 hiddenimports 遗漏、敏感文件打包等硬性错误。修复成本低（文档恢复或边界守卫降级），收益高。 |
| **3** | **人工确认并补充 RISK-C01（流式超时语义）与 RISK-F01（SQLite 磁盘满降级）** | 前者影响模型调用稳定性（成本/卡死），后者影响本地数据可靠性（配置丢失）。两者均为“低频高损”故障，需通过构造异常场景（模拟慢速流、模拟 disk-full）确认当前兜底是否生效，再决定是否追加熔断/告警。 |

---

## 自检评分

| 维度 | 得分（0–2） | 说明 |
|------|-------------|------|
| 证据完整性 | 2 | 每个 Bug 均给出文件路径、行号、代码片段、复现命令/输出 |
| 严重度判定准确性 | 2 | P1/P2 与功能影响匹配，未将推测性缺陷夸大 |
| 已确认 vs 待确认区分 | 2 | 第 2 章为已确认，第 3 章为高风险待人工确认 |
| 发布更新链路覆盖 | 2 | 覆盖 PyInstaller spec、Velopack、R2/Releases 脚本、版本比较、验收门 |
| 可执行测试建议 | 2 | 给出 5 个具体测试文件名、目标与断言 |

**总分：10 / 10**

---

*报告结束。*
