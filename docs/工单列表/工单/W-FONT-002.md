# W-FONT-002 — 助手设置「字体设置」tab 新增本地字体文件导入

> **来源**：W-FONT-001（前置：字体设置 tab + 4 个 config key + `QFont(family, ...)` 渲染钩子）  
> **执行者**：Codex / Cursor Agent  
> **优先级**：中  
> **预计工时**：60–90 分钟  
> **风格参考**：W-FP-002（新模块）、W-LIVE-TOPIC-001（Web 控件 + 助手函数）、`app/web_api/preview_compress.py`（唯一 multipart 路由样板）

---

## 工单 ID

W-FONT-002

## 工单标题

助手设置「字体设置」tab 新增本地 `.ttf` / `.otf` 字体文件导入（`POST /api/fonts/import` + `GET /api/fonts` + `DELETE /api/fonts/{sha256}`）

## 背景

W-FONT-001 已完成「系统字体名称选择」（`Microsoft YaHei` / `SimHei` 等 7 项 + 手输），但**未实现**用户上传自定义字体文件的能力。`app/overlay.py:178` 与 `app/floating_panel.py:257` 的 `QFont(family, size)` 完全依赖系统已安装字体集 —— 用户希望使用自己的字体（如开源中文字体、品牌字体）时**无路可走**。

按用户当前需求：
- 字体文件**不存原路径**，复制到 `%APPDATA%/DanmuAI/fonts/`，避免用户移动/删除原文件后失效；
- 落地文件名 = **`<sha256>.<ext>`**（用 sha256 作 id，原文件名仅在 `original_name` 元信息中保留），**不**用原文件名直接保存，以规避重名覆盖、路径穿越、特殊字符 3 类问题；
- 启动时一次性 `addApplicationFont` 全部已注册字体；导入通过 `QFontDatabase.addApplicationFont(...)` 读取**真实 family name**；
- 前端提供 `<input type="file" accept=".ttf,.otf">` + 「导入字体」按钮，导入成功后：
  1. 刷新字体 `<datalist>`，把新 family 追加进候选；
  2. 自动填入**当前聚焦**的字体输入框（`danmu_font_family` 或 `floating_panel_font_family`）；无焦点时默认填 `danmu_font_family`；
  3. 用户仍需点「保存配置」才**持久化**到 config.db（导入文件本身**立即**落盘，不需「保存」）；
- 字体文件**不上传**到任何外部服务（Supabase / 远端字体市场），仅本机 `QFontDatabase` 加载；
- 删除已导入字体走 `DELETE /api/fonts/{sha256}`：删文件 + 卸载字体 + 清 config.db 记录；
- 已落地的 4 个 W-FONT-001 config key（`danmu_font_family` / `danmu_font_bold` / `floating_panel_font_family` / `floating_panel_font_bold`）**不动**；用户选 family 名仍走 `danmu_font_family` / `floating_panel_font_family` 字符串 key。

## 目标

完成后：

1. Web「助手设置 → 字体设置」tab 末尾新增「导入本地字体」区，含文件选择 + 导入按钮 + 授权提醒 + 已导入列表（带删除按钮）；
2. `POST /api/fonts/import`（multipart/form-data）成功导入 1 个 `.ttf` / `.otf` 文件，落盘到 `%APPDATA%/DanmuAI/fonts/<sha256>.<ext>`，**立即**在当前会话内 `QFontDatabase.addApplicationFont` 加载，**立即**追加到 `<datalist id="font-family-options">`；
3. `GET /api/fonts` 返回 `{"families": [...], "imported": [{sha256, family, original_name, size, imported_at}, ...]}`，前端用于刷新 datalist + 渲染已导入列表；
4. `DELETE /api/fonts/{sha256}` 卸载字体、删文件、清元信息；
5. 启动时自动加载 `%APPDATA%/DanmuAI/fonts/` 全部 `.ttf` / `.otf` + 从 `config.db` `imported_fonts` key 读取元信息，**两边互为校验**（DB 记录但文件丢失 → 启动时清记录；文件存在但 DB 无记录 → 启动时补记录）；
6. 导入字体后选其 family → 保存配置 → 横向弹幕 / 悬浮窗在 5 秒内用新字体渲染（含**正在上屏**与**已飞入** item 重建 pixmap），无需重启；
7. **安全边界**：仅 `.ttf` / `.otf`、≤ 5 MB、sha256 命名杜绝路径穿越、`QFontDatabase` 错误显式 4xx 不影响主链路。

## 依赖项

- W-FONT-001（字体设置 tab + 4 个 family/bold config key + `overlay.apply_display_settings()` / `floating_panel.apply_config()` 既有热更钩子）
- `app/config_store.py:52` 的 `CONFIG_DIR` 范式（`Path(os.environ.get("APPDATA", ".")) / "DanmuAI"`）
- `app/web_console.py:166` 的 `bridge.invoke_on_main(...)` 主线程同步桥接
- `app/web_api/preview_compress.py:1-30` 的 multipart `UploadFile` 路由样板（**仓内唯一** multipart 路由）
- `app/web_api/routes.py:111-116` 的 `_invoke_main(fn, ...)` 写操作约定
- `tests/test_web_preview_compress.py:1-79` 的 `FastAPI` + `TestClient` + multipart 测试样板

## 允许修改的区域

