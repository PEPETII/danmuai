"""pywebview 浮动面板边界收口层：协议、WS 桥接与子进程生命周期。

职责：
- panel_protocol：WS 消息类型与字段契约
- panel_bridge：主线程 → uvicorn 线程的 card 缓冲与推送
- panel_process：pywebview/WebView2 子进程 spawn / stop / restart

不含 QTimer 驱动的主链路；不直接读 DanmuApp 私有字段。
数据通信必须走 WebSocket，禁止从非 UI 线程调用 evaluate_js。
"""
