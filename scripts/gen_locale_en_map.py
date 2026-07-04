"""Generate locale_en_strings.json — zh text -> en text for all UI strings."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ZH_LIST = ROOT / "_zh_strings_list.json"
OUT = ROOT / "locale_en_strings.json"

# Ordered phrase replacements (longest first) for prose translation
PHRASES: list[tuple[str, str]] = [
    ("DanmuAI - 你的温馨弹幕小助手", "DanmuAI - Your Cozy Danmu Assistant"),
    ("视觉模型服务的网址。火山方舟豆包一般填到 /api/v3；多数 OpenAI 兼容服务填到 /v1。",
     "Visual model service URL. Volcengine Ark (Doubao) usually uses /api/v3; most OpenAI-compatible services use /v1."),
    ("doubao：火山方舟豆包。openai：其他兼容 Chat 接口的服务（如部分第三方中转）。",
     "doubao: Volcengine Ark (Doubao). openai: other Chat-compatible services (e.g. some third-party proxies)."),
    ("开启时开麦与识图共用上方「API 与模型」的接口与模型；关闭后可在本标签单独配置支持麦克风的模型。",
     "When on, mic uses the same API & model as capture above; when off, configure a mic-capable model in this tab."),
    ("为麦克风接话选择服务商预设，会自动填入麦克风 API 地址与模式。OpenAI 兼容类预设不保证支持音频，需模型声明支持或在模型配置档案中勾选「支持麦克风」。",
     "Pick a provider preset for mic replies; fills mic API endpoint and mode. OpenAI-compatible presets may not support audio—check model docs or enable「Supports microphone」in model profiles."),
    ("麦克风专用 API 地址。豆包一般填到 /api/v3；MiMo 等 OpenAI 兼容服务填到 /v1。",
     "Mic-only API endpoint. Doubao usually /api/v3; MiMo and OpenAI-compatible services /v1."),
    ("麦克风请求使用的 API 模式。开麦需 doubao 全模态或 MiMo 的 mimo-v2.5。",
     "API mode for mic requests. Mic needs doubao multimodal or MiMo mimo-v2.5."),
    ("听懂麦克风并生成接话弹幕的模型；与识图视觉模型可不同。",
     "Model that hears the mic and generates reply danmu; can differ from the vision model."),
    ("麦克风专用 API 密钥，与识图密钥分开加密保存。留空保存不会覆盖已有密钥。",
     "Mic API key, encrypted separately from capture key. Blank save won't overwrite existing key."),
    ("实际调用的模型名称或接入点 ID。也可在下方「模型配置档案」里保存多套 endpoint/密钥/模型。",
     "Model name or endpoint ID. You can also save multiple endpoint/key/model sets in「Model profiles」below."),
    ("截图和弹幕叠在哪块显示器上。编号无效时会自动改用主屏。",
     "Which display to capture and overlay danmu on. Invalid index falls back to primary display."),
    ("创意程度（0–2）。越高弹幕用词越发散，越低越稳定、越像固定话术。",
     "Creativity (0–2). Higher = more varied wording; lower = steadier, more formulaic tone."),
    ("单次 AI 回复允许的最长输出。开启「思考」类模型时，程序会自动提高实际下限。",
     "Max output length per AI reply. Thinking models get a higher effective minimum automatically."),
    ("实验功能：说完一句话后额外生成几条接话弹幕，插队显示，不影响看屏识图节奏。需豆包接口且模型支持麦克风；默认关，录音仅在内存、不落盘。使用 Windows「设置 → 系统 → 声音 → 输入」里的默认麦克风；换耳机后建议先停弹幕再开或重启应用。",
     "Experimental: after you speak, extra reply danmu are generated and插队 shown without affecting capture rhythm. Needs Doubao + mic-capable model; off by default; audio stays in memory only. Uses Windows default mic (Settings → System → Sound → Input); after switching headsets, stop danmu or restart."),
    ("每次说话时，附带最近多少秒的麦克风录音发给 AI（1–30 秒，默认 5）。",
     "Seconds of recent mic audio sent with each utterance (1–30, default 5)."),
    ("录大约 3 秒，检查麦克风是否有声音。不联网、不上传、不保存文件。",
     "Records ~3s to check mic input. No network, upload, or file save."),
    ("录大约 3 秒后，把声音和占位图发给 AI，确认模型能收到你的麦克风输入。",
     "After ~3s, sends audio + placeholder image to AI to verify mic input."),
    ("访问 AI 的密钥，保存在本机并加密。留空点「保存配置」不会覆盖已有密钥。",
     "API key stored locally encrypted. Leaving blank on Save won't overwrite existing key."),
    ("普通模式下，每隔多少秒识图并生成一批弹幕（1–60 秒）。",
     "In normal mode, seconds between capture and danmu batch (1–60)."),
    ("普通模式下，每次识图固定生成几条弹幕（1–50 条）。",
     "In normal mode, fixed danmu count per capture (1–50)."),
    ("弹幕横向移动快慢（约 0.5–5）。数字越大滚得越快。",
     "Horizontal danmu speed (~0.5–5). Higher = faster scroll."),
    ("屏幕上最多几行弹幕轨道（12–20 行）。",
     "Max danmu track rows on screen (12–20)."),
    ("AI 生成弹幕最多显示多少字（5–80），超出会截断并加省略号。公式化弹幕（自定义库、烂梗）完整展示。未填写时默认中文约 15、英文约 40。",
     "Max characters for AI danmu (5–80); excess truncated with ellipsis. Formula danmu (custom/meme pools) show in full. Default ~15 CN / ~40 EN if unset."),
    ("弹幕字号，约 12–72 像素。", "Danmu font size, ~12–72 px."),
    ("横向弹幕使用的系统字体名。留空或填入不存在的字体名时回退到默认。",
     "System font for horizontal danmu. Blank or invalid name uses default."),
    ("是否加粗横向弹幕。", "Bold horizontal danmu."),
    ("悬浮窗使用的系统字体名。", "System font for floating panel."),
    ("是否加粗悬浮窗弹幕。", "Bold floating-panel danmu."),
    ("弹幕透明度 0–100%，100 为完全不透明。", "Danmu opacity 0–100%; 100 = fully opaque."),
    ("和最近弹幕有多像就算重复（0–1）。越高越容易判重复并丢掉，默认约 0.5。",
     "Similarity threshold vs recent danmu (0–1). Higher = more duplicates dropped; default ~0.5."),
    ("弹幕显示区域占整块屏幕的比例（全屏、四分之三、一半、四分之一）。",
     "Danmu area as fraction of screen (full, 3/4, 1/2, 1/4)."),
    ("全局快捷键，随时开始或停止生成弹幕。首次使用可能需在系统里允许本程序监听键盘。",
     "Global hotkey to start/stop danmu. OS may ask to allow keyboard listening first time."),
    ("自然：按正常速度滚出屏幕。加速：换场景或清屏时让旧弹幕更快消失。",
     "Natural: normal scroll off screen. Accelerated: old danmu clear faster on scene change."),
    ("入口区（屏幕右侧待滚入）最多保留几条 pending 弹幕。新装默认 300；填 0 表示无限制。超出时淘汰最远屏外条目而非拒绝新弹幕。",
     "Max pending danmu in entry zone (right edge). Default 300; 0 = unlimited. Drops farthest off-screen items, not new ones."),
    ("所有轨道上同时保留的弹幕总条数上限。新装默认 600；填 0 表示无限制；超出时优先淘汰屏外 pending。",
     "Max total danmu on all tracks. Default 600; 0 = unlimited; drops off-screen pending first."),
    ("AI 回复在入队等待上屏时的最大条数。0 表示不裁剪；>0 时超出会从队首丢弃最旧条目。",
     "Max queued AI replies before display. 0 = no trim; >0 drops oldest from front when exceeded."),
    ("某行轨道空了时，暂时加快滚动，让新弹幕更快占满空位。",
     "When a track is empty, briefly speed up scroll to fill the gap."),
    ("横向弹幕：全屏透明 Overlay 横向滚动。从下到上：右侧窄窗自下而上连续上滚，越过顶部后消失。打游戏时建议游戏使用无边框窗口或窗口化全屏；独占全屏可能遮挡弹幕。",
     "Horizontal: full-screen transparent overlay scroll. Bottom-to-top: narrow right panel scrolls up. Use borderless/windowed fullscreen for games; exclusive fullscreen may hide danmu."),
    ("从下到上模式窗口宽度（200–800 px），默认靠右显示。", "Bottom-to-top panel width (200–800 px), right side by default."),
    ("从下到上模式的滚动速度（0.5–5.0，默认 1）。数值越大上移越快（引擎约 120×速度 px/s）。",
     "Bottom-to-top scroll speed (0.5–5.0, default 1). Higher = faster (~120×speed px/s)."),
    ("悬浮窗与屏幕右边缘的距离（px）。", "Floating panel distance from right edge (px)."),
    ("悬浮窗与屏幕上/下边缘的距离（px）。", "Floating panel distance from top/bottom (px)."),
    ("悬浮窗整体不透明度 0–100（0 = 完全透明，100 = 完全不透明）。",
     "Floating panel opacity 0–100 (0 = transparent, 100 = opaque)."),
    ("悬浮窗内每条弹幕的字号（12–48 px）。", "Font size per danmu in floating panel (12–48 px)."),
    ("悬浮窗同时显示的最多条数。超过时按 FIFO 丢最旧。",
     "Max simultaneous danmu in floating panel; FIFO drops oldest."),
    ("发给 AI 前把截图缩到多宽。越小越省流量和费用，越大越清晰。",
     "Screenshot width before sending to AI. Smaller = less bandwidth/cost; larger = sharper."),
    ("JPEG 压缩质量 1–100，默认 85。越高图越清楚、文件越大。",
     "JPEG quality 1–100, default 85. Higher = clearer, larger file."),
    ("用当前填写的地址、模式和密钥试连一次 AI，不开始弹幕，也不改其它设置。",
     "Test AI with current endpoint, mode, and key—no danmu, no other changes."),
    ("描述本次要玩的游戏或直播主题，便于 AI 生成更贴场景的弹幕。留空则不注入；建议 50 字内，上限 200 字。",
     "Game or stream topic for more contextual danmu. Empty = not injected; best under 50 chars, max 200."),
    ("你的昵称，AI 可在合适时自然称呼你。全局生效，与当前人格无关；上限 20 字。",
     "Your nickname for AI to use naturally. Global, persona-independent; max 20 chars."),
    ("选择要编辑的人格模板。内置人格可覆盖保存，也可点「恢复默认」还原。",
     "Persona template to edit. Built-ins can be overwritten; use Restore defaults to reset."),
    ("只读的 JSON 输出格式要求。每次生成条数与弹幕设置「弹幕显示」中的条数同步；改条数请去弹幕设置。",
     "Read-only JSON output contract. Count syncs with Danmu display settings; change count there."),
    ("追加到该人格系统提示词的风格与人格要求；点「保存人格」后生效。",
     "Extra style/persona appended to system prompt; applies after Save persona."),
    ("开启后按下方配置独立采集与展示烂梗弹幕，不与 AI 生成弹幕共用展示额度。",
     "When on, meme danmu are collected/displayed separately per settings below."),
    ("烂梗采集间隔（1–60 秒）。每隔该秒数从源拉取一批候选弹幕。",
     "Meme collect interval (1–60s). Pulls a batch of candidates each interval."),
    ("每次采集拉取的弹幕数量（1–100 条）。", "Danmu count per collect (1–100)."),
    ("烂梗展示间隔（1–60 秒）。每隔该秒数从待展示队列取出弹幕上屏。",
     "Meme display interval (1–60s). Shows danmu from queue each interval."),
    ("每次展示取出的弹幕条数（1–50 条）。", "Danmu shown per display batch (1–50)."),
    ("清空本地烂梗库与待展示队列；不影响已上屏弹幕。",
     "Clears local meme library and display queue; on-screen danmu unchanged."),
    ("启用后，系统会从你保存的自定义弹幕句中抽取短句，用于弹幕不足时补足。",
     "When on, pulls short lines from your custom pool when danmu count is low."),
    ("当屏幕上的弹幕少于该数量时，从自定义公式化弹幕库抽取短句补足。设为 0 则关闭补足。",
     "When on-screen danmu fall below this, pull from custom pool. 0 disables fill."),
    ("一行一条短句，保存后上屏时完整展示、不截断。重复句会自动跳过。",
     "One short line per row; full display on screen. Duplicates skipped."),
    ("勾选后可选中列表全部自定义句，便于批量删除。",
     "When checked, select all custom lines for batch delete."),
    ("开启后桌宠显示在桌面；临时隐藏请使用桌宠右键菜单。",
     "Shows desktop pet; use pet context menu to hide temporarily."),
    ("桌宠显示大小倍率（0.5–2.0）。1 为默认尺寸。", "Pet scale (0.5–2.0). 1 = default size."),
    ("桌宠窗口不透明度（0.2–1.0）。1 为完全不透明。", "Pet window opacity (0.2–1.0). 1 = opaque."),
    ("开启后桌宠窗口始终置顶，不会被其它窗口遮挡。",
     "Keeps pet window always on top."),
    ("开启后鼠标可穿透桌宠，但将无法拖动桌宠位置。",
     "Mouse passes through pet; dragging disabled."),
    ("开启后双击桌宠可弹出弹幕指令输入框。", "Double-click pet to open danmu command box."),
    ("指令提交后在此秒数内有效（5–300 秒），超时自动失效。",
     "Command valid for this many seconds (5–300), then expires."),
    ("一条指令最多影响几次截图弹幕生成（1–5 次）。",
     "Max screenshot danmu generations per command (1–5)."),
    ("在 Web 页调试注入弹幕指令；不会立即请求 AI，而是并入下一次正常截图生成。",
     "Debug-inject danmu command on Web; merged into next normal capture, not immediate AI call."),
    ("从本地文件夹导入桌宠素材。目录需包含 pet.json 与 spritesheet.webp 或 spritesheet.png。",
     "Import pet assets from folder with pet.json and spritesheet.webp or .png."),
    ("恢复为内置默认桌宠，不会删除你原来的本地素材文件。",
     "Restore built-in default pet; your local asset files are kept."),
    ("模型配置档案：为不同接口地址、模型、密钥保存多套配置，可指定默认；这里的密钥与上方全局密钥分开管理。",
     "Model profiles: multiple endpoint/model/key sets with optional default; keys separate from global above."),
    ("上传一张样图，预览当前「最大宽度」和「JPEG 质量」下的压缩效果。图片只在内存里处理，不会保存到硬盘。",
     "Upload a sample image to preview compression at current max width and JPEG quality. In-memory only."),
    ("随机：从全库抽取。自选：限选最多 3 个标签。本地库：仅使用本地导入的烂梗句。",
     "Random: from full library. Custom: up to 3 tags. Local: imported meme lines only."),
    ("全展示：采集结果全部进入展示队列。AI识别展示：由 AI 根据当前画面从候选中筛选。",
     "Show all: all collects go to display queue. AI pick: AI filters candidates by current screen."),
    ("仅「自选」分类时可选择标签，最多 3 个。", "Tags only for Custom category, max 3."),
    ("控制烂梗弹幕的采集节奏：间隔秒数与每批采集条数。",
     "Meme collect rhythm: interval seconds and batch size."),
    ("控制烂梗弹幕的上屏节奏：间隔秒数与每批展示条数。",
     "Meme display rhythm: interval seconds and batch size."),
    ("勾选多个人格后，运行时每轮随机选一个生成弹幕；点「保存激活列表」生效。",
     "Multiple checked personas: one random per round; Save active list to apply."),
    ("温馨控制台", "Dashboard"),
    ("人格工坊", "Persona Studio"),
    ("AI管家", "AI Butler"),
    ("公式化弹幕库", "Formula Danmu Pool"),
    ("桌宠", "Desktop Pet"),
    ("弹幕设置", "Danmu Settings"),
    ("直播设置", "Live Settings"),
    ("教程|日志|反馈|公告", "Guide | Logs | Feedback | News"),
    ("赞赏", "Support"),
    ("当前版本：", "Current version:"),
    ("最新版本：", "Latest version:"),
    ("检查更新", "Check for updates"),
    ("下载并重启", "Download & restart"),
    ("能做什么", "What you can do"),
    ("七个分页", "Seven tabs"),
    ("使用前注意", "Before you start"),
    ("弹幕设置说明", "Danmu settings help"),
    ("有新公告", "New announcement"),
    ("字段说明", "Field description"),
    ("小助手正在待命，随时为你生成暖心弹幕~", "Assistant is on standby, ready to generate cozy danmu anytime~"),
    ("小助手正在为你生成暖心弹幕~", "Assistant is generating cozy danmu for you~"),
    ("生成弹幕", "Start danmu"),
    ("停止弹幕", "Stop danmu"),
    ("待命", "Standby"),
    ("生成中", "Generating"),
    ("连接中", "Connecting"),
    ("已连接", "Connected"),
    ("重连中", "Reconnecting"),
    ("已降级轮询", "Polling fallback"),
    ("实时", "Realtime"),
    ("HTTP 同步", "HTTP sync"),
    ("保存", "Save"),
    ("取消", "Cancel"),
    ("关闭", "Close"),
    ("删除", "Delete"),
    ("加载中…", "Loading…"),
    ("加载中...", "Loading..."),
    ("保存配置", "Save settings"),
    ("恢复默认", "Restore defaults"),
    ("测试连接", "Test connection"),
    ("发送", "Send"),
    ("发送反馈", "Send feedback"),
    ("已复制到剪贴板", "Copied to clipboard"),
    ("请求失败", "Request failed"),
    ("连接失败", "Connection failed"),
    ("连接成功", "Connected successfully"),
    ("配置已保存~", "Settings saved"),
    ("处理中...", "Processing..."),
    ("重试", "Retry"),
    ("确认删除", "Confirm delete"),
    ("编辑", "Edit"),
    ("默认", "Default"),
    ("未命名", "Unnamed"),
    ("待接入", "Coming soon"),
    ("否", "No"),
    ("是", "Yes"),
    ("未知", "Unknown"),
    ("自然", "Natural"),
    ("加速", "Accelerated"),
    ("全屏", "Fullscreen"),
    ("随机", "Random"),
    ("自选", "Custom pick"),
    ("本地库", "Local library"),
    ("全展示", "Show all"),
    ("清除", "Clear"),
    ("刷新", "Refresh"),
    ("上一页", "Previous"),
    ("下一页", "Next"),
    ("全选本页", "Select all on page"),
    ("删除选中", "Delete selected"),
    ("中文", "Chinese"),
    ("英语", "English"),
    ("黑夜模式", "Dark mode"),
    ("浅色模式", "Light mode"),
    ("切换黑夜模式", "Switch to dark mode"),
    ("切换浅色模式", "Switch to light mode"),
    ("语言已切换为中文，正在重载页面…", "Language switched to Chinese, reloading…"),
    ("小助手已休息", "Assistant is resting"),
    ("弹幕生成已开启", "Danmu generation started"),
    ("小助手遇到了一点问题", "Assistant hit a small snag"),
    ("无法连接小助手，请确认 DanmuAI 已启动", "Cannot connect; confirm DanmuAI is running"),
    ("状态轮询失败，界面可能不是最新", "Status poll failed; UI may be stale"),
    ("WebSocket 连接数已达上限，请关闭其他控制台窗口后刷新页面",
     "WebSocket connections full; close other console windows and refresh"),
]

WORD_MAP: list[tuple[str, str]] = [
    ("弹幕", "danmu"), ("识图", "capture"), ("麦克风", "microphone"), ("模型", "model"),
    ("配置", "settings"), ("保存", "Save"), ("失败", "failed"), ("成功", "succeeded"),
    ("正在", "In progress: "), ("请", "Please "), ("已", "Already "), ("无法", "Unable to "),
    ("开启", "Enable "), ("关闭", "Disable "), ("删除", "Delete "), ("导入", "Import "),
    ("测试", "Test "), ("连接", "connection"), ("加载", "Loading "), ("刷新", "Refresh "),
    ("复制", "Copy "), ("发送", "Send "), ("停止", "Stop "), ("生成", "Generate "),
    ("人格", "persona"), ("桌宠", "desktop pet"), ("烂梗", "meme"), ("公式化", "formula"),
    ("字体", "font"), ("透明度", "opacity"), ("快捷键", "hotkey"), ("全屏", "fullscreen"),
    ("悬浮窗", "floating panel"), ("轨道", "track"), ("队列", "queue"), ("密钥", "API key"),
    ("地址", "endpoint"), ("温度", "temperature"), ("输出", "output"), ("输入", "input"),
    ("运行", "runtime"), ("诊断", "diagnostics"), ("公告", "announcement"), ("反馈", "feedback"),
    ("教程", "guide"), ("日志", "logs"), ("更新", "update"), ("版本", "version"),
    ("下载", "download"), ("重启", "restart"), ("谢谢", "Thank you"), ("昵称", "nickname"),
    ("主题", "topic"), ("预览", "preview"), ("试听", "Preview"), ("恢复", "Restore"),
    ("默认", "default"), ("当前", "current"), ("最新", "latest"), ("条", "items"),
    ("秒", "s"), ("分钟", "min"), ("小时", "h"), ("页", "page"), ("项", "items"),
]


def translate_template(s: str) -> str:
    """Translate Chinese fragments in template/HTML strings."""
    exact_templates = {
        "${h}小时${m}分": "${h}h ${m}min",
        "${r}秒": "${r}s",
        "${originalText}中...": "${originalText}...",
        "${device.name}（默认）": "${device.name} (default)",
        "${base}（手动 ${manual} 条）": "${base} (manual ${manual})",
        "${m.name || mid}（未完成）": "${m.name || mid} (incomplete)",
        "${msg}（左侧为原图；请重启 DanmuAI 后重试）": "${msg} (original on left; restart DanmuAI and retry)",
        "${pct}% · ${formatBytes(downloaded)} / 约 ${formatBytes(totalBytes)}":
            "${pct}% · ${formatBytes(downloaded)} / ~${formatBytes(totalBytes)}",
        "${shareText}\\n\\n链接：${url}": "${shareText}\\n\\nLink: ${url}",
        "${start} - ${end}  ${model}  输入 ${input}  输出 ${output}  总 ${total}":
            "${start} - ${end}  ${model}  in ${input}  out ${output}  total ${total}",
        ")} 等 ${successLabels.length} 项": ")} and ${successLabels.length} more",
        "0=无限制": "0=unlimited",
        "<option value=\"\">— 系统默认 —</option>": "<option value=\"\">— System default —</option>",
        "<option value=\"${safe}\">自定义：${safe}</option>": "<option value=\"${safe}\">Custom: ${safe}</option>",
        "<p class=\"announcements-empty\">暂无公告</p>": "<p class=\"announcements-empty\">No announcements</p>",
        "<p class=\"announcements-error\">未配置云端公告服务。请将 supabase-config.example.js 复制为 supabase-config.js 并填入项目地址与密钥。</p>":
            "<p class=\"announcements-error\">Cloud announcements not configured. Copy supabase-config.example.js to supabase-config.js and fill in project URL and key.</p>",
        "<p class=\"text-gray-500 text-sm\">正在加载公告…</p>": "<p class=\"text-gray-500 text-sm\">Loading announcements…</p>",
        "<p class=\"text-sm text-gray-400\">暂无模型配置档案，点击上方新增~</p>":
            "<p class=\"text-sm text-gray-400\">No model profiles yet—click Add above~</p>",
        "<span class=\"announcement-pinned-badge\">置顶</span>": "<span class=\"announcement-pinned-badge\">Pinned</span>",
        "<span class=\"model-tooltip-line\">模型 ID：${model.id}</span>":
            "<span class=\"model-tooltip-line\">Model ID: ${model.id}</span>",
        "<span class=\"model-tooltip-line\">模型名称：${model.name}</span>":
            "<span class=\"model-tooltip-line\">Model name: ${model.name}</span>",
        "<span class=\"model-tooltip-line\">输入价格：${formatTokenPrice(price.input, price.currency)}</span>":
            "<span class=\"model-tooltip-line\">Input price: ${formatTokenPrice(price.input, price.currency)}</span>",
        "<span class=\"model-tooltip-line\">输出价格：${formatTokenPrice(price.output, price.currency)}</span>":
            "<span class=\"model-tooltip-line\">Output price: ${formatTokenPrice(price.output, price.currency)}</span>",
        "<span class=\"model-tooltip-line\">音频价格：${formatTokenPrice(price.audio, price.currency)}</span>":
            "<span class=\"model-tooltip-line\">Audio price: ${formatTokenPrice(price.audio, price.currency)}</span>",
        ")} <button type=\"button\" class=\"underline font-semibold\" id=\"btnAnnouncementsRetry\">重试</button></p>":
            ")} <button type=\"button\" class=\"underline font-semibold\" id=\"btnAnnouncementsRetry\">Retry</button></p>",
        "✅ ${labelText} 已应用": "✅ ${labelText} applied",
        "✓ 使用": "✓ In use",
        "❌ 应用设置超时，请重试": "❌ Apply settings timed out, please retry",
        "❌ 设置保存失败：${msg}": "❌ Save settings failed: ${msg}",
        "❌ 配置存储异常，请重启应用": "❌ Config storage error, please restart",
        "· 已回退默认输入": "· Fell back to default input",
        "· 所选设备不可用，已回退到系统默认": "· Selected device unavailable, using system default",
        "· 接口：": "· Endpoint:",
        "· 输入：${activeInputLabel}": "· Input: ${activeInputLabel}",
        "· 默认输入：${defaultInputLabel}": "· Default input: ${defaultInputLabel}",
        "— 系统默认 —": "— System default —",
    }
    if s in exact_templates:
        return exact_templates[s]
    out = s
    for zh, en in sorted(PHRASES, key=lambda x: -len(x[0])):
        out = out.replace(zh, en)
    for zh, en in WORD_MAP:
        out = out.replace(zh, en)
    return out


def translate_prose(s: str) -> str:
    for zh, en in sorted(PHRASES, key=lambda x: -len(x[0])):
        if s == zh:
            return en
    out = s
    for zh, en in sorted(PHRASES, key=lambda x: -len(x[0])):
        out = out.replace(zh, en)
    if re.search(r"[\u4e00-\u9fff]", out):
        for zh, en in WORD_MAP:
            out = out.replace(zh, en)
    return out


def translate_zh(s: str) -> str:
    if not re.search(r"[\u4e00-\u9fff]", s):
        return s
    if "${" in s or "<" in s or s.startswith("[") or "\\n" in s:
        return translate_template(s)
    return translate_prose(s)


def main() -> None:
    zh_list: list[str] = json.loads(ZH_LIST.read_text(encoding="utf-8"))
    en_map: dict[str, str] = {}
    untranslated: list[str] = []
    for zh in zh_list:
        en = translate_zh(zh)
        en_map[zh] = en
        if re.search(r"[\u4e00-\u9fff]", en):
            untranslated.append(zh)
    OUT.write_text(json.dumps(en_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(en_map)} entries to {OUT.name}")
    print(f"Still contain CJK: {len(untranslated)}")
    if untranslated[:5]:
        for u in untranslated[:5]:
            print(f"  - {u[:60]}...")


if __name__ == "__main__":
    main()