- **新增** `app/font_registry.py`（字体注册表模块）
- **新增** `app/web_api/font_registry.py`（HTTP 路由模块）
- `app/web_api/routes.py`（**仅**在顶部追加 1 行 `from app.web_api import font_registry as font_registry_api` + `register_font_registry_routes(app, bridge, check_token)`，**不**改其它行）
- `main.py`（**仅** `__init__` 末尾、`attach_web_console(self)` 之后、`config_changed.connect(self._on_config_changed)` 之前插入 3 行：`self.font_registry = FontRegistry(self.config); self.font_registry.load_all(); log_startup("font_registry.loaded", count=N)`；**不**改 `__init__` 其它段、**不**改 `_on_config_changed`、**不**改主链路）
- `scripts/boundary_guard/constants.py`（`RUNTIME_FIELD_EXCLUDE` 追加 `"font_registry"` 一项，与 `"floating_panel"` 同处理，**不**改其它规则）
- `web/static/index.html`（**仅** `#settingsTab-font` panel 末尾追加 1 个 `settings-section` 「导入本地字体」，含 1 个文件 input、1 个按钮、1 段提示、1 个已导入列表容器 + 1 个 `<template id="fontRowTemplate">`；**不**改其它 tab、**不**改既有字段）
- `web/static/modules/settings.js`（**仅**追加 `uploadFontFile()` / `loadFontFamilies()` / `refreshFontDatalist()` 三个函数 + 在 `initSettingsTabs` 之后调用 `loadFontFamilies()` 一次 + 在 `applyDefaultToField` / `fillForm` / `collectFormData` 之外的位置实现，**不**改 `CONFIG_FIELDS` / `SETTINGS_RESTORE_GROUPS` / `SETTINGS_RESTORE_CHECKBOXES` —— 因 family 名是字符串、不需走恢复默认）
- `app/config_defaults.py`（**仅** `CONFIG_DEFAULTS` 末尾追加 `"imported_fonts": "[]"` 一项，提供空 JSON 列表默认；**不**改既有项）
- `tests/test_config_defaults.py`（追加 1 个用例：默认 `imported_fonts == "[]"`）
- `tests/test_font_registry.py`（**新增**，10 个用例覆盖：合法 / 非法扩展名 / 空文件 / 超大文件 / sha256 去重 / `load_all` 扫目录 / 元信息持久化往返 / 启动时 DB 与目录互校验 / `applicationFontFamilies` 解析 / 删除幂等）
- `tests/test_web_routes.py`（追加 5 个端到端用例：上传合法 .ttf 返回 family + 落盘 + 出现在 `GET /api/fonts`；非法扩展名 400；空文件 400；超大文件 400；上传后 PUT `danmu_font_family=<imported family>` 走既有 `apply_web_config_patch` 链路正常生效）
- `tests/test_floating_panel.py`（追加 1 个 Qt 用例：`imported_fonts` 列表注入后，`apply_config` 用 imported family 重建 `_active_items` pixmap）
- `tests/test_overlay_render.py`（追加 1 个 Qt 用例：同 family 注入后 `apply_display_settings` 重建 pixmap）
- `docs/工单列表/工单/W-FONT-002.md`（本文件）
- `docs/workflow/工单列表.md`（追加登记表行）
- `docs/WEB_CONSOLE.md`（追加「导入本地字体」UI + 3 个新路由说明）

## 禁止修改的区域

- `app/web_console.py`（既有 `WebConsoleBridge` 信号清单够用，**不**加新信号）
- `app/web_console_runtime.py`（既有 `app.mount("/static", ...)` 不动；**不** mount `FONTS_DIR` —— 字体仅进程内消费，不经 HTTP）
- `app/overlay.py` 与 `app/floating_panel.py`（W-FONT-001 已锁定；本工单**不**再改任何 Qt 渲染逻辑）
- `app/danmu_engine.py` / `app/ai_client.py` / `app/danmu_pool.py` / `app/mic_*.py` / `app/danmu_tts*.py`
- `app/personae.py` / `app/persona_contract.py`（与字体无关）
- `app/translations.py`（本工单不引入新翻译键）
- `app/model_providers.py` / `app/model_catalog.py` / `app/model_selection.py`
- `main.py` 的 `__init__` 其它段、`_on_config_changed`、`_consume_reply_queue`、`_on_screenshot_timer`（主链路）
- `requirements.txt` 与锁文件（`PyQt6` 已带 `QFontDatabase`；`python-multipart>=0.0.20` 已在 `requirements.txt:11`，FastAPI `UploadFile` 可直接用）
- `scripts/boundary_guard.py` 主文件（仅改 `constants.py` 的 `RUNTIME_FIELD_EXCLUDE`，**不**加新规则）
- `docs/main-pipeline-sequence.md` / `docs/runtime-state-map.md` / `docs/final-architecture-baseline.md`（不引入新线程 / 新 `DanmuApp` 核心字段 —— `font_registry` 仅是新增的**单例**资源管理字段，与 `floating_panel` / `overlay` 同级，无需动 runtime-state-map）
- `web/static/app.js`（设置 UI 全部在 `modules/settings.js`；本工单**不**改 `app.js`）
- `web/static/modules/content-pages.js`（与字体无关）
- `tests/conftest.py` / `tests/fakes.py`（既有 fixture 够用）

## 需求

### A. 新增 `app/font_registry.py`（核心模块）

1. **模块级常量**（**严格照搬** `app/config_store.py:52-54` 风格）：

   ```python
   from __future__ import annotations

   import hashlib
   import json
   import os
   from datetime import datetime, timezone
   from pathlib import Path
   from typing import Any

   # 与 app/config_store.py:52 风格完全一致
   FONTS_DIR = Path(os.environ.get("APPDATA", ".")) / "DanmuAI" / "fonts"
   ALLOWED_SUFFIXES: tuple[str, ...] = (".ttf", ".otf")
   MAX_FILE_BYTES: int = 5 * 1024 * 1024  # 5 MB
   CONFIG_KEY_IMPORTED = "imported_fonts"
   ```

