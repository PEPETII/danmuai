# pywebview + Edge WebView2 浮动面板可行性验证结果

运行时间: 2026-07-21 18:45:55
平台: win32

## 1. WebView2 Runtime 探测

- **PASS**: WebView2 Runtime 已安装

## 2. 子进程启动与 pywebview 加载

- loaded 信号: **PASS**
- pywebview 版本: ?

## 3. Win32 exstyle / 透明 / 鼠标穿透 探针输出

```
[ready] loaded
[ready] hwnd:6818226
probe-hwnd-found:6818226
initial-exstyle:0x000d0008
initial-layered:True
initial-transparent:False
initial-caption:False
initial-dpi:144
initial-rect:(1989, 478, 2496, 1294)
initial-foreground:6818226 hwnd=6818226 match=True
after-set-topmost:True
exstyle-stable:10s
js-probe-show:flex
after-click-through-exstyle:0x000d0028
after-click-through-transparent:True
click-through-top-left:point=(1994,483) hwnd=1050402 is_panel=False
click-through-top-right:point=(2491,483) hwnd=1050402 is_panel=False
click-through-bottom-left:point=(1994,1289) hwnd=1050402 is_panel=False
click-through-bottom-right:point=(2491,1289) hwnd=1050402 is_panel=False
click-through-center:point=(2242,886) hwnd=1050402 is_panel=False
click-through-summary:pass=True
click-through-exstyle-stable:5s
probe-done
reassert-topmost:True
final-foreground:6818226 hwnd=6818226 match=True
monitors-count:1
monitor-0:{'handle': 65537, 'rect': (0, 0, 2560, 1440), 'work': (0, 0, 2560, 1368), 'primary': True}
probe-exit
```

## 3.5 透明度像素对比报告

- 未生成透明度报告

## 3.6 鼠标穿透（click-through）

- click-through-summary: PASS
- 详细探针输出（WindowFromPoint 测试 5 个点）：见 §3 日志

## 4. JS 交互 / Vue 动画 / CSS 渲染

### 4.1 evaluate_js 探针（从探针线程调用）

```
js-measure:{"x":16,"y":473.07293701171875,"w":146.7291717529297,"h":54.927085876464844,"offsetY":473,"computedStyle":{"boxShadow":"rgba(0, 0, 0, 0.1) 0px 2px 4px 0px, rgba(0, 0, 0, 0.08) 0px 4px 8px 0px, rgba(0,","transform":"none","borderRadius":"12px"}}
js-anim-start:started
js-anim-frame-after-1s:59
js-body-bg:rgba(0, 0, 0, 0)
js-panel-bg:rgba(0, 0, 0, 0)
js-ws-state:{"clients":1,"readyState":1,"received":7,"lastMsg":"ws-msg:ping"}
js-probe-show:flex
js-add-card:ok
js-cards-count:2
js-first-card:{"w":146.7291717529297,"h":54.927085876464844,"bg":"rgb(255, 247, 237)","shadow":"rgba(0, 0, 0, 0.1) 0px 2px 4px 0px, rgba(0, 0, 0, 0.08) 0px 4px 8px 0px, rgba(0, 0, 0, 0.06) 0px 8px","radius":"12px","transform":"none","opacity":"1"}
js-body-alpha:{"bg":"rgba(0, 0, 0, 0)","color":"rgb(0, 0, 0)","html_bg":"rgba(0, 0, 0, 0)"}
```


### 4.2 WebSocket state-report（通过 WS 获取页面渲染状态）

```json
{
  "welcome": {
    "type": "card",
    "username": "系统",
    "content": "WebSocket 已连接"
  }
}
{
  "other": {
    "type": "ping",
    "t": 1784630753.3494132
  }
}
{
  "state-report": {
    "type": "state-report",
    "cardsCount": 2,
    "cardInfo": {
      "w": 147,
      "h": 55,
      "bg": "rgb(255, 247, 237)",
      "shadow": "rgba(0, 0, 0, 0.1) 0px 2px 4px 0px, rgba(0, 0, 0, 0.08) 0px 4px 8px 0px, rgba(0, 0, 0, 0.06) 0px 8px",
      "radius": "12px",
      "transform": "none",
      "opacity": "1"
    },
    "bodyBg": "rgba(0, 0, 0, 0)",
    "bodyColor": "rgb(0, 0, 0)",
    "htmlBg": "rgba(0, 0, 0, 0)",
    "panelBg": "rgba(0, 0, 0, 0)",
    "animationFrame": 59,
    "wsReceived": 15,
    "wsOpen": true,
    "timestamp": 1784630753352
  }
}
{
  "state-report-after-card": {
    "type": "state-report",
    "cardsCount": 3,
    "cardInfo": {
      "w": 147,
      "h": 55,
      "bg": "rgb(255, 247, 237)",
      "shadow": "rgba(0, 0, 0, 0.1) 0px 2px 4px 0px, rgba(0, 0, 0, 0.08) 0px 4px 8px 0px, rgba(0, 0, 0, 0.06) 0px 8px",
      "radius": "12px",
      "transform": "none",
      "opacity": "1"
    },
    "bodyBg": "rgba(0, 0, 0, 0)",
    "bodyColor": "rgb(0, 0, 0)",
    "htmlBg": "rgba(0, 0, 0, 0)",
    "panelBg": "rgba(0, 0, 0, 0)",
    "animationFrame": 59,
    "wsReceived": 17,
    "wsOpen": true,
    "timestamp": 1784630754155
  }
}
```
- 卡片数量: 2
- 首张卡片尺寸: 147x55
- 首张卡片背景: rgb(255, 247, 237)
- 首张卡片阴影: rgba(0, 0, 0, 0.1) 0px 2px 4px 0px, rgba(0, 0, 0, 0.08) 0px 4px 8px 0px, rgba(0, 0, 0, 0.06) 0px 8px
- 首张卡片圆角: 12px
- 首张卡片 transform: none
- 首张卡片 opacity: 1
- body 背景: rgba(0, 0, 0, 0)
- html 背景: rgba(0, 0, 0, 0)
- panel 背景: rgba(0, 0, 0, 0)
- animationFrame: 59
- WS 接收数: 15
- WS 已连接: True
- **PASS**: Vue/HTML/CSS 渲染正常（卡片已渲染，有尺寸、阴影、圆角）

