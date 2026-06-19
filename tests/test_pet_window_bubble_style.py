"""W-PET-BUBBLE-STYLE-001 / W-PET-BUBBLE-MULTILINE-001: comic speech-bubble contracts."""

from app.pet.pet_window import (
    _BUBBLE_HEAD_ANCHOR_Y,
    _BUBBLE_MAX_ALPHA,
    _BUBBLE_RADIUS,
    PetWindow,
    bubble_band_height,
    bubble_colors,
    bubble_layout_width,
    compute_bubble_layout,
    window_content_width,
)
from main import DanmuApp
from PyQt6.QtGui import QFont, QFontMetricsF, QPainter, QPixmap

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import FakeConfig


def _layout_for_side(*, window_x: int, geo_center_x: float, pet_w: int = 192, sprite_y: int | None = None):
    if sprite_y is None:
        sprite_y = bubble_band_height()
    pixmap = QPixmap(1, 1)
    painter = QPainter(pixmap)
    try:
        return compute_bubble_layout(
            pet_w=pet_w,
            sprite_y=sprite_y,
            command_band_y=0,
            bubble_text="测试弹幕",
            painter=painter,
            geo_center_x=geo_center_x,
            window_x=window_x,
        )
    finally:
        painter.end()


def test_bubble_colors_light_theme():
    bg, border, text = bubble_colors(0.92)
    assert bg.red() > 200 and bg.green() > 200 and bg.blue() > 200
    assert text.red() < 80 and text.green() < 80 and text.blue() < 80
    assert border.red() < 80
    assert bg.getRgb()[0:3] != (30, 30, 38)
    assert text.getRgb()[0:3] != (255, 255, 255)


def test_bubble_radius_increased():
    assert _BUBBLE_RADIUS >= 20


def test_compute_bubble_layout_side_flip(qapp):
    pet_w = 192
    left_side = _layout_for_side(window_x=100, geo_center_x=1000, pet_w=pet_w)
    right_side = _layout_for_side(window_x=1800, geo_center_x=1000, pet_w=pet_w)
    assert left_side is not None
    assert right_side is not None
    assert left_side.show_left is False
    assert right_side.show_left is True
    assert left_side.bubble_x == 0
    assert left_side.sprite_x == 0
    assert right_side.bubble_x == 0
    overflow = window_content_width(pet_w) - pet_w
    assert right_side.sprite_x == float(overflow)


def test_compute_bubble_layout_bubble_stays_inside_window(qapp):
    pet_w = 192
    layout = _layout_for_side(window_x=1800, geo_center_x=1000, pet_w=pet_w)
    assert layout is not None
    content_w = window_content_width(pet_w)
    assert layout.bubble_x >= 0
    assert layout.bubble_x + layout.bubble_w <= content_w
    assert layout.bubble_w == bubble_layout_width(pet_w)


def test_compute_bubble_layout_vertical_anchor(qapp):
    sprite_y = 200
    layout = _layout_for_side(window_x=100, geo_center_x=1000, sprite_y=sprite_y)
    assert layout is not None
    assert layout.tail_tip_y == sprite_y + _BUBBLE_HEAD_ANCHOR_Y
    assert layout.tail_tip_y > layout.bubble_y + layout.bubble_h
    assert layout.bubble_y + layout.bubble_h < sprite_y


def test_compute_bubble_layout_long_chinese_text_keeps_document_height(qapp):
    pixmap = QPixmap(1, 1)
    painter = QPainter(pixmap)
    font = QFont("Microsoft YaHei", 10)
    painter.setFont(font)
    text = "多行中文气泡回归验证文本" * 8
    try:
        layout = compute_bubble_layout(
            pet_w=192,
            sprite_y=bubble_band_height(),
            command_band_y=0,
            bubble_text=text,
            painter=painter,
            geo_center_x=1000,
            window_x=100,
        )
    finally:
        painter.end()
    assert layout is not None
    line_spacing = QFontMetricsF(font).lineSpacing()
    assert layout.text_document.size().height() >= line_spacing * 3
    assert layout.text_rect.height() >= layout.text_document.size().height()


def test_set_bubble_text_fade_target_unchanged(qapp):
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, config=FakeConfig({"pet_asset_source": "builtin", "pet_scale": "1.0"}))
    window = PetWindow(app)
    window.set_bubble_text("hello")
    assert window._bubble_target_alpha == _BUBBLE_MAX_ALPHA
    window.set_bubble_text("")
    assert window._bubble_target_alpha == 0.0
    window.close()
