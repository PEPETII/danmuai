"""桌宠在 stop() 停止弹幕时应保持可见（与弹幕 Overlay 解耦）。"""

from unittest.mock import Mock

from main import DanmuApp

from tests.conftest import FakeTimer, make_minimal_danmu_app


def test_stop_does_not_hide_pet_window():
    app = make_minimal_danmu_app()
    pet_window = Mock()
    pet_window.isVisible = Mock(return_value=True)
    pet_window.hide_pet = Mock()
    pet_window.stop_render_loop = Mock()
    app.pet_window = pet_window
    app.engine.running = True
    app.config.set_batch({"pet_enabled": "1", "pet_visible": "1"})
    app._pool_topup_timer = FakeTimer()
    app._mic_orchestrator = Mock(stop_detector=Mock())
    app._sync_mic_service = Mock()
    app.overlay = Mock(stop_render_loop=Mock(), hide=Mock())
    app.tray = Mock(update_state=Mock())
    app.state_changed = Mock(emit=Mock())
    app.stop = DanmuApp.stop.__get__(app, DanmuApp)

    app.stop()

    pet_window.hide_pet.assert_not_called()
    pet_window.stop_render_loop.assert_not_called()
