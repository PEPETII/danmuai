(function () {
  "use strict";

  var MAX_RECONNECT_ATTEMPTS = 10;
  var panel = document.getElementById("panel");
  var maxCards = 6;
  var entryAnimation = "fade";
  var exitDurationMs = 250;
  var exitAnimation = "fade";
  var pushDurationMs = 180;
  var ws = null;
  var reconnectAttempts = 0;
  var reconnectTimer = null;
  var wsReceived = 0;
  var wsOpen = false;
  var animationFrame = 0;
  var cardIds = new Set();

  function applyClickThroughFromUrl() {
    var params = new URLSearchParams(window.location.search);
    var raw = params.get("click_through");
    // Default to through=on when query missing (matches config default "1").
    var through = raw == null || raw === "" ? true : raw === "1" || raw === "true";
    if (panel) {
      panel.classList.toggle("is-interactive", !through);
    }
  }
  applyClickThroughFromUrl();

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
    // LineLike tail geometry (blivechat LineLike)
    if (style.tail_border != null) s.setProperty("--tail-border", Number(style.tail_border) + "px");
    if (style.tail_long_side != null) s.setProperty("--tail-long-side", Number(style.tail_long_side) + "px");
    if (style.tail_rotate_deg != null) s.setProperty("--tail-rotate", Number(style.tail_rotate_deg) + "deg");
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
    var layout = String(style.layout || "inline");
    cardEl.classList.toggle("layout-stacked", layout === "stacked");
    cardEl.classList.toggle("layout-inline", layout !== "stacked");
    cardEl.classList.toggle("no-border", style.border_enabled === false || style.border_width === 0);
    cardEl.classList.toggle("no-card-surface", style.card_opacity != null && Number(style.card_opacity) <= 0);
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

  function applyClickThroughMode(clickThrough) {
    // click_through true (default) → pass-through; false → interactive/draggable
    var passThrough = true;
    if (clickThrough === false || clickThrough === 0 || clickThrough === "0") {
      passThrough = false;
    } else if (clickThrough === true || clickThrough === 1 || clickThrough === "1") {
      passThrough = true;
    }
    if (panel) {
      panel.classList.toggle("is-interactive", !passThrough);
    }
  }

  function normalizeAnimation(raw, choices, fallback) {
    var value = String(raw == null ? "" : raw).trim().toLowerCase();
    return choices.indexOf(value) >= 0 ? value : fallback;
  }

  function readDuration(raw, fallback) {
    var value = Number(raw);
    if (!isFinite(value)) return fallback;
    return Math.max(0, Math.min(2000, value));
  }

  function applyEntryAnimationClass(card) {
    if (!card) return;
    card.classList.remove("entry-fade", "entry-slide-up");
    if (entryAnimation === "fade") card.classList.add("entry-fade");
    if (entryAnimation === "slide_up") card.classList.add("entry-slide-up");
  }

  function parseTransformY(value) {
    var raw = String(value || "");
    if (!raw || raw === "none") return 0;
    var match = raw.match(/^matrix3d\\(([^)]+)\\)$/);
    if (match) {
      var matrix3d = match[1].split(",");
      return Number(matrix3d[13]) || 0;
    }
    match = raw.match(/^matrix\\(([^)]+)\\)$/);
    if (match) {
      var matrix = match[1].split(",");
      return Number(matrix[5]) || 0;
    }
    return 0;
  }

  function freezeCardMotion(card) {
    if (!card) return;
    var computed = getComputedStyle(card);
    var currentY = parseTransformY(computed.transform);
    var currentOpacity = computed.opacity;
    if (card.getAnimations) {
      card.getAnimations().forEach(function (animation) {
        try {
          animation.cancel();
        } catch (_e) {
          /* ignore stale animation handles */
        }
      });
    }
    card.classList.remove("is-pushing", "entry-fade", "entry-slide-up", "exiting");
    if (Math.abs(currentY) > 0.01) {
      card.style.transform = "translateY(" + currentY + "px)";
    } else {
      card.style.removeProperty("transform");
    }
    if (currentOpacity !== "1") {
      card.style.opacity = currentOpacity;
    } else {
      card.style.removeProperty("opacity");
    }
  }

  function freezeAllCardMotions() {
    if (!panel) return;
    for (var i = 0; i < panel.children.length; i += 1) {
      freezeCardMotion(panel.children[i]);
    }
  }

  function snapshotCardTops() {
    var tops = new Map();
    if (!panel) return tops;
    for (var i = 0; i < panel.children.length; i += 1) {
      var card = panel.children[i];
      tops.set(card, card.getBoundingClientRect().top);
    }
    return tops;
  }

  function animatePushedCards(previousTops) {
    if (!panel || !previousTops) return;
    previousTops.forEach(function (beforeTop, card) {
      if (!card.parentNode) return;
      var afterRect = card.getBoundingClientRect();
      var frozenY = parseTransformY(getComputedStyle(card).transform);
      var layoutTop = afterRect.top - frozenY;
      var delta = beforeTop - layoutTop;
      if (!isFinite(delta)) delta = 0;
      card.style.opacity = "1";
      card.classList.remove("is-pushing");
      if (pushDurationMs <= 0 || Math.abs(delta) <= 0.01) {
        card.style.removeProperty("transform");
        return;
      }
      card.style.transform = "translateY(" + delta + "px)";
      void card.offsetWidth;
      card.classList.add("is-pushing");
      card.style.removeProperty("transform");
      card.addEventListener("transitionend", function (event) {
        if (event.propertyName !== "transform") return;
        card.classList.remove("is-pushing");
        card.style.removeProperty("transform");
      }, { once: true });
    });
  }

  function applyConfig(msg) {
    freezeAllCardMotions();
    var previousTops = snapshotCardTops();
    if (msg.max_cards != null) {
      var rawMaxCards = Number(msg.max_cards);
      maxCards = isFinite(rawMaxCards)
        ? Math.max(1, Math.min(50, Math.floor(rawMaxCards)))
        : 6;
    }
    if (msg.stack_gap != null) {
      document.documentElement.style.setProperty("--stack-gap", Number(msg.stack_gap) + "px");
    }
    if (msg.panel_padding != null) {
      document.documentElement.style.setProperty("--panel-padding", Number(msg.panel_padding) + "px");
    }
    if (msg.entry_animation != null) {
      entryAnimation = normalizeAnimation(msg.entry_animation, ["none", "fade", "slide_up"], "fade");
    }
    if (msg.entry_duration_ms != null) {
      document.documentElement.style.setProperty("--entry-duration", readDuration(msg.entry_duration_ms, 250) + "ms");
    }
    if (msg.push_duration_ms != null) {
      pushDurationMs = readDuration(msg.push_duration_ms, 180);
      document.documentElement.style.setProperty("--push-duration", pushDurationMs + "ms");
    }
    if (msg.exit_animation != null) {
      exitAnimation = normalizeAnimation(msg.exit_animation, ["none", "fade"], "fade");
    }
    if (msg.exit_duration_ms != null) {
      exitDurationMs = readDuration(msg.exit_duration_ms, 250);
      document.documentElement.style.setProperty("--exit-duration", exitDurationMs + "ms");
    }
    if (msg.panel_opacity != null) {
      document.documentElement.style.setProperty("--panel-opacity", Math.max(0, Math.min(100, Number(msg.panel_opacity))) / 100);
    }
    if (Object.prototype.hasOwnProperty.call(msg, "click_through")) {
      applyClickThroughMode(msg.click_through);
    }
    // Converge to maxCards after config change. Evicted cards must leave the
    // layout synchronously; an exit node in flex would expose maxCards + 1.
    removeOldestIfNeeded();
    animatePushedCards(previousTops);
  }

  function removeOldestIfNeeded() {
    // The last DOM child is the oldest because column-reverse puts the first
    // child at the bottom. Remove it before the next layout is painted.
    while (panel.children.length > maxCards) {
      var oldest = panel.lastElementChild;
      if (!oldest) break;
      var cid = oldest.dataset.cardId;
      if (cid) cardIds.delete(cid);
      if (oldest.parentNode) oldest.parentNode.removeChild(oldest);
    }
  }

  function addCard(msg) {
    var id = msg.id != null ? String(msg.id) : "";
    if (id && cardIds.has(id)) return;
    // Freeze a possibly running push/entry animation before measuring. This
    // makes rapid arrivals retarget from the current visual position instead
    // of restarting a second CSS animation over a moving layout.
    freezeAllCardMotions();
    var previousTops = snapshotCardTops();
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
    // Build inner HTML (dual DOM: stacked wraps content in .bubble)
    var usernameEnabled = msg.style ? msg.style.username_enabled !== false : true;
    var usernameSeparator =
      msg.style && msg.style.username_separator != null
        ? String(msg.style.username_separator)
        : "：";
    var layout = msg.style && msg.style.layout === "stacked" ? "stacked" : "inline";
    var usernameHtml = usernameEnabled
      ? '<div class="username">' + username + usernameSeparator + "</div>"
      : '<div class="username is-hidden"></div>';
    if (layout === "stacked") {
      card.innerHTML =
        usernameHtml +
        '<div class="bubble"><div class="content">' + content + "</div></div>";
    } else {
      card.innerHTML =
        usernameHtml +
        '<div class="content">' + content + "</div>";
    }
    applyEntryAnimationClass(card);
    // column-reverse places the first DOM child at the bottom. Prepending
    // keeps the newest card at the bottom and physically pushes older cards up.
    panel.prepend(card);
    removeOldestIfNeeded();
    animatePushedCards(previousTops);
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

  // Boot from query before WS config (click_through=0 → interactive/drag)
  try {
    var bootCt = new URLSearchParams(window.location.search).get("click_through");
    if (bootCt != null && bootCt !== "") {
      applyClickThroughMode(bootCt);
    }
  } catch (_e) {
    /* ignore */
  }

  connectWS();
})();
