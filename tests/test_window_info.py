"""Tests for window_info classification logic."""

from app.window_info import (
    ACTIVITY_TYPE_BROWSER,
    ACTIVITY_TYPE_CHAT,
    ACTIVITY_TYPE_DESKTOP,
    ACTIVITY_TYPE_GAME,
    ACTIVITY_TYPE_GAME_LAUNCHER,
    ACTIVITY_TYPE_IDE,
    ACTIVITY_TYPE_UNKNOWN,
    ACTIVITY_TYPE_VIDEO,
    ActivityObservation,
    classify_foreground_window,
)


def _obs(exe: str, title: str = "") -> ActivityObservation:
    return classify_foreground_window(title, exe)


class TestIDEClassification:
    def test_vscode(self):
        o = _obs("Code.exe", "main.py - DanmuAI - Visual Studio Code")
        assert o.activity_type == ACTIVITY_TYPE_IDE
        assert o.app_or_game_name == "VS Code"
        assert o.confidence >= 0.9

    def test_pycharm(self):
        o = _obs("pycharm64.exe", "main.py – DanmuAI")
        assert o.activity_type == ACTIVITY_TYPE_IDE
        assert o.app_or_game_name == "PyCharm"

    def test_cursor(self):
        o = _obs("cursor.exe")
        assert o.activity_type == ACTIVITY_TYPE_IDE
        assert o.app_or_game_name == "Cursor"

    def test_sublime_text_no_leading_space(self):
        o = _obs("sublime_text.exe")
        assert o.activity_type == ACTIVITY_TYPE_IDE
        assert o.app_or_game_name == "Sublime Text"

    def test_codex(self):
        o = _obs("Codex.exe", "Codex")
        assert o.activity_type == ACTIVITY_TYPE_IDE
        assert o.app_or_game_name == "Codex"


class TestGameClassification:
    def test_league_of_legends(self):
        o = _obs("LeagueClient.exe", "英雄联盟 [在线]")
        assert o.activity_type == ACTIVITY_TYPE_GAME
        assert o.app_or_game_name == "英雄联盟"
        assert o.confidence >= 0.9

    def test_valorant(self):
        o = _obs("Valorant.exe", "VALORANT")
        assert o.activity_type == ACTIVITY_TYPE_GAME
        assert o.app_or_game_name == "无畏契约"

    def test_genshin(self):
        o = _obs("YuanShen.exe", "原神")
        assert o.activity_type == ACTIVITY_TYPE_GAME
        assert o.app_or_game_name == "原神"

    def test_unknown_game_exe(self):
        o = _obs("SomeGame.exe", "SomeGame")
        assert o.activity_type == ACTIVITY_TYPE_UNKNOWN

    def test_javaw_with_minecraft_title(self):
        o = _obs("javaw.exe", "Minecraft 1.20.4")
        assert o.activity_type == ACTIVITY_TYPE_GAME
        assert o.app_or_game_name == "Minecraft"

    def test_javaw_with_chinese_minecraft_title(self):
        o = _obs("javaw.exe", "我的世界 1.20")
        assert o.activity_type == ACTIVITY_TYPE_GAME
        assert o.app_or_game_name == "我的世界"

    def test_javaw_without_game_title(self):
        o = _obs("javaw.exe", "Some Java App")
        assert o.activity_type == ACTIVITY_TYPE_UNKNOWN

    def test_game_title_without_game_exe(self):
        o = _obs("unknown.exe", "英雄联盟 [排位赛]")
        assert o.activity_type == ACTIVITY_TYPE_GAME
        assert o.app_or_game_name == "英雄联盟"

    def test_game_exe_no_name_no_title_match(self):
        o = _obs("GGEX.exe", "Game Window")
        assert o.activity_type == ACTIVITY_TYPE_GAME
        assert o.app_or_game_name == ""
        assert o.confidence < 0.9


