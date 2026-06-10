# W-FONT-001 — 助手设置新增「字体设置」tab（横向弹幕 + 悬浮窗字体）

> **来源**：悬浮窗字体基础来自 W-FP-001 / W-FP-002 / W-FP-003（已完成的 `floating_panel_font_size`）。  
> **执行者**：Codex / Cursor Agent  
> **优先级**：中  
> **预计工时**：45–60 分钟

---

## 工单 ID

W-FONT-001

## 工单标题

助手设置新增独立「字体设置」tab，支持横向弹幕与悬浮窗字体名 / 加粗 / 字号可配置

## 背景

横向弹幕（`DanmuOverlay`）与悬浮窗（`FloatingPanel`）目前**硬编码**使用 `"Microsoft YaHei"` + `setBold(True)`，字号分别硬限位 `font_size` / `floating_panel_font_size` 两个 number 字段，且 `font_size` 字段还埋在「弹幕显示」tab 的「外观与行为」grid 里，与弹幕速度/不透明度挤在一起，违反「字体类设置应集中」的设计直觉。

按用户当前需求：
- 字体设置**单独成 tab**，不再塞回「弹幕显示」；
- 提供 7 个常用系统字体的**下拉 + 允许手输**（`<datalist>` 形式），不做字体文件上传；
- 同步打开「加粗」复选框，让用户可关掉硬编码 bold；
- 配置保存后**热更新**到 Overlay 与悬浮窗；运行中**正在上屏的弹幕**与悬浮窗**已飞入**的 item 也要用新字体重新渲染；
- 不改主链路「截图 → AI → 解析 → 入队 → 上屏」任何时序。

## 目标

完成后：

1. Web「助手设置」tab 栏新增「字体设置」tab（`data-settings-tab="font"`），与既有 6 个 tab 并列；
2. 「字体设置」panel 集中管理 6 项配置：
   - 横向弹幕字体：`danmu_font_family`
   - 横向弹幕加粗：`danmu_font_bold`
   - 横向弹幕字号：`font_size`（从「弹幕显示」tab **迁出**，避免重复）
   - 悬浮窗字体：`floating_panel_font_family`
   - 悬浮窗加粗：`floating_panel_font_bold`
   - 悬浮窗字号：`floating_panel_font_size`（仍在「悬浮窗模式」上下文，但通过「字体设置」tab 集中暴露）
3. `GET /api/config` 自动暴露上述 6 项；`PUT /api/config` 修改后无需重启，5 秒内**正在上屏**的 Overlay 弹幕与悬浮窗**已飞入**的 item 都按新字体重新渲染；
4. 「助手设置 → 字体设置 → 恢复默认」只恢复本 tab 的 6 项；
5. 后端对 6 项做归一化：字号钳位、加粗只允许 `"0"`/`"1"`、字体名为非空字符串（不强制白名单，允许手输系统字体）。

## 依赖项

- W-FP-001（`floating_panel_font_size` 等字段已存在并归一化）
- W-FP-003（`floating_panel.apply_config()` 主线程热更链路已就绪）
- `web/static/index.html` 当前 6 个 tab + 既有 font_size 字段
- `app/overlay.py` 的 `display_settings_dirty()` / `apply_display_settings()` 现有钩子

## 允许修改的区域

