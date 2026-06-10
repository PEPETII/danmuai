# 已知问题记录

## 问题 ID

ISSUE-006

## 发现时间

2026-05-29

## 发现来源

Web 控制台 WebSocket 调试 / 用户 Console 报错

## 所属模块

`web/static/index.html`

## 问题描述

`index.html` 通过 `<script src="https://cdn.tailwindcss.com">` 与 Google Fonts `css2` 加载样式；当外网被阻断或 `ERR_CONNECTION_CLOSED` 时，Console 出现 `tailwind is not defined`，部分 Tailwind 类名样式缺失。本地已有 `warm-tokens.css`，但页面仍依赖 CDN 上的 Tailwind 运行时。

## 影响范围

用户可见（控制台 UI 样式降级；核心 API/弹幕功能不受影响）

## 严重程度

低

## 是否阻塞当前工单

否

## 临时处理方式

保证可访问外网；或忽略 Console 中 CDN 报错，依赖 `warm-tokens.css` 基础样式。WebSocket 与 HTTP API 不依赖 Tailwind CDN。

## 建议后续工单

Web 静态资源：Tailwind 本地化或构建时打入 `/static/`，移除运行时 CDN 依赖。

## 备注

与 Immersive Translate 等浏览器扩展的 `content_main.js` 报错无关；扩展报错可忽略。
