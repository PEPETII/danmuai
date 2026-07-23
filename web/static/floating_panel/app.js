(function () {
  "use strict";

  var MAX_RECONNECT_ATTEMPTS = 10;
  var panel = document.getElementById("panel");
  var maxCards = 6;
  var exitDurationMs = 250;
  var ws = null;
  var reconnectAttempts = 0;
  var reconnectTimer = null;
  var wsReceived = 0;
  var wsOpen = false;
  var animationFrame = 0;
  var cardIds = new Set();

  function tickAnimation() {
    animationFrame += 1;
    requestAnimationFrame(tickAnimation);
  }
  requestAnimationFrame(tickAnimation);

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[c];
    });
  }

  function readToken() {
    var params = new URLSearchParams(window.location.search);
    var q = params.get("ws_token") || params.get("token") || "";
    if (q) return q;
    var m = document.cookie.match(/(?:^|;\s*)ws_token=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function buildWsUrl() {
    var params = new URLSearchParams(window.location.search);
    var explicit = params.get("ws_url");
    if (explicit) return explicit;
    var token = readToken();
    var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    var host = window.location.host || "127.0.0.1:18765";
    var url = proto + "//" + host + "/ws/panel";
    if (token) url += "?ws_token=" + encodeURIComponent(token);
    return url;
  }

  function applyStyleVars(style) {
    if (!style || typeof style !== "object") return;
    var root = document.documentElement.style;
    if (style.card_bg) root.setProperty("--card-bg", String(style.card_bg));
    if (style.card_border) root.setProperty("--card-border", String(style.card_border));
    if (style.username_color) root.setProperty("--username-color", String(style.username_color));
    if (style.content_color) root.setProperty("--content-color", String(style.content_color));
    if (style.outline_color) root.setProperty("--outline-color", String(style.outline_color));
    if (style.font_family) root.setProperty("--font-family", String(style.font_family));
    if (style.font_size_username) root.setProperty("--font-size-username", Number(style.font_size_username) + "px");
    if (style.font_size_content) root.setProperty("--font-size-content", Number(style.font_size_content) + "px");
    if (style.border_radius != null) root.setProperty("--card-radius", Number(style.border_radius) + "px");
    if (style.max_width != null) root.setProperty("--card-max-width", Number(style.max_width) + "px");
    if (style.box_shadow) root.setProperty("--card-shadow", String(style.box_shadow));
  }

  function applyConfig(msg) {
    if (msg.max_cards != null) maxCards = Math.max(1, Number(msg.max_cards) || 6);
    if (msg.stack_gap != null) {
      document.documentElement.style.setProperty("--stack-gap", Number(msg.stack_gap) + "px");
    }
    if (msg.panel_padding != null) {
      document.documentElement.style.setProperty("--panel-padding", Number(msg.panel_padding) + "px");
    }
    if (msg.entry_duration_ms != null) {
      document.documentElement.style.setProperty("--entry-duration", Number(msg.entry_duration_ms) + "ms");
    }
    if (msg.exit_duration_ms != null) {
      exitDurationMs = Number(msg.exit_duration_ms) || 250;
      document.documentElement.style.setProperty("--exit-duration", exitDurationMs + "ms");
    }
  }

  function removeOldestIfNeeded() {
    while (panel.children.length > maxCards) {
      var oldest = panel.firstElementChild;
      if (!oldest) break;
      var id = oldest.dataset.cardId;
      oldest.classList.add("exiting");
      setTimeout(function (node, cardId) {
        if (node && node.parentNode) node.parentNode.removeChild(node);
        if (cardId) cardIds.delete(cardId);
      }, exitDurationMs, oldest, id);
    }
  }

  function addCard(msg) {
    var id = msg.id != null ? String(msg.id) : "";
    if (id && cardIds.has(id)) return;
    if (msg.style) applyStyleVars(msg.style);
    var card = document.createElement("div");
    card.className = "card";
    if (id) {
      card.dataset.cardId = id;
      cardIds.add(id);
    }
    var username = escapeHtml(msg.username || "AI");
    var content = escapeHtml(msg.content || "");
    card.innerHTML =
      '<div class="username">' + username + "</div>" +
      '<div class="content">' + content + "</div>";
    panel.appendChild(card);
    removeOldestIfNeeded();
  }

  function clearCards() {
    panel.innerHTML = "";
    cardIds.clear();
  }

  function sendJson(obj) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    try {
      ws.send(JSON.stringify(obj));
    } catch (_e) {
      /* ignore */
    }
  }

  function sendPong(t) {
    sendJson({ type: "pong", t: t != null ? t : Date.now() / 1000 });
  }

  function sendStateReport() {
    var firstCard = document.querySelector(".card");
    var cardInfo = null;
    if (firstCard) {
      var r = firstCard.getBoundingClientRect();
      var s = getComputedStyle(firstCard);
      cardInfo = {
        w: Math.round(r.width),
        h: Math.round(r.height),
        bg: s.backgroundColor,
        shadow: String(s.boxShadow || "").substring(0, 100),
        radius: s.borderRadius,
        transform: s.transform,
        opacity: s.opacity,
      };
    }
    var bodyStyle = getComputedStyle(document.body);
    sendJson({
      type: "state-report",
      cardsCount: document.querySelectorAll(".card").length,
      cardInfo: cardInfo,
      bodyBg: bodyStyle.backgroundColor,
      htmlBg: getComputedStyle(document.documentElement).backgroundColor,
      panelBg: getComputedStyle(panel).backgroundColor,
      animationFrame: animationFrame,
      wsReceived: wsReceived,
      wsOpen: wsOpen === true,
      timestamp: Date.now(),
    });
  }

  function sendError(message, stack) {
    sendJson({
      type: "error",
      message: String(message || "unknown"),
      stack: stack != null ? String(stack) : undefined,
      timestamp: Date.now(),
    });
  }

  function handleMessage(raw) {
    wsReceived += 1;
    var msg;
    try {
      msg = JSON.parse(raw);
    } catch (err) {
      sendError("invalid json", err && err.stack);
      return;
    }
    if (!msg || typeof msg !== "object") return;
    switch (msg.type) {
      case "card":
        addCard(msg);
        break;
      case "config":
        applyConfig(msg);
        break;
      case "clear":
        clearCards();
        break;
      case "ping":
        sendPong(msg.t);
        break;
      case "get-state":
        sendStateReport();
        break;
      case "reload":
        window.location.reload();
        break;
      case "auth":
        break;
      default:
        break;
    }
  }

  function getReconnectInterval() {
    return Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
  }

  function scheduleReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      sendError("Max reconnect attempts reached");
      return;
    }
    if (reconnectTimer) clearTimeout(reconnectTimer);
    var delay = getReconnectInterval();
    reconnectAttempts += 1;
    reconnectTimer = setTimeout(connectWS, delay);
  }

  function connectWS() {
    var url = buildWsUrl();
    try {
      ws = new WebSocket(url);
    } catch (err) {
      sendError("WebSocket connection failed", err && err.stack);
      scheduleReconnect();
      return;
    }
    ws.onopen = function () {
      wsOpen = true;
      reconnectAttempts = 0;
      var token = readToken();
      if (token && url.indexOf("ws_token=") === -1) {
        sendJson({ type: "auth", token: token });
      }
    };
    ws.onmessage = function (e) {
      handleMessage(e.data);
    };
    ws.onclose = function () {
      wsOpen = false;
      scheduleReconnect();
    };
    ws.onerror = function () {
      wsOpen = false;
    };
  }

  window.onerror = function (message, _source, _lineno, _colno, error) {
    sendError(message, error && error.stack);
  };
  window.addEventListener("unhandledrejection", function (ev) {
    var reason = ev && ev.reason;
    sendError(reason && reason.message ? reason.message : String(reason), reason && reason.stack);
  });

  window.__panelApi = {
    addCard: addCard,
    clearCards: clearCards,
    applyConfig: applyConfig,
    sendStateReport: sendStateReport,
  };

  connectWS();
})();