## 5. WebSocket 通信

- WS 客户端连接数: 0
- WS 发送消息数: 21
- WS 接收消息数: 18
- 最后接收: {'type': 'state-report', 'cardsCount': 3, 'cardInfo': {'w': 147, 'h': 55, 'bg': 'rgb(255, 247, 237)', 'shadow': 'rgba(0, 0, 0, 0.1) 0px 2px 4px 0px, rgba(0, 0, 0, 0.08) 0px 4px 8px 0px, rgba(0, 0, 0, 0.06) 0px 8px', 'radius': '12px', 'transform': 'none', 'opacity': '1'}, 'bodyBg': 'rgba(0, 0, 0, 0)', 'bodyColor': 'rgb(0, 0, 0)', 'htmlBg': 'rgba(0, 0, 0, 0)', 'panelBg': 'rgba(0, 0, 0, 0)', 'animationFrame': 59, 'wsReceived': 17, 'wsOpen': True, 'timestamp': 1784630754155}
- **PASS**: WebSocket 双向通信已建立

## 6. 截图

截图已保存: E:\test\danmu\prototype_floating_panel\screenshot.png
请肉眼检查：
- 卡片背景是否半透明（能看到桌面/下层窗口）
- 卡片阴影/圆角/文字描边是否正常
- 整体窗口是否无边框

## 7. 屏幕信息

- 主屏分辨率: 1707x960
- 逻辑 DPI: 96.0
- 窗口位置: (1326, 319)
- 多屏数量: 1
  - 屏 0: x=0 y=0 w=1707 h=960 dpi=96.0 (主屏)

## 8. 子进程退出

- panel_pid: 51140
- exitcode: -15
- **PASS**: 子进程已退出

## 9. 完整探针日志（原始）

```
webview_version:?
[ready] loaded
[ready] hwnd:6818226
probe-hwnd-found:6818226
initial-exstyle:0x000d0008
initial-style:0x16010000
initial-layered:True
initial-transparent:False
initial-caption:False
initial-dpi:144
initial-rect:(1989, 478, 2496, 1294)
initial-foreground:6818226 hwnd=6818226 match=True
after-set-topmost:True
exstyle-stable:10s
js-measure:{"x":16,"y":473.07293701171875,"w":146.7291717529297,"h":54.927085876464844,"offsetY":473,"computedStyle":{"boxShadow":"rgba(0, 0, 0, 0.1) 0px 2px 4px 0px, rgba(0, 0, 0, 0.08) 0px 4px 8px 0px, rgba(0,","transform":"none","borderRadius":"12px"}}
js-anim-start:started
js-anim-frame-after-1s:59
js-body-bg:rgba(0, 0, 0, 0)
js-panel-bg:rgba(0, 0, 0, 0)
js-ws-state:{"clients":1,"readyState":1,"received":7,"lastMsg":"ws-msg:ping"}
js-probe-show:flex
js-add-card:ok
js-cards-count:2
js-first-card:{"w":146.7291717529297,"h":54.927085876464844,"bg":"rgb(255, 247, 237)","shadow":"rgba(0, 0, 0, 0.1) 0px 2px 4px 0px, rgba(0, 0, 0, 0.08) 0px 4px 8px 0px, rgba(0, 0, 0, 0.06) 0px 8px","radius":"12px","transform":"none","opacity":"1"}
js-body-alpha:{"bg":"rgba(0, 0, 0, 0)","color":"rgb(0, 0, 0)","html_bg":"rgba(0, 0, 0, 0)"}
after-click-through-exstyle:0x000d0028
after-click-through-transparent:True
click-through-top-left:point=(1994,483) hwnd=1050402 is_panel=False
click-through-top-right:point=(2491,483) hwnd=1050402 is_panel=False
click-through-bottom-left:point=(1994,1289) hwnd=1050402 is_panel=False
click-through-bottom-right:point=(2491,1289) hwnd=1050402 is_panel=False
click-through-center:point=(2242,886) hwnd=1050402 is_panel=False
click-through-summary:pass=True
click-through-exstyle-stable:5s
probe-done
reassert-topmost:True
final-foreground:6818226 hwnd=6818226 match=True
monitors-count:1
monitor-0:{'handle': 65537, 'rect': (0, 0, 2560, 1440), 'work': (0, 0, 2560, 1368), 'primary': True}
probe-exit
```
