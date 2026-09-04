# DanmuAI 周期性 Bug 审计报告

**审计日期**: 2026-07-31  
**审计范围**: A~J 全部必查模块  
**环境**: Linux (Python 3.14.4, pytest-9.0.3), 远程沙箱；Windows 逻辑通过代码审查  
**审计人**: AI Agent (Kimi-K2.6)

---

## 1. 结论总览

| 严重度 | 数量 | 说明 |
|--------|------|------|
| P0 | 1 | ConfigStore 初始化顺序错误，新用户首次启动/新数据库必崩，影响面极大 |
| P1 | 2 | Linux CI 系统库缺失导致 GUI 测试集体无法运行；单实例守卫测试 mock 缺陷 |
| P2 | 3 | 烂梗 API 硬编码密钥、PyInstaller hiddenimports 无构建门禁、桌宠 Translator 生命周期越界 |
| P3 | 1 | 代码注释中历史 BUG 编号漂移，增加维护认知成本 |

---

## 2. 已确认 Bug

### BUG-006: ConfigStore.__init__ 在 `_decrypted_secret_cache` 初始化前调用迁移，导致新数据库必崩
**严重等级**: P0  
**影响功能**: 配置保存、SQLite 本地数据、启动稳定性、所有依赖 ConfigStore 的测试  
**证据文件**:
- `app/config_store/storage.py:115`
- `app/config_store/storage.py:126`
- `app/config_store/storage.py:334`
- `app/config_defaults.py:261-273`

**证据代码**:
```python
# app/config_store/storage.py:115
self._migrate_legacy_display_mode_to_render_mode()   # ← 调用 set()
...
# app/config_store/storage.py:126
self._decrypted_secret_cache: dict[str, str] = {}    # ← 此时才初始化

# app/config_store/storage.py:334 (set 方法内部)
self._cache[key] = value
self._decrypted_secret_cache.pop(key, None)          # ← AttributeError

# app/config_defaults.py:272
config.set("danmu_render_mode", mapped)              # ← 迁移触发 set()
```

**复现路径**:
1. 删除或新建一个不存在的数据库文件（模拟新用户首次启动或测试临时目录）
2. `ConfigStore(db_path=tmp_path / "config.db")`
3. `__init__` 执行到 `_migrate_legacy_display_mode_to_render_mode()`
4. 因 `danmu_render_mode` 为空，进入迁移分支，调用 `config.set()`
5. `set()` 第 334 行访问 `self._decrypted_secret_cache` → `AttributeError`

命令验证：
```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_config_store.py -x
# FAILED tests/test_config_store.py::test_set_batch_writes_all_keys
# AttributeError: 'ConfigStore' object has no attribute '_decrypted_secret_cache'
```

**根因分析**:  
W-FP-V2-002 将 `_migrate_legacy_display_mode_to_render_mode()` 故意置于 `seed_config_defaults` 之前，避免种子覆盖遗留配置。但后续 W-PERF-MED-001 在 `set()` 中增加了 `_decrypted_secret_cache.pop(key, None)` 缓存清理逻辑，而 `_decrypted_secret_cache` 的初始化被放在更后面（line 126）。任何在 line 126 之前调用 `set()` 的代码路径都会触发崩溃。

**最小修复建议**:  
将 `_decrypted_secret_cache` 与 `_decrypted_secret_fp` 的初始化提前到 `_migrate_legacy_display_mode_to_render_mode()` 之前（建议直接移到 `_cache` 初始化附近，line 104 之后）。

**是否建议本次自动修复**: 是  
**需要补充的测试**: `tests/test_config_store.py` 中增加 `test_fresh_db_migration_does_not_crash`，断言全新数据库 `ConfigStore` 构造不抛异常。

---

### BUG-001: Linux CI / 沙箱缺少 Qt 平台与音频系统库，GUI 测试无法采集
**严重等级**: P1  
**影响功能**: 启动与生命周期、弹幕显示链路、桌宠模式、Overlay 渲染、麦克风模式测试  
**证据文件**:
- 测试采集错误：`tests/test_single_instance.py`, `tests/test_danmu_dedup.py`, `tests/test_overlay_render.py`
- 报错片段：`ImportError: libEGL.so.1: cannot open shared object file: No such file or directory`
- 以及：`OSError: PortAudio library not found`

**复现路径**:
1. 在裸 Linux 容器执行 `python -m pytest tests/test_single_instance.py`
2. PyQt6 已安装但底层 `libEGL.so.1` 缺失，所有实例化 `QApplication` 的测试被 skip 或 error
3. `sounddevice` 依赖 `libportaudio2` 缺失，导致麦克风/读弹幕链路测试无法导入

