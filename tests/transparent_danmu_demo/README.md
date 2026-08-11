# 透明弹幕 Demo

这是一个与 DanmuAI 正式功能隔离的最小验证 Demo，仅验证 pywebview + Edge WebView2 是否能显示透明桌面浮层。

## 运行

在仓库根目录执行：

```powershell
python tests/transparent_danmu_demo/transparent_danmu_demo.py
```

Demo 使用 `gui="edgechromium"` 创建无边框、置顶、不可调整大小的 pywebview 窗口，并设置 `transparent=True`。窗口内只绘制 5 条固定弹幕；按 `Alt+F4` 关闭窗口。

## 验收重点

- 弹幕文字和气泡正常显示。
- 气泡之外能直接看到 Windows 桌面，而不是白色、黑色或其他实色窗口背景。
- 没有启动 DanmuAI 正式入口、HTTP 服务、WebSocket、真实弹幕或动画。

运行需要 Windows 和已安装的 Microsoft Edge WebView2 Runtime。
