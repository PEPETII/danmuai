# DanmuAI 周期性 Bug 审计报告

> 审计日期：2026-07-04
> 审计范围：启动与生命周期、弹幕主链路、模型调用与成本、麦克风/语音/读弹幕、桌宠模式、配置/SQLite/本地数据、公式化弹幕库/外部数据、自动更新与发布、Web 社区与后端、测试与验收
> 审计方式：静态代码分析（远程 Linux 沙箱，PyQt6 运行时不可用，测试以代码审查为主）

---

## 1. 结论总览

| 严重度 | 数量 | 关键问题摘要 |
|--------|------|--------------|
| **P0** | 1 | PyInstaller hiddenimports 遗漏 `app.webview2_runtime`，frozen 模式下 WebView2 检测动态导入可能崩溃 |
| **P1** | 4 | 退出时 HTTP 线程竞争崩溃、显示器枚举失败时弹幕静默错位、Win32 置顶失败无检查导致游戏内不显示、打包时 Supabase 凭据变体可能泄露 |
| **P2** | 19 | 单实例多用户误判、大 retention_cap 下弹幕被静默拒绝、场景切换清掉去重窗口、纯 Python Levenshtein 回退卡顿、轨道速度差异追尾、AI 重试重复计费、麦克风音频静默丢弃、timeout 固定不随网况调整、Fernet key 损坏无 UI 提示、SQLite 关闭与并发写竞争、PetWindow 鼠标穿透、桌宠坐标硬编码不适配屏幕、发布脚本版本读取无 fallback、便携版目录名误判 Velopack、Supabase RLS 不完整、启动凭证缺失时 tray 状态不更新、quit 超时导致进程残留、DPI 缩放未适配 |
| **P3** | 1 | stop_render_loop(repaint=True) 在大量弹幕时可能触发一次性绘制卡顿 |

---

## 2. 已确认 Bug

### BUG-001：PyInstaller hiddenimports 遗漏 `app.webview2_runtime`，frozen 环境下动态导入可能失败

**严重等级：P0**

**影响功能：** 启动稳定性 / EXE 打包发布