- `web/static/index.html`（tab 栏追加 1 个按钮 + 新增 1 个 panel；「弹幕显示」tab 移除原 `font_size` input 块）
- `web/static/modules/settings.js`（`CONFIG_FIELDS` / `SETTINGS_RESTORE_GROUPS` / `SETTINGS_RESTORE_CHECKBOXES` 各追加 `font` 分组；`collectFormData` 追加 2 个 checkbox 读；`fillForm` 追加 4 个 `setIfEmpty` + 2 个 checkbox 回填；`applyDefaultToField` checkbox 分支追加 2 个 key；`SETTINGS_FIELD_TIPS` 追加 6 条 help）
- `app/config_defaults.py`（`CONFIG_DEFAULTS` 追加 4 项：`danmu_font_family` / `danmu_font_bold` / `floating_panel_font_family` / `floating_panel_font_bold`）
- `app/application/config_service.py`（`WEB_CONFIG_KEYS` 追加 4 项；`_normalize_items` 追加 5 个归一化分支：`font_size` 钳位 12–72、`floating_panel_font_size` 钳位 12–48、`danmu_font_bold` / `floating_panel_font_bold` 归一为 0/1、字体名 trim 后非空）
- `app/overlay.py`（`_apply_font_from_config` 改用 `danmu_font_family` / `danmu_font_bold` / `font_size`；`_config_font_size` 名称**保留**不动以减少外部调用面；`display_settings_dirty` 增加 `danmu_font_family` / `danmu_font_bold` 两个 marker；`apply_display_settings` 流程不变 —— 其内层 `for item in tracks` 已重建 pixmap，**只要 `_apply_font_from_config` 被先调用即可生效**）
- `app/floating_panel.py`（`_apply_config` 改用 `floating_panel_font_family` / `floating_panel_font_bold` / `floating_panel_font_size`；`apply_config` 末尾追加 `_rebuild_active_pixmaps` 步骤，重建所有 `_active_items[i].pixmap`）
- `tests/test_config_defaults.py`（追加 `FONT_KEYS = (...)` 与 4 个用例：默认值存在、白名单存在、seed 写库、非法值回落）
- `tests/test_web_routes.py`（追加 3 个端到端用例：6 键 round-trip 持久化、`font_size=9999` 钳位 72、`danmu_font_bold="true"` 归一为 `"1"`）
- `tests/test_floating_panel.py`（追加 2 个 Qt 用例：font family 变化时 `apply_config` 重建 `_active_items` pixmap；font_size 钳位 12–48 边界）
- `tests/test_overlay_render.py`（追加 1 个 Qt 用例：`apply_display_settings` 在 family / bold 变化后正确重建 pixmap）
- `docs/工单列表/工单/W-FONT-001.md`（本文件）
- `docs/workflow/当前仓库状态.md`（追加最近变更）
- `docs/workflow/工单列表.md`（追加登记表行）
- `docs/WEB_CONSOLE.md`（追加「字体设置」tab + 4 个新字段说明）

## 禁止修改的区域

- `main.py`（主链路 `_consume_reply_queue` 不动；`_on_config_changed` 已有 `overlay.apply_display_settings()` / `panel.apply_config()` 钩子，**不需要再改**）
- `app/ai_client.py` / `app/danmu_engine.py` / `app/danmu_pool.py` / `app/live_freshness.py`
- `app/danmu_tts*.py` / `app/danmu_read_service.py`（读弹幕与字体无关）
- `app/mic_*.py`（麦克风与字体无关）
- `app/web_console.py` / `app/web_console_runtime.py`（既有 `PUT/GET /api/config` 透传，**不加**新路由）
- `app/web_api/*`（`ConfigService` 已收口所有写入面，不旁路）
- `scripts/boundary_guard.py` 与 `scripts/boundary_guard/constants.py`（不引入新 `QTimer` / 线程 / DanmuApp 字段，**不动**）
- `requirements.txt` / 锁文件
- `docs/main-pipeline-sequence.md` / `docs/runtime-state-map.md` / `docs/final-architecture-baseline.md`（不引入新线程 / 新 DanmuApp 字段 / 新 timer，**不动**）
- `app/translations.py`（本工单不引入新翻译键）
- `app/model_providers.py` / `app/model_catalog.py` / `app/model_selection.py`（与字体无关）

## 需求

1. **HTML tab 栏**（`web/static/index.html:357-370`）：在「弹幕显示」与「节奏与图像」之间插入新按钮，**不**插入到末尾以避免破坏 `initSettingsTabs` 默认激活逻辑；新按钮形态：
   ```html
   <button type="button" role="tab" class="settings-tab" data-settings-tab="font" aria-selected="false">字体设置</button>
   ```

2. **HTML 新 panel**：在「弹幕显示」panel（`id="settingsTab-danmu"`）之后插入新 panel，结构必须为：
   - `id="settingsTab-font"`
   - `class="settings-tab-panel space-y-6"`（**带** `hidden`，**不**带 `active` —— 沿用既有 6 个 panel 的 hidden-by-default 约定）
   - `data-settings-panel="font"`
   - `role="tabpanel"`
   - panel 内含 1 个 `<h3>`（与既有 panel 同款 SVG icon + 标题样式）、2 个 `settings-section`（**横向弹幕字体** / **悬浮窗字体**），每段 3 个 `settings-field` 块

