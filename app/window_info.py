"""Foreground window information and activity classification (Windows only)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass


@dataclass
class WindowActivity:
    title: str
    exe_name: str
    pid: int


IDE_EXE_NAMES: frozenset[str] = frozenset({
    "Code.exe", "devenv.exe", "idea64.exe", "pycharm64.exe",
    "webstorm64.exe", "cursor.exe", "Codex.exe", "neovide.exe",
    "nvim-qt.exe", "gvim.exe", "sublime_text.exe", "atom.exe",
    "Rider64.exe", "clion64.exe", "goland64.exe",
})

BROWSER_EXE_NAMES: frozenset[str] = frozenset({
    "chrome.exe", "msedge.exe", "firefox.exe",
    "opera.exe", "brave.exe", "vivaldi.exe",
})

GAME_EXE_NAMES: frozenset[str] = frozenset({
    "LeagueClient.exe", "LeagueClientUx.exe",
    "Valorant.exe",
    "csgo.exe", "cs2.exe",
    "Overwatch.exe",
    "Minecraft.exe",
    "Dota2.exe",
    "GenshinImpact.exe", "YuanShen.exe",
    "StarCraft.exe",
    "GGEX.exe", "GGEX2.exe",
})

GAME_LAUNCHER_EXE_NAMES: frozenset[str] = frozenset({
    "Steam.exe", "WeGame.exe", "WeGameLauncher.exe",
})

CHAT_EXE_NAMES: frozenset[str] = frozenset({
    "WeChat.exe", "Discord.exe", "Telegram.exe",
    "TIM.exe", "QQ.exe", "Skype.exe",
})

GAME_KEYWORDS_IN_TITLE: frozenset[str] = frozenset({
    "英雄联盟", "League of Legends", "LOL",
    "无畏契约", "Valorant",
    "原神", "Genshin",
    "CS2", "Counter-Strike",
    "守望先锋", "Overwatch",
    "我的世界", "Minecraft",
    "刀塔", "Dota",
    "星际争霸", "StarCraft",
})

VIDEO_KEYWORDS_IN_TITLE: frozenset[str] = frozenset({
    "哔哩哔哩", "bilibili", "YouTube", "youtube",
    "爱奇艺", "优酷", "腾讯视频", "Netflix", "netflix",
})

GAME_NAME_FROM_EXE: dict[str, str] = {
    "LeagueClient.exe": "英雄联盟",
    "LeagueClientUx.exe": "英雄联盟",
    "Valorant.exe": "无畏契约",
    "csgo.exe": "CS:GO",
    "cs2.exe": "CS2",
    "Overwatch.exe": "守望先锋",
    "Minecraft.exe": "我的世界",
    "Dota2.exe": "刀塔2",
    "GenshinImpact.exe": "原神",
    "YuanShen.exe": "原神",
    "StarCraft.exe": "星际争霸",
}

IDE_NAME_FROM_EXE: dict[str, str] = {
    "Code.exe": "VS Code",
    "devenv.exe": "Visual Studio",
    "idea64.exe": "IntelliJ IDEA",
    "pycharm64.exe": "PyCharm",
    "webstorm64.exe": "WebStorm",
    "cursor.exe": "Cursor",
    "Codex.exe": "Codex",
    "Rider64.exe": "Rider",
    "clion64.exe": "CLion",
    "goland64.exe": "GoLand",
    "sublime_text.exe": "Sublime Text",
}

CHAT_NAME_FROM_EXE: dict[str, str] = {
    "WeChat.exe": "微信",
    "Discord.exe": "Discord",
    "Telegram.exe": "Telegram",
    "TIM.exe": "TIM",
    "QQ.exe": "QQ",
    "Skype.exe": "Skype",
}

GAME_LAUNCHER_NAME_FROM_EXE: dict[str, str] = {
    "Steam.exe": "Steam",
    "WeGame.exe": "WeGame",
    "WeGameLauncher.exe": "WeGame",
}

ACTIVITY_TYPE_IDE = "coding"
ACTIVITY_TYPE_BROWSER = "browsing"
ACTIVITY_TYPE_GAME = "game"
ACTIVITY_TYPE_GAME_LAUNCHER = "game_launcher"
ACTIVITY_TYPE_VIDEO = "video"
ACTIVITY_TYPE_CHAT = "chat"
ACTIVITY_TYPE_DESKTOP = "desktop"
ACTIVITY_TYPE_UNKNOWN = "unknown"

ACTIVITY_TYPES = frozenset({
    ACTIVITY_TYPE_IDE, ACTIVITY_TYPE_BROWSER, ACTIVITY_TYPE_GAME,
    ACTIVITY_TYPE_GAME_LAUNCHER, ACTIVITY_TYPE_VIDEO, ACTIVITY_TYPE_CHAT,
    ACTIVITY_TYPE_DESKTOP, ACTIVITY_TYPE_UNKNOWN,
})


@dataclass
class ActivityObservation:
    activity_type: str
    main_scene: str
    app_or_game_name: str
    topic_hint: str
    confidence: float
    observed_at: float = 0.0
    scene_generation: int = 0


def _extract_game_from_title(title: str) -> str:
    for keyword in GAME_KEYWORDS_IN_TITLE:
        if keyword in title:
            return keyword
    return ""


def _extract_topic_from_title(title: str) -> str:
    return ""


def classify_foreground_window(title: str, exe_name: str) -> ActivityObservation:
    if exe_name in IDE_EXE_NAMES:
        return ActivityObservation(
            activity_type=ACTIVITY_TYPE_IDE,
            main_scene="IDE",
            app_or_game_name=IDE_NAME_FROM_EXE.get(exe_name, ""),
            topic_hint=_extract_topic_from_title(title),
            confidence=0.9,
        )

    if exe_name in GAME_EXE_NAMES:
        game_name = GAME_NAME_FROM_EXE.get(exe_name, "") or _extract_game_from_title(title)
        return ActivityObservation(
            activity_type=ACTIVITY_TYPE_GAME,
            main_scene="游戏",
            app_or_game_name=game_name,
            topic_hint="",
            confidence=0.9 if game_name else 0.7,
        )

    if exe_name == "javaw.exe":
        game_name = _extract_game_from_title(title)
        if game_name:
            return ActivityObservation(
                activity_type=ACTIVITY_TYPE_GAME,
                main_scene="游戏",
                app_or_game_name=game_name,
                topic_hint="",
                confidence=0.8,
            )

    if exe_name in GAME_LAUNCHER_EXE_NAMES:
        launcher_name = GAME_LAUNCHER_NAME_FROM_EXE.get(exe_name, "")
        return ActivityObservation(
            activity_type=ACTIVITY_TYPE_GAME_LAUNCHER,
            main_scene="游戏启动器",
            app_or_game_name=launcher_name,
            topic_hint="",
            confidence=0.5,
        )

    if exe_name in BROWSER_EXE_NAMES:
        if any(k in title for k in VIDEO_KEYWORDS_IN_TITLE):
            return ActivityObservation(
                activity_type=ACTIVITY_TYPE_VIDEO,
                main_scene="浏览器",
                app_or_game_name="",
                topic_hint="",
                confidence=0.7,
            )
        return ActivityObservation(
            activity_type=ACTIVITY_TYPE_BROWSER,
            main_scene="浏览器",
            app_or_game_name="",
            topic_hint="",
            confidence=0.8,
        )

    if exe_name in CHAT_EXE_NAMES:
        return ActivityObservation(
            activity_type=ACTIVITY_TYPE_CHAT,
            main_scene="聊天",
            app_or_game_name=CHAT_NAME_FROM_EXE.get(exe_name, ""),
            topic_hint="",
            confidence=0.9,
        )

    if exe_name.lower() == "explorer.exe" or not title:
        return ActivityObservation(
            activity_type=ACTIVITY_TYPE_DESKTOP,
            main_scene="桌面",
            app_or_game_name="",
            topic_hint="",
            confidence=0.6,
        )

    if any(k in title for k in GAME_KEYWORDS_IN_TITLE):
        game_name = _extract_game_from_title(title)
        return ActivityObservation(
            activity_type=ACTIVITY_TYPE_GAME,
            main_scene="游戏",
            app_or_game_name=game_name,
            topic_hint="",
            confidence=0.7 if game_name else 0.5,
        )

    return ActivityObservation(
        activity_type=ACTIVITY_TYPE_UNKNOWN,
        main_scene="",
        app_or_game_name=exe_name,
        topic_hint="",
        confidence=0.3,
    )


def get_foreground_window_info() -> WindowActivity:
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return WindowActivity(title="", exe_name="", pid=0)

        title_buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title_buf, 256)
        title = title_buf.value

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        exe_name = _get_exe_name_for_pid(pid.value)

        return WindowActivity(title=title, exe_name=exe_name, pid=pid.value)
    except Exception:
        return WindowActivity(title="", exe_name="", pid=0)


def _get_exe_name_for_pid(pid: int) -> str:
    if pid <= 0:
        return ""
    try:
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(260)
            psapi.GetModuleFileNameExW(handle, None, buf, 260)
            full_path = buf.value
            if not full_path:
                return ""
            return full_path.split("\\")[-1]
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ""