2. **`safe_filename(sha256: str, suffix: str) -> str`** 内部辅助函数：返回 `f"{sha256}{suffix.lower()}"`，**不**接受任何用户输入字符串作为文件名前缀 —— 杜绝路径穿越。

3. **`class FontRegistry`**：

   ```python
   class FontRegistry:
       def __init__(self, config) -> None:
           self._config = config
           self._font_ids: dict[str, int] = {}  # sha256 -> QFontDatabase font id
           self._families: dict[str, str] = {}  # sha256 -> family name
           FONTS_DIR.mkdir(parents=True, exist_ok=True)

       def load_all(self) -> int:
           """启动时调用：扫 FONTS_DIR 全部 .ttf/.otf，addApplicationFont 并与 DB 互校验。返回已加载数量。"""
           ...

       def list_imported(self) -> list[dict[str, Any]]:
           """GET /api/fonts 用：返回 [{sha256, family, original_name, size, imported_at}, ...]"""
           ...

       def list_families(self) -> list[str]:
           """datalist 合并用：返回所有已加载 family 列表（去重）"""
           ...

       def import_bytes(self, data: bytes, original_name: str) -> dict[str, Any]:
           """POST /api/fonts/import 用：验扩展名/大小/sha256/写盘/addApplicationFont，返回 {sha256, family, original_name, size, imported_at}"""
           ...

       def delete(self, sha256: str) -> bool:
           """DELETE /api/fonts/{sha256} 用：removeApplicationFont + 删文件 + 删 DB 记录"""
           ...
   ```

4. **`import_bytes` 必须做的事**（**不可遗漏任一**）：
   - 校验 `len(data) > 0`，否则 `raise ValueError("empty_file")`；
   - 校验 `len(data) <= MAX_FILE_BYTES`，否则 `raise ValueError("file_too_large")`；
   - 校验后缀 `Path(original_name).suffix.lower() in ALLOWED_SUFFIXES`，否则 `raise ValueError("unsupported_extension")`；
   - `sha256 = hashlib.sha256(data).hexdigest()`；
   - 目标路径 `target = FONTS_DIR / safe_filename(sha256, Path(original_name).suffix.lower())`；
   - **若 `target.exists()`**（同 sha256 重复上传）：**幂等返回**已有记录，**不**覆盖写；
   - 否则 `target.write_bytes(data)`；
   - `from PyQt6.QtGui import QFontDatabase`；`font_id = QFontDatabase.addApplicationFont(str(target))`；负值表示失败 → `raise ValueError("qfont_load_failed")`；
   - `families = QFontDatabase.applicationFontFamilies(font_id)`；空列表 → `QFontDatabase.removeApplicationFont(font_id); target.unlink(missing_ok=True); raise ValueError("no_family_detected")`；
   - `family = families[0]`（取第一个；多 family 字体取主 family 是 Qt 标准做法）；
   - 写元信息到 DB：读 `config.get(CONFIG_KEY_IMPORTED, "[]")` → `json.loads` → 列表（已含同 sha256 跳过）→ 追加 `{sha256, family, original_name, size: len(data), imported_at: ISO8601}` → `config.set(CONFIG_KEY_IMPORTED, json.dumps(list, ensure_ascii=False))`；
   - 更新内存 `self._font_ids[sha256] = font_id` 与 `self._families[sha256] = family`；
   - 返回该字典。

5. **`load_all` 必须做的事**：
   - 读 `config.get(CONFIG_KEY_IMPORTED, "[]")` → `parsed = json.loads(...)`（解析失败 → 视为 `[]` 并 `config.set(..., "[]")` 修正）；
   - 扫 `FONTS_DIR.glob("*.ttf") | FONTS_DIR.glob("*.otf")`（**仅这两类**，忽略其它文件如 `.txt` / `.db`）；
   - 对每个文件：计算 sha256，查 `parsed` 是否有同 sha256 记录：
     - **有** → 用记录的 `original_name` + `family`（不再 `addApplicationFont` 二次加载，因 DB 记录的 family 可能与本次 Qt 解析不同 —— 但 Qt `addApplicationFont` 幂等，**仍**调一次覆盖内存映射），用 DB 记录的 family 写入内存；
     - **无**（孤儿文件）→ 调 `addApplicationFont` 拿 family + 写一条新元信息到 DB + 内存；
   - 对 DB 中**有记录但文件不存在**的 sha256：跳过（不抛错），下次 `delete` 会自动清；不主动删 DB 记录（保留「已删但 DB 未清」状态供调试日志）；
   - 写回 DB（孤儿补录后）；
   - 返回 `len(self._font_ids)`。

6. **`delete(sha256)` 必须做的事**：
   - 内存 `font_id = self._font_ids.pop(sha256, None)`；若有 → `QFontDatabase.removeApplicationFont(font_id)`；
   - 从 `FONTS_DIR` 找以 `sha256` 开头的文件（`.ttf` / `.otf`），`Path.unlink(missing_ok=True)`；
   - 读 `config.get(CONFIG_KEY_IMPORTED, "[]")` → 过滤掉同 sha256 → 写回；
   - `self._families.pop(sha256, None)`；
   - 返回 `True`（存在并删除）/ `False`（sha256 不存在）。

7. **`list_families` 必须做的事**：
   - 返回 `sorted(set(self._families.values()))`（**不**包含 W-FONT-001 的 7 项系统字体 —— 那是前端硬编码 + datalist 默认；该函数**只**返回用户导入的 family）。

### B. 新增 `app/web_api/font_registry.py`（HTTP 路由）

