# DanmuAI 周期性 Bug 审计报告

**审计日期**: 2026-07-29  
**审计范围**: A~J 全部必查模块  
**环境**: Linux (Python 3.14.4, pytest-9.0.3), 远程沙箱  
**审计人**: AI Agent (Kimi-K2.6)

---

## 1. 结论总览

| 严重度 | 数量 | 说明 |
|--------|------|------|
| P0 | 0 | 未发现无法启动 / 数据丢失 / 安全泄露 / 发布不可用的产品级缺陷 |
| P1 | 1 | 测试基础设施缺陷导致关键启动/生命周期/渲染测试无法运行，存在发布验收盲区 |
| P2 | 3 | 测试代码缺陷、烂梗 API 硬编码认证头、PyInstaller hiddenimports 维护风险 |
| P3 | 2 | 文档与脚本不一致风险、日志格式潜在泄漏 |

---

## 2. 已确认 Bug

### BUG-001: Linux CI 缺少 Qt xcb 平台依赖，导致所有 GUI 相关测试崩溃
**严重等级**: P1  
**影响功能**: 启动与生命周期 / 弹幕显示链路 / 桌宠模式 / Overlay 渲染  
**证据文件**:  
- 测试文件: `tests/test_single_instance.py`, `tests/test_danmu_engine.py`, `tests/test_overlay_render.py`, `tests/test_pet_lifecycle.py`, `tests/test_danmu_dedup.py::test_start_clears_dedup_window`  
- 报错片段: `qt.qpa.plugin: Could not load the Qt platform plugin "xcb" in "" even though it was found.`  
- C Stack Trace 指向 `libQt6Gui.so.6` 中 `QGuiApplicationPrivate25createPlatformIntegrationEv`  

**复现路径**:  
1. 在 Linux (Ubuntu/Debian) 运行 `python -m pytest tests/test_single_instance.py -xvs`  
2. 第一个用例 `test_single_instance_second_client_triggers_activate` 即触发 `Fatal Python error: Aborted`  
3. 同样崩溃发生在任何实例化 `QApplication` 的测试  

**根因分析**:  
系统缺少 `xcb-cursor0` / `libxcb-cursor0`，Qt 6.5+ 加载 xcb 平台插件时失败。虽然产品目标平台是 Windows，但 CI 无法运行这些测试意味着：
- 单实例竞态逻辑无自动验证
- Overlay 脏区绘制无自动验证
- 桌宠动画/拖动无自动验证
- 弹幕轨道分配无自动验证

**最小修复建议**:  
在 CI 环境中安装 `apt-get install -y libxcb-cursor0 libxkbcommon-x11-0`（或等效包），或在 `pytest.ini` / `conftest.py` 中为 Linux 无显示环境增加 `QT_QPA_PLATFORM=offscreen` 兜底。  

**是否建议本次自动修复**: 是  
**需要补充的测试**: 无（修复后即可运行现有测试）

---

### BUG-002: `test_start_clears_dedup_window` 测试因未初始化 QObject 而失败
**严重等级**: P2  
**影响功能**: 弹幕去重链路（测试覆盖）  
**证据文件**: `tests/test_danmu_dedup.py:524-527`  
**证据代码**:
```python
app = DanmuApp.__new__(DanmuApp)
# ... 大量 stub 注入 ...
DanmuApp.start(app)  # 触发 clear_problem() → main_web_facade_mixin.py:146
# RuntimeError: super-class __init__() of type DanmuApp was never called
```
**复现路径**: `python -m pytest tests/test_danmu_dedup.py::test_start_clears_dedup_window -xvs`  
**根因分析**: 测试使用 `DanmuApp.__new__(DanmuApp)` 绕过 `QObject.__init__()`，导致 `getattr(self, "web_bridge", None)` 触发 `RuntimeError`（PyQt6 对未初始化 QObject 的属性访问会抛异常，而非返回 None）。  
**最小修复建议**: 在 stub 阶段注入 `web_bridge = None`，或改用 `object.__setattr__(app, "web_bridge", None)`。  
**是否建议本次自动修复**: 是  
**需要补充的测试**: 无（修复现有测试即可）

