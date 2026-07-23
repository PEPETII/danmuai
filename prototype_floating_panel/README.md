# 浮动面板 pywebview + WebView2 可行性验证原型

本目录是最小验证原型，不触碰任何正式 `app/floating_panel_overlay.py` 代码。

## 目的

验证现有 pywebview + Edge WebView2 技术栈是否能替代 `app/floating_panel_overlay.py` 的 QPainter 渲染层，承载 blivechat-dev 风格的 Vue/HTML/CSS 浮动面板。

## 文件

- `win32_probe.py` — Win32 探针：读/写 exstyle、HWND_TOPMOST、DPI
- `panel.html` — Vue 3 + CSS 浮动面板演示页（含底锚堆积、卡片阴影、文字描边、CSS 动画、WebSocket 客户端）
- `panel_window.py` — pywebview 子进程：透明 + 无边框 + 置顶 + 鼠标穿透窗口 + Win32 探针线程
- `run_prototype.py` — 主入口：FastAPI + WebSocket 服务 + 子进程协调 + 测试运行器

## 运行

```bash
# 测试模式（运行完整测试套件，输出 TEST_RESULTS.md）
python -m prototype_floating_panel.run_prototype --mode test

# 演示模式（启动后保持运行，肉眼观察）
python -m prototype_floating_panel.run_prototype --mode demo
```

## 测试覆盖

1. WebView2 Runtime 探测
2. pywebview 子进程启动 + 加载
3. Win32 exstyle 初始状态（WebView2 是否自动设 LAYERED）
4. 应用 WS_EX_TRANSPARENT 后 10 秒持续监测（验证 WebView2 是否会重置 exstyle）
5. HWND_TOPMOST 设置
6. DPI 读取
7. JS 交互（evaluate_js 测量卡片尺寸、启动动画、读取 body computed style）
8. CSS 渲染（box-shadow / border-radius / text-shadow / animation）
9. WebSocket 双向通信
10. 屏幕截图（肉眼验证透明效果）
11. 子进程退出码