8. **模块级注册函数**（照搬 `app/web_api/preview_compress.py:1-30` 模式）：

   ```python
   """字体文件导入 / 列表 / 删除路由：POST /api/fonts/import + GET /api/fonts + DELETE /api/fonts/{sha256}。"""
   from __future__ import annotations

   from fastapi import APIRouter, File, Header, HTTPException, Path, UploadFile
   from app.font_registry import FontRegistry

   router = APIRouter()

   def register_font_registry_routes(app, bridge, check_token) -> None:
       @router.post("/api/fonts/import")
       async def fonts_import(
           file: UploadFile = File(...),
           authorization: str | None = Header(default=None),
       ):
           check_token(authorization)
           data = await file.read()
           try:
               record = bridge.invoke_on_main(
                   bridge.danmu_app.font_registry.import_bytes,
                   data,
                   file.filename or "uploaded.ttf",
               )
           except ValueError as exc:
               raise HTTPException(status_code=400, detail=str(exc)) from exc
           return {"ok": True, **record, "families": bridge.danmu_app.font_registry.list_families()}

       @router.get("/api/fonts")
       def fonts_list(authorization: str | None = Header(default=None)):
           check_token(authorization)
           return {
               "families": bridge.danmu_app.font_registry.list_families(),
               "imported": bridge.danmu_app.font_registry.list_imported(),
           }

       @router.delete("/api/fonts/{sha256}")
       def fonts_delete(
           sha256: str = Path(..., pattern=r"^[0-9a-f]{64}$"),
           authorization: str | None = Header(default=None),
       ):
           check_token(authorization)
           ok = bridge.invoke_on_main(bridge.danmu_app.font_registry.delete, sha256)
           if not ok:
               raise HTTPException(status_code=404, detail="font_not_found")
           return {"ok": True, "families": bridge.danmu_app.font_registry.list_families()}

       app.include_router(router)
   ```

   说明：
   - `delete` 用 FastAPI `Path(..., pattern=r"^[0-9a-f]{64}$")` 限定 sha256 形态，**不**接任意字符串；
   - `import_bytes` 是**写操作**，**必须**经 `bridge.invoke_on_main`（`QFontDatabase.addApplicationFont` 须在主线程）；
   - `list_families` / `list_imported` 读 `bridge.danmu_app.font_registry` 公开属性，**不**经过 `_…` 私有字段；
   - **不**使用 `@app.post` 装饰器嵌在 `register_font_registry_routes` 内部 —— 仿 `preview_compress.py` 用模块级 `APIRouter()` + `app.include_router` 避免 Python 3.14 + Pydantic v2 路由解析坑。

9. **`app/web_api/routes.py:29` 注册**（**仅**追加 2 行）：

   ```python
   from app.web_api import font_registry as font_registry_api  # W-FONT-002
   ```

   并在 `register_web_routes` 函数体**末尾**追加 1 行：

   ```python
   def register_web_routes(app, bridge, check_token):
       register_preview_compress_route(app, check_token)
       # ... 既有调用 ...
       font_registry_api.register_font_registry_routes(app, bridge, check_token)  # W-FONT-002
   ```

   **不**改 `routes.py` 任何其它行。

### C. `main.py` 启动 hook

10. **`main.py` 插入位置**（**仅** `attach_web_console(self)` 之后、`config_changed.connect(...)` 之前）：

    ```python
    # W-FONT-002：启动时加载已导入字体
    from app.font_registry import FontRegistry
    font_registry_started = time.perf_counter()
    self.font_registry = FontRegistry(self.config)
    loaded_count = self.font_registry.load_all()
    log_startup("font_registry.loaded", count=loaded_count, ms=(time.perf_counter() - font_registry_started) * 1000.0)
    ```

    **不**改 `__init__` 其它段；**不**改 `_on_config_changed`（既有 `overlay.apply_display_settings()` / `floating_panel.apply_config()` 钩子已就绪，导入字体的 family 选择仍走 `danmu_font_family` 字符串经 `config_changed` 自动热更，**不**需要新钩子）。

### D. boundary_guard 白名单

11. **`scripts/boundary_guard/constants.py`** 的 `RUNTIME_FIELD_EXCLUDE` 列表（**仅**追加 1 行）：

    ```python
    "font_registry",  # W-FONT-002
    ```

    位置紧跟 `"floating_panel"` 之后。**不**改 `constants.py` 其它规则。

### E. 前端 HTML（仅追加，**不**改既有字段）

12. **在 `#settingsTab-font` panel 末尾**追加 1 个 `settings-section`（位置在 `</div>` 闭合 panel 前）：

    ```html
    <div class="settings-section space-y-3">
      <p class="settings-section-title">导入本地字体</p>
      <p class="settings-section-hint">
        支持 .ttf / .otf 格式，单文件最大 5MB。
        <br>请确认字体授权允许个人使用；DanmuAI 只在本机加载字体，不会上传到外部服务。
      </p>
      <div class="settings-params-grid cols-2">
        <div class="settings-field">
          <label for="font_file_input" class="settings-field-label">选择字体文件</label>
          <input type="file" id="font_file_input" accept=".ttf,.otf" class="settings-field-control">
        </div>
        <div class="settings-field" style="align-self: end;">
          <button type="button" id="btnImportFont" class="settings-action-btn">导入字体</button>
        </div>
      </div>
      <div id="importedFontsList" class="settings-imported-fonts-list"></div>
      <template id="fontRowTemplate">
        <div class="settings-imported-font-row">
          <span class="font-family"></span>
          <span class="font-meta"></span>
          <button type="button" class="settings-action-btn-sm btn-delete-font">删除</button>
        </div>
      </template>
    </div>
    ```

    **不**改既有 6 字段（4 family/bold + 2 字号）；**不**改 datalist；**不**新建 panel；**不**新建 tab。

### F. 前端 JS（仅追加函数 + 1 次初始化调用）

