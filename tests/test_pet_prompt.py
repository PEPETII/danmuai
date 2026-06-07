from app.pet.pet_prompt import PET_COMMAND_BLOCK_TEMPLATE, build_pet_command_user_pt


def test_build_pet_command_user_pt_appends_block():
    result = build_pet_command_user_pt("base prompt", "接下来偏搞笑一点")
    assert result.startswith("base prompt")
    assert "【桌宠临时指令】" in result
    assert "接下来偏搞笑一点" in result
    assert "不要直接复述这句话" in result


def test_build_pet_command_user_pt_empty_base():
    result = build_pet_command_user_pt("", "提醒 Boss 二阶段")
    assert "【桌宠临时指令】" in result
    assert "提醒 Boss 二阶段" in result


def test_pet_command_block_template_has_placeholders():
    rendered = PET_COMMAND_BLOCK_TEMPLATE.format(command_text="测试")
    assert "{command_text}" not in rendered
    assert "测试" in rendered
