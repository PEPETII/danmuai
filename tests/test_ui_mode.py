"""Web 桌面壳启动模式解析测试。"""

import os
import sys
from unittest.mock import patch

from main import _web_launch_mode_from_argv


def test_default_launch_mode_is_webview():
    with patch.object(sys, "argv", ["main.py"]):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DANMU_WEB_LAUNCH", None)
            assert _web_launch_mode_from_argv() == "webview"


def test_web_browser_flag():
    with patch.object(sys, "argv", ["main.py", "--web-browser"]):
        assert _web_launch_mode_from_argv() == "browser"


def test_web_launch_env_browser():
    with patch.object(sys, "argv", ["main.py"]):
        with patch.dict(os.environ, {"DANMU_WEB_LAUNCH": "browser"}, clear=False):
            assert _web_launch_mode_from_argv() == "browser"
