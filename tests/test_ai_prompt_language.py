"""AI prompt paths respect Translator language selection."""

from __future__ import annotations

import re

from app.meme_barrage.ai_select import build_meme_select_user_prompt
from app.mic_prompt import build_mic_insert_user_pt
from app.pet.pet_prompt import build_pet_command_user_pt
from app.translations import Translator

CJK = re.compile(r"[\u4e00-\u9fff]")


def test_pet_prompt_english():
    Translator.set_language("en")
    out = build_pet_command_user_pt("base", "hello pet")
    assert "Desktop pet" in out or "Pet command" in out
    assert not CJK.search(out)
    Translator.set_language("zh")


def test_mic_prompt_english():
    Translator.set_language("en")
    out = build_mic_insert_user_pt("base")
    assert "[Mic insert]" in out
    assert not CJK.search(out)
    Translator.set_language("zh")


def test_meme_select_user_prompt_english():
    Translator.set_language("en")
    out = build_meme_select_user_prompt(["line one", "line two"], 2)
    assert "candidate" in out.lower()
    assert not CJK.search(out)
    Translator.set_language("zh")
