# DanmuAI × blivechat LineLike 视觉 1:1 实现说明

## 1\. 文档目的

本目录用于指导 IDE/Codex 在 `PEPETII/danmuai` 中实现 **blivechat LineLike 普通文字消息块的视觉 1:1 复刻**。

目标不是“参考”“接近”“类似微信气泡”，而是在相同浏览器、字体、缩放、文字和容器宽度下，使 DanmuAI 的普通弹幕消息块与 blivechat `LineLike.vue` 默认样式在以下方面一致：

* 用户名位于消息气泡外；
* 用户名与气泡的垂直间距一致；
* 气泡内边距、圆角、宽度自适应一致；
* 左上角尾巴的几何、位置和旋转角度一致；
* 默认字号、字重、颜色一致；
* 短文本、长文本、两行文本的换行和尺寸一致；
* 入场动画的透明度、位移、持续时间一致；
* 样式生成器预览与真实 Web 浮窗一致；
* WebView2 主路径和 QPainter 回退路径在布局语义上保持一致。

## 2\. “1:1”的范围

### 本次必须实现

普通文字消息块：

```text
用户名
  ┌──────────────┐
  │ 消息内容       │
  └──────────────┘
```

具体包括：

1. `username` 独立于气泡；
2. `bubble` 只包裹消息内容；
3. `bubble::before` 复刻 LineLike 尾巴；
4. LineLike 默认参数；
5. Web 真实浮窗；
6. 样式生成器实时预览；
7. 样式契约、WebSocket 协议和 QPainter 回退；
8. 自动化测试与视觉对比验收。

### 本次不新增

除非项目已有数据，否则不要为了“1:1”虚构：

* 用户头像；
* 舰长、房管、主播徽章；
* 时间戳；
* 表情系统；
* SC/付费消息；
* 礼物合并；
* B 站协议或 YouTube DOM 全量兼容。

因此，本任务是 **普通文字消息组件级视觉 1:1**，不是把 DanmuAI 改造成 blivechat。

## 3\. 上游参考

参考仓库：

```text
xfgryujk/blivechat
```

关键文件：

```text
frontend/src/components/ChatRenderer/TextMessage.vue
frontend/src/assets/css/youtube/yt-live-chat-text-message-renderer.css
frontend/src/views/StyleGenerator/LineLike.vue
frontend/src/views/StyleGenerator/common.js
LICENSE
```

LineLike 核心默认参数：

```text
全局缩放：1
字体缩放：1
用户名字体：Noto Sans SC
用户名字号：18px
用户名字重：700
用户名颜色：#CCCCCC
消息字体：Noto Sans SC
消息字号：20px
消息字重：700
消息颜色：#000000
普通消息背景：#FFFFFF
用户名与消息间距：5px
气泡纵向内边距：12px
气泡横向内边距：20px
气泡圆角：24px
尾巴基础边框：8px
尾巴长边：18px
尾巴旋转：35deg
入场淡入：200ms
入场滑动：启用
```

LineLike 核心 CSS 语义：

```css
#message {
  display: block;
  position: relative;
  width: fit-content;
  overflow: visible;
  padding: 12px 20px;
  border-radius: 24px;
}

#message::before {
  content: "";
  display: block;
  position: absolute;
  top: 0;
  left: 0;
  border: 8px solid transparent;
  border-left-width: 18px;
  border-right: 18px solid var(--bubble-bg);
  transform: translate(-50%, -50%) rotate(35deg);
}
```

实现时将选择器语义翻译为 DanmuAI 自有 DOM，不要完整复制 `yt-live-chat-\\\*` 标签树。

## 4\. 阅读顺序

1. `01\\\_ARCHITECTURE\\\_AND\\\_SCOPE.md`
2. `02\\\_WEB\\\_AND\\\_STYLE\\\_CONTRACT\\\_IMPLEMENTATION.md`
3. `03\\\_QPAINTER\\\_FALLBACK\\\_IMPLEMENTATION.md`
4. `04\\\_TEST\\\_AND\\\_VISUAL\\\_ACCEPTANCE.md`
5. `05\\\_IDE\\\_MASTER\\\_PROMPT.md`

## 5\. 核心原则

### 必须做

* 保留 `classic` 和 `wechat` 旧预设；
* 新增 `blivechat\\\_line` 预设；
* 新增独立布局字段 `floating\\\_panel\\\_layout`；
* 使用稳定 DOM：`.card > .username + .bubble > .content`；
* 真实浮窗和预览使用同一布局语义；
* WebView2 作为像素级 1:1 主验收路径；
* QPainter 回退实现相同层级与几何，不再把用户名画在气泡内部；
* 使用截图叠加和像素差异完成验收；
* 若复制上游实质性 CSS，保留 MIT 版权声明。

### 禁止做

* 只修改颜色、圆角和尾巴参数后声称“1:1”；
* 继续把用户名和内容画在同一个背景盒子里；
* 只修改样式生成器预览；
* 只修改 Web 浮窗而忽略协议与 QPainter 回退；
* 直接把完整 blivechat 前端嵌入 DanmuAI；
* 使用大量 `yt-live-chat-\\\*` 假标签制造无必要兼容层；
* 改动弹幕生成、WebSocket 连接、堆积顺序和去重逻辑；
* 删除旧预设或破坏现有配置；
* 用肉眼“看起来差不多”代替视觉测试。

## 6\. 完成定义

只有同时满足以下条件，任务才算完成：

* \[ ] `blivechat\\\_line` 可在样式生成器中选择；
* \[ ] 真实 Web 浮窗用户名位于气泡外；
* \[ ] 预览与真实 Web DOM 同构；
* \[ ] 尾巴使用 LineLike 左上旋转三角几何；
* \[ ] 默认参数与上游 LineLike 默认参数一致；
* \[ ] 短文本、长文本、两行文本通过尺寸测试；
* \[ ] Web 主路径视觉差异达到文档阈值；
* \[ ] QPainter 回退不再将用户名绘制在气泡内部；
* \[ ] 原有 `classic`、`wechat` 和 `custom` 行为不回归；
* \[ ] 全部新增/受影响测试通过；
* \[ ] 输出变更报告、测试结果和视觉对比结果。