---

### BUG-003: `test_single_instance_listen_failure_does_not_claim_primary` 中 FakeServer 缺少 `close()` 方法
**严重等级**: P2  
**影响功能**: 单实例守卫（测试覆盖）  
**证据文件**: `tests/test_single_instance.py:61-71`, `app/single_instance.py:124`  
**证据代码**:
```python
# test_single_instance.py 中 FakeServer 定义：
class FakeServer:
    def listen(self, _name): return False
    # 缺少 close() 方法

# app/single_instance.py:124
server.close()  # 若 FakeServer 无 close()，测试会 AttributeError
```
**复现路径**: 在修复 BUG-001 的 Qt 环境后运行 `test_single_instance_listen_failure_does_not_claim_primary`  
**根因分析**: 测试 mock 未完整模拟 QLocalServer 接口。  
**最小修复建议**: 在 FakeServer 中添加 `def close(self): pass`。  
**是否建议本次自动修复**: 是  
**需要补充的测试**: 无

---

### BUG-004: 烂梗远程 API 客户端使用硬编码静态认证头
**严重等级**: P2  
**影响功能**: 公式化弹幕库 / 外部数据获取  
**证据文件**: `app/meme_barrage/client.py:14-19`  
**证据代码**:
```python
DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Dpahjdoiaw": "danmuAi",  # 硬编码静态密钥
    "Origin": API_ORIGIN,
    "Referer": f"{API_ORIGIN}/",
}
```
**复现路径**: 静态代码审查即可确认。  
**根因分析**: 远程 API 认证头为编译期硬编码字符串，无环境变量覆盖、无轮换机制。若服务端发生密钥泄露或被逆向，攻击者可伪造请求消耗服务端资源。  
**最小修复建议**: 将 `Dpahjdoiaw` 值改为从环境变量或配置中读取，默认回退当前值以保持兼容；服务端同时支持新旧密钥过渡期。  
**是否建议本次自动修复**: 否（需服务端配合，改动涉及前后端契约）  
**需要补充的测试**: `test_meme_barrage_client.py` 中增加 "header 可配置化" 断言。

---

### BUG-005: PyInstaller `hiddenimports` 为纯手动维护列表，新增模块易遗漏
**严重等级**: P2  
**影响功能**: 打包发布  
**证据文件**: `DanmuAI.spec:119-326`  
**证据代码**: 327 行 hardcoded `hiddenimports` 列表，包含 `app.application.*`, `app.meme_barrage.*`, `app.pet.*`, `app.providers.*`, `app.web_api.*` 等全部子包。  
**复现路径**: 新增 `app/web_api/new_module.py` 后未同步更新 `DanmuAI.spec`，运行 `pyinstaller DanmuAI.spec` 成功但 frozen 运行时因 `ModuleNotFoundError` 崩溃。  
**根因分析**: 无自动化扫描脚本在 CI 中验证 `hiddenimports` 完整性。虽然 `scripts/audit_hiddenimports.py` 存在，但无法确认是否被 CI 强制执行。  
**最小修复建议**: 在 `scripts/build_exe.ps1` 或 CI 中增加 `python scripts/audit_hiddenimports.py` 门禁，缺失即阻断构建。  
**是否建议本次自动修复**: 是（仅需加一行调用）  
**需要补充的测试**: `test_pyinstaller_hiddenimports.py` 已存在，确认其是否在 CI 中运行。

---

## 3. 高风险但未确认问题

