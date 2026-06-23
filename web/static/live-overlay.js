/*
 * live-overlay.js — 直播伴侣透明弹幕层 SSE 客户端。
 *
 * 独立模块（不依赖 app.js / modules/*），直接由 live-overlay.html 内联加载。
 * 仅做 3 件事：
 *   1) connect()：与 /api/live-overlay/events 建立 EventSource；hello 事件重置
 *      reconnectDelay=2s；onerror 走 1.5x 退避，上限 30s
 *   2) handlePayload()：按 event 类型分派
 *      - 'danmu_item'（或兼容旧协议 {text,...}）→ spawnDanmuItem
 *      - 'danmu_batch' → spawnFromBatch（多行测试弹幕）
 *   3) spawnDanmuItem()：按 payload.y / screen_height 比例映射到当前 viewport，
 *      requestAnimationFrame 推进 transform，结束自动从 DOM 移除
 *
 * 坐标映射：scaleY() 处理 y 单位（server 端以源屏幕高度为基），客户端按当前
 * 视口高度等比缩放；保证 OBS 1920×1080 源与本机 2560×1440 浏览器源视觉一致。
 *
 * 线程：浏览器主线程；不写任何持久化状态；不与主链路 Qt Overlay 通信。
 */
(function () {
  'use strict';

  const ENGINE_FPS = 60;
  const STAGE = document.getElementById('stage');

  let fontSizePx = 28;

  function scaleY(y, screenHeight) {
    const sh = screenHeight > 0 ? screenHeight : 1080;
    const h = STAGE.clientHeight || window.innerHeight || 1080;
    return (y / sh) * h;
  }

  function pxPerSec(speed) {
    return Math.max(speed * ENGINE_FPS, 1);
  }

  function spawnDanmuItem(payload) {
    const text = String(payload.text || '').trim();
    if (!text) {
      return;
    }
    const item = document.createElement('div');
    item.className = 'danmu-item';
    item.textContent = text;
    item.style.fontSize = `${fontSizePx}px`;
    const topPx = scaleY(Number(payload.y) || 50, Number(payload.screen_height) || 1080);
    item.style.top = `${topPx}px`;
    STAGE.appendChild(item);

    const stageW = STAGE.clientWidth || window.innerWidth || 1920;
    const w = item.offsetWidth || 200;
    const startX = stageW + 16;
    const endX = -w - 16;
    const speed = Number(payload.speed) || 2;
    const velocity = pxPerSec(speed);
    const durationMs = Math.max(4000, ((startX - endX) / velocity) * 1000);
    const start = performance.now();

    function tick(now) {
      const t = Math.min(1, (now - start) / durationMs);
      item.style.left = `${startX + (endX - startX) * t}px`;
      if (t < 1) {
        requestAnimationFrame(tick);
      } else {
        item.remove();
      }
    }
    requestAnimationFrame(tick);
  }

  function spawnFromBatch(payload) {
    const lineHeight = 40;
    const topMargin = 50;
    const screenH = Number(payload.screen_height) || 1080;
    const screenW = Number(payload.screen_width) || 1920;
    const speed = Number(payload.speed) || 2;
    payload.items.forEach((line, index) => {
      if (!line) {
        return;
      }
      spawnDanmuItem({
        text: line,
        y: topMargin + index * lineHeight,
        screen_width: screenW,
        screen_height: screenH,
        speed,
        source: payload.source || 'test',
      });
    });
  }

  function handlePayload(payload) {
    if (!payload || typeof payload !== 'object') {
      return;
    }
    const event = payload.event;
    if (event === 'danmu_item' || (!event && payload.text)) {
      spawnDanmuItem(payload);
      return;
    }
    if (event === 'danmu_batch' && Array.isArray(payload.items)) {
      spawnFromBatch(payload);
    }
  }

  function loadFontSize() {
    fetch('/api/config', { cache: 'no-store' })
      .then((r) => r.json())
      .then((cfg) => {
        const fs = parseInt(cfg.font_size, 10);
        if (fs > 0) {
          fontSizePx = fs;
        }
      })
      .catch(() => {});
  }

  let source = null;
  let reconnectDelay = 2000;

  function connect() {
    if (source) {
      source.close();
    }
    source = new EventSource('/api/live-overlay/events');

    source.addEventListener('hello', () => {
      reconnectDelay = 2000;
    });

    source.onmessage = (ev) => {
      try {
        handlePayload(JSON.parse(ev.data));
      } catch (_e) {
        /* ignore malformed */
      }
    };

    source.onerror = () => {
      source.close();
      source = null;
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(30000, reconnectDelay * 1.5);
    };
  }

  connect();
  loadFontSize();
})();