3. **HTML 字段**（在 `#settingsTab-font` 内，6 个 `settings-field`）：
   - 横向弹幕字体（`danmu_font_family`）：`<input type="text" id="danmu_font_family" list="font-family-options" name="danmu_font_family" class="settings-field-control" placeholder="Microsoft YaHei">`
   - 横向弹幕加粗（`danmu_font_bold`）：`<input type="checkbox" id="danmu_font_bold" name="danmu_font_bold" class="settings-field-control">`（**注意**：与既有 `empty_accel` 一样，外层用 `settings-toggle-row`）
   - 横向弹幕字号（`font_size`）：`<input type="number" name="font_size" id="font_size" min="12" max="72" class="settings-field-control">`（**id/name 保持 `font_size` 不变**以兼容 `CONFIG_FIELDS` / 后端 key）
   - 悬浮窗字体（`floating_panel_font_family`）：同横向字体 pattern
   - 悬浮窗加粗（`floating_panel_font_bold`）：checkbox 同上
   - 悬浮窗字号（`floating_panel_font_size`）：`<input type="number" name="floating_panel_font_size" id="floating_panel_font_size" min="12" max="48" class="settings-field-control">`
   - panel 末尾追加一个**共享的** `<datalist id="font-family-options">`，含 7 个 `<option value="...">`：`Microsoft YaHei` / `SimHei` / `SimSun` / `KaiTi` / `DengXian` / `Arial` / `Segoe UI`（datalist 可放在 `</form>` 之前任意位置，本工单放在 `#settingsTab-font` 内部 `</div>` 之前）

4. **HTML 移除**（`web/static/index.html:578-581`）：从「弹幕显示」tab 的「外观与行为」grid 中**整块删除**以下 4 行：
   ```html
   <div class="settings-field">
     <label for="font_size" class="settings-field-label">字号 (px)</label>
     <input type="number" name="font_size" id="font_size" min="12" max="72" class="settings-field-control">
   </div>
   ```
   **不**调整 `cols-3` 布局（grid 自动 reflow）。`floating_panel_font_size` 输入框**不动**（它当前在「弹幕显示」tab 末尾，作为悬浮窗 6 字段之一；本工单允许其在两 tab 各出现一次是**禁止的**，故将其从「弹幕显示」tab 末尾**也迁出**到「字体设置」tab，**整块删除** `web/static/index.html:644-647` 处的对应 `settings-field`，避免重复 UI）。

5. **前端 JS — `CONFIG_FIELDS`**（`web/static/modules/settings.js:26-42`）：在 W-FP-003 注释之后追加 4 项（**不**含 2 个 checkbox）：
   ```js
   // W-FONT-001：字体设置（横向弹幕 + 悬浮窗）
   'danmu_font_family',
   'floating_panel_font_family',
   ```
   说明：`font_size` 与 `floating_panel_font_size` 已在 `CONFIG_FIELDS` 中，**只追加 2 个新增的 family 文本字段**，2 个加粗 checkbox **不**进入 `CONFIG_FIELDS`。

6. **前端 JS — `SETTINGS_RESTORE_GROUPS`**（`web/static/modules/settings.js:49-65`）：新增 `font` 分组：
   ```js
   font: [
     'danmu_font_family', 'floating_panel_font_family',
     'font_size', 'floating_panel_font_size',
   ],
   ```
   并**从 `danmu` 分组移除** `'font_size'`（避免「恢复默认」双计）。`floating_panel_font_size` **保留在 `danmu` 分组中**（避免破坏既有 W-FP-001 范围；本工单「字体设置」tab 恢复默认时通过 family 分组覆盖）。

7. **前端 JS — `SETTINGS_RESTORE_CHECKBOXES`**（`web/static/modules/settings.js:67-73`）：新增 `font` 分组：
   ```js
   font: ['danmu_font_bold', 'floating_panel_font_bold'],
   ```

