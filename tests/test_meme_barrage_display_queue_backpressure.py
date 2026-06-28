"""BUG-14: MemeBarrageService display queue backpressure — enqueue capacity trim."""

from app.config_store import ConfigStore
from app.meme_barrage.config import DISPLAY_QUEUE_MAX
from app.meme_barrage.service import MemeBarrageService


def _make_service(tmp_path) -> MemeBarrageService:
    config = ConfigStore(db_path=tmp_path / "backpressure.db")
    return MemeBarrageService(config)


def test_enqueue_under_limit_no_trim(tmp_path):
    """入队 <= DISPLAY_QUEUE_MAX 条时，全部保留，不触发裁剪。"""
    service = _make_service(tmp_path)
    count = DISPLAY_QUEUE_MAX  # 500
    added = service.enqueue_display([f"item-{i}" for i in range(count)])
    assert added == count
    assert service.display_queue_size() == count


def test_enqueue_over_limit_trims_oldest(tmp_path):
    """入队 > DISPLAY_QUEUE_MAX 条时，超出部分被裁剪，队列长度 = DISPLAY_QUEUE_MAX。"""
    service = _make_service(tmp_path)
    total = DISPLAY_QUEUE_MAX + 200  # 700
    added = service.enqueue_display([f"item-{i}" for i in range(total)])
    assert added == total  # 返回值是实际 append 数（含后被裁剪的）
    assert service.display_queue_size() == DISPLAY_QUEUE_MAX


def test_trimmed_items_are_oldest(tmp_path):
    """裁剪后队列中保留的是最新入队的条目（FIFO：最旧的先丢弃）。"""
    service = _make_service(tmp_path)
    total = DISPLAY_QUEUE_MAX + 100
    items = [f"line-{i}" for i in range(total)]
    service.enqueue_display(items)

    # 队列中应保留最后 DISPLAY_QUEUE_MAX 条
    remaining = list(service.pop_display_batch(DISPLAY_QUEUE_MAX))
    expected = items[total - DISPLAY_QUEUE_MAX :]
    assert remaining == expected
    # 最旧的条目已被丢弃
    assert "line-0" not in remaining
    assert "line-99" not in remaining
    # 最新条目仍在
    assert remaining[-1] == f"line-{total - 1}"


def test_multiple_enqueues_accumulate_then_trim(tmp_path):
    """多次小批量入队累计超过限制后触发裁剪。"""
    service = _make_service(tmp_path)
    batch_size = 100

    # 前 5 批：500 条 = 刚好到上限，不裁剪
    for i in range(5):
        service.enqueue_display([f"batch{i}-item{j}" for j in range(batch_size)])
    assert service.display_queue_size() == DISPLAY_QUEUE_MAX

    # 第 6 批：超出上限，触发裁剪
    service.enqueue_display([f"batch5-item{j}" for j in range(batch_size)])
    assert service.display_queue_size() == DISPLAY_QUEUE_MAX


def test_empty_texts_do_not_affect_queue(tmp_path):
    """空字符串和空列表不影响裁剪逻辑。"""
    service = _make_service(tmp_path)
    # 先填入一些数据
    service.enqueue_display(["a", "b", "c"])
    assert service.display_queue_size() == 3

    # 入队空/空白字符串（None 经 str(None) → "None" 会通过过滤，这是 enqueue_display 的已有行为）
    added = service.enqueue_display(["", "  ", ""])
    assert added == 0
    assert service.display_queue_size() == 3

    # 入队空列表
    added2 = service.enqueue_display([])
    assert added2 == 0
    assert service.display_queue_size() == 3
