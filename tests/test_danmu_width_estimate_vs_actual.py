"""UG-04: DanmuEngine 宽度估算与实际测量对比验证。

验证 _estimate_char_width / _estimate_content_width 的动态估算精度，
以及 add_text() 使用估算值（非固定 len*25 常数）的行为。
"""

import pytest

from PyQt6.QtGui import QFont, QFontMetrics
from PyQt6.QtWidgets import QApplication

from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine
from app.danmu_engine_models import _DANMU_FALLBACK_CHAR_WIDTH, DanmuItem, Track
from tests.conftest import bind_minimal_danmu_app
from tests.fakes import FakeConfig

# ── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture()
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def engine(workspace_tmp):
    db_path = workspace_tmp / "config.db"
    store = ConfigStore(db_path=db_path)
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "2")
    eng = DanmuEngine(store)
    eng.recent.clear()
    eng.recent_exact_set.clear()
    eng.screen_width = 1920.0
    return eng


def _make_engine(font_size: int = 24, bold: str = "1") -> DanmuEngine:
    """用 FakeConfig 快速创建指定字体参数的引擎（无 DB）。"""
    cfg = FakeConfig(
        {
            "danmu_speed": "2.0",
            "font_size": str(font_size),
            "danmu_font_bold": bold,
        }
    )
    eng = DanmuEngine(cfg)
    eng.screen_width = 1920.0
    return eng


def _actual_width(content: str, font_size: int = 24, bold: bool = True) -> float:
    """用 QFontMetrics 测量实际渲染宽度（需 QApplication）。"""
    font = QFont("Microsoft YaHei", font_size)
    font.setBold(bold)
    return float(QFontMetrics(font).horizontalAdvance(content))


# ── _estimate_char_width ───────────────────────────────────────────────────


class TestEstimateCharWidth:
    def test_default_font_size_24_bold(self):
        eng = _make_engine(24, "1")
        w = eng._estimate_char_width()
        # 24 * 1.08 = 25.92
        assert w == pytest.approx(25.92, abs=0.01)

    def test_font_size_12(self):
        eng = _make_engine(12, "1")
        w = eng._estimate_char_width()
        assert w == pytest.approx(12.96, abs=0.01)

    def test_font_size_48(self):
        eng = _make_engine(48, "1")
        w = eng._estimate_char_width()
        assert w == pytest.approx(51.84, abs=0.01)

    def test_non_bold_smaller(self):
        eng_bold = _make_engine(24, "1")
        eng_normal = _make_engine(24, "0")
        assert eng_bold._estimate_char_width() > eng_normal._estimate_char_width()
        ratio = eng_bold._estimate_char_width() / eng_normal._estimate_char_width()
        assert ratio == pytest.approx(1.08, abs=0.01)

    def test_default_fallback(self):
        cfg = FakeConfig({"danmu_speed": "2.0"})
        eng = DanmuEngine(cfg)
        # 无 font_size 配置时 fallback 到 24
        assert eng._estimate_char_width() == pytest.approx(25.92, abs=0.01)


# ── _estimate_content_width ────────────────────────────────────────────────


class TestEstimateContentWidth:
    def test_pure_cjk(self):
        eng = _make_engine(24, "1")
        content = "这是一条中文弹幕测试内容"
        w = eng._estimate_content_width(content)
        # 全部全角字符：12 * 25.92 = 311.04
        assert w == pytest.approx(311.04, abs=0.5)

    def test_pure_ascii(self):
        eng = _make_engine(24, "1")
        content = "Hello World Test"
        w = eng._estimate_content_width(content)
        char_w = eng._estimate_char_width()
        # 16 个半角字符 * char_width * 0.55
        expected = 16 * char_w * 0.55
        assert w == pytest.approx(expected, abs=0.5)

    def test_mixed_cjk_ascii(self):
        eng = _make_engine(24, "1")
        content = "Hello世界你好World"
        w = eng._estimate_content_width(content)
        char_w = eng._estimate_char_width()
        # 4 个全角 + 10 个半角
        expected = 4 * char_w + 10 * char_w * 0.55
        assert w == pytest.approx(expected, abs=0.5)

    def test_mixed_narrower_than_len_times_constant(self):
        """中英混合文本的估算应小于 len*char_width（旧式估算法）。"""
        eng = _make_engine(24, "1")
        content = "Test测试ABC"
        new_way = eng._estimate_content_width(content)
        old_way = len(content) * 25.0
        # 新方法区分了半角字符，应更小
        assert new_way < old_way

    def test_empty_string(self):
        eng = _make_engine(24, "1")
        assert eng._estimate_content_width("") == 0.0

    def test_single_char(self):
        eng = _make_engine(24, "1")
        w = eng._estimate_content_width("字")
        assert w == pytest.approx(eng._estimate_char_width(), abs=0.5)

    def test_respects_font_size_scaling(self):
        eng_small = _make_engine(12, "1")
        eng_large = _make_engine(48, "1")
        content = "弹幕文字"
        w_small = eng_small._estimate_content_width(content)
        w_large = eng_large._estimate_content_width(content)
        # 大字号估算应约为小字号的 4 倍
        ratio = w_large / w_small
        assert ratio == pytest.approx(4.0, rel=0.05)