8. **前端 JS — `collectFormData`**（`web/static/modules/settings.js:383-401`）：在 `data.floating_panel_click_through = ...` 之后追加 2 行：
   ```js
   data.danmu_font_bold = document.getElementById('danmu_font_bold')?.checked ? '1' : '0';
   data.floating_panel_font_bold = document.getElementById('floating_panel_font_bold')?.checked ? '1' : '0';
   ```
   **不**追加 `data.danmu_font_family` / `data.floating_panel_font_family`（已在 `CONFIG_FIELDS` 走 `el.value` 自动收）。

9. **前端 JS — `fillForm`**（`web/static/modules/settings.js:481-571`）：在 `setIfEmpty('floating_panel_font_size');` 之后追加 2 个 `setIfEmpty`；在 `floating_panel_click_through` 回填块之后追加 2 个 checkbox 回填块：
   ```js
   setIfEmpty('danmu_font_family');
   setIfEmpty('floating_panel_font_family');
   ```
   ```js
   const danmuBold = document.getElementById('danmu_font_bold');
   if (danmuBold) {
     const v = cfg.danmu_font_bold;
     if (v === '0' || v === 'false') danmuBold.checked = false;
     else if (v === '1' || v === 'true') danmuBold.checked = true;
     else danmuBold.checked = configDefaultValue('danmu_font_bold') !== '0';
   }
   const fpBold = document.getElementById('floating_panel_font_bold');
   if (fpBold) {
     const v = cfg.floating_panel_font_bold;
     if (v === '0' || v === 'false') fpBold.checked = false;
     else if (v === '1' || v === 'true') fpBold.checked = true;
     else fpBold.checked = configDefaultValue('floating_panel_font_bold') !== '0';
   }
   ```
   **删除** `setIfEmpty('font_size');` 之前的引用不需要改 —— 它会被 `CONFIG_FIELDS.forEach` 自动填回；仅保留 `setIfEmpty('font_size')` 作为「后端未返回时的兜底」即可（与既有保持一致）。

10. **前端 JS — `applyDefaultToField`**（`web/static/modules/settings.js:286-315`）：扩展 checkbox 分支：
    ```js
    if (key === 'mic_mode_enabled' || key === 'mic_use_visual_model' || key === 'empty_accel' || key === 'floating_panel_click_through' || key === 'danmu_font_bold' || key === 'floating_panel_font_bold') {
    ```
    font family 走 `el.value = value` 默认分支（无 enum 约束）。

11. **前端 JS — `SETTINGS_FIELD_TIPS`**（`web/static/modules/settings.js:1457-1481`）：追加 6 条 help：
    ```js
    danmu_font_family: '横向弹幕使用的系统字体名。留空或填入不存在的字体名时回退到默认。',
    danmu_font_bold: '是否加粗横向弹幕。',
    floating_panel_font_family: '悬浮窗使用的系统字体名。',
    floating_panel_font_bold: '是否加粗悬浮窗弹幕。',
    floating_panel_font_size: '悬浮窗弹幕字号，12–48 像素。',
    ```
    `font_size` 已有 help，不动。

12. **后端 — `CONFIG_DEFAULTS`**（`app/config_defaults.py:32`）：在 `font_size` 行附近追加 4 项（位置贴近既有 font 字段，便于阅读）：
    ```python
    "font_size": "24",
    "danmu_font_family": "Microsoft YaHei",
    "danmu_font_bold": "1",
    "floating_panel_font_family": "Microsoft YaHei",
    "floating_panel_font_bold": "1",
    ```
    （`floating_panel_font_size` 已在 W-FP-001 末段保持为 `"18"`，不重复。）

13. **后端 — `WEB_CONFIG_KEYS`**（`app/application/config_service.py:12-53`）：在 `floating_panel_click_through` 之后追加 4 项：
    ```python
    # W-FONT-001：字体设置
    "danmu_font_family",
    "danmu_font_bold",
    "floating_panel_font_family",
    "floating_panel_font_bold",
    ```
    `font_size` / `floating_panel_font_size` 已在既有位置。`RESTORABLE_CONFIG_KEYS = WEB_CONFIG_KEYS` 自动跟随。