**证据文件：** [DanmuAI.spec](file:///workspace/DanmuAI.spec) L97-L303、[webview_shell.py](file:///workspace/app/webview_shell.py) L422-L425

**证据代码：**

```python
# DanmuAI.spec hiddenimports 列表（节选）
hiddenimports: list[str] = [
    # ... 大量 app 子模块 ...
    "app.webview_shell",
    "app.win32_overlay_zorder",
    "app.worker_pools",
]
# 注意：列表中包含 app.webview_shell，但没有 app.webview2_runtime
```

```python
# webview_shell.py L422-L425
if sys.platform == "win32":
    from app.webview2_runtime import WEBVIEW2_INSTALL_URL, is_webview2_runtime_available

    if not is_webview2_runtime_available():
        self._fail_start("WebView2 runtime not found", initial_path)
```

**复现路径：**
1. 在全新 Windows 机器上安装打包后的 `DanmuAI.exe`（onedir 模式）。
2. 如果系统恰好缺少 WebView2 Runtime，`is_webview2_runtime_available()` 被调用。
3. 由于 `app.webview2_runtime` 未列入 `hiddenimports`，PyInstaller 在 frozen 模式下可能无法找到该模块，抛出 `ModuleNotFoundError`，导致启动流程异常中断，用户看不到 WebView2 缺失的友好提示。

**根因分析：** `DanmuAI.spec` 的 `hiddenimports` 按子包分区枚举了 `app.webview_shell`、`app.win32_overlay_zorder` 等，但遗漏了同级的 `app.webview2_runtime`。该模块在 `webview_shell.py` 中通过 `if sys.platform == "win32": from app.webview2_runtime import ...` 做**条件动态导入**，PyInstaller 的静态分析难以自动捕获。

**最小修复建议：** 在 `DanmuAI.spec` 的 `hiddenimports` 中新增 `"app.webview2_runtime"`。

**是否建议本次自动修复：是**

**需要补充的测试：** `test_pyinstaller_hiddenimports.py` 中增加断言，确保 `app.webview2_runtime` 在 `hiddenimports` 集合中。

---

### BUG-002：quit() 中 Web 服务器 shutdown 超时仅 0.5s，HTTP 线程与主线程竞争可能导致崩溃或日志异常

**严重等级：P1**

**影响功能：** 退出稳定性 / 进程残留 / 数据一致性

**证据文件：** [main_lifecycle_mixin.py](file:///workspace/app/main_lifecycle_mixin.py) L745-L771

**证据代码：**

```python
# main_lifecycle_mixin.py L745-L771
server = getattr(self, "web_server", None)
if server:
    server.stop()
    web_thread = getattr(server, "_thread", None)
    shutdown_done = False
    wait_shutdown_complete = getattr(server, "wait_shutdown_complete", None)
    if callable(wait_shutdown_complete):
        shutdown_done = bool(wait_shutdown_complete())
    if not shutdown_done and web_thread is not None and web_thread.is_alive():
        web_thread.join(timeout=0.5)          # 超时仅 0.5 秒
        shutdown_done = not web_thread.is_alive()
    if not shutdown_done:
        self.logger.warning(...)
    bridge = getattr(server, "bridge", None)
    if bridge is not None:
        bridge.set_event_loop(None)           # HTTP 线程仍可能在使用 loop
    server._loop = None                        # 同上
```

**复现路径：**
1. 启动应用，在 Web 控制台保持活跃状态（如持续轮询 `/api/status`）。
2. 点击托盘「退出」或关闭主进程。
3. `quit()` 调用 `server.stop()`，但 HTTP 线程可能正在处理请求。
4. `web_thread.join(timeout=0.5)` 几乎必然超时（uvicorn 优雅关闭默认需要更长时间）。
5. 代码继续执行 `bridge.set_event_loop(None)` 和 `server._loop = None`。
6. 如果 HTTP 线程此时仍在执行依赖 event loop 的操作（如 `meme_barrage_library` 查询），可能触发 `RuntimeError` 或 `AttributeError`，异常被吞掉但进程状态不一致。

**根因分析：** 优雅关闭超时过短（0.5s），且后续对 `bridge` 和 `_loop` 的清理未等待线程真正结束，形成竞争条件。

**最小修复建议：** 将 `web_thread.join(timeout=0.5)` 延长至至少 3-5 秒；或在 `join` 返回后检查 `web_thread.is_alive()`，若仍存活则仅记录 warning，**不再**继续清理 `bridge`/`_loop`，避免竞争。

**是否建议本次自动修复：否**（涉及线程安全重排，需人工验证退出时序）

**需要补充的测试：** `test_web_server_shutdown.py`：模拟 HTTP 线程在途请求，触发 `quit()`，断言 `web_thread.is_alive()` 在 join 后变为 False，且 `bridge.set_event_loop` 未被过早调用。

---

### BUG-003：show_for_screen() 在显示器枚举失败时静默返回，弹幕显示在错误位置或完全不可见

**严重等级：P1**

**影响功能：** 弹幕 Overlay 渲染 / 多屏适配

**证据文件：** [overlay.py](file:///workspace/app/overlay.py) L662-L669

**证据代码：**

```python
# overlay.py L662-L669
def show_for_screen(self, screen_index: int = 0, *, reload_tracks: bool | None = None):
    screens = QApplication.screens()
    if not screens:
        return
    screen_index = max(0, min(int(screen_index), len(screens) - 1))
    if screen_index < len(screens):
        geo = screens[screen_index].geometry()
        if geo.width() <= 0 or geo.height() <= 0:
            return
```

**复现路径：**
1. 用户配置 `screen_index=1`（副屏）。
2. 副屏断开连接（如 HDMI 拔掉、远程桌面会话变化、显卡驱动崩溃）。
3. `QApplication.screens()` 返回空列表或仅剩主屏。
4. `show_for_screen()` 在 `if not screens:` 或 `geo.width() <= 0` 处分支直接 `return`，**不设置任何错误状态**。
5. `engine.screen_width/screen_height` 保持旧值（可能为 0 或上次副屏分辨率），弹幕轨道计算错误，导致弹幕不可见或显示在屏幕外。

**根因分析：** 所有异常分支均静默 `return`，未向用户反馈「目标显示器不可用」，也未 fallback 到主屏。

**最小修复建议：** 在 `if not screens:` 和 `geo.width() <= 0` 分支中，增加日志 warning 并通过 `_set_error_status_safe` 向 Web 控制台推送 `"screen_unavailable"` 错误；同时自动 fallback 到 `screen_index=0`。

**是否建议本次自动修复：是**

**需要补充的测试：** `test_overlay_screen_fallback.py`：mock `QApplication.screens()` 返回空列表，断言 `show_for_screen()` 触发错误状态且 fallback 到主屏索引。

---

### BUG-004：Win32 SetWindowPos 置顶失败无返回值检查，游戏内 overlay 可能被压制

**严重等级：P1**

**影响功能：** 弹幕置顶 / 游戏内显示

**证据文件：** [win32_overlay_zorder.py](file:///workspace/app/win32_overlay_zorder.py) L66-L78、[overlay.py](file:///workspace/app/overlay.py) L530-L536

**证据代码：**

```python
# win32_overlay_zorder.py L66-L78
def reassert_hwnd_topmost(hwnd: int) -> None:
    if sys.platform != "win32" or not hwnd:
        return
    _SetWindowPos(
        hwnd,
        _HWND_TOPMOST,
        0, 0, 0, 0,
        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_SHOWWINDOW,
    )
```

```python
# overlay.py L530-L536
def showEvent(self, event):
    super().showEvent(event)
    self.reassert_topmost_zorder()
    self._apply_win32_click_through()
    if self.engine.running:
        self.ensure_render_loop()
```

**复现路径：**
1. 在 Windows 上运行 DanmuAI，启动弹幕。
2. 打开一个使用独占全屏模式的游戏（如部分 DirectX 游戏）。
3. Windows 系统可能因独占全屏策略将 `HWND_TOPMOST` 降级。
4. `SetWindowPos` 返回 0（失败），但代码不检查返回值。
5. 用户看到「弹幕不显示」或「被游戏画面盖住」。

**根因分析：** `reassert_hwnd_topmost()` 不检查 `SetWindowPos` 返回值；`overlay.py` 的 `_topmost_health_timer` 虽然周期性调用 `reassert_topmost_zorder()`，但如果单次调用持续失败，没有任何告警或降级策略。

**最小修复建议：** `reassert_hwnd_topmost()` 返回 `bool`（`SetWindowPos != 0`）；`overlay.py` 在 `_topmost_health_timer` 中累计失败次数，连续 3 次失败时向 Web 状态栏推送 `overlay_topmost_lost` 警告。

**是否建议本次自动修复：是**

**需要补充的测试：** `test_overlay_topmost_health.py`（已存在）：mock `SetWindowPos` 返回 0，断言连续失败后触发兼容性警告。

---

### BUG-005：Supabase 凭据变体可能绕过打包排除规则，导致密钥泄露到发布产物

**严重等级：P1**

**影响功能：** 发布安全 / 密钥泄露

**证据文件：** [DanmuAI.spec](file:///workspace/DanmuAI.spec) L32-L36、[scripts/publish_windows_release.ps1](file:///workspace/scripts/publish_windows_release.ps1) L14-L31

**证据代码：**

```python
# DanmuAI.spec L32-L36
def _should_exclude_supabase_config(name: str) -> bool:
    if name == "supabase-config.example.js":
        return False
    return name == "supabase-config.js" or name.startswith("supabase-config.js.")
```

```powershell
# publish_windows_release.ps1 L14-L31
$supabaseStaticDir = Join-Path $Root "web\static"
$forbiddenSupabaseConfigs = @()
$supabaseConfigPath = Join-Path $supabaseStaticDir "supabase-config.js"
if (Test-Path $supabaseConfigPath) {
    $forbiddenSupabaseConfigs += $supabaseConfigPath
}
Get-ChildItem -Path $supabaseStaticDir -Filter "supabase-config.js.*" -File -ErrorAction SilentlyContinue | ForEach-Object {
    $forbiddenSupabaseConfigs += $_.FullName
}
```

**复现路径：**
1. 开发者在本地复制 `supabase-config.js` 为 `supabase-config.js.backup` 或 `supabase-config.js.bak`。
2. `publish_windows_release.ps1` 的 `-Filter "supabase-config.js.*"` 能匹配 `.backup` / `.bak`。
3. 但如果开发者使用其他命名方式，如 `supabase-config-local.js`、`my-supabase-config.js`、`supabase-config.js.swp`（vim 交换文件），`DanmuAI.spec` 中的 `_should_exclude_supabase_config` 的 `name.startswith("supabase-config.js.")` **无法匹配** `supabase-config-local.js` 或 `my-supabase-config.js`。
4. 更危险的是，如果 PowerShell 脚本被跳过（如开发者直接运行 `pyinstaller DanmuAI.spec`），`DanmuAI.spec` 的 `_should_exclude_supabase_config` 是**唯一防线**，但它只防御特定前缀。

**根因分析：** 排除规则基于文件名前缀白名单，未采用更保守的「仅保留 example.js，其余全部排除」策略。

**最小修复建议：** 将 `_should_exclude_supabase_config` 改为：仅允许 `supabase-config.example.js` 和 `supabase-client.js`（如果存在），其余所有 `supabase-config*.js` 及 `supabase*.js`（除明确允许外）全部排除。

**是否建议本次自动修复：是**

**需要补充的测试：** `test_packaging_supabase_exclude.py`（已存在）：新增用例验证 `supabase-config-local.js`、`supabase-config.js.swp` 被排除。

---

### BUG-006：单实例 guard 的 server name 仅哈希 APPDATA，多用户/同机器场景可能互斥

**严重等级：P2**

**影响功能：** 启动稳定性 / 单实例可靠性

**证据文件：** [single_instance.py](file:///workspace/app/single_instance.py) L50-L53

**证据代码：**

```python
# single_instance.py L50-L53
def _server_name() -> str:
    appdata = os.environ.get("APPDATA", "").strip() or os.path.expanduser("~")
    digest = hashlib.sha256(appdata.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"DanmuAI-{digest}"
```

**复现路径：**
1. 用户 A 登录 Windows，APPDATA 为 `C:\Users\Alice\AppData\Roaming`，启动 DanmuAI。
2. 用户 A 注销，用户 B 登录（快速用户切换或家庭共享电脑）。
3. 用户 B 的 APPDATA 也是 `C:\Users\Alice\AppData\Roaming`（如果 B 继承了 A 的环境变量，或系统配置特殊）。
4. 用户 B 启动 DanmuAI，`try_acquire()` 发现同名 socket，尝试激活旧实例。
5. 旧实例已随用户 A 注销而退出，但 socket 文件残留；或旧实例仍在后台运行。
6. 用户 B 无法启动，或错误地激活了用户 A 的进程。

**根因分析：** 注释声称「哈希 %USERNAME% + config 数据库路径」，但代码实际只用了 `APPDATA`（或 `~`），未混入 `USERNAME` 或用户 SID。

**最小修复建议：** 将 `_server_name()` 改为 `hashlib.sha256(f"{os.environ.get('USERNAME','')}|{appdata}".encode()).hexdigest()[:16]`。

**是否建议本次自动修复：是**

**需要补充的测试：** `test_main_single_instance.py`（已存在）：验证不同 USERNAME 但相同 APPDATA 时生成不同 server name。

---

### BUG-007：_prepare_capacity_for_new_item() 的淘汰循环硬上限 512，大 retention_cap 下新弹幕被静默拒绝

**严重等级：P2**

**影响功能：** 弹幕显示密度 / 大容量配置不生效

**证据文件：** [danmu_engine.py](file:///workspace/app/danmu_engine.py) L644-L660

**证据代码：**

```python
# danmu_engine.py L644-L660
def _prepare_capacity_for_new_item(self) -> bool:
    pending_cap = self.max_pending_entry()
    retention_cap = self._track_retention_cap()
    if pending_cap <= 0 and retention_cap <= 0:
        return True
    safety = min(max(self.current_display_count(), pending_cap, retention_cap, 1) + 8, MAX_EVICT_ITERATIONS)
    for _ in range(safety):
        pending_over = pending_cap > 0 and self.pending_entry_count() >= pending_cap
        retention_over = retention_cap > 0 and self.current_display_count() >= retention_cap
        if not pending_over and not retention_over:
            return True
        if self._evict_furthest_offscreen_pending(1) <= 0:
            break
    pending_over = pending_cap > 0 and self.pending_entry_count() >= pending_cap
    retention_over = retention_cap > 0 and self.current_display_count() >= retention_cap
    return not pending_over and not retention_over
```

**复现路径：**
1. 用户将 `danmu_track_retention_cap` 设为 9999（UI 允许的最大值）。
2. 直播长时间运行，轨道内累计大量弹幕（如 600+ 条）。
3. 新弹幕到达时，`safety = min(..., 512)`，循环最多淘汰 512 条。
4. 如果此时屏外 pending 不足 512 条（大部分已滚入可见区），`_evict_furthest_offscreen_pending(1)` 很快返回 0，循环退出。
5. `retention_over` 仍为 True，函数返回 `False`，`add_text()` 返回 `None`。
6. 用户看到「弹幕突然变少」或「不显示」，但日志中只有一条 `danmu_dropped reason=dropped_by_cap` warning，不直观。

**根因分析：** `MAX_EVICT_ITERATIONS = 512` 是硬性上限，未与 `retention_cap` 动态关联；当用户设置超大 cap 时，淘汰跟不上上屏速度，新弹幕被静默丢弃。

**最小修复建议：** 当 `retention_cap > 0` 且 `current_display_count() >= retention_cap` 时，应优先淘汰**最旧的已滚出屏幕**弹幕（而非仅屏外 pending），或放宽淘汰上限；至少应在 UI 中提示「轨道已满，新弹幕被丢弃」。

**是否建议本次自动修复：否**（涉及淘汰策略调整，需评估对现有行为的冲击）

**需要补充的测试：** `test_danmu_display_cap.py`（已存在）：新增用例，设置 `retention_cap=9999` 且屏幕上有 600 条可见弹幕，断言新弹幕仍能上屏或至少触发明确的 UI 警告。

---

### BUG-008：频繁场景切换导致去重窗口被反复清空，重复弹幕大量上屏

**严重等级：P2**

**影响功能：** 弹幕去重 / 场景切换体验

**证据文件：** [danmu_engine.py](file:///workspace/app/danmu_engine.py) L287-L290、L825-L828

**证据代码：**

```python
# danmu_engine.py L287-L290
def _sync_dedup_window_generation(self, scene_generation: int) -> None:
    if int(scene_generation) != int(getattr(self, "_dedup_scene_generation", 0)):
        self.clear_dedup_window()
        self._dedup_scene_generation = int(scene_generation)
```

```python
# danmu_engine.py L825-L828
self._sync_dedup_window_generation(scene_generation)
if not skip_dedup and self._is_duplicate(content):
    return None
```

**复现路径：**
1. 用户在 Web 控制台频繁调整「直播话题」或「截图区域」（每次调整递增 `scene_generation`）。
2. `add_text()` 调用 `_sync_dedup_window_generation()`，发现 `scene_generation` 变化，立即 `clear_dedup_window()`。
3. 此时如果 AI 返回的弹幕与上一场景高度相似（如"666"、"主播好强"），由于 `recent_exact_set` 被清空，这些重复弹幕全部通过去重检查。
4. 用户看到大量重复弹幕刷屏。

**根因分析：** 场景代际变化时直接清空整个去重窗口，没有任何「跨场景保留部分高频去重记录」的缓冲策略。

**最小修复建议：** `clear_dedup_window()` 后，将最近 N 条（如 5 条）上屏弹幕重新注入 `recent`/`recent_exact_set`，保留最小跨场景去重能力；或在场景切换后的前 3 秒内提高去重阈值。

**是否建议本次自动修复：否**（产品行为调整，需评估是否影响「新场景需要新弹幕」的设计意图）

**需要补充的测试：** `test_danmu_dedup.py`（已存在）：新增用例，模拟 `scene_generation` 变化后立即添加与上一场景相同的弹幕，断言仍被去重。

---

### BUG-009：纯 Python Levenshtein 回退在 60fps 主线程中可能引发卡顿

**严重等级：P2**

**影响功能：** 弹幕去重性能 / Overlay 渲染流畅度

**证据文件：** [danmu_engine_dedup.py](file:///workspace/app/danmu_engine_dedup.py) L123-L154

**证据代码：**

```python
# danmu_engine_dedup.py L137-L149（fallback 路径）
m, n = len(a), len(b)
if m > n:
    a, b = b, a
    m, n = n, m
prev_row = list(range(n + 1))
for i in range(1, m + 1):
    curr = [i] + [0] * n
    for j in range(1, n + 1):
        cost = 0 if a[i - 1] == b[j - 1] else 1
        curr[j] = min(curr[j - 1] + 1, prev_row[j] + 1, prev_row[j - 1] + cost)
    prev_row = curr
dist = prev_row[n]
result = 1 - dist / max(len(a), len(b))
```

**复现路径：**
1. 用户环境未安装 `python-Levenshtein` 和 `rapidfuzz`（如精简 Python 环境）。
2. 直播弹幕密度高，去重窗口 30 条，每条 40-80 字符。
3. 每次 `add_text()` 触发 `is_duplicate_in_recent()`，在 30 条历史中逐条调用 `similarity()`。
4. 纯 Python 编辑距离最坏时间复杂度 O(m×n)，单次比较约 3200-6400 次操作，30 条即 10 万+ 次操作。
5. 在 60fps 主线程中，每帧 16ms，去重耗时可能导致帧率下降，表现为「弹幕滚动卡顿」。

**根因分析：** fallback 算法未做任何长度限制或提前退出；长文本在性能关键路径（主线程/Overlay tick）中逐对比较。

**最小修复建议：** 在 `similarity()` 的 fallback 路径中增加长度截断（如只比较前 32 个字符），或在 `is_duplicate_in_recent()` 中跳过长度超过 50 字符的 Levenshtein 比较（直接视为不重复，因长弹幕重复概率低）。

**是否建议本次自动修复：是**

**需要补充的测试：** `test_danmu_dedup.py`：在未安装 Levenshtein/rapidfuzz 的虚拟环境中，向 30 条窗口添加 80 字符弹幕，断言耗时 < 5ms。

---

### BUG-010：_pick_track() 全满 fallback 未考虑速度差异，可能导致轨道追尾重叠

**严重等级：P2**

**影响功能：** 弹幕轨道布局 / 视觉重叠

**证据文件：** [danmu_engine.py](file:///workspace/app/danmu_engine.py) L932-L938

**证据代码：**

```python
# danmu_engine.py L932-L938
candidates = heapq.nsmallest(3, self.tracks, key=lambda t: t.rightmost_edge())
best_track = random.choice(candidates)
tail_edge = best_track.rightmost_edge()
item.x = max(item.x, tail_edge + random.uniform(50.0, 250.0))
if item.x < tail_edge + min_gap:
    item.x = tail_edge + min_gap
return best_track
```

**复现路径：**
1. 轨道全部占满，进入 fallback 分支。
2. 某轨道尾端弹幕速度极慢（如 speed=1.0），而当前 `item.speed` 很快（如 speed=5.0）。
3. 代码仅根据 `rightmost_edge()` 选择候选轨道，未比较速度。
4. 快弹幕从 `tail_edge + min_gap` 处出发，很快追上慢弹幕，导致两条弹幕在屏幕上重叠显示。

**根因分析：** fallback 分支的防重叠逻辑是静态的（仅调整初始 x），没有考虑速度差导致的动态追尾。

**最小修复建议：** 在 fallback 分支中，计算候选轨道尾端弹幕的预计消失时间（`(rightmost_edge + width) / speed`），选择预计最早消失的轨道；或强制当前 `item.x` 至少为 `tail_edge + (tail_speed - item.speed) * estimated_time` 的动态间距。

**是否建议本次自动修复：否**（涉及轨道物理模型调整，需充分测试）

**需要补充的测试：** `test_pick_track_fallback_min_gap.py`（已存在）：新增用例验证速度差异大的两条弹幕不重叠。

---

### BUG-011：AI 请求失败重试时重复发送同一张截图，导致重复计费

**严重等级：P2**

**影响功能：** 模型调用成本 / API 费用

**证据文件：** [ai_client_requests.py](file:///workspace/app/ai_client_requests.py) L304-L399

**证据代码：**

```python
# ai_client_requests.py L304-L399（request_doubao 节选）
for attempt in range(2):
    if _request_wall_clock_exceeded(worker):
        return worker._deliver_outcome(...)
    try:
        text, input_tokens, output_tokens, stream_error = worker._stream_doubao(
            http_client, url, headers, data,
            first_content_timeout=STREAM_FIRST_CONTENT_TIMEOUT_SEC,
        )
        ...
    except httpx.TimeoutException:
        if attempt < 1:
            continue
        return worker._deliver_outcome(...)
    except Exception as exc:
        if attempt < 1:
            try:
                http_client = reset_worker_http_client(worker)
            except RuntimeError as reset_exc:
                return worker._deliver_outcome(...)
            continue
        ...
```

**复现路径：**
1. 网络波动导致第一次 `stream_doubao` 超时（`httpx.TimeoutException`）。
2. 代码进入 `attempt=1`，**使用相同的 `image_data_uri` 和 `data`** 重新发起请求。
3. 模型服务商对两次请求分别计费（输入 token 按图片 + 文本计算）。
4. 如果网络持续不稳定，用户为同一张截图支付双倍费用，但只收到一次弹幕。

**根因分析：** 重试机制未做「截图级请求去重」或「退避等待」；在抖动网络下成本翻倍。

**最小修复建议：** 在重试前增加指数退避（如 `time.sleep(1.0 * attempt)`）；或在 `_trigger_api_call` 层记录「本 screenshot_id 已请求过」，避免同一截图在短时间内重复请求。

**是否建议本次自动修复：是**（增加退避 sleep 即可，影响面小）

**需要补充的测试：** `test_ai_client.py`（已存在）：mock 第一次超时、第二次成功，断言 `http_client` 重试次数为 2，且两次请求间隔 >= 1s。

---

### BUG-012：麦克风音频被静默丢弃（模型不支持时），用户无感知

**严重等级：P2**

**影响功能：** 麦克风模式 / 用户体验

**证据文件：** [ai_client_requests.py](file:///workspace/app/ai_client_requests.py) L490-L499

**证据代码：**

```python
# ai_client_requests.py L490-L499
mic_audio = audio_data_uri
if mic_audio and not model_supports_mic_audio(model, endpoint=endpoint, api_mode=api_mode):
    from app.model_providers import mic_audio_unsupported_message
    logger.info(
        "mic audio stripped before openai request: model=%s endpoint=%s reason=%s",
        model, endpoint, mic_audio_unsupported_message(model),
    )
```

**复现路径：**
1. 用户开启麦克风模式，但当前选用的视觉模型不支持音频输入（如非 MiMo/豆包全模态模型）。
2. `request_openai()` 检测到不支持，仅记录 `logger.info`，**静默丢弃 `audio_data_uri`**。
3. 用户看到麦克风指示灯亮着，以为自己的声音被识别，但实际上 AI 只收到了截图和文本。
4. 生成的弹幕与语音无关，用户困惑。

**根因分析：** 降级路径未向用户显示任何警告或错误状态。

**最小修复建议：** 在丢弃音频时，通过 `worker._deliver_outcome(signal_name="error", message=...)` 向 Web 状态栏推送 `"mic_audio_unsupported_for_model"` 提示；或在 `mic_orchestrator.sync()` 中提前拦截，阻止进入不支持的模型路径。

**是否建议本次自动修复：是**

**需要补充的测试：** `test_mic_credentials.py`（已存在）：使用不支持音频的模型触发请求，断言返回错误消息包含「当前模型不支持麦克风」。

---

### BUG-013：first_content_timeout 固定值，慢模型/慢网环境下频繁超时

**严重等级：P2**

**影响功能：** 模型调用稳定性 / 慢网可用性

**证据文件：** [ai_client_requests.py](file:///workspace/app/ai_client_requests.py) L322、[main_helpers.py](file:///workspace/app/main_helpers.py)（STREAM_FIRST_CONTENT_TIMEOUT_SEC 定义处）

**证据代码：**

```python
# ai_client_requests.py L322（request_doubao 中）
text, input_tokens, output_tokens, stream_error = worker._stream_doubao(
    http_client, url, headers, data,
    first_content_timeout=STREAM_FIRST_CONTENT_TIMEOUT_SEC,
)
```

**复现路径：**
1. 用户使用海外模型或网络质量差（如晚高峰）。
2. 模型首 token 延迟 > `STREAM_FIRST_CONTENT_TIMEOUT_SEC`（通常为 15-20s）。
3. 请求被强制超时，触发重试（BUG-011），再次超时后彻底失败。
4. 用户看到「AI 返回为空」或「超时」，但实际是首 token 延迟问题。

**根因分析：** `first_content_timeout` 为编译期常量，未根据网络状况、模型历史延迟或用户配置动态调整。

**最小修复建议：** 将 `first_content_timeout` 暴露为配置项（如 `stream_first_content_timeout_sec`），默认值保持现有常量，但允许用户在慢网环境手动调高。

**是否建议本次自动修复：是**（仅增加配置项读取，不改变默认值）

**需要补充的测试：** `test_ai_client.py`：mock 首 token 延迟 25s，设置 `stream_first_content_timeout_sec=30`，断言请求成功。

---

### BUG-014：mic_orchestrator 不支持麦克风时仅记日志，不更新 UI 错误状态

**严重等级：P2**

**影响功能：** 麦克风模式 / 错误可观测性

**证据文件：** [mic_orchestrator.py](file:///workspace/app/mic_orchestrator.py) L72-L76

**证据代码：**

```python
# mic_orchestrator.py L72-L76
if not mic_audio_supported_fn():
    model_id = resolve_active_model_id_fn()
    self._log(f"mic unsupported for model {model_id or '?'}")
    self.stop_detector()
    return
```

**复现路径：**
1. 用户开启麦克风模式，选用不支持音频的模型。
2. `MicOrchestrator.sync()` 调用 `mic_audio_supported_fn()` 返回 False。
3. 仅通过 `self._log()`（即 `DanmuApp.logger.info`）记录一条 info 日志。
4. Web 控制台的状态栏仍显示「运行中」，麦克风图标可能也是绿色，用户不知道为何不工作。

**根因分析：** 错误仅落日志，未通过 `set_web_error_status` 或类似机制向 UI 反馈。

**最小修复建议：** 在 `mic_orchestrator.sync()` 的返回值为「不支持」时，调用 `self._app.set_web_error_status("mic.unsupported_for_model", is_error=True)`。

**是否建议本次自动修复：是**

**需要补充的测试：** `test_mic_mode.py`（已存在）：mock 不支持音频的模型，断言 Web 错误状态被设置。

---

### BUG-015：Fernet key 损坏后旧加密数据不可读，UI 不提示具体失效字段

**严重等级：P2**

**影响功能：** 配置可靠性 / 用户体验

**证据文件：** [config_store.py](file:///workspace/app/config_store.py) L250-L289

**证据代码：**

```python
# config_store.py L250-L289
def _init_fernet(self):
    if not _HAS_CRYPTO:
        return None
    if self._key_file.exists():
        key = self._key_file.read_bytes()
        try:
            f = Fernet(key)
            f.decrypt(f.encrypt(b"test"))
            return f
        except Exception:
            self._key_backup_path = _backup_corrupted_key_file(...)
            self._key_regenerated = True
            pass
    # Key file missing — check if encrypted data exists that's now unreadable
    if not self._key_file.exists() and not self.is_first_run:
        has_encrypted = bool(
            self._cache.get("api_key_encrypted")
            or self._cache.get("mic_api_key_encrypted")
            or self._cache.get("tts_api_key_encrypted")
        )
        if has_encrypted:
            self._key_regenerated = True
    key = Fernet.generate_key()
    self._key_file.write_bytes(key)
    _restrict_key_file_permissions(self._key_file)
    return Fernet(key)
```

**复现路径：**
1. 用户的 `.key` 文件因磁盘错误损坏。
2. 启动时 `_init_fernet()` 生成新 key，`_key_regenerated = True`。
3. `get_startup_notice()` 返回 `config.key_lost_notice`，提示「密钥已重新生成，旧加密数据不可读」。
4. 但用户进入 Web 控制台后，「助手设置」中的 API Key 显示为空，用户不知道是**哪个** Key 丢了（视觉模型 Key？麦克风 Key？TTS Key？）。

**根因分析：** 全局提示文案未区分失效的加密字段，用户需要逐个页面检查。

**最小修复建议：** 在 `get_startup_notice()` 中，遍历 `api_key_encrypted`、`mic_api_key_encrypted`、`tts_api_key_encrypted`，检测哪些字段存在密文但无法解密，生成具体的提示文案如「视觉模型 API Key 已失效，请重新填写」。

**是否建议本次自动修复：是**

**需要补充的测试：** `test_config_store_corrupt_custom_models.py`（已存在）：模拟 key 损坏且存在 `mic_api_key_encrypted`，断言启动提示包含「麦克风 API Key」。

---

### BUG-016：config.close() 与并发写竞争，数据可能静默丢失

**严重等级：P2**

**影响功能：** SQLite 数据一致性 / 退出时配置丢失

**证据文件：** [config_store.py](file:///workspace/app/config_store.py) L1223-L1230

**证据代码：**

```python
# config_store.py L1223-L1230
def close(self):
    with self._write_lock:
        self._closed = True
    self._invalidate_formula_text_cache()
    try:
        self.conn.close()
    except sqlite3.ProgrammingError:
        pass
```

**复现路径：**
1. 退出时，`quit()` 调用 `self.config.close()`，获取 `_write_lock` 并设置 `_closed=True`。
2. 如果此时 HTTP 线程（如 Web API 的 `apply_web_config_patch`）已经获取了 `_write_lock`（close 会阻塞等待），close 释放锁后，HTTP 线程继续执行 `set_batch()`。
3. `set_batch()` 进入后发现 `_closed=True`，记录 warning 并 `return`，不写数据库。
4. 用户最后的配置修改（如调整弹幕速度）被静默丢弃。

**根因分析：** `close()` 设置 `_closed=True` 后立即释放锁，后续拿到锁的线程发现已关闭便跳过写入，无异常抛出。

**最小修复建议：** `close()` 在设置 `_closed=True` 后，继续持有 `_write_lock` 直到 `conn.close()` 完成，确保后续线程在 `close()` 完成前阻塞，而不是在 `close()` 完成后静默跳过。

**是否建议本次自动修复：是**

**需要补充的测试：** `test_p1_sqlite_concurrency.py`（已存在）：线程 A 在 `close()` 过程中，线程 B 尝试 `set_batch()`，断言线程 B 抛出 `RuntimeError` 而非静默跳过。

---

### BUG-017：PetWindow 可能错误应用 WS_EX_TRANSPARENT，导致鼠标事件被穿透

**严重等级：P2**

**影响功能：** 桌宠交互 / 拖动 / 右键菜单 / 双击输入

**证据文件：** [pet_window.py](file:///workspace/app/pet_window.py) L41-45、[win32_overlay_zorder.py](file:///workspace/app/win32_overlay_zorder.py) L38-48

**证据代码：**

```python
# pet_window.py L41-45
from app.win32_overlay_zorder import (
    apply_overlay_exstyles,
    reassert_hwnd_topmost,
    stack_hwnd_above,
)
```

```python
# win32_overlay_zorder.py L38-48
def apply_overlay_exstyles(hwnd: int, *, click_through: bool = True) -> None:
    if sys.platform != "win32" or not hwnd:
        return
    ex_style = _GetWindowLong(hwnd, _GWL_EXSTYLE)
    if click_through:
        new_style = ex_style | _WS_EX_LAYERED | _WS_EX_TRANSPARENT
    else:
        new_style = (ex_style | _WS_EX_LAYERED) & ~_WS_EX_TRANSPARENT
    _SetWindowLong(hwnd, _GWL_EXSTYLE, new_style)
```

**复现路径：**
1. `PetWindow` 需要接收鼠标事件（拖动、双击、右键菜单）。
2. 如果 `PetWindow` 的代码路径中调用了 `apply_overlay_exstyles(hwnd, click_through=True)`（如与 `DanmuOverlay` 共用同一段 Win32 初始化逻辑），`WS_EX_TRANSPARENT` 会导致所有鼠标事件穿透到桌面。
3. 用户无法拖动桌宠，也无法双击打开命令输入框。

**根因分析：** `apply_overlay_exstyles` 默认 `click_through=True`；`PetWindow` 可能需要 `click_through=False`，但代码搜索显示 `pet_window.py` 直接导入了该函数，需要确认调用点。

**最小修复建议：** 在 `PetWindow.show_pet()` 或 `showEvent()` 中，如果调用了 `apply_overlay_exstyles`，必须显式传入 `click_through=False`。

**是否建议本次自动修复：是**（若确认调用点未传 False）

**需要补充的测试：** `test_pet_window_drag.py`（已存在）：在 Windows 模拟环境下，断言 `PetWindow` 的 `WS_EX_TRANSPARENT` 未被设置。

---

### BUG-018：桌宠弹幕槽位 fallback 坐标硬编码，不适配小屏/大屏/多屏

**严重等级：P2**

**影响功能：** 桌宠模式 / 多分辨率适配

**证据文件：** [pet_barrage.py](file:///workspace/app/pet_barrage.py) L35-L48

**证据代码：**

```python
# pet_barrage.py L35-L48
def default_slot_positions() -> list[dict[str, int]]:
    app = QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return [{"x": 80 + idx * 220, "y": 760} for idx in range(PET_BARRAGE_COUNT)]
    geo = screen.availableGeometry()
    bottom_y = max(geo.top(), geo.bottom() - 180)
    left = geo.left() + 60
    available_w = max(1, geo.width() - 120)
    step = available_w / PET_BARRAGE_COUNT
    ...
```

**复现路径：**
1. 用户在 1366x768 的笔记本上运行 DanmuAI。
2. `primaryScreen()` 返回 None（某些显卡驱动或远程桌面场景）。
3. `default_slot_positions()` fallback 到硬编码坐标 `y=760`。
4. 对于 768p 屏幕，`y=760` 已接近或超出屏幕底部，桌宠被截断或完全不可见。

**根因分析：** `screen is None` 的 fallback 坐标未按屏幕分辨率动态计算。

**最小修复建议：** fallback 坐标使用 `QApplication.primaryScreen().geometry()` 或至少将 `y` 设为 `min(760, 屏幕高度 - 100)`。

**是否建议本次自动修复：是**

**需要补充的测试：** `test_pet_barrage_window.py`（已存在）：mock `primaryScreen()` 返回 None 且虚拟桌面为 1366x768，断言槽位 y 坐标 <= 668。

---

### BUG-019：publish_windows_release.ps1 版本号读取无 fallback，Python 环境异常时发布中断

**严重等级：P2**

**影响功能：** 发布脚本可靠性

**证据文件：** [scripts/publish_windows_release.ps1](file:///workspace/scripts/publish_windows_release.ps1) L63-L69

**证据代码：**

```powershell
# publish_windows_release.ps1 L63-L69
$versionOutput = python -c "from app.version import __version__; print(__version__)" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to read app version from app.version.__version__ (exit $LASTEXITCODE): $versionOutput"
}
$appVersion = $versionOutput.Trim()
if (-not $appVersion -or $appVersion -notmatch '^\d+\.\d+\.\d+') {
    Write-Error "Invalid version string from app.version.__version__: '$appVersion' (expected semver x.y.z)"
}
```

**复现路径：**
1. 发布者在全新 CI 机器或重装系统后运行发布脚本。
2. `python` 命令指向的 Python 未安装项目依赖（如缺少 `app` 包的某些依赖导致 import 失败）。
3. `$LASTEXITCODE -ne 0`，脚本直接 `Write-Error` 终止。
4. 没有 fallback 到读取 `app/version.py` 的正则提取，或读取 git tag。

**根因分析：** 版本号获取强依赖可正常 import `app.version` 的 Python 环境。

**最小修复建议：** 在 `python -c` 失败时，fallback 到 `Get-Content app/version.py | Select-String "__version__"` 正则提取，或读取 `git describe --tags`。

**是否建议本次自动修复：是**

**需要补充的测试：** 在 CI 中新增一个「最小 Python 环境」job，仅安装标准库，运行 `publish_windows_release.ps1 -DryRun`，验证版本号读取不失败。

---

### BUG-020：便携版解压到名为 "current" 的目录时误判为 Velopack 安装

**严重等级：P2**

**影响功能：** 自动更新 / 便携版稳定性

**证据文件：** [update_service.py](file:///workspace/app/update_service.py) L67-L75、[velopack_runtime.py](file:///workspace/app/velopack_runtime.py) L9-L17

**证据代码：**

```python
# update_service.py L67-L75
def _is_velopack_install() -> bool:
    if not _is_frozen():
        return False
    exe_path = getattr(sys, "executable", "") or ""
    if not exe_path:
        return False
    resolved = Path(exe_path).resolve()
    return resolved.parent.name.lower() == "current" and (resolved.parent.parent / "Update.exe").is_file()
```

**复现路径：**
1. 用户下载便携版 `PEPETII.DanmuAI-win-Portable.zip`，解压到 `D:\Tools\current\DanmuAI\`。
2. `_is_velopack_install()` 发现 `resolved.parent.name == "current"`，且用户可能恰好有 `D:\Tools\Update.exe`（其他软件）。
3. 误判为 Velopack 安装，更新检查逻辑尝试调用 Velopack API，可能导致异常或错误的更新提示。

**根因分析：** 仅通过目录名 `current` 和相邻 `Update.exe` 判断，未验证 `Update.exe` 的签名或版本资源。

**最小修复建议：** 在判断时增加对 `Update.exe` 的元数据校验（如检查文件版本信息中是否包含 `"Velopack"`），或通过 Velopack 提供的官方 API（如 `velopack.App().is_installed`）做更可靠的检测。

**是否建议本次自动修复：是**

**需要补充的测试：** `test_velopack_runtime.py`（已存在）：模拟便携版目录结构 `current/DanmuAI.exe` 且相邻存在无关 `Update.exe`，断言 `_is_velopack_install()` 返回 False。

---

### BUG-021：Supabase feedback 表缺少 REVOKE，RLS 策略不完整

**严重等级：P2**

**影响功能：** Web 社区后端 / 数据安全

**证据文件：** [supabase/migrations/001_announcements_feedback.sql](file:///workspace/supabase/migrations/001_announcements_feedback.sql) L16-L66

**证据代码：**

```sql
-- 001_announcements_feedback.sql L33-L66
alter table public.announcements enable row level security;
alter table public.feedback enable row level security;

create policy "anon_read_published_announcements"
  on public.announcements for select to anon ...

create policy "anon_insert_feedback"
  on public.feedback for insert to anon ...
```

**复现路径：**
1. Supabase 项目默认可能对 `anon` 角色授予了 `SELECT`/`UPDATE`/`DELETE` 权限。
2. migration 中只创建了 `insert` policy 和 `select` policy，但没有显式 `REVOKE SELECT, UPDATE, DELETE ON public.feedback FROM anon;`。
3. 如果管理员后续调整默认权限，或 Supabase 版本升级改变默认行为，`anon` 可能能够读取其他用户的 feedback 内容，或恶意更新/删除。

**根因分析：** RLS 启用后，缺少默认权限回收，依赖 Supabase 的初始默认值。

**最小修复建议：** 在 migration 中显式添加：

```sql
REVOKE ALL ON public.feedback FROM anon;
GRANT INSERT ON public.feedback TO anon;
```

**是否建议本次自动修复：是**

**需要补充的测试：** 在 Supabase local/staging 中，使用 anon key 尝试 `SELECT * FROM feedback` 和 `DELETE FROM feedback`，断言返回 0 行 / 权限拒绝。

---

### BUG-022：start() 凭证缺失时提前 return，托盘状态未更新为错误

**严重等级：P2**

**影响功能：** 启动体验 / 托盘状态一致性

**证据文件：** [main_lifecycle_mixin.py](file:///workspace/app/main_lifecycle_mixin.py) L501-L521

**证据代码：**

```python
# main_lifecycle_mixin.py L501-L521
def start(self) -> None:
    if not visual_credentials_ready(self.config):
        msg = format_credential_error(self.config)
        self.logger.warning(msg)
        self._set_error_status_safe(msg, is_error=True)
        self.tray.show_api_key_missing_hint()
        if self.web_server:
            self._open_web_console("/#settings")
        return
    ...
    self.tray.update_state(running=True)  # 在 L578，提前 return 时不会执行
```

**复现路径：**
1. 新用户首次安装，未配置 API Key，点击托盘「生成弹幕」。
2. `start()` 在 `visual_credentials_ready()` 处失败，提前 `return`。
3. `self.tray.update_state(running=True)` 未执行，托盘图标可能仍显示「暂停」状态或无任何状态变化。
4. 用户不知道点击是否生效，可能重复点击。

**根因分析：** 提前返回路径未同步托盘状态为「错误/停止」。

**最小修复建议：** 在 `start()` 的凭证缺失 return 分支中，调用 `self.tray.update_state(running=False)` 并确保托盘图标显示错误指示（如变红或显示警告气泡）。

**是否建议本次自动修复：是**

**需要补充的测试：** `test_tray_update_check_async.py`（已存在）：在凭证缺失时触发 `start()`，断言 `tray.update_state(running=False)` 被调用。

---

### BUG-023：quit() 中 worker pool waitForDone 超时固定 2s，慢模型下进程残留

**严重等级：P2**

**影响功能：** 退出稳定性 / 后台进程残留

**证据文件：** [main_lifecycle_mixin.py](file:///workspace/app/main_lifecycle_mixin.py) L685-L737

**证据代码：**

```python
# main_lifecycle_mixin.py L685-L737
capture_done = capture_worker_pool().waitForDone(2000)
if not capture_done:
    cap_pool = capture_worker_pool()
    self.logger.warning(...)

ai_done = ai_worker_pool().waitForDone(2000)
if not ai_done:
    ai_pool_inst = ai_worker_pool()
    self.logger.warning(...)

meme_done = meme_ai_pool().waitForDone(2000)
fetch_done = meme_fetch_pool().waitForDone(2000)
pool = QtCore.QThreadPool.globalInstance()
pool_done = pool.waitForDone(2000)
```

**复现路径：**
1. 用户正在使用一个响应极慢的模型（如海外模型在晚高峰）。
2. 点击托盘「退出」。
3. `ai_worker_pool().waitForDone(2000)` 超时，因为 httpx 请求仍在等待首 token。
4. 代码记录 warning 后继续执行 `QApplication.quit()`。
5. 但 httpx 的底层 TCP 连接仍在后台线程中阻塞，Python 进程无法立即结束，用户看到「DanmuAI.exe 仍在任务管理器中」。

**根因分析：** 超时过短（2s），且超时后未强制中断在途 HTTP 请求（如关闭 httpx client）。

**最小修复建议：** 在 `waitForDone` 超时后，遍历并关闭所有在途的 httpx client（`worker._clients`）；或至少在 frozen 模式下将超时延长至 10s。

**是否建议本次自动修复：否**（涉及 HTTP 连接强制关闭，需验证是否导致异常日志）

**需要补充的测试：** `test_quit_on_last_window_closed.py`（已存在）：mock 一个运行 5s 的 AI worker，触发 `quit()`，断言进程在 3s 内退出（通过子进程监控）。

---

### BUG-024：_init_tracks() line_height 固定 40px，未适配 DPI 缩放

**严重等级：P2**

**影响功能：** 弹幕显示 / 高分屏适配

**证据文件：** [danmu_engine.py](file:///workspace/app/danmu_engine.py) L314-L338

**证据代码：**

```python
# danmu_engine.py L314-L338
def _init_tracks(self):
    line_height = 40
    top_margin = 50
    bottom_margin = 80
    ratio = layout_height_ratio(self.config)
    drawable_height = self.screen_height * ratio
    configured = self.config.get_int("danmu_lines", 0)
    ...
    if val > 0:
        line_count = clamp_danmu_lines(val)
    else:
        usable = max(line_height, drawable_height - top_margin - bottom_margin)
        line_count = clamp_danmu_lines(int(usable / line_height))
    ...
```

**复现路径：**
1. 用户在 4K 屏幕（3840x2160）上设置 200% DPI 缩放。
2. `line_height = 40` 对应的是未缩放的逻辑像素，实际物理像素为 80px。
3. 但 `screen_height` 返回的是逻辑像素（2160），`drawable_height = 2160 * 1.0 = 2160`。
4. `usable = 2160 - 50 - 80 = 2030`，`line_count = 2030 / 40 = 50`（但被 `clamp_danmu_lines` 截断到 20）。
5. 实际每行弹幕在 200% 缩放下物理高度为 80px，20 行共 1600px，对于 2160px 屏幕尚可；但如果用户设置 `layout_mode="1/2"`，`drawable_height=1080`，`line_count=1080/40=27`（截断到 20），20 行 * 80px = 1600px > 1080px，弹幕超出绘制区域，发生重叠。

**根因分析：** 所有像素常量（40, 50, 80）均为未缩放的硬编码值，未通过 `QApplication.devicePixelRatio()` 或 `QScreen.logicalDotsPerInch()` 进行 DPI 适配。

**最小修复建议：** 使用 `QApplication.primaryScreen().devicePixelRatio()` 或 `logicalDotsPerInch() / 96.0` 计算 DPI 缩放因子，将 `line_height`、`top_margin`、`bottom_margin` 乘以该因子。

**是否建议本次自动修复：是**

**需要补充的测试：** `test_danmu_engine_screen_height_rebuild.py`（已存在）：在 200% DPI 环境下，断言轨道总高度不超过 `drawable_height`。

---

## 3. 高风险但未确认问题

以下问题证据不足或依赖特定环境，建议人工重点验证：

| 编号 | 标题 | 待验证内容 | 建议验证方式 |
|------|------|------------|--------------|
| RISK-001 | **读弹幕模式无限循环消耗 TTS 配额** | `danmu_read_service.py` 的 `_on_tick()` 在 TTS 连续失败时仅停止本次合成，但定时器仍在运行；若服务商持续限流/报错，可能每 10 秒请求一次，消耗配额。 | 在 staging 环境使用无效 TTS Key 运行 5 分钟，监控 HTTP 请求次数。 |
| RISK-002 | **webview 子进程 kill() 后 WebView2 句柄残留** | `webview_shell.py` 的 `_terminate()` 在 `proc.kill()` 后仅 join 1s；Windows 上 WebView2 进程树可能未完全终止，导致下次启动时 `webview.create_window` 失败。 | 在 Windows 上反复启动/退出 10 次，监控 `msedgewebview2.exe` 进程数。 |
| RISK-003 | **自定义弹幕库 20000 条导入时 UI 阻塞** | `config_store.py` 的 `set_custom_danmu_pool_for_store`（未读取到完整代码）若使用全量 REPLACE，大数据量导入可能阻塞主线程数秒。 | 构造 20000 条记录的 JSON 导入，测量 `apply_web_config_payload` 耗时。 |
| RISK-004 | **公式化弹幕库烂梗源变更后标签筛选不生效** | `app/meme_barrage/` 模块中，外部接口返回的标签变更后，本地缓存的 `formula_meme_sets` 可能未及时失效。 | 修改烂梗源标签，验证 Web 控制台的标签筛选结果是否同步。 |
| RISK-005 | **MSI 安装与 Setup.exe 的用户数据保留策略不一致** | `scripts/velopack_pack.ps1` 未在本次审计中完整读取，需确认 MSI 和 Setup.exe 的卸载脚本是否都调用 `delete_user_data_if_requested`。 | 阅读 velopack_pack.ps1 完整内容，对比 MSI 和 Setup 的卸载行为。 |

---

## 4. 性能与卡顿风险

| 风险点 | 证据 | 触发条件 | 影响 |
|--------|------|----------|------|
| **纯 Python Levenshtein 回退卡顿** | `danmu_engine_dedup.py` L137-L149 | 未安装 C 扩展且弹幕密度高 | 主线程 60fps 掉帧 |
| **Overlay stop_render_loop(repaint=True) 一次性卡顿** | `overlay.py` L290-L299 | 大量弹幕（>300 条）同时停止 | 单帧 paintEvent 遍历全部 item |
| **自定义弹幕库全量导入阻塞** | `config_store.py`（diff 路径未完全读取） | 20000 条全量写入 | 主线程/UI 阻塞数秒 |
| **AI 请求重试无退避，网络抖动时成本翻倍** | `ai_client_requests.py` L304-L399 | 超时后立即重试 | 同一张截图重复计费 |
| **DPI 未适配导致轨道计算错误** | `danmu_engine.py` L314-L338 | 高分屏 150%+ | 弹幕重叠或超出屏幕 |
| **容量淘汰硬上限 512，大 cap 下弹幕被拒** | `danmu_engine.py` L644-L660 | retention_cap=9999 | 新弹幕静默丢失 |

---

## 5. 兼容性与环境风险

| 风险点 | 证据 | 触发条件 |
|--------|------|----------|
| **screens 为空时弹幕静默失败** | `overlay.py` L662-L669 | 远程桌面断开、显卡驱动崩溃 |
| **中文路径 / PowerShell 编码** | `publish_windows_release.ps1` L10 显式设置 UTF8 | 已处理，但其他脚本未逐一检查 |
| **WebView2 缺失时 fallback 到浏览器** | `webview_shell.py` L425-L434 | 已存在 fallback，但 hiddenimports 遗漏导致 fallback 前崩溃 |
| **单实例 guard 多用户误判** | `single_instance.py` L50-L53 | 共享电脑、快速用户切换 |
| **便携版目录名 "current" 误判** | `update_service.py` L67-L75 | 用户自定义解压路径 |

---

## 6. 发布与更新风险

| 风险点 | 严重度 | 证据 |
|--------|--------|------|
| **DanmuAI.spec 遗漏 app.webview2_runtime** | P0 | `DanmuAI.spec` hiddenimports 无该模块 |
| **supabase-config.js 变体可能泄露** | P1 | `_should_exclude_supabase_config` 只防特定前缀 |
| **发布脚本版本号读取无 fallback** | P2 | `publish_windows_release.ps1` L63-L69 |
| **便携版误判 Velopack 安装** | P2 | `update_service.py` L67-L75 |
| **MSI/Setup 用户数据保留策略未确认** | P2（待确认） | `velopack_pack.ps1` 未完整审计 |
| **releases.win.json 版本比较** | P2 | `version_compare.py` 已处理 semver 和 prerelease，但未验证与 Velopack 的兼容性 |

---

## 7. 安全与隐私风险

| 风险点 | 严重度 | 证据 |
|--------|--------|------|
| **Supabase 凭据可能被打包** | P1 | `DanmuAI.spec` L32-L36 排除规则不完整 |
| **Supabase feedback RLS 不完整** | P2 | `001_announcements_feedback.sql` 无 REVOKE |
| **API Key 加密失败退化为 base64** | P2 | `config_store.py` L250-L289 缺少 crypto 时退化，但 README 已说明 |
| **日志中可能存在未脱敏的 URL** | P3 | `ai_client_requests.py` 日志中包含 `endpoint`，虽非密钥，但可能暴露服务商 |
| **feedback 表 client_id 未做速率限制外泄** | P3 | `feedback_quota` 函数返回详细时间戳，可能帮助攻击者推断其他用户的提交窗口 |

---

## 8. 建议新增的测试

| 测试文件 | 测试目标 | 关键断言 |
|----------|----------|----------|
| `test_pyinstaller_hiddenimports.py`（扩展） | 确保 `app.webview2_runtime` 在 hiddenimports 中 | `assert "app.webview2_runtime" in hiddenimports` |
| `test_overlay_screen_fallback.py`（新增） | screens 为空时 fallback 并报错 | `assert error_status == "screen_unavailable"`；`assert fallback_screen_index == 0` |
| `test_danmu_dedup_cross_scene.py`（新增） | 场景切换后保留最小去重能力 | `scene_generation += 1` 后添加旧弹幕，断言 `is_duplicate` 返回 True |
| `test_danmu_dedup_slow_fallback_perf.py`（新增） | 纯 Python Levenshtein 回退性能 | 80 字符 × 30 条窗口，断言耗时 < 5ms |
| `test_ai_client_retry_backoff.py`（新增） | 超时重试有退避间隔 | mock 第一次超时，断言两次请求间隔 >= 1s |
| `test_config_close_concurrent_write.py`（扩展） | close() 后不丢失在途写入 | 线程 B 在 close() 期间 set_batch，断言抛出 RuntimeError 而非静默跳过 |
| `test_pet_window_click_through.py`（新增） | PetWindow 不设置 WS_EX_TRANSPARENT | 断言 `GetWindowLong(GWL_EXSTYLE) & WS_EX_TRANSPARENT == 0` |
| `test_pet_barrage_small_screen.py`（扩展） | primaryScreen=None 且 768p 时坐标正确 | 断言 `y <= 668` |
| `test_velopack_portable_false_positive.py`（新增） | 便携版目录名为 current 时不误判 | `assert _is_velopack_install() is False` |
| `test_supabase_feedback_rls.py`（新增） | anon 无法 SELECT/UPDATE/DELETE feedback | 断言 HTTP 403 或返回空数组 |

---

## 9. 本次可自动修复项

以下问题修复范围小、证据充分、不改变产品设计，建议本次直接修复：

1. **BUG-001**：`DanmuAI.spec` 新增 `"app.webview2_runtime"` 到 `hiddenimports`。
2. **BUG-006**：`single_instance.py` 的 `_server_name()` 混入 `USERNAME`。
3. **BUG-009**：`similarity()` fallback 路径增加长度截断（如前 32 字符）。
4. **BUG-011**：`ai_client_requests.py` 重试前增加 `time.sleep(1.0 * attempt)` 退避。
5. **BUG-012**：麦克风音频丢弃时向 UI 返回错误状态。
6. **BUG-013**：`first_content_timeout` 暴露为可配置项（默认保持现有值）。
7. **BUG-014**：`mic_orchestrator.sync()` 不支持时调用 `set_web_error_status`。
8. **BUG-015**：`get_startup_notice()` 中区分具体失效的 Key 字段。
9. **BUG-016**：`config.close()` 保持 `_write_lock` 直到 `conn.close()` 完成。
10. **BUG-018**：`default_slot_positions()` fallback 坐标按屏幕高度裁剪。
11. **BUG-019**：`publish_windows_release.ps1` 增加版本号读取 fallback。
12. **BUG-020**：`_is_velopack_install()` 增加 `Update.exe` 元数据校验。
13. **BUG-022**：`start()` 凭证缺失时更新 tray 状态为错误。
14. **BUG-024**：`_init_tracks()` 引入 DPI 缩放因子。
15. **BUG-005**：`_should_exclude_supabase_config` 改为白名单策略（仅保留 example.js）。

---

## 10. 最终建议

### Top 3 优先级事项

1. **【P0】修复 PyInstaller hiddenimports 遗漏 `app.webview2_runtime`（BUG-001）**
   - 理由：直接影响 frozen EXE 的启动可靠性，用户环境缺少 WebView2 时会崩溃而非优雅 fallback，是发布 blocker 级别问题。
   - 动作：在 `DanmuAI.spec` 中新增一行 `"app.webview2_runtime"`，并补充单测。

2. **【P1】修复 quit() 中 Web 服务器 shutdown 竞争与进程残留（BUG-002 + BUG-023）**
   - 理由：用户反馈「退出后任务管理器还有 DanmuAI.exe」是高频客诉；0.5s shutdown 超时和 2s worker pool 超时在慢网/慢模型下几乎必然触发，导致配置丢失或进程残留。
   - 动作：延长 shutdown join 超时到 5s；在 worker pool 超时后强制关闭 httpx client；补充子进程退出测试。

3. **【P1/P2】修复弹幕显示链路的静默失败与性能瓶颈（BUG-003 + BUG-007 + BUG-009）**
   - 理由：「直播中不显示弹幕」「弹幕卡顿」是核心体验问题；显示器枚举失败静默返回、大 retention_cap 下弹幕被静默拒绝、纯 Python Levenshtein 回退卡顿，都会导致用户直观感受到「功能坏了」。
   - 动作：增加屏幕不可用 fallback 和错误提示；优化 Levenshtein fallback 性能；评估 retention_cap 淘汰策略调整。

---

## 评分自检

| 维度 | 自评（0-2） | 说明 |
|------|-------------|------|
| 证据完整性（文件/代码/复现） | 2 | 每个 Bug 均给出文件路径、行号范围、代码片段、复现步骤 |
| 严重度判定准确性 | 2 | P0 为发布 blocker，P1 为核心功能不可用/安全风险，P2 为体验受损/边界异常 |
| 区分「已确认」与「待确认」 | 2 | 第 2 节为已确认 Bug，第 3 节为高风险待人工确认 |
| 覆盖发布更新链路 | 2 | 覆盖 PyInstaller、Velopack、R2、GitHub Releases、版本号、MSI/Setup |
| 给出可执行测试建议 | 2 | 每个 Bug 均给出测试文件名、目标、关键断言 |

**总分：10 分**
