from app.pet.pet_prompt import (
    PET_COMMAND_BLOCK_TEMPLATE,
    append_pet_command_to_system_pt,
    build_pet_command_user_pt,
)


def test_build_pet_command_user_pt_appends_block():
    result = build_pet_command_user_pt("base prompt", "接下来偏搞笑一点")
    assert result.startswith("base prompt")
    assert "【桌宠观众指令 · 本批优先】" in result
    assert "接下来偏搞笑一点" in result
    assert "至少半数弹幕要围绕或呼应这条指令" in result
    assert "不能只评论画面而忽略指令" in result


def test_build_pet_command_user_pt_empty_base():
    result = build_pet_command_user_pt("", "提醒 Boss 二阶段")
    assert "【桌宠观众指令 · 本批优先】" in result
    assert "提醒 Boss 二阶段" in result


def test_append_pet_command_to_system_pt():
    result = append_pet_command_to_system_pt("contract sys", "你们好")
    assert result.startswith("contract sys")
    assert "桌宠指令：你们好" in result
    assert "不可忽视" in result


def test_append_pet_command_to_system_pt_empty_command():
    assert append_pet_command_to_system_pt("sys", "") == "sys"
    assert append_pet_command_to_system_pt("sys", "   ") == "sys"


def test_pet_command_block_template_has_placeholders():
    rendered = PET_COMMAND_BLOCK_TEMPLATE.format(command_text="测试")
    assert "{command_text}" not in rendered
    assert "测试" in rendered
