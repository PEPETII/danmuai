"""启动与入口辅助函数（W-REFACTOR-MAIN-001）。

职责边界：
- 废弃启动参数检测（--qt-ui / --legacy-ui / DANMU_WEB_CONSOLE=0 → sys.exit(2)）
- Web 启动模式解析（webview vs browser）
- 全局异常钩子（global_exception_hook）
- 启动提示与错误对话框（show_startup_notice、QMessageBox）

与 DanmuApp 关系：main.py 在 DanmuApp.__init__ 之前调用这些函数。
本模块不依赖 DanmuApp 实例。

代码归属判断：应用启动前的环境检测、参数解析、错误提示放这里。
"""

from __future__ import annotations

import os
import sys
import traceback

from PyQt6.QtWidgets import QApplication, QMessageBox

from app.logger import SanitizedLogger
from app.translations import tr

DEPRECATED_LAUNCH_MSG = (
    "已移除 Qt 主窗（--qt-ui）。请使用: python main.py 或 python main.py --web-browser\n"
    "设置、日志、人格均在 Web 控制台（http://127.0.0.1:18765）。\n"
)


def check_deprecated_launch_args() -> None:
    reasons: list[str] = []
    if "--qt-ui" in sys.argv or "--legacy-ui" in sys.argv:
        reasons.append("命令行参数 --qt-ui / --legacy-ui")
    env_qt = os.environ.get("DANMU_QT_UI", "").strip().lower()
    if env_qt in ("1", "true", "yes", "on"):
        reasons.append("环境变量 DANMU_QT_UI")
    env_web = os.environ.get("DANMU_WEB_CONSOLE", "").strip().lower()
    if env_web in ("0", "false", "no", "off"):
        reasons.append("环境变量 DANMU_WEB_CONSOLE=0")
    if not reasons:
        return
    sys.stderr.write(DEPRECATED_LAUNCH_MSG)
    sys.stderr.write("废弃入口: " + "、".join(reasons) + "\n")
    sys.exit(2)


def web_launch_mode_from_argv() -> str:
    """webview = pywebview 桌面窗（默认）；browser = 系统浏览器。"""
    if "--web-browser" in sys.argv:
        return "browser"
    env = os.environ.get("DANMU_WEB_LAUNCH", "").strip().lower()
    if env in ("browser", "webview"):
        return env
    return "webview"


def global_exception_hook(exc_type, exc_value, exc_tb) -> None:
    if exc_type in (KeyboardInterrupt, SystemExit):
        return
    message = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        logger = SanitizedLogger()
        logger.error(tr("app.unhandled_exception_log").format(message=message))
    except Exception:
        import re

        safe_message = re.sub(r"sk-[A-Za-z0-9_-]{20,}", "sk-****", message)
        print(f"FATAL: {safe_message}", file=sys.stderr)
    if issubclass(exc_type, RuntimeError) and "has been deleted" in str(exc_value):
        return
    try:
        if QApplication.instance() is not None:
            msg_box = QMessageBox(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle(tr("app.error_title"))
            msg_box.setText(tr("app.error_friendly_message"))
            msg_box.setDetailedText(message)
            msg_box.exec()
    except Exception:
        pass
    sys.exit(1)


def show_startup_notice_if_needed(config, logger) -> bool:
    notice = config.get_startup_notice()
    if not notice:
        return False
    logger.info(notice)
    QMessageBox.information(None, tr("app.window_title"), notice)
    return True