14. **后端 — `_normalize_items`**（`app/application/config_service.py:176-275`）：在 W-FP-001 段（`floating_panel_click_through` 行）之后追加 5 个分支：
    ```python
    # W-FONT-001：字体名 / 加粗 / 字号归一化
    if "font_size" in items:
        _clamp_int_key(items, "font_size", 24, 12, 72)
    if "floating_panel_font_size" in items:
        _clamp_int_key(items, "floating_panel_font_size", 18, 12, 48)
    for _key in ("danmu_font_bold", "floating_panel_font_bold"):
        if _key in items:
            _v = str(items[_key]).strip().lower()
            items[_key] = "1" if _v in ("1", "true", "yes", "on") else "0"
    for _key in ("danmu_font_family", "floating_panel_font_family"):
        if _key in items:
            _v = str(items[_key]).strip()
            items[_key] = _v if _v else "Microsoft YaHei"
    ```

15. **`app/overlay.py` — `_apply_font_from_config`**（`app/overlay.py:150-154`）：改为读 3 个字段：
    ```python
    def _apply_font_from_config(self) -> None:
        from app.config_defaults import DEFAULT_FONT_SIZE
        family = str(self.config.get("danmu_font_family", "Microsoft YaHei") or "Microsoft YaHei").strip() or "Microsoft YaHei"
        size = max(12, min(72, self.config.get_int("font_size", DEFAULT_FONT_SIZE)))
        bold = str(self.config.get("danmu_font_bold", "1") or "1").strip().lower() not in ("0", "false", "no")
        self.font = QFont(family, size)
        self.font.setBold(bold)
        self.font_metrics = QFontMetrics(self.font)
    ```
    `_config_font_size`（line 113）**保留不动**（向后兼容 `display_settings_dirty` 内的调用）。

16. **`app/overlay.py` — `display_settings_dirty` + `_sync_applied_display_settings_markers`**（`app/overlay.py:119-129`）：增加 2 个 marker（family / bold），比较 3 项：
    ```python
    def _sync_applied_display_settings_markers(self) -> None:
        self._applied_font_size = self._config_font_size()
        self._applied_danmu_max_chars = resolve_danmu_max_chars(self.config)
        self._applied_danmu_font_family = str(self.config.get("danmu_font_family", "Microsoft YaHei") or "Microsoft YaHei")
        self._applied_danmu_font_bold = str(self.config.get("danmu_font_bold", "1") or "1").strip().lower() not in ("0", "false", "no")

    def display_settings_dirty(self) -> bool:
        if self._config_font_size() != getattr(self, "_applied_font_size", -1):
            return True
        if resolve_danmu_max_chars(self.config) != getattr(self, "_applied_danmu_max_chars", -1):
            return True
        current_family = str(self.config.get("danmu_font_family", "Microsoft YaHei") or "Microsoft YaHei")
        if current_family != getattr(self, "_applied_danmu_font_family", ""):
            return True
        current_bold = str(self.config.get("danmu_font_bold", "1") or "1").strip().lower() not in ("0", "false", "no")
        if current_bold != getattr(self, "_applied_danmu_font_bold", True):
            return True
        return False
    ```
    `apply_display_settings` **流程不变**（line 131-148 已先调 `_apply_font_from_config` 再遍历 tracks 重建 pixmap）。

17. **`app/floating_panel.py` — `_apply_config`**（`app/floating_panel.py:210-239`）：改 font 行为：
    ```python
    def _safe_str(key: str, default: str) -> str:
        raw = str(self.config.get(key, "") or "")
        raw = raw.strip()
        return raw or default

    self._font_size = max(12, min(48, _safe_int("floating_panel_font_size", 18)))
    self._opacity_pct = max(0, min(100, _safe_int("floating_panel_opacity", 85)))
    self._max_items = max(5, min(200, _safe_int("floating_panel_max_items", 60)))
    self._speed = max(0.5, min(5.0, _safe_float("floating_panel_speed", 1.5)))
    self._click_through = (
        str(self.config.get("floating_panel_click_through", "1") or "1").strip().lower()
        not in ("0", "false", "no")
    )
    family = _safe_str("floating_panel_font_family", "Microsoft YaHei")
    bold = str(self.config.get("floating_panel_font_bold", "1") or "1").strip().lower() not in ("0", "false", "no")
    self._font = QFont(family, self._font_size)
    self._font.setBold(bold)
    self._font_metrics = QFontMetrics(self._font)
    ```