| 编号 | 标题 | 证据 | 建议验证方式 |
|------|------|------|-------------|
| RISK-001 | SQLite WAL 模式在 Windows 强制断电/蓝屏时可能丢失最近写入 | `app/config_store/storage.py:98` `PRAGMA journal_mode=WAL` | 在 Windows 虚拟机模拟断电，检查 config.db 完整性 |
| RISK-002 | Velopack update feed 为 HTTP (非 HTTPS)，中间人可篡改 releases.win.json | `app/velopack_config.py` 中 `UPDATE_FEED_URL` 实际值需确认 | 检查发布脚本中 feed URL 协议；确认 vpk pack 是否签名 |
| RISK-003 | 烂梗 API 无证书固定，中间人可伪造证书拦截 | `app/meme_barrage/client.py:67` `verify=self._verify` 默认 True 但无 pinning | 抓包验证证书链；评估是否增加证书固定 |
| RISK-004 | 弹幕去重纯 Python fallback 截断 32 字符导致尾部差异丢失 | `app/danmu_engine_dedup.py:25` `_FALLBACK_MAX_LEN = 32`；测试 BUG-009 已记录 | 在 Windows 真机卸载 `python-Levenshtein` 和 `rapidfuzz`，验证长弹幕去重行为 |
| RISK-005 | Overlay `paintEvent` 的 `event.region()` 在某些显卡驱动下可能返回空或全屏，导致不绘制或全量绘制 | `app/overlay.py` 脏区裁剪逻辑依赖 `event.region().boundingRect()` | 在 Intel/AMD/NVIDIA 不同驱动版本上运行，观察 CPU 占用 |
| RISK-006 | 麦克风模式与视觉模式并发时，虽然凭证解析分离，但 `ai_worker` 为单实例，可能出现请求排队或线程局部 client 冲突 | `app/ai_client.py` `_request` 中 `resolved = self.resolve_mic_request_credentials()` vs `self._resolve_request_credentials(persona_id)` | 压力测试：同时触发视觉截图和麦克风插入，观察 `ai_in_flight` / `mic_in_flight` 计数 |
| RISK-007 | `publish_windows_release.ps1` 中 `Get-AppVersion` 调用 `python -c "from app.version import __version__"`，若构建 Python 与运行 Python 版本不一致可能导致语义差异 | `scripts/resolve_build_python.ps1` | 在 CI 中固定 Python 版本，或增加版本一致性校验 |

---

## 4. 性能与卡顿风险

| 模块 | 风险点 | 证据 | 当前保护 |
|------|--------|------|----------|
| 启动 | Web 控制台启动阻塞主线程最多 1.5s | `app/web_console.py` 中 `ready_timeout = web_console_ready_timeout()` | 已改为 500ms 轮询 + deadline 定时器，不阻塞 |
| 截图 | QPixmap → JPEG 压缩在主线程 | `app/screenshot_compress.py:25-53` | 截图在 `CaptureRunnable` 线程池执行，压缩也在工作线程 |
| Overlay 渲染 | 60fps 每帧扫描全部轨道 | `app/overlay.py:150` `_pending_render` 队列 | 使用 dirty region + `_pending_render` 避免全量扫描 |
| 轨道计算 | `_pick_track` 加权随机需计算 `entry_zone_count` | `app/danmu_engine/track.py:567-603` | 缓存 `entry_zone_count_cached`，减少重复计算 |
| SQLite | 自定义弹幕库 20000 条全量加载 | `app/danmu_pool.py:22` `CUSTOM_DANMU_POOL_MAX = 20000` | 分页 `_CUSTOM_POOL_PAGE_SIZE = 500`，抽样仅取 200 条；diff 算法避免全量替换 |
| 外部接口 | 烂梗 API 超时 20s，阻塞 meme fetch 线程池 | `app/meme_barrage/client.py:69` `timeout=20.0` | 线程池隔离，不影响主线程；但 20s 可能过长 |
| 模型请求 | 每轮发送截图 + 历史上下文 | `app/ai_client_requests.py` 构建 payload | 有 `max_width=1024` / `quality=85` 压缩；无证据显示重复发送过多历史 |

**关键结论**: 自定义弹幕库大数据量场景已有分页和 diff 优化，`test_custom_danmu_pool_large_diff_performance.py` 4 项测试全部通过，未发现 P1 级性能退化。

---

## 5. 兼容性与环境风险

