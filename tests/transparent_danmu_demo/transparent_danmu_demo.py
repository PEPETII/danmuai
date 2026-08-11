"""Minimal pywebview + Edge WebView2 transparent danmu demo.

This file is intentionally standalone. It does not import or start DanmuAI's
production application, web server, overlay, or websocket stack.
"""

from __future__ import annotations

import sys
from pathlib import Path

import webview

DEMO_HTML = Path(__file__).with_name("index.html").resolve()


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("This demo requires Windows WebView2 (EdgeChromium).")

    webview.create_window(
        "DanmuAI transparent WebView2 demo",
        url=DEMO_HTML.as_uri(),
        width=760,
        height=420,
        resizable=False,
        frameless=True,
        easy_drag=False,
        shadow=False,
        focus=True,
        on_top=True,
        background_color="#000000",
        transparent=True,
        text_select=False,
        zoomable=False,
        draggable=False,
    )
    webview.start(gui="edgechromium", debug=False)


if __name__ == "__main__":
    main()
