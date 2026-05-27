
import pytest
from app.bundle_paths import is_frozen, project_root, resource_path

from tests.conftest import _ensure_feedback_static_images


def test_project_root_is_repo_in_dev():
    assert not is_frozen()
    root = project_root()
    assert (root / "main.py").is_file()
    assert (root / "web" / "static" / "index.html").is_file()


def test_resource_path_data_pool():
    pool = resource_path("data", "danmu_pool_zh.json")
    assert pool.is_file()
    assert pool.parent == project_root() / "data"


def test_feedback_static_images_packaged():
    root = project_root()
    _ensure_feedback_static_images()
    for name in (
        "qrcode_1779738450536.jpg",
        "mm_reward_qrcode_1779738306814.png",
    ):
        path = root / "web" / "static" / "image" / name
        src = root / "image" / name
        if not path.is_file() and not src.is_file():
            pytest.skip(f"feedback assets missing: {src}")
        assert path.is_file(), f"missing {path}; run python scripts/copy_feedback_images.py"
        assert path.stat().st_size > 0


def test_feedback_page_in_index_html():
    html = (project_root() / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'data-page="feedback"' in html
    assert 'id="page-feedback"' in html
    assert 'id="feedbackForm"' in html
    assert 'id="feedbackContent"' in html
    assert "/static/image/qrcode_1779738450536.jpg" in html
    assert 'id="rewardModal"' in html


def test_announcements_page_in_index_html():
    html = (project_root() / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'data-page="announcements"' in html
    assert 'id="page-announcements"' in html
    assert 'id="announcementsList"' in html
    assert 'id="announcementsNavBadge"' in html
    assert "/static/supabase-client.js" in html


def test_memory_settings_visible_in_simplified_mode():
    """记忆控件不得带 settings-full-only，否则简化模式下会被 CSS 隐藏。"""
    html = (project_root() / "web" / "static" / "index.html").read_text(encoding="utf-8")
    for field_id in ("memory_mode", "memory_window"):
        idx = html.index(f'id="{field_id}"')
        chunk = html[max(0, idx - 120) : idx]
        assert "settings-full-only" not in chunk, field_id
