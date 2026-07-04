"""Desktop pet window and façade user-visible strings."""

TRANSLATIONS_ZH: dict[str, str] = {
    "pet.command_placeholder": "输入弹幕指令，Enter 提交，Esc 关闭",
    "pet.load_failed": "宠物加载失败",
    "pet.menu.stop_danmu": "停止弹幕",
    "pet.menu.start_danmu": "开始弹幕",
    "pet.menu.hide": "隐藏桌宠",
    "pet.menu.show": "显示桌宠",
    "pet.menu.settings": "桌宠设置",
    "pet.menu.close": "关闭桌宠",
    "pet.menu.quit_app": "退出应用",
    "pet.toast.command_queued": "已加入下一次弹幕生成",
    "pet.dialog.select_folder": "选择桌宠文件夹",
    "pet.dialog.select_slot_folder": "选择槽位 {slot} 桌宠文件夹",
    "pet.error.invalid_slot": "无效的桌宠槽位",
    "pet.error.invalidSpritesheetLayout": "pet.json spritesheetLayout 无效：{raw}（允许：{allowed}）",
    "pet.error.path_out_of_range": (
        "桌宠资源路径不在允许范围内：{path}。自定义资源必须放在 {allowed} 目录下。"
    ),
    "pet.error.missingPetJson": "缺少 pet.json：{path}",
    "pet.error.petJsonParseFailed": "pet.json 解析失败：{error}",
    "pet.error.petJsonMustBeObject": "pet.json 必须是 JSON 对象",
    "pet.error.petJsonMissingField": "pet.json 缺少必填字段：{field}",
    "pet.error.spritesheetNotFound": "找不到 spritesheet：{path}",
    "pet.error.spritesheetLoadFailed": "spritesheet 无法加载：{path}",
    "pet.error.spritesheetInvalidSize": "spritesheet 宽高须为 {frame_w}×{frame_h} 的整数倍，实际为 {width}×{height}",
    "pet.error.spritesheetInvalidGrid": "spritesheet 网格须在 1–{max_cols} 列、1–{max_rows} 行内，实际为 {cols}×{rows}",
    "pet.resourceLabel.local": "本地目录",
    "pet.resourceLabel.builtin": "内置默认",
    "pet.displayName.default": "默认桌宠",
    "pet.displayName.custom": "自定义桌宠",
    "pet.error.emptyCommand": "指令内容不能为空",
    "pet.error.slot_path_out_of_range": (
        "桌宠槽位资源路径不在允许范围内：{path}。自定义资源必须放在 {allowed} 目录下。"
    ),
    "pet.error.service_not_initialized": "桌宠指令服务未初始化",
    "pet.error.enable_pet_first": "请先启用桌宠",
}

TRANSLATIONS_EN: dict[str, str] = {
    "pet.command_placeholder": "Enter danmu command; Enter to submit, Esc to close",
    "pet.load_failed": "Failed to load pet",
    "pet.menu.stop_danmu": "Stop Danmu",
    "pet.menu.start_danmu": "Start Danmu",
    "pet.menu.hide": "Hide Pet",
    "pet.menu.show": "Show Pet",
    "pet.menu.settings": "Pet Settings",
    "pet.menu.close": "Close Pet",
    "pet.menu.quit_app": "Quit App",
    "pet.toast.command_queued": "Queued for the next danmu batch",
    "pet.dialog.select_folder": "Select pet folder",
    "pet.dialog.select_slot_folder": "Select pet folder for slot {slot}",
    "pet.error.invalid_slot": "Invalid pet slot",
    "pet.error.invalidSpritesheetLayout": "Invalid pet.json spritesheetLayout: {raw} (allowed: {allowed})",
    "pet.error.path_out_of_range": (
        "Pet asset path is not allowed: {path}. Custom assets must be under {allowed}."
    ),
    "pet.error.missingPetJson": "Missing pet.json: {path}",
    "pet.error.petJsonParseFailed": "Failed to parse pet.json: {error}",
    "pet.error.petJsonMustBeObject": "pet.json must be a JSON object",
    "pet.error.petJsonMissingField": "pet.json missing required field: {field}",
    "pet.error.spritesheetNotFound": "Spritesheet not found: {path}",
    "pet.error.spritesheetLoadFailed": "Failed to load spritesheet: {path}",
    "pet.error.spritesheetInvalidSize": "Spritesheet dimensions must be integer multiples of {frame_w}×{frame_h}; actual {width}×{height}",
    "pet.error.spritesheetInvalidGrid": "Spritesheet grid must be within 1–{max_cols} cols and 1–{max_rows} rows; actual {cols}×{rows}",
    "pet.resourceLabel.local": "Local directory",
    "pet.resourceLabel.builtin": "Built-in default",
    "pet.displayName.default": "Default Pet",
    "pet.displayName.custom": "Custom Pet",
    "pet.error.emptyCommand": "Command content cannot be empty",
    "pet.error.slot_path_out_of_range": (
        "Pet slot asset path is not allowed: {path}. Custom assets must be under {allowed}."
    ),
    "pet.error.service_not_initialized": "Pet command service is not initialized",
    "pet.error.enable_pet_first": "Enable the desktop pet first",
}
