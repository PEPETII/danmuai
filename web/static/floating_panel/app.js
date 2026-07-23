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

  /** Parse #RRGGBB / #RRGGBBAA → rgba(); alphaOverride in 0..1 optional. */
  function hexToRgba(hex, alphaOverride) {
    var h = String(hex || "").trim();
    if (h.charAt(0) === "#") h = h.slice(1);
    var r = 255;
    var g = 255;
    var b = 255;
    var a = 1;
    if (h.length === 6 || h.length === 8) {
      r = parseInt(h.slice(0, 2), 16);
      g = parseInt(h.slice(2, 4), 16);
      b = parseInt(h.slice(4, 6), 16);
      if (h.length === 8) a = parseInt(h.slice(6, 8), 16) / 255;
    }
    if (alphaOverride !== undefined && alphaOverride !== null && !isNaN(alphaOverride)) {
      a = Math.max(0, Math.min(1, Number(alphaOverride)));
    }
    if (isNaN(r) || isNaN(g) || isNaN(b)) {
      r = 255;
      g = 247;
      b = 237;
    }
    return "rgba(" + r + "," + g + "," + b + "," + a + ")";
  }

  /** Apply style vars to a single card element (not document.documentElement). */
  function applyCardStyleVars(cardEl, style) {
    if (!cardEl || !style || typeof style !== "object") return;
    var s = cardEl.style;
    if (style.username_color) s.setProperty("--username-color", String(style.username_color));
    if (style.content_color) s.setProperty("--content-color", String(style.content_color));
    if (style.outline_color) s.setProperty("--outline-color", String(style.outline_color));
    if (style.font_family) s.setProperty("--font-family", String(style.font_family));
    if (style.font_size_username != null) s.setProperty("--font-size-username", Number(style.font_size_username) + "px");
    if (style.font_size_content != null) s.setProperty("--font-size-content", Number(style.font_size_content) + "px");
    if (style.border_radius != null) s.setProperty("--card-radius", Number(style.border_radius) + "px");
    if (style.max_width != null) s.setProperty("--card-max-width", Number(style.max_width) + "px");
    if (style.box_shadow) s.setProperty("--card-shadow", String(style.box_shadow));

    // === 扩展字段 ===
    if (style.padding_x != null) s.setProperty("--padding-x", Number(style.padding_x) + "px");
    if (style.padding_y != null) s.setProperty("--padding-y", Number(style.padding_y) + "px");
    if (style.border_width != null) s.setProperty("--border-width", Number(style.border_width) + "px");
    if (style.outline_width != null) s.setProperty("--outline-w", Number(style.outline_width) + "px");
    if (style.tail_width != null) s.setProperty("--tail-w", Number(style.tail_width) + "px");
    if (style.tail_height != null) s.setProperty("--tail-h", Number(style.tail_height) + "px");
    if (style.tail_offset_y != null) s.setProperty("--tail-offset-y", Number(style.tail_offset_y) + "%");
    // card_bg / tail with card_opacity (0-100)
    (function applyCardBg() {
      var bg = String(style.card_bg || "#fff7ed");
      var rgba = hexToRgba(bg, style.card_opacity != null ? Number(style.card_opacity) / 100 : undefined);
      s.setProperty("--card-bg", rgba);
      s.setProperty("--tail-color", rgba);
    })();
    // border color × border_opacity
    if (style.card_border || style.border_opacity != null) {
      s.setProperty(
        "--card-border",
        hexToRgba(String(style.card_border || "#fbbf24"), style.border_opacity != null ? Number(style.border_opacity) / 100 : undefined)
      );
    }
    if (style.username_weight != null) s.setProperty("--font-weight-username", String(style.username_weight));
    if (style.content_weight != null) s.setProperty("--font-weight-content", String(style.content_weight));
    if (style.content_line_height != null) s.setProperty("--content-line-height", Number(style.content_line_height) / 100);
    if (style.gap_username_content != null) s.setProperty("--gap-username-content", Number(style.gap_username_content) + "px");

    // Classes
    cardEl.classList.toggle("no-border", style.border_enabled === false || style.border_width === 0);
    cardEl.classList.toggle("has-outline", style.outline_enabled === true && style.outline_width > 0);
    cardEl.classList.toggle("is-bold", style.font_bold === true);
    var isBubble = style.shape === "bubble" && style.tail_enabled === true;
    cardEl.classList.toggle("is-bubble", isBubble);
    if (isBubble) {
      cardEl.dataset.tailStyle = String(style.tail_style || "round");
    } else {
      delete cardEl.dataset.tailStyle;
    }
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
    if (msg.panel_opacity != null) {
      document.documentElement.style.setProperty("--panel-opacity", Math.max(0, Math.min(100, Number(msg.panel_opacity))) / 100);
    }
    // Converge to maxCards after config change
    removeOldestIfNeeded();
  }

  function scheduleCardExit(node) {
    if (!node || node.classList.contains("exiting")) return;
    var id = node.dataset.cardId;
    node.classList.add("exiting");
    setTimeout(function (n, cid) {
      if (n && n.parentNode) n.parentNode.removeChild(n);
      if (cid) cardIds.delete(cid);
    }, exitDurationMs, node, id);
  }

  function removeOldestIfNeeded() {
    // Count non-exiting cards
    var active = 0;
    var i;
    for (i = 0; i < panel.children.length; i++) {
      if (!panel.children[i].classList.contains("exiting")) active += 1;
    }
    var needExit = active - maxCards;
    if (needExit <= 0) return;
    // Schedule exit for oldest active cards (first children are oldest)
    for (i = 0; i < panel.children.length && needExit > 0; i++) {
      if (panel.children[i].classList.contains("exiting")) continue;
      scheduleCardExit(panel.children[i]);
      needExit -= 1;
    }
    // Hard limit: if somehow still > maxCards * 2, force remove
    var hardLimit = maxCards * 2;
    while (panel.children.length > hardLimit) {
      var oldest = panel.firstElementChild;
      if (!oldest) break;
      var cid = oldest.dataset.cardId;
      if (cid) cardIds.delete(cid);
      if (oldest.parentNode) oldest.parentNode.removeChild(oldest);
    }
  }

  function addCard(msg) {
    var id = msg.id != null ? String(msg.id) : "";
    if (id && cardIds.has(id)) return;
    var card = document.createElement("div");
    card.className = "card";
    if (id) {
      card.dataset.cardId = id;
      cardIds.add(id);
    }
    var username = escapeHtml(msg.username || "AI");
    var content = escapeHtml(msg.content || "");
    // Apply per-card style (not via document root)
    if (msg.style) applyCardStyleVars(card, msg.style);
    // Build inner HTML
    var usernameEnabled = msg.style ? msg.style.username_enabled !== false : true;
    var usernameSeparator = (msg.style && msg.style.username_separator) || "：";
    if (usernameEnabled) {
      card.innerHTML =
        '<div class="username">' + username + usernameSeparator + '</div>' +
        '<div class="content">' + content + '</div>';
    } else {
      card.innerHTML =
        '<div class="username is-hidden"></div>' +
        '<div class="content">' + content + '</div>';
    }
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
      if (token && url.indexOf("ws_token") === -1) {
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