18. **`app/floating_panel.py` — `apply_config` + 新增 `_rebuild_active_pixmaps`**（`app/floating_panel.py:189-199`）：末尾追加：
    ```python
    def apply_config(self) -> None:
        """热更新 6 项配置 + 字体 family/bold/size（主线程；W-FP-003 / W-FONT-001 调用）。"""
        previous_max = self._max_items
        previous_click_through = self._click_through
        self._apply_config()
        if self._max_items < previous_max and len(self._active_items) > self._max_items:
            del self._active_items[: len(self._active_items) - self._max_items]
        if self._click_through != previous_click_through:
            self._apply_win32_click_through()
        # W-FONT-001：字体变化后重建所有在飞 item 的 pixmap
        self._rebuild_active_pixmaps()
        if self.isVisible():
            self.update()

    def _rebuild_active_pixmaps(self) -> None:
        """字体 / 加粗 / 字号变更后，用新 QFont 重新渲染所有 _active_items.pixmap。"""
        if not self._active_items:
            return
        dpr = self.devicePixelRatio() or 1.0
        for item in self._active_items:
            text = item.content
            width = self._font_metrics.horizontalAdvance(text) + 10
            height = self._font_metrics.height() + 10
            item.pixmap = self._render_item_pixmap(text, width, height, dpr)
            item.height = height
    ```
    `feed` 路径**不动**（line 136 起）—— 新弹幕会自然用新 font。

19. **测试 — `tests/test_config_defaults.py`**：追加：
    ```python
    FONT_KEYS = (
        "danmu_font_family",
        "danmu_font_bold",
        "floating_panel_font_family",
        "floating_panel_font_bold",
    )

    def test_font_keys_present_in_defaults():
        for key in FONT_KEYS:
            assert key in CONFIG_DEFAULTS, f"missing default for {key}"
            assert CONFIG_DEFAULTS[key] != ""

    def test_font_keys_present_in_web_config_keys():
        from app.application.config_service import WEB_CONFIG_KEYS
        for key in FONT_KEYS:
            assert key in WEB_CONFIG_KEYS, f"missing web key for {key}"

    def test_seed_writes_font_defaults_on_blank_db(tmp_path):
        from app.config_store import ConfigStore
        store = ConfigStore(db_path=tmp_path / "config.db")
        for key in FONT_KEYS:
            store.set(key, "")
        seed_config_defaults(store)
        for key in FONT_KEYS:
            assert store.get(key) == CONFIG_DEFAULTS[key], key
        store.close()

    def test_font_size_clamps_to_72():
        from app.application.config_service import _clamp_int_key
        items = {"font_size": "9999"}
        _clamp_int_key(items, "font_size", 24, 12, 72)
        assert items["font_size"] == "72"
    ```

20. **测试 — `tests/test_web_routes.py`**：追加 3 个端到端用例（仿 W-FP-003 段 350-484 的 `_DanmuAppStub` 模式）：
    - `test_font_family_persists_via_config_service`：`apply_web_config_patch(app, {"danmu_font_family": "SimHei"})` 后 `store.get("danmu_font_family") == "SimHei"`；
    - `test_font_size_out_of_range_clamps_via_config_service`：`{"font_size": "9999"}` 后 `store.get("font_size") == "72"`；
    - `test_font_bold_truthy_strings_normalize_to_one`：`{"danmu_font_bold": "true"}` 后 `store.get("danmu_font_bold") == "1"`。

21. **测试 — `tests/test_floating_panel.py`**：追加 2 个 Qt 用例（需 `QApplication`，仿既有 `make_widget` fixture）：
    - `test_apply_config_rebuilds_active_pixmaps_on_font_change`：先 `feed("hello")` 让 `_active_items` 长度 ≥ 1，断言 `item.pixmap is not None`；改 config 中 `floating_panel_font_family = "SimHei"` + `floating_panel_font_size = "32"`；调 `panel.apply_config()`；断言 `item.pixmap` 已被替换（`is not` 旧对象，宽度变化）。
    - `test_floating_panel_font_size_clamped_to_48`：`{"floating_panel_font_size": "9999"}` 经 `apply_config` 后 `panel._font_size == 48`。