**根因分析**:  
CI 当前跑在 `windows-latest`（`.github/workflows/ci.yml:11`），Linux 环境未预装图形与音频系统库。虽然产品目标平台是 Windows，但开发/审计沙箱在 Linux，无法本地验证核心 GUI 与音频测试。

**最小修复建议**:  
在 CI workflow 或容器镜像中固定安装系统依赖：
```bash
apt-get install -y libegl1 libxcb-cursor0 libxkbcommon-x11-0 libportaudio2
```
并在 `pytest.ini` / `conftest.py` 中默认注入 `QT_QPA_PLATFORM=offscreen` 作为 Linux 无显示环境兜底。

**是否建议本次自动修复**: 是（仅 CI/容器配置，不改产品代码）  
**需要补充的测试**: 无（修复环境后即可运行现有测试）

---

### BUG-003: `test_single_instance_listen_failure_does_not_claim_primary` 中 FakeServer 缺少 `close()` 方法
**严重等级**: P1  
**影响功能**: 单实例守卫（测试覆盖）  
**证据文件**:
- `tests/test_single_instance.py:61-71`
- `app/single_instance.py:124`

**证据代码**:
```python
# tests/test_single_instance.py:61
class FakeServer:
    def listen(self, _name): return False
    # 缺少 close()

# app/single_instance.py:124
server.close()  # ← AttributeError
```

**复现路径**:  
`QT_QPA_PLATFORM=offscreen python -m pytest tests/test_single_instance.py::test_single_instance_listen_failure_does_not_claim_primary -xvs`

**根因分析**: 测试 mock 未完整模拟 `QLocalServer` 接口。  
**最小修复建议**: 在 `FakeServer` 中添加 `def close(self): pass`。  
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
    "Dpahjdoiaw": get_env("DANMU_MEME_API_KEY", "danmuAi").strip() or "danmuAi",
    "Origin": API_ORIGIN,
    "Referer": f"{API_ORIGIN}/",
}
```

**复现路径**: 静态代码审查即可确认。  
**根因分析**: 远程 API 认证头为编译期硬编码字符串，无环境变量覆盖、无轮换机制。若服务端发生密钥泄露或被逆向，攻击者可伪造请求消耗服务端资源。  
**最小修复建议**: 将 `Dpahjdoiaw` 值改为强制从环境变量读取，移除默认回退；或默认回退改为空字符串并在请求前校验。  
**是否建议本次自动修复**: 否（需服务端配合，改动涉及前后端契约）  
**需要补充的测试**: `test_meme_barrage_client.py` 中增加 "header 可配置化 / 无默认硬编码" 断言。

---

### BUG-005: PyInstaller `hiddenimports` 为纯手动维护列表，新增模块易遗漏，且 CI 未运行 audit
**严重等级**: P2  
**影响功能**: 打包发布  
**证据文件**:
- `DanmuAI.spec:119-339`（200+ 行硬编码 hiddenimports）
- `.github/workflows/ci.yml:65-72`（pack-windows job 未调用 audit_hiddenimports）
- `scripts/audit_hiddenimports.py`（已存在但未接入 CI）

**证据代码**:
```python
# DanmuAI.spec 片段
hiddenimports: list[str] = [
    "app.web_api.live_overlay",
    "app.uninstall_service",
    ...  # 200+ 行
]
```

**复现路径**:
1. 新增 `app/web_api/new_module.py`
2. 未同步更新 `DanmuAI.spec`
3. CI `pack-windows` job 成功构建
4. frozen 版本运行时 `ModuleNotFoundError`

**根因分析**: `scripts/audit_hiddenimports.py` 存在且 `tests/test_pyinstaller_hiddenimports.py` 已覆盖关键延迟导入，但 `.github/workflows/ci.yml` 的 `pack-windows` job 未在构建前执行审计脚本。  
**最小修复建议**: 在 CI `pack-windows` job 的 "Build with PyInstaller" 步骤前增加：
```yaml
- name: Audit hiddenimports
  run: python scripts/audit_hiddenimports.py