13. **`web/static/modules/settings.js` 末尾**追加 3 个函数 + 1 个初始化调用：

    ```js
    // W-FONT-002：本地字体文件导入
    export async function uploadFontFile() {
      const input = document.getElementById('font_file_input');
      const file = input?.files?.[0];
      if (!file) {
        showToast('请先选择一个 .ttf 或 .otf 文件', true);
        return;
      }
      const form = new FormData();
      form.append('file', file, file.name);
      try {
        const res = await fetch('/api/fonts/import', {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + (window.__danmu_token || '') },
          body: form,
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || ('HTTP ' + res.status));
        }
        const data = await res.json();
        showToast('已导入字体：' + data.family, false);
        await loadFontFamilies();
        // 自动填入当前聚焦的字体输入框；无焦点时填 danmu_font_family
        const focused = document.activeElement;
        if (focused && (focused.id === 'danmu_font_family' || focused.id === 'floating_panel_font_family')) {
          focused.value = data.family;
        } else {
          const danmu = document.getElementById('danmu_font_family');
          if (danmu) danmu.value = data.family;
        }
        input.value = '';
      } catch (exc) {
        showToast('导入失败：' + (exc.message || exc), true);
      }
    }

    export async function loadFontFamilies() {
      try {
        const res = await fetch('/api/fonts', {
          headers: { 'Authorization': 'Bearer ' + (window.__danmu_token || '') },
        });
        if (!res.ok) return;
        const data = await res.json();
        refreshFontDatalist(data.families || []);
        renderImportedFontsList(data.imported || []);
      } catch (exc) {
        console.warn('loadFontFamilies failed:', exc);
      }
    }

    function refreshFontDatalist(families) {
      const datalist = document.getElementById('font-family-options');
      if (!datalist) return;
      // 保留 7 项 W-FONT-001 内置系统字体；追加 imported families（去重）
      const builtin = ['Microsoft YaHei', 'SimHei', 'SimSun', 'KaiTi', 'DengXian', 'Arial', 'Segoe UI'];
      const merged = Array.from(new Set([...builtin, ...families]));
      datalist.innerHTML = merged.map((f) => `<option value="${f.replace(/"/g, '&quot;')}"></option>`).join('');
    }

    function renderImportedFontsList(imported) {
      const list = document.getElementById('importedFontsList');
      const tmpl = document.getElementById('fontRowTemplate');
      if (!list || !tmpl) return;
      list.innerHTML = '';
      imported.forEach((item) => {
        const node = tmpl.content.firstElementChild.cloneNode(true);
        node.querySelector('.font-family').textContent = item.family;
        node.querySelector('.font-meta').textContent =
          `（${item.original_name} · ${(item.size / 1024).toFixed(1)} KB）`;
        node.querySelector('.btn-delete-font').addEventListener('click', async () => {
          if (!confirm('确认删除已导入字体「' + item.family + '」？此操作不可撤销。')) return;
          try {
            const res = await fetch('/api/fonts/' + item.sha256, {
              method: 'DELETE',
              headers: { 'Authorization': 'Bearer ' + (window.__danmu_token || '') },
            });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            showToast('已删除字体：' + item.family, false);
            await loadFontFamilies();
          } catch (exc) {
            showToast('删除失败：' + (exc.message || exc), true);
          }
        });
        list.appendChild(node);
      });
    }
    ```

    并在 `initSettingsTabs` 之后**追加 1 行**初始化调用（位置紧跟现有 `initSettingsTabs(); initSettingsUiMode();` 等之后）：

    ```js
    loadFontFamilies();  // W-FONT-002：刷新字体 datalist + 渲染已导入列表
    ```

    并在 `initRestoreDefaultsControls` 之类的位置追加**事件绑定**：

    ```js
    document.getElementById('btnImportFont')?.addEventListener('click', uploadFontFile);
    ```

    **不**改 `CONFIG_FIELDS` / `SETTINGS_RESTORE_GROUPS` / `SETTINGS_RESTORE_CHECKBOXES` —— family 名是普通字符串，恢复默认走既有 `font` 分组即可。

14. **token 来源**：`window.__danmu_token` 在既有 W-FP-003 之类的实现中已设置（自查 `web/static/app.js` 的 `__danmu_token` 注入位置）；若既有代码用其它变量名（如 `window.danmuToken`），**复用**之，**不**新增。

### G. `app/config_defaults.py`

15. **追加 1 项默认**（`CONFIG_DEFAULTS` 末尾，与既有 W-FP / W-FONT 字段风格一致）：

    ```python
    "imported_fonts": "[]",  # W-FONT-002：[{sha256, family, original_name, size, imported_at}, ...]
    ```

    **不**改既有项。

### H. 测试

16. **`tests/test_config_defaults.py`** 追加 1 个用例：

    ```python
    def test_imported_fonts_default_is_empty_list():
        from app.config_defaults import CONFIG_DEFAULTS
        import json
        assert CONFIG_DEFAULTS["imported_fonts"] == "[]"
        assert json.loads(CONFIG_DEFAULTS["imported_fonts"]) == []
    ```

17. **`tests/test_font_registry.py`（新增）** 至少 10 个用例：

    - `test_import_bytes_writes_to_fonts_dir`：用 `workspace_tmp` fixture + 真实 .ttf（建议 `importlib.resources` 读仓库内 `tests/fixtures/sample.ttf` 或 `from fontTools.ttLib import TTFont` 构造最小 ttf 字节）→ 调 `import_bytes` → 断言 `FONTS_DIR` 下出现 `sha256` 命名的文件；
    - `test_import_bytes_rejects_empty_file`：`data = b""` → 期望 `ValueError("empty_file")`；
    - `test_import_bytes_rejects_unsupported_extension`：`data = b"abc"; original_name = "foo.zip"` → 期望 `ValueError("unsupported_extension")`；
    - `test_import_bytes_rejects_oversized_file`：`data = b"\\x00" * (5 * 1024 * 1024 + 1)` → 期望 `ValueError("file_too_large")`；
    - `test_import_bytes_returns_real_family`：构造最小有效 ttf → 返回字典含 `family` 字段且非空；
    - `test_import_bytes_dedup_by_sha256`：连续 2 次 import 同一字节 → 第 2 次幂等返回，文件不被覆盖，DB 列表长度仍为 1；
    - `test_load_all_scans_fonts_dir_and_reconciles_db`：构造「DB 有但文件丢失」+「文件存在但 DB 无」2 种状态 → 启动 `load_all` → DB 自洽，孤儿文件被补录；
    - `test_delete_removes_file_and_unregisters`：import 一次 → delete → 断言文件 `not exists()`、DB 列表为空、`_font_ids` 不含该 sha256；
    - `test_delete_nonexistent_returns_false`：delete 不存在的 sha256 → 返回 `False`；
    - `test_list_families_dedup`：`import_bytes` 同一 family 多个文件 → `list_families()` 去重。

18. **`tests/test_web_routes.py`** 追加 5 个端到端用例（**新增强桩**：

    ```python
    class _DanmuAppStubWithFonts:
        def __init__(self):
            from app.font_registry import FontRegistry
            self.config = ConfigStore(...)
            self.font_registry = FontRegistry(self.config)
        # ...其它与既有 _DanmuAppStub 一致...
    ```

    ）：
    - `test_post_fonts_import_with_valid_ttf_returns_family`：`TestClient.post("/api/fonts/import", files={"file": ("my.ttf", ttf_bytes, "application/octet-stream")}, headers=...)` → 200 + body 含 `family` + `GET /api/fonts` 返回含该 family；
    - `test_post_fonts_import_rejects_unsupported_extension`：`.zip` 文件 → 400；
    - `test_post_fonts_import_rejects_empty_file`：空字节 → 400；
    - `test_post_fonts_import_rejects_oversized_file`：5 MB + 1 字节 → 400；
    - `test_delete_font_removes_from_list`：`POST /api/fonts/import` → 拿 sha256 → `DELETE /api/fonts/<sha256>` → `GET /api/fonts` 不再含该 family。

19. **`tests/test_floating_panel.py`** 追加 1 个 Qt 用例：
    - `test_apply_config_uses_imported_font_family`：手动设 `self.floating_panel._active_items` 1 个 item → 改 `config.set("floating_panel_font_family", "<imported family>")` → 调 `apply_config()` → 断言 `panel._font.family() == "<imported family>"`（用 `QFont.family()` 取实际 Qt family 名）。

20. **`tests/test_overlay_render.py`** 追加 1 个 Qt 用例：
    - `test_apply_display_settings_uses_imported_font_family`：改 `config.set("danmu_font_family", "<imported family>")` → 调 `apply_display_settings()` → 断言 `overlay.font.family() == "<imported family>"`。

### I. 文档

21. **`docs/WEB_CONSOLE.md`** 追加：
    - 「字体设置」tab 末段补充：导入本地字体区（4 项元素：文件 input、导入按钮、提示、列表）；
    - 路由清单追加 3 个：`POST /api/fonts/import` / `GET /api/fonts` / `DELETE /api/fonts/{sha256}`，含 request/response 示例与 4xx 错误码。

22. **`docs/workflow/工单列表.md`** 追加 1 行（**W-FONT-001 行之后**）：

    ```
    | W-FONT-002 | 助手设置「字体设置」tab 新增本地 .ttf / .otf 字体文件导入 | 待办 | app/font_registry.py（新增）、app/web_api/font_registry.py（新增）、main.py（启动 hook）、web/static/index.html、web/static/modules/settings.js、tests、docs | — | 见 [工单/W-FONT-002.md](工单/W-FONT-002.md) |
    ```

    并把顶部 `**最后更新**` 改为 `2026-06-06（W-FONT-002 已登记；W-FONT-001 已完成；W-CI-LINT-001 待办）`。

## 非目标

- 不实现字体**预览**（Web 端用 `font-family` CSS 渲染示例文字）—— 范围过大、属于 W-FONT-003 候选；
- 不实现**批量**上传（一次 1 个文件）；
- 不实现**云端**字体市场或 Supabase 同步；
- 不修改 `app/overlay.py` / `app/floating_panel.py` 的 `QFont(family, ...)` 解析（W-FONT-001 已锁定）—— 用户在 `danmu_font_family` 输入 imported family 名即可生效；
- 不修改主链路 `_consume_reply_queue` / `_on_screenshot_timer` / `_on_config_changed`（既有 W-FONT-001 钩子已能 hot reload family 名选择）；
- 不实现**字体子集化**（subset）、**字符回退**（fallback chain）—— Qt 自行处理；
- 不实现**字体版权校验**（用户自负其责，仅在 UI 文案提醒「请确认字体授权允许个人使用」）；
- 不实现 `ttc`（TrueType Collection，多字体包）支持 —— 需求 #1 限定 `.ttf` / `.otf`；
- 不实现 `QFontDatabase.removeApplicationFont` 的**全应用范围**清空（仅清本工单注册的 id）；
- 不实现 macOS / Linux 字体加载路径（`%APPDATA%` 在非 Windows 平台回退 `~/DanmuAI/fonts`，与 `config_store.py:52` 一致；字体可用性取决于系统是否安装对应 Qt 平台插件）；
- 不修改 `app/translations.py`（错误信息中英混用：英文 key 在 API、文案中文在 UI —— 与 W-FONT-001 既有错误提示风格一致）；
- 不在 `docs/main-pipeline-sequence.md` / `docs/runtime-state-map.md` / `docs/final-architecture-baseline.md` 增项（不引入新线程 / 新 Qt 主线程外行为）；
- 不持久化 `original_path`（用户原始路径永不上 DanmuAI 磁盘；用户挪动原文件不影响已导入字体 —— 这是用 `%APPDATA%/DanmuAI/fonts/` 复制的设计目标）。

## 验收标准

- [x] `python -m pytest tests/ -q` 本工单相关用例全绿（全量 989 passed；3 例 `test_lifetime_stats` 失败为范围外）
- [x] `python scripts/boundary_guard.py` **PASS**（`RUNTIME_FIELD_EXCLUDE` 已加 `"font_registry"`）
- [ ] Web 控制台 → 助手设置 → 「字体设置」tab → 「导入本地字体」区可见 4 元素
- [ ] 上传一个真实的 `.ttf` 文件（≤ 5 MB）→ toast「已导入字体：xxx」→ 5 秒内该 family 出现在 `font-family-options` datalist
- [ ] 上传后焦点在 `danmu_font_family` 输入框 → 自动填入新 family；焦点在 `floating_panel_font_family` → 同样自动填入
- [ ] 上传后 `GET /api/fonts` 返回 `imported` 含新记录（含 `sha256` / `family` / `original_name` / `size` / `imported_at`）
- [ ] 上传一个 `.zip` / `.txt` → 400 + 错误信息「unsupported_extension」类提示
- [ ] 上传 0 字节文件 → 400
- [ ] 上传 > 5 MB 文件 → 400
- [ ] 把 `danmu_font_family` 改为 imported family → 保存 → 5 秒内横向弹幕用新字体上屏（手动对比像素）
- [ ] 把 `floating_panel_font_family` 改为 imported family → 保存 → 5 秒内悬浮窗已飞入 item 用新字体
- [ ] 在 Web 列表点「删除」→ confirm 后 → 字体从 datalist 消失，文件从 `%APPDATA%/DanmuAI/fonts/` 消失
- [ ] 关闭 `python main.py` → 重启 → `imported_fonts` 自动从 DB 恢复 + 文件自动重新 `addApplicationFont`
- [ ] 删除 `%APPDATA%/DanmuAI/fonts/` 中一个文件后启动 → DB 中对应 sha256 仍保留记录（**不**主动清，方便调试；下次 `delete` 调用时清）
- [ ] 在 `%APPDATA%/DanmuAI/fonts/` 放一个 `.ttf` 但 DB 无记录 → 启动时自动补录元信息
- [ ] `QFont(family, size)` 在 imported family 不存在时仍走既有 `_safe_str(... or "Microsoft YaHei")` 兜底

## 手动验证步骤

1. `pip install -r requirements.txt`（如已装可跳；确保 `python-multipart` 与 `PyQt6` 已就位）；
2. `python -m pytest tests/test_config_defaults.py tests/test_font_registry.py tests/test_web_routes.py tests/test_floating_panel.py tests/test_overlay_render.py -q` → 全绿；
3. `python -m pytest tests/ -q` → 全绿（基线 958 + 本工单 ≥ 18 = ≥ 976 passed）；
4. `python scripts/boundary_guard.py` → **PASS**；
5. `python main.py` 启动 → Web 控制台 → 助手设置 → 「字体设置」tab 滚到底部看到「导入本地字体」区；
6. 准备一个真实的开源 .ttf 文件（如 `C:/Windows/Fonts/simhei.ttf` 复制到桌面），点击「选择字体文件」→ 选该 ttf → 点「导入字体」；
7. 1 秒内 toast「已导入字体：XXX」+ datalist 出现新 family + 已导入列表出现一行；
8. 焦点在 `横向弹幕字体` 输入框 → 应自动填入新 family；切焦点到「悬浮窗字体」再导入一次 → 同样自动填入；
9. 点击「保存配置」→ 5 秒内上屏的横向弹幕（手动发一条或等 AI）字体变化；悬浮窗模式亦同；
10. 切到「仅悬浮窗」模式 → 已飞入 item 字体已变；
11. 在已导入列表点「删除」→ confirm → 字体从 datalist 与列表消失；
12. 在 `C:/Windows/Fonts/msyh.ttc`（.ttc，**不在白名单**）试导入 → 400 + 中文错误「暂不支持该格式，请使用 .ttf / .otf」；
13. 选 0 字节文件 → 400 + 提示「文件为空」；
14. 关闭 `python main.py` → 检查 `%APPDATA%/DanmuAI/fonts/` 有 1 个 `<sha256>.ttf` 文件；
15. 重启 `python main.py` → 启动日志 `font_registry.loaded count=1` → `GET /api/fonts` 返回 1 条 imported；
16. DevTools Network 看 `POST /api/fonts/import` 请求：`Content-Type: multipart/form-data; boundary=...`，`Authorization: Bearer ...`，response 200 + `{"ok": true, "sha256": "abc...", "family": "...", "original_name": "...", "size": 12345, "imported_at": "2026-06-06T...", "families": [...]}`。

## 风险点

- **`addApplicationFont` 在主线程**：必须**所有**调用经 `bridge.invoke_on_main`；HTTP 线程**严禁**直接调 `QFontDatabase`（Qt 跨线程未保证安全）。W-FP-003 已示范该模式，本工单照搬。
- **`write_bytes` 失败时的一致性**：若 `target.write_bytes(data)` 成功但 `QFontDatabase.addApplicationFont` 失败，文件已落盘但字体未注册。`import_bytes` 内**先** `addApplicationFont`，**再**写盘？不可行（`addApplicationFont` 需要文件路径）。**正确做法**：先 `target.write_bytes(data)`，**再** `addApplicationFont`；若后者失败 → `target.unlink(missing_ok=True)` + `raise`，**不留垃圾**。
- **sha256 重复上传的幂等性**：若同字节再次上传，**不**重新 `addApplicationFont`（避免 Qt id 泄漏），直接复用内存 `self._font_ids[sha256]`。需求 #4 明确「target.exists() 幂等返回」。
- **`%APPDATA%` 不可写**：极少见（如权限问题），`FONTS_DIR.mkdir(parents=True, exist_ok=True)` 抛 `PermissionError` → 在 `FontRegistry.__init__` 用 try/except 包装，记录日志 `font_registry.init_failed` 并 `self._disabled = True`；`import_bytes` / `list_families` 全部返回空 + 抛 `ValueError("font_registry_disabled")`，HTTP 路由转 503。这样**不**让字体目录失败把整个 app 启动拖崩。
- **DB 解析失败**：`load_all` 中 `json.loads(...)` 失败 → 视为 `[]` + 立即 `config.set("imported_fonts", "[]")` 修正。**不**抛错。
- **`Path.unlink(missing_ok=True)`**：Windows 上文件被 Qt `QFontDatabase` 句柄持有时 unlink 抛 `PermissionError`。**解决**：先 `removeApplicationFont(font_id)`（释放句柄）**再** unlink。需求 #6 严格按此序。
- **路径穿越**：`safe_filename(sha256, suffix)` 仅接受 sha256（64 hex）+ 后缀（`.ttf`/`.otf`），**绝不**接受用户输入字符串作前缀。`delete` 的 `Path(..., pattern=r"^[0-9a-f]{64}$")` 限定入参形态（FastAPI 自动 422）。**双保险**。
- **超大多字体文件**：即使 ≤ 5 MB，`QFontDatabase.addApplicationFont` 仍可能 OOM（极少见）→ 用 try/except 兜底，删文件 + `raise ValueError("qfont_load_failed")`。
- **`window.__danmu_token` 名称**：需求 #13 用 `window.__danmu_token`，执行者**必须**先 grep `web/static/app.js` 确认既有 token 注入变量名，**复用**之。若没有此变量，则本工单须**新增** 1 行注入（在 `app.js` 既有 token 发送处），这等同于修改 `app.js`，属**禁止区**——故遇到此情况应在完成报告 §8 写入已知问题并停手。
- **`renderImportedFontsList` 在「恢复默认」后被覆盖**：`applySettingsDefaults('all')` 不动 `importedFontsList`（DOM 元素非字段），但**前端**仍应保留已导入字体——本工单**不**改 `applySettingsDefaults`；导入的字体**与** `danmu_font_family` 字符串**解耦**，恢复默认不删文件。
- **boundary_guard 新规则**：本工单**不**引入新规则（`RUNTIME_FIELD_EXCLUDE` 仅追加 1 项），故 `scripts/boundary_guard.py` 主文件**不动**；`constants.py` 改动**不**触发 `web_rules` / `request_rules` 之类新扫描。
- **测试中构造真实 .ttf**：`tests/font_registry.py` 需用 `fontTools` 或自带 `Lib/site-packages` 下 .ttf；项目**已有** `fontTools` 依赖（`requirements.txt` 中 `Pillow` / `fonttools`），若无则改用 `Lib/site-packages/PIL` 周边 .ttf（**严禁**从网络下载）。

## 完成后必须更新的文档

- [ ] [docs/workflow/工单列表.md](../../workflow/工单列表.md)（追加 W-FONT-002 登记表行；顶部「最后更新」日期刷新）
- [ ] [docs/WEB_CONSOLE.md](../../WEB_CONSOLE.md)（追加「导入本地字体」UI 描述 + 3 路由说明）
- [ ] [docs/工单列表/工单/W-FONT-002-完成报告.md](../../工单列表/工单/W-FONT-002-完成报告.md)（按 `Codex完成报告模板.md` 10 节结构；**强制** §3 列出未越界关键区域）

## Codex 完成报告要求

- 使用 [Codex完成报告模板.md](../Codex完成报告/Codex完成报告模板.md)（10 节）
- 必须列出**全部**修改文件路径（**新增** 3 个：`app/font_registry.py` / `app/web_api/font_registry.py` / `tests/test_font_registry.py`；**修改** ≈ 10 个：main.py / routes.py / constants.py / config_defaults.py / index.html / settings.js / test_config_defaults.py / test_web_routes.py / test_floating_panel.py / test_overlay_render.py / WEB_CONSOLE.md / 工单列表.md / 本完成报告）
- 范围外问题写入 [docs/已知问题与后续事项.md](../../workflow/已知问题与后续事项.md)，**不**顺手修复
- **强制**：完成报告 §3「未修改的关键区域」必须列出 `app/overlay.py` / `app/floating_panel.py` / `app/danmu_engine.py` / `app/ai_client.py` / `app/mic_*.py` / `app/web_console.py` / `app/web_console_runtime.py` 证明未越界
- **强制**：完成报告 §7 须说明 8 个核心边界用例的手动验证结果（合法导入 / 4 类 4xx 拒绝 / hot reload 上屏字体 / 重启后 `imported_fonts` 持久化 / 目录与 DB 互校验 / 删除幂等 / `_safe_str` 兜底 / `__danmu_token` 复用核查）
- **强制**：完成报告 §8 必须确认 `window.__danmu_token` 名称与既有 `web/static/app.js` 一致；若不一致须写「ISSUE-XXX：token 注入需重命名」并停手