22. **测试 — `tests/test_overlay_render.py`**：追加 1 个 Qt 用例：
    - `test_apply_display_settings_detects_font_family_change`：构造 `DanmuApp` + Overlay，初始化后调 `_sync_applied_display_settings_markers()`；改 config `danmu_font_family = "SimHei"`；断言 `overlay.display_settings_dirty() is True`；调 `apply_display_settings()` 后再次断言 `False`。

23. **文档 — `docs/WEB_CONSOLE.md`**：在「助手设置」小节追加「字体设置」tab 描述，列出 6 字段与默认值；说明「恢复默认」只恢复本 tab 字段。

24. **文档 — `docs/workflow/当前仓库状态.md` / `docs/workflow/工单列表.md`**：按既有 §5 规则更新（追加最近变更 + 登记表新行）。

## 非目标

- 不实现字体文件 `.ttf` / `.otf` 上传功能（本工单仅支持系统字体名）；
- 不修改 `DanmuEngine` 任何字段或方法；
- 不修改主链路 `_consume_reply_queue` / `_on_screenshot_timer` / `_consume_reply_queue` 时序；
- 不引入新的 `QTimer` / 线程 / 异步通道 —— 字体热更走既有 `config_changed` → `_on_config_changed` → `apply_display_settings()` / `apply_config()`；
- 不落「字号持久化但 Overlay 不刷」的兼容态；保存后 5 秒内必须可见新字体；
- 不动 `floating_panel_font_size` 的 W-FP-001 既有位置（仍可被「弹幕显示」tab 末尾的悬浮窗字段块引用 —— **本工单禁止**：见需求 #4，将其从弹幕显示 tab 也迁出到字体设置 tab）；
- 不支持 macOS / Linux 字体（按 W-FP 既有约定仅 Windows 优先；非 Windows 平台字体名由 Qt 系统回退）；
- 不修改 `translations.py`（`字体设置` 4 个汉字不需要 i18n key）；
- 不修改 `app/personae.py` / `app/persona_contract.py`（系统提示词与字体无关）；
- 不为 `QFontDatabase` 加白名单（用户手输任何字符串，由 Qt 自行回退；需求 #14 已做空字符串兜底）。

## 验收标准

- [x] `python -m pytest tests/ -q` 全量绿（**958 passed, 5 skipped** + 本工单追加 9 用例全过）
- [x] `python scripts/boundary_guard.py` **PASS**（不引入新线程 / 字段 / timer）
- [ ] Web 控制台 → 助手设置 → 「字体设置」tab 可见，含 6 字段 + 1 个共享 datalist
- [ ] 「弹幕显示」tab 不再含「字号 (px)」字段（**已迁出**）
- [ ] `GET /api/config` 响应 JSON 包含 4 个新 key：`danmu_font_family` / `danmu_font_bold` / `floating_panel_font_family` / `floating_panel_font_bold`
- [ ] `PUT /api/config` 修改 `danmu_font_family` 后 5 秒内正在上屏的横向弹幕**像素**变化（建议改 `"KaiTi"` 对比）
- [ ] `PUT /api/config` 修改 `floating_panel_font_size` / `floating_panel_font_family` 后 5 秒内悬浮窗内**已飞入**的 item 重渲
- [x] `font_size=9999` 经后端落库后为 `"72"`
- [x] `danmu_font_bold="true"` 经后端落库后为 `"1"`
- [ ] 「恢复默认」按钮在「字体设置」tab 下只重置 6 字段，不影响其它 tab

## 手动验证步骤