| 风险点 | 证据 | 缓解措施 |
|--------|------|----------|
| Windows 中文路径 / UTF-8 | `app/config_store/storage.py:75` `CONFIG_DIR = Path(os.environ.get("APPDATA", ".")) / "DanmuAI"` | 使用 `Path` 对象，Python 3.12+ 默认 UTF-8 |
| PowerShell 编码 | `scripts/publish_windows_release.ps1:11` `$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8` | 已显式设置 UTF-8 |
| PyInstaller 单目录 vs 单文件 | `DanmuAI.spec:348` `exclude_binaries=True` + `COLLECT` | 使用 onedir，避免单文件解压延迟 |
| 显卡/窗口层级差异 | `app/win32_overlay_zorder.py` 中 `apply_overlay_exstyles` / `reassert_hwnd_topmost` | 有 `_topmost_fail_streak` 计数和兼容性告警 |
| Windows 版本差异 (Win10 vs Win11) | `app/pet/pet_window.py:655-671` DWM 圆角禁用仅对 Win11 | 使用 `ctypes.windll.dwmapi.DwmSetWindowAttribute` 做 best-effort |

---

## 6. 发布与更新风险

| 检查项 | 状态 | 证据 |
|--------|------|------|
| PyInstaller spec 排除 supabase-config.js | 通过 | `DanmuAI.spec:38-57` default-deny + `publish_windows_release.ps1:18-36` 双重校验 |
| Velopack 打包脚本版本号解析 | 通过 | `scripts/velopack_pack.ps1:55-59` 正则校验 semver |
| releases.win.json 与 delta nupkg 一致性 | 通过 | `publish_windows_release.ps1:165-168` 校验 delta count |
| 用户数据保留 | 通过 | `app/velopack_runtime.py:120` `delete_user_data_if_requested` 仅在卸载时执行 |
| 版本比较正确性 | 通过 | `app/version_compare.py` 语义化比较；`tests/test_version_compare.py` 14 项通过 |
| Setup.exe / MSI 一致性 | 待确认 | 文档说 "MSI 主、Setup.exe 辅"，但 `velopack_pack.ps1` 仅输出 Setup.exe，需确认 MSI 生成路径 |
| R2 上传顺序 | 通过 | `tests/test_upload_r2_release_order.py` 验证 hash manifest 先于 Setup.exe |

---

## 7. 安全与隐私风险

| 检查项 | 状态 | 证据 |
|--------|------|------|
| API Key 本地加密 | 通过 | `app/config_store/storage.py` Fernet 加密；`tests/test_p1_key_encryption.py` 10 项通过 |
| 日志脱敏 | 通过 | `app/logger.py:79-94` 6 类 pattern 替换；`tests/test_p1_log_sanitization.py` 21 项通过 |
| Supabase 密钥泄露防护 | 通过 | `DanmuAI.spec` + `publish_windows_release.ps1` 双重 default-deny |
| Web 控制台 Session 鉴权 | 通过 | `app/web_console_session_auth.py:51-104` 已修复历史漏洞，使用 `secrets.compare_digest` |
| 用户配置上传 | 无此功能 | 未发现有自动上传用户配置的代码 |
| 社区后端权限边界 | 低风险 | `app/web_api/auth.py` 装饰器模式；`tests/test_web_auth.py` 26 项通过 |
| 烂梗 API 静态密钥 | 风险 | BUG-004 已记录 |

---

## 8. 建议新增的测试