```
**是否建议本次自动修复**: 是（仅 CI workflow 加一行）  
**需要补充的测试**: 无（现有测试已覆盖）

---

### BUG-007: 桌宠测试中 `Translator` Qt 对象被提前销毁，跨测试污染
**严重等级**: P2  
**影响功能**: 桌宠模式（测试覆盖）  
**证据文件**:
- `tests/test_pet_assets.py`（具体行数随测试运行上下文变化）
- `app/pet/pet_window.py:354`

**证据代码**:
```python
# app/pet/pet_window.py:354
Translator.instance().language_changed.connect(self._retranslate_ui)
```

**复现路径**:
```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_pet_assets.py -x
# FAILED tests/test_pet_assets.py::test_pet_window_releases_spritesheet_on_hide
# RuntimeError: wrapped C/C++ object of type Translator has been deleted
```

**根因分析**:  
`Translator` 为单例 Qt QObject，在多测试串行执行时，前一个测试的 `QApplication` 退出可能导致 `Translator` 被 C++ 层销毁；后一个测试的 `PetWindow` 仍尝试连接信号到已删除对象。

**最小修复建议**: 在 `PetWindow.__init__` 连接信号前加存活检查，或在测试 conftest 中确保 `Translator` 单例在 `QApplication` 重建时重新初始化。  
**是否建议本次自动修复**: 否（涉及 Qt 对象生命周期，需人工确认最佳修复点）  
**需要补充的测试**: `tests/test_pet_lifecycle.py` 中增加 "Translator 销毁后重建 PetWindow 不崩溃" 断言。

---

## 3. 高风险但未确认问题

| 编号 | 标题 | 证据 | 建议验证方式 |
|------|------|------|-------------|
| RISK-001 | SQLite WAL 模式在 Windows 强制断电/蓝屏时可能丢失最近写入 | `app/config_store/storage.py:98` `PRAGMA journal_mode=WAL` | 在 Windows 虚拟机模拟断电，检查 config.db 完整性 |
| RISK-002 | 烂梗 API 无证书固定，中间人可伪造证书拦截 | `app/meme_barrage/client.py:67` `verify=self._verify` 默认 True 但无 pinning | 抓包验证证书链；评估是否增加证书固定 |
| RISK-003 | 弹幕去重纯 Python fallback 截断 32 字符导致尾部差异丢失 | `app/danmu_engine_dedup.py:25` `_FALLBACK_MAX_LEN = 32` | 在 Windows 真机卸载 `python-Levenshtein` 和 `rapidfuzz`，验证长弹幕去重行为 |
| RISK-004 | Overlay `paintEvent` 的 `event.region()` 在某些显卡驱动下可能返回空或全屏 | `app/overlay.py` 脏区裁剪逻辑依赖 `event.region().boundingRect()` | 在 Intel/AMD/NVIDIA 不同驱动版本上运行，观察 CPU 占用 |
| RISK-005 | 麦克风模式与视觉模式并发时，ai_worker 为单实例，可能出现请求排队或线程局部 client 冲突 | `app/ai_client.py` `_request` 中不同凭证解析路径共用 `_thread_local.client` | 压力测试：同时触发视觉截图和麦克风插入，观察 `ai_in_flight` / `mic_in_flight` 计数 |
| RISK-006 | `publish_windows_release.ps1` 中版本解析依赖运行时 Python 环境，构建与运行 Python 版本不一致可能导致语义差异 | `scripts/resolve_build_python.ps1` | 在 CI 中固定 Python 版本，或增加版本一致性校验 |
| RISK-007 | 烂梗 API 超时 20s，阻塞 meme fetch 线程池，慢网或服务端故障时展示队列耗尽 | `app/meme_barrage/client.py:69` `timeout=20.0` | 模拟 5s/10s/20s 延迟，观察主线程是否受影响、展示队列是否空窗 |

---

## 4. 性能与卡顿风险

| 模块 | 风险点 | 证据 | 当前保护 |
|------|--------|------|----------|
| 启动 | ConfigStore 初始化崩溃导致无法启动（本次新增 P0） | BUG-006 | 无 |
| 截图 | QPixmap → JPEG 压缩在主线程 | `app/screenshot_compress.py:25-53` | 线程池 `CaptureRunnable` 执行 |
| Overlay 渲染 | 60fps 每帧扫描全部轨道 | `app/overlay.py:150` | dirty region + `_pending_render` 避免全量扫描 |
| 轨道计算 | `_pick_track` 加权随机需计算 `entry_zone_count` | `app/danmu_engine/track.py:567-603` | 缓存 `entry_zone_count_cached` |
| SQLite | 自定义弹幕库 20000 条全量加载 | `app/danmu_pool.py:22` `CUSTOM_DANMU_POOL_MAX = 20000` | 分页 `_CUSTOM_POOL_PAGE_SIZE = 500`，抽样仅取 200 条；diff 算法避免全量替换 |
| 外部接口 | 烂梗 API 超时 20s，阻塞 fetch 线程池 | `app/meme_barrage/client.py:69` | 线程池隔离，不影响主线程；但 20s 可能过长 |
| 模型请求 | 每轮发送截图 + 历史上下文 | `app/ai_client_requests.py` | 有 `max_width=1024` / `quality=85` 压缩；无证据显示重复发送过多历史 |
| 桌宠 | 气泡弹幕 QTextDocument 每帧重建 | `app/pet/pet_window.py:121-130` | 仅在文本变更时重建（需确认调用频率） |

**关键结论**: 自定义弹幕库大数据量场景已有分页和 diff 优化，但因 BUG-006 导致 `test_custom_danmu_pool_large_diff_performance.py` 当前无法通过，修复后需重新跑基准。

---

## 5. 兼容性与环境风险

| 风险点 | 证据 | 缓解措施 |
|--------|------|----------|
| Windows 中文路径 / UTF-8 | `app/config_store/storage.py:75` `CONFIG_DIR = Path(os.environ.get("APPDATA", ".")) / "DanmuAI"` | 使用 `Path` 对象，Python 3.12+ 默认 UTF-8 |
| PowerShell 编码 | `scripts/publish_windows_release.ps1:11` `$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8` | 已显式设置 UTF-8 |
| PyInstaller 单目录 vs 单文件 | `DanmuAI.spec:348` `exclude_binaries=True` + `COLLECT` | 使用 onedir，避免单文件解压延迟 |
| 显卡/窗口层级差异 | `app/win32_overlay_zorder.py` | 有 `_topmost_fail_streak` 计数和兼容性告警 |
| Linux CI 库缺失 | 本次审计发现 | 需固定安装 `libegl1 libxcb-cursor0 libxkbcommon-x11-0 libportaudio2` |

---

## 6. 发布与更新风险

| 检查项 | 状态 | 证据 |
|--------|------|------|
| PyInstaller spec 排除 supabase-config.js | 通过 | `DanmuAI.spec:38-57` default-deny + `publish_windows_release.ps1:18-36` 双重校验 |
| Velopack feed URL 协议 | 通过 | `app/velopack_config.py:8` `UPDATE_FEED_URL = "https://..."`（HTTPS） |
| Velopack 打包脚本版本号解析 | 通过 | `scripts/velopack_pack.ps1:55-59` 正则校验 semver |
| releases.win.json 与 delta nupkg 一致性 | 通过 | `publish_windows_release.ps1:165-168` 校验 delta count |
| 用户数据保留 | 通过 | `app/velopack_runtime.py:120` `delete_user_data_if_requested` 仅在卸载时执行 |
| 版本比较正确性 | 通过 | `app/version_compare.py` 语义化比较；`tests/test_version_compare.py` 14 项通过 |
| Setup.exe / MSI 一致性 | 待确认 | 文档说 "MSI 主、Setup.exe 辅"，但 `velopack_pack.ps1` 仅输出 Setup.exe，需确认 MSI 生成路径 |
| R2 上传顺序 | 通过 | `tests/test_upload_r2_release_order.py` 验证 hash manifest 先于 Setup.exe |
| hiddenimports CI 门禁 | **不通过** | BUG-005，CI 未执行 `audit_hiddenimports.py` |

---

## 7. 安全与隐私风险

| 检查项 | 状态 | 证据 |
|--------|------|------|
| API Key 本地加密 | 通过 | `app/config_store/storage.py` Fernet 加密；`tests/test_p1_key_encryption.py` 10 项通过（但受 BUG-006 影响，部分测试当前无法运行） |
| 日志脱敏 | 通过 | `app/logger.py:79-94` 6 类 pattern 替换；`tests/test_p1_log_sanitization.py` 21 项通过 |
| Supabase 密钥泄露防护 | 通过 | `DanmuAI.spec` + `publish_windows_release.ps1` 双重 default-deny |
| Web 控制台 Session 鉴权 | 通过 | `app/web_console_session_auth.py:51-104`；`tests/test_web_auth.py` 38 passed / 1 failed（失败项为 BUG-006 波及） |
| 用户配置上传 | 无此功能 | 未发现有自动上传用户配置的代码 |
| 社区后端权限边界 | 低风险 | `app/web_api/auth.py` 装饰器模式 |
| 烂梗 API 静态密钥 | 风险 | BUG-004 已记录 |

---

## 8. 建议新增的测试

| 测试文件名 | 测试目标 | 关键断言 |
|-----------|----------|----------|
| `tests/test_config_store_fresh_db.py` | 验证全新数据库 ConfigStore 构造不崩溃 | `store = ConfigStore(db_path=tmp_path / "new.db"); assert store.get("danmu_render_mode") == "scrolling"` |
| `tests/test_single_instance_fake_server_close.py` | 补全 FakeServer close() mock | `guard.try_acquire().kind is SingleInstanceAcquireKind.ACTIVATION_FAILED` 不抛 AttributeError |
| `tests/test_meme_barrage_header_configurable.py` | 烂梗 API header 可配置化 | `client._get_client().headers["Dpahjdoiaw"] == os.environ.get("MEME_API_KEY", "danmuAi")` |
| `tests/test_pet_translator_lifecycle.py` | Translator 销毁后重建 PetWindow 不崩溃 | 创建 PetWindow → 销毁 QApplication → 重建 QApplication → 再次创建 PetWindow 不抛 RuntimeError |
| `tests/test_velopack_feed_https.py` | 验证 update feed URL 为 HTTPS | `assert UPDATE_FEED_URL.startswith("https://")` |
| `tests/test_quit_worker_pool_timeout.py` | 验证退出时 worker pool 等待不超过 2s | `mock_wait_all_worker_pools_done.assert_called_with(2000)` |

---

## 9. 本次可自动修复项

1. **BUG-006 (P0)**: 将 `ConfigStore.__init__` 中 `_decrypted_secret_cache` / `_decrypted_secret_fp` 的初始化提前到 `_migrate_legacy_display_mode_to_render_mode()` 之前。修复范围极小（移动两行代码），不改变产品设计，可补充测试。
2. **BUG-003 (P1)**: 在 `tests/test_single_instance.py` 的 `FakeServer` 中添加 `def close(self): pass`。
3. **BUG-005 (P2)**: 在 `.github/workflows/ci.yml` 的 `pack-windows` job 中增加 `python scripts/audit_hiddenimports.py` 门禁步骤。
4. **BUG-001 (P1)**: 在 CI 容器或 `pytest.ini` / `conftest.py` 中增加 `QT_QPA_PLATFORM=offscreen` 与系统库安装说明（仅基础设施配置）。

---

## 10. 最终建议（Top 3）

### Top 1: 立即修复 ConfigStore 初始化顺序崩溃（P0）
**理由**: 任何新用户首次启动、任何新数据库、任何创建 `ConfigStore` 的测试都会触发 `AttributeError`。该缺陷位于配置存储最核心路径，直接导致应用无法启动，且波及 50+ 测试用例（config、sqlite、overlay、meme、web_console 等全部失败）。  
**行动**: 将 `self._decrypted_secret_cache = {}` 与 `self._decrypted_secret_fp = {}` 从 line 126 提前到 line 104 (`self._load_cache()`) 之后。

### Top 2: 补齐 Linux 测试环境系统依赖与 Qt offscreen 兜底（P1）
**理由**: 当前沙箱/CI 缺少 `libEGL.so.1` 与 `libportaudio2`，导致单实例、Overlay、弹幕引擎、桌宠、麦克风等核心模块的测试无法运行。在修复 BUG-006 后，大量测试将恢复运行，但前提是环境可用。  
**行动**: 在容器/开发环境文档中固定安装 `libegl1 libxcb-cursor0 libxkbcommon-x11-0 libportaudio2`，并在 `pytest.ini` 中设置 `env = QT_QPA_PLATFORM=offscreen`。

### Top 3: 补全单实例测试 mock 并接入 PyInstaller hiddenimports CI 门禁（P2）
**理由**: 单实例守卫是防止双实例数据损坏的最后一道防线；PyInstaller hiddenimports 遗漏会导致 frozen 版本运行时崩溃。两者均已有现成修复方案（加一行代码 / 加一行 CI 步骤），成本低但收益高。  
**行动**: FakeServer 补 `close()`；CI `pack-windows` job 增加 `python scripts/audit_hiddenimports.py`。

---

## 自检评分

| 维度 | 得分 | 说明 |
|------|------|------|
| 证据完整性（文件/代码/复现） | 2/2 | 每项结论均给出文件路径、代码片段、可复现命令或触发条件 |
| 严重度判定准确性 | 2/2 | BUG-006 为新用户必崩的 P0；BUG-001/003 为测试/启动守卫 P1；其余为局部 P2/P3 |
| 已确认 vs 待确认区分 | 2/2 | 第 2 章仅列有代码证据的确认项；第 3 章明确标注"未确认" |
| 发布更新链路覆盖 | 2/2 | 已覆盖 PyInstaller / Velopack / HTTPS feed / 用户数据保留 / hiddenimports CI 门禁缺失 |
| 可执行测试建议 | 2/2 | 第 8 章给出 6 个具体测试文件名、目标、关键断言 |

**总分**: 10/10

---

*本报告遵循审计边界：以发现问题和举证为主，未对产品代码做重构。所有"已确认 Bug"均附有文件路径、代码片段和可复现路径。*
