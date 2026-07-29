# UI 变更检查清单

给 **AI Agent 与人类** 在改 Web 控制台 UI 前/后勾选。权威规范：[DESIGN_SYSTEM.md](DESIGN_SYSTEM.md)。

---

## 开工前

- [ ] 已读 [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md)（Token 以 `warm-tokens-base.css` 为准）
- [ ] 已搜索现有 `.ui-button*` / `.ui-field*` / `.ui-control*` / `.ui-card*`，确认能否复用
- [ ] 工单「允许修改区域」覆盖本次路径；**未**触碰 `floating_panel*` 业务与 `app/` 主链路（除非工单授权）
- [ ] 明确 **不改**：DOM `id`、`data-*`、API 字段、i18n 键、事件契约（除非工单要求）

---

## 实现中

- [ ] 颜色/间距/圆角/阴影/控件高度只引用 Token，无新增硬编码品牌色
- [ ] 新 Token 同时写了浅色 `:root` 与 `[data-theme="dark"]`
- [ ] 通用视觉进 `warm-tokens-components.css`（或既定 pages 文件），**不是**业务 partial 内联
- [ ] **禁止**在 `web/static/partials/*.html` 新增裸 `<style>`
- [ ] **禁止**无说明的 `style=""` 堆视觉；**禁止**无注释的 `!important` 扩张
- [ ] 静态卡片 **无** hover `translateY`；仅 `.ui-card--interactive` 可轻位移
- [ ] 主操作使用 `ui-button ui-button--primary`（可与 `btn-primary` 双 class）
- [ ] 同一操作栏按钮同高（`--sm` / `--md` / `--lg`）

---

## 构建与测试

- [ ] 改了 partial 或 `index.template.html` → 已运行  
  `python web/static/build_index_html.py`
- [ ] 按范围跑定向测试（示例）：

```bash
python -m pytest tests/test_ui_token_contract.py tests/test_ui_component_contract.py \
  tests/test_ui_partial_hygiene.py tests/test_ui_theme_init.py \
  tests/test_ui_responsive_shell.py tests/test_console_theme.py tests/test_ui_mode.py -q -x
```

- [ ] **未**跑本地全量 `pytest tests/`（见根 `AGENTS.md` §7）
- [ ] 未把 Playwright 写进主 `requirements.txt`（可选独立 ui-tests 另议）

---

## 视觉验收（真机 / WebView）

- [ ] 浅色主题
- [ ] 深色主题
- [ ] 窗口约 **1366×768**、**1024×768**、**800×600**（无横向溢出、导航可用）
- [ ] 焦点环可见；键盘可达核心操作
- [ ] 无法截图时写明 **NOT VERIFIED**，不得声称已完成视觉验收

---

## 交付说明至少包含

1. 复用的组件与 Token  
2. 修改文件列表  
3. `build_index_html` + 定向测试结果  
4. 视觉验收表或 NOT VERIFIED  
5. 未解决问题（只记入已知问题，不顺手改范围外）