1. `pip install -r requirements.txt`（如已装可跳）；
2. `python -m pytest tests/test_config_defaults.py tests/test_web_routes.py tests/test_floating_panel.py tests/test_overlay_render.py -q` → 全绿；
3. `python -m pytest tests/ -q` → 全绿；
4. `python scripts/boundary_guard.py` → PASS；
5. `python main.py` 启动；
6. Web 控制台 → 助手设置 → 看到 7 个 tab（含「字体设置」），点击「字体设置」；
7. 6 字段 + 7 个字体下拉候选可见；下拉选 `KaiTi`，手输栏亦可改；
8. 关闭「横向弹幕加粗」→ 保存 → 启动一次弹幕（手动发或等 AI）→ 5 秒内横向弹幕变**细体**；
9. 重选 `Microsoft YaHei` + 打开加粗 → 保存 → 5 秒内回到原状；
10. 改「悬浮窗字号」到 36 + 字体 `SimHei` → 保存 → 切换到「仅悬浮窗」模式 → 5 秒内悬浮窗**已飞入** item 用 `SimHei` 36px 渲染；
11. 「恢复默认」按钮在「字体设置」tab 内点击 → 6 字段全部回默认（family 回到 `Microsoft YaHei`、加粗回到 1、字号 24 / 18）；
12. 关闭 `python main.py` → 重启 → 6 字段保留上次值（持久化生效）；
13. DevTools Network 看 `GET /api/config/defaults` 响应含 4 个新 key。

## 风险点

- **`_rebuild_active_pixmaps` 的 QPixmap 重渲成本**：悬浮窗若有 60 条 in-flight item，font family 切换会触发 60 次 `_render_item_pixmap` —— 60 项 × ~3ms ≈ 180ms，**主线程可接受**；若未来发现掉帧，再考虑异步。
- **字体名不存在的回退**：Qt 对不存在的 family **不会**抛错，会回退到默认 sans 字体。`display_settings_dirty` 比较的是 `config.get("danmu_font_family")` 的字符串值，与实际生效字体解耦 —— 这是有意为之（避免每次 paint 都查 `QFontDatabase`），用户看到效果不对可改回推荐 7 项。
- **`font_size` HTML id 复用**：「弹幕显示」tab 删 `font_size` 后，`CONFIG_FIELDS` 中的 `font_size` 字符串仍指向「字体设置」tab 内的新 input —— 因 DOM 中 `id` 唯一，**不会**冲突。`floating_panel_font_size` 同理从「弹幕显示」tab 末段迁出。
- **`SETTINGS_RESTORE_GROUPS.danmu` 中保留 `floating_panel_font_size`**：用户「弹幕显示」tab 内的「恢复默认」仍会重置悬浮窗字号（与 W-FP-001 行为一致）；「字体设置」tab 内的「恢复默认」会通过 `font` 分组重置 family + 加粗 + 字号（含 `floating_panel_font_size`），**两边都重置** `floating_panel_font_size` —— 这是幂等的、最终值一致，可接受。
- **boundary_guard 不需改**：`DanmuApp.__init__` 不新增字段；`main.py` 不改；无新 `QTimer` / 线程 / asyncio；`runtime-state-map.md` / `main-pipeline-sequence.md` 不动。
- **`applyDefaultToField` checkbox 分支必须扩**：`danmu_font_bold` / `floating_panel_font_bold` 若不加入，单独点「恢复默认」会把 checkbox 还原成空字符串（DOM 默认 unchecked），与默认 `"1"` 不符 —— **本工单必须在需求 #10 处加**。

## 完成后必须更新的文档

- [x] [docs/workflow/当前仓库状态.md](../../workflow/当前仓库状态.md)
- [x] [docs/workflow/工单列表.md](../../workflow/工单列表.md)（追加 W-FONT-001 登记表行，状态「待办」/「已完成」由执行者维护）
- [x] [docs/WEB_CONSOLE.md](../../WEB_CONSOLE.md)（追加「字体设置」tab + 4 新字段说明）

## Codex 完成报告要求

- 使用 [Codex完成报告模板.md](../Codex完成报告/Codex完成报告模板.md)
- 必须列出**全部**修改文件路径（HTML / JS / Python / tests / docs 共约 12 个文件）
- 范围外问题写入 [docs/已知问题与后续事项.md](../../workflow/已知问题与后续事项.md)，不得顺手修复
- **强制**：完成报告 §3「未修改的关键区域」必须列出 `main.py` / `app/danmu_engine.py` / `app/ai_client.py` / `app/mic_*.py` / `app/web_console.py` / `app/web_console_runtime.py` 证明未越界
- **强制**：完成报告 §7 须说明 6 个核心边界用例的手动验证结果（字体名切换 / 加粗切换 / 字号 9999 钳位 / `true` 归一 / 「恢复默认」作用域 / 持久化重启）