class TestGameLauncherClassification:
    def test_steam(self):
        o = _obs("Steam.exe", "Steam")
        assert o.activity_type == ACTIVITY_TYPE_GAME_LAUNCHER
        assert o.app_or_game_name == "Steam"
        assert o.confidence < 0.7

    def test_wegame(self):
        o = _obs("WeGame.exe", "WeGame")
        assert o.activity_type == ACTIVITY_TYPE_GAME_LAUNCHER
        assert o.app_or_game_name == "WeGame"

    def test_steam_not_classified_as_game(self):
        o = _obs("Steam.exe", "Steam Store")
        assert o.activity_type != ACTIVITY_TYPE_GAME


class TestBrowserClassification:
    def test_chrome(self):
        o = _obs("chrome.exe", "Google - Google Chrome")
        assert o.activity_type == ACTIVITY_TYPE_BROWSER
        assert o.main_scene == "浏览器"

    def test_edge(self):
        o = _obs("msedge.exe", "Microsoft Edge")
        assert o.activity_type == ACTIVITY_TYPE_BROWSER

    def test_firefox(self):
        o = _obs("firefox.exe", "Mozilla Firefox")
        assert o.activity_type == ACTIVITY_TYPE_BROWSER


class TestVideoClassification:
    def test_bilibili_in_chrome(self):
        o = _obs("chrome.exe", "哔哩哔哩 - 视频页面")
        assert o.activity_type == ACTIVITY_TYPE_VIDEO
        assert o.main_scene == "浏览器"

    def test_youtube_in_edge(self):
        o = _obs("msedge.exe", "YouTube - Some Video")
        assert o.activity_type == ACTIVITY_TYPE_VIDEO

    def test_iqiyi_in_firefox(self):
        o = _obs("firefox.exe", "爱奇艺 - 热播")
        assert o.activity_type == ACTIVITY_TYPE_VIDEO

    def test_chrome_without_video_keyword_is_browsing(self):
        o = _obs("chrome.exe", "Stack Overflow - Google Search")
        assert o.activity_type == ACTIVITY_TYPE_BROWSER


class TestChatClassification:
    def test_wechat(self):
        o = _obs("WeChat.exe", "微信")
        assert o.activity_type == ACTIVITY_TYPE_CHAT
        assert o.app_or_game_name == "微信"

    def test_discord(self):
        o = _obs("Discord.exe", "Discord")
        assert o.activity_type == ACTIVITY_TYPE_CHAT
        assert o.app_or_game_name == "Discord"

    def test_qq(self):
        o = _obs("QQ.exe", "QQ")
        assert o.activity_type == ACTIVITY_TYPE_CHAT


class TestDesktopClassification:
    def test_explorer(self):
        o = _obs("explorer.exe", "")
        assert o.activity_type == ACTIVITY_TYPE_DESKTOP

    def test_empty_title_unknown_exe(self):
        o = _obs("some.exe", "")
        assert o.activity_type == ACTIVITY_TYPE_DESKTOP


class TestUnknownClassification:
    def test_unknown_exe_unrelated_title(self):
        o = _obs("random.exe", "Some Random App")
        assert o.activity_type == ACTIVITY_TYPE_UNKNOWN
        assert o.confidence < 0.5

    def test_empty_exe(self):
        o = _obs("", "Some Title")
        assert o.activity_type == ACTIVITY_TYPE_UNKNOWN


class TestEdgeCases:
    def test_case_sensitivity_exe(self):
        o = _obs("code.exe", "main.py")
        assert o.activity_type == ACTIVITY_TYPE_UNKNOWN

    def test_empty_both(self):
        o = _obs("", "")
        assert o.activity_type == ACTIVITY_TYPE_DESKTOP

    def test_game_launcher_not_elevated_to_game(self):
        o = _obs("Steam.exe", "Steam")
        assert o.activity_type == ACTIVITY_TYPE_GAME_LAUNCHER
        assert o.activity_type != ACTIVITY_TYPE_GAME