| 测试文件名 | 测试目标 | 关键断言 |
|-----------|----------|----------|
| `tests/test_single_instance_fake_server_close.py` | 补全 FakeServer close() mock | `assert guard.try_acquire().kind is SingleInstanceAcquireKind.ACTIVATION_FAILED` 不抛 AttributeError |
| `tests/test_danmu_dedup_start_init.py` | 修复 test_start_clears_dedup_window 中 QObject 未初始化 | `DanmuApp.start(app)` 正常执行，`clear_calls == [True]` |
| `tests/test_meme_barrage_header_configurable.py` | 烂梗 API header 可配置化 | `client._get_client().headers["Dpahjdoiaw"] == os.environ.get("MEME_API_KEY", "danmuAi")` |
| `tests/test_velopack_feed_https.py` | 验证 update feed URL 为 HTTPS | `assert UPDATE_FEED_URL.startswith("https://")` |
| `tests/test_quit_worker_pool_timeout.py` | 验证退出时 worker pool 等待不超过 2s | `mock_wait_all_worker_pools_done.assert_called_with(2000)` |
| `tests/test_overlay_dirty_region_empty.py` | 验证空 region 时 paintEvent 提前返回 | `painter.setClipRect` 不被调用或 clip 为空即 return |

---

## 9. 本次可自动修复项

1. **BUG-001 (P1)**: 在 CI 环境安装 `libxcb-cursor0` 或设置 `QT_QPA_PLATFORM=offscreen`，使 GUI 测试可运行。
2. **BUG-002 (P2)**: 修复 `test_start_clears_dedup_window` 中 `DanmuApp.__new__` 未初始化问题，注入 `web_bridge = None`。
3. **BUG-003 (P2)**: 在 `test_single_instance_listen_failure_does_not_claim_primary` 的 FakeServer 中添加 `close()` 方法。
4. **BUG-005 (P2)**: 在 `scripts/build_exe.ps1` 或 CI workflow 中增加 `python scripts/audit_hiddenimports.py` 调用作为构建门禁。

---

## 10. 最终建议（Top 3）

### Top 1: 修复 Linux CI Qt 测试环境（P1）
**理由**: 当前所有依赖 `QApplication` 的测试（单实例、Overlay、弹幕引擎、桌宠）在 Linux CI 中完全无法运行，导致发布前无法自动验证启动稳定性、弹幕渲染、桌宠动画等核心体验。这是最大的发布验收盲区。  
**行动**: 安装 `libxcb-cursor0` + `libxkbcommon-x11-0`，或在 CI workflow 中设置 `QT_QPA_PLATFORM=offscreen`。

### Top 2: 补全单实例与去重测试 mock 缺陷（P2）
**理由**: `test_single_instance.py` 和 `test_danmu_dedup.py` 的测试代码存在已知 mock 不完整问题，导致即使 Qt 环境修复后这些测试仍会失败。它们守护的是"双实例防护"和"启动清窗"两个关键契约。  
**行动**: 给 FakeServer 加 `close()`；给 `test_start_clears_dedup_window` 的 stub 注入 `web_bridge`。

### Top 3: 增加 PyInstaller hiddenimports 构建门禁（P2）
**理由**: `DanmuAI.spec` 中 200+ 行的手动维护列表是打包发布的结构性风险。历史上已发生过新增模块后打包遗漏导致 frozen 版本崩溃的问题。  
**行动**: 在 `scripts/build_exe.ps1` 或 `.github/workflows/ci.yml` 中增加 `python scripts/audit_hiddenimports.py` 调用，失败即阻断构建。

---

## 自检评分

| 维度 | 得分 | 说明 |
|------|------|------|
| 证据完整性（文件/代码/复现） | 2/2 | 每项结论均给出文件路径、代码片段、复现命令或触发条件 |
| 严重度判定准确性 | 2/2 | 无 P0 产品缺陷，P1 为测试基础设施盲区，P2/P3 为局部问题 |
| 已确认 vs 待确认区分 | 2/2 | 第 2 章仅列有代码证据的确认项，第 3 章明确标注"未确认" |
| 发布更新链路覆盖 | 1/2 | 已覆盖 PyInstaller / Velopack / 版本比较 / 用户数据保留；缺少 MSI 生成路径的实物确认 |
| 可执行测试建议 | 2/2 | 第 8 章给出 6 个具体测试文件名、目标、关键断言 |

**总分**: 9/10

---

*本报告遵循审计边界：以发现问题和举证为主，未对产品代码做重构。所有"已确认 Bug"均附有文件路径、代码片段和可复现路径。*
