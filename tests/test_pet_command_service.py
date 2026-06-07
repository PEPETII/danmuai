import time

import pytest

from app.pet.pet_command_service import MAX_COMMAND_LEN, PetCommandService


def test_submit_rejects_empty():
    svc = PetCommandService()
    with pytest.raises(ValueError, match="不能为空"):
        svc.submit("", ttl_sec=30, apply_count=1)


def test_submit_truncates_to_200_chars():
    svc = PetCommandService()
    text = "a" * 250
    result = svc.submit(text, ttl_sec=30, apply_count=1)
    assert result["ok"] is True
    assert svc.has_pending()
    consumed = svc.consume_for_prompt()
    assert consumed is not None
    assert len(consumed) == MAX_COMMAND_LEN


def test_max_one_pending_replaces_previous():
    svc = PetCommandService()
    svc.submit("first", ttl_sec=30, apply_count=1)
    svc.submit("second", ttl_sec=30, apply_count=1)
    assert svc.consume_for_prompt() == "second"


def test_ttl_expiry_purges_on_peek():
    svc = PetCommandService()
    svc.submit("expire me", ttl_sec=1, apply_count=1)
    svc._pending.created_at = time.monotonic() - 5  # noqa: SLF001
    assert not svc.has_pending()
    assert svc.consume_for_prompt() is None


def test_apply_count_decrements_before_clear():
    svc = PetCommandService()
    svc.submit("multi", ttl_sec=30, apply_count=2)
    assert svc.consume_for_prompt() == "multi"
    assert svc.has_pending()
    assert svc.consume_for_prompt() == "multi"
    assert not svc.has_pending()