# ── 估算值 vs QFontMetrics 实际值对比（需要 QApplication） ───────────────


class TestEstimateVsActual:
    """用 QFontMetrics 做实际测量，验证估算误差在合理范围内。"""

    def test_pure_cjk_within_tolerance(self, qapp):
        eng = _make_engine(24, "1")
        content = "这是一条二十个字的中文弹幕内容用于测试"[:20]
        estimated = eng._estimate_content_width(content)
        actual = _actual_width(content, 24, True)
        # 允许 ±30% 误差
        assert estimated > actual * 0.7
        assert estimated < actual * 1.3

    def test_pure_ascii_within_tolerance(self, qapp):
        eng = _make_engine(24, "1")
        content = "This is a longer English sentence for testing width estimate"
        estimated = eng._estimate_content_width(content)
        actual = _actual_width(content, 24, True)
        assert estimated > actual * 0.7
        assert estimated < actual * 1.3

    def test_mixed_within_tolerance(self, qapp):
        eng = _make_engine(24, "1")
        content = "Hello世界这是一个Mixed中英混合Content测试Text"
        estimated = eng._estimate_content_width(content)
        actual = _actual_width(content, 24, True)
        assert estimated > actual * 0.7
        assert estimated < actual * 1.3

    def test_font_size_12_within_tolerance(self, qapp):
        eng = _make_engine(12, "0")
        content = "小字体弹幕测试内容十二个字左右"
        estimated = eng._estimate_content_width(content)
        actual = _actual_width(content, 12, False)
        assert estimated > actual * 0.7
        assert estimated < actual * 1.3

    def test_font_size_48_within_tolerance(self, qapp):
        eng = _make_engine(48, "1")
        content = "大字体弹幕测试"
        estimated = eng._estimate_content_width(content)
        actual = _actual_width(content, 48, True)
        assert estimated > actual * 0.7
        assert estimated < actual * 1.3


# ── add_text() 集成验证 ───────────────────────────────────────────────────


class TestAddTextUsesDynamicEstimate:
    def test_add_text_item_width_not_old_constant(self, engine):
        """add_text 设置的 item.width 不应等于旧的 len*25.0。"""
        item = engine.add_text("测试弹幕宽度估算")
        assert item is not None
        old_style = len("测试弹幕宽度估算") * 25.0
        # 新估算基于 font_size=24/bold → 每全角字 ~25.92px
        # 8 个全角字 ≈ 207.36，不等于 8*25=200
        assert item.width != old_style

    def test_add_text_item_width_matches_estimate(self, engine):
        """add_text 设置的 item.width 应等于 _estimate_content_width 返回值。"""
        content = "验证动态估算宽度是否生效"
        expected = engine._estimate_content_width(content)
        item = engine.add_text(content)
        assert item is not None
        assert item.width == pytest.approx(expected, abs=0.5)

    def test_add_text_long_cjk(self, engine):
        engine.config.set("danmu_max_chars", "40")
        content = "这是一条很长的中文弹幕用于测试宽度估算在高密度场景下的行为表现"
        item = engine.add_text(content)
        assert item is not None
        assert item.width > 0
        # 应显著不同于旧式估算
        old = len(content) * 25.0
        assert abs(item.width - old) / old > 0.03  # 至少 3% 差异


# ── Track can_accept 与估算一致性 ─────────────────────────────────────────


class TestTrackCanAcceptWithEstimatedWidth:
    def test_can_accept_uses_estimated_not_constant(self):
        track = Track(y=0.0)
        eng = _make_engine(36, "1")

        # 先添加一条占位弹幕
        item1 = DanmuItem(content="第一条占位弹幕用于测试轨道入口区判断逻辑")
        item1.x = 1600.0
        item1.width = eng._estimate_content_width(item1.content)
        track.add(item1)

        # 用相同引擎的估算宽度判断新弹幕能否被接受
        item2 = DanmuItem(content="新弹幕")
        item2.width = eng._estimate_content_width(item2.content)
        min_gap = max(80.0, item2.width * 0.5)

        screen_width = 1920.0
        can = track.can_accept(item2, screen_width, min_gap)
        # can_accept 基于 item1.width (估算值) 和 item2.width (估算值) 判断
        # 只验证不抛异常且返回 bool
        assert isinstance(can, bool)


# ── _DANMU_FALLBACK_CHAR_WIDTH 常量一致性 ────────────────────────────────


class TestFallbackConstant:
    def test_constant_value(self):
        assert _DANMU_FALLBACK_CHAR_WIDTH == 25.0

    def test_item_right_edge_uses_constant(self):
        item = DanmuItem(content="test")
        item.x = 100.0
        item.width = 0.0  # 触发 fallback 路径
        edge = Track.item_right_edge(item)
        expected = 100.0 + len("test") * _DANMU_FALLBACK_CHAR_WIDTH
        assert edge == expected

    def test_can_accept_uses_constant(self):
        track = Track(y=0.0)
        last = DanmuItem(content="existing")
        last.x = 500.0
        last.width = 0.0  # 触发 fallback
        track.add(last)

        new_item = DanmuItem(content="new")
        new_item.width = 100.0
        result = track.can_accept(new_item, 1920.0, 150.0)
        # 基于 fallback 宽度计算，只验证不异常
        assert isinstance(result, bool)
