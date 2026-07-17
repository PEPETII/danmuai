"""Runtime interpolation contract for Web locale dynamic placeholders."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "web" / "static" / "locales"
MODULES = ROOT / "web" / "static" / "modules"
I18N_JS = MODULES / "i18n.js"

ALLOWED_MODULES = {
    "app.js",
    "app-ai-butler-page.js",
    "app-danmu-pool-page.js",
    "app-error-reporting.js",
    "app-live-overlay-panel.js",
    "app-meme-barrage-page.js",
    "app-persona-topic-page.js",
    "app-pet-page.js",
    "app-update-banner.js",
    "content-feedback.js",
    "settings-capture-region.js",
    "settings-core.js",
    "settings-custom-models.js",
    "settings-danmu-preview.js",
    "settings-defaults.js",
    "settings-fonts.js",
    "settings-model-catalog.js",
    "settings-providers.js",
    "settings.js",
    "transport.js",
    "i18n.js",
}

T_CALL_HEAD_RE = re.compile(r"t\(['\"](dynamic\.[^'\"]+)['\"]")
LOCALE_PARAM_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

USER_PATH_KEYS = [
    "dynamic.settings.跟随系统默认_当前_defaultLabel",
    "dynamic.settings.device_name_默认",
    "dynamic.settings.当前将跟随_Windows_默认录音设备_d",
    "dynamic.settings.当前固定使用_selectedLabel",
    "dynamic.settings.配置已保存_当前生效模型_label",
    "dynamic.app.originalText_中",
]

NAMED_PLACEHOLDER = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")
LEGACY_DOLLAR_PLACEHOLDER = re.compile(r"\$\{")


def _flatten(obj: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, val in obj.items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            out.update(_flatten(val, full))
        else:
            out[full] = str(val)
    return out


def _load_dynamic(lang: str) -> dict[str, str]:
    path = LOCALES / lang / "dynamic.json"
    return _flatten(json.loads(path.read_text(encoding="utf-8")))


def _interpolate(text: str, params: dict[str, str] | None = None) -> str:
    """Mirror web/static/modules/i18n.js t() post-replace cleanup."""
    if params:
        for key, value in params.items():
            text = re.sub(r"\{" + re.escape(key) + r"\}", str(value), text)
    text = NAMED_PLACEHOLDER.sub("", text)
    text = re.sub(r"\$\{[^}]+\}", "", text)
    return text


def test_user_path_locale_values_use_named_brace_protocol():
    for key in USER_PATH_KEYS:
        zh = _load_dynamic("zh")[key]
        en = _load_dynamic("en")[key]
        assert not LEGACY_DOLLAR_PLACEHOLDER.search(zh), f"zh {key} still uses ${{"
        assert not LEGACY_DOLLAR_PLACEHOLDER.search(en), f"en {key} still uses ${{"
        assert NAMED_PLACEHOLDER.search(zh), f"zh {key} missing named placeholder"
        assert NAMED_PLACEHOLDER.search(en), f"en {key} missing named placeholder"


def test_interpolation_replaces_defaultLabel_name_originalText():
    zh = _load_dynamic("zh")
    en = _load_dynamic("en")

    assert _interpolate(zh["dynamic.settings.跟随系统默认_当前_defaultLabel"], {"defaultLabel": "麦克风阵列"}) == (
        "跟随系统默认（当前：麦克风阵列）"
    )
    assert _interpolate(en["dynamic.settings.跟随系统默认_当前_defaultLabel"], {"defaultLabel": "Mic Array"}) == (
        "Follow system default (current: Mic Array)"
    )

    assert _interpolate(zh["dynamic.settings.device_name_默认"], {"name": "Realtek HD"}) == "Realtek HD（默认）"
    assert _interpolate(en["dynamic.settings.device_name_默认"], {"name": "Realtek HD"}) == "Realtek HD (default)"

    assert _interpolate(zh["dynamic.app.originalText_中"], {"originalText": "测试连接"}) == "测试连接中..."
    assert _interpolate(en["dynamic.app.originalText_中"], {"originalText": "Test connection"}) == (
        "Test connection..."
    )


def test_missing_params_never_expose_template_source():
    zh = _load_dynamic("zh")
    samples = [
        zh["dynamic.settings.跟随系统默认_当前_defaultLabel"],
        zh["dynamic.settings.device_name_默认"],
        zh["dynamic.app.originalText_中"],
        zh["dynamic.settings.配置已保存_当前生效模型_label"],
    ]
    for template in samples:
        result = _interpolate(template)
        assert "${" not in result
        assert not NAMED_PLACEHOLDER.search(result), f"unresolved placeholder in: {result!r}"


def test_i18n_js_does_not_use_eval_or_function_for_interpolation():
    source = I18N_JS.read_text(encoding="utf-8")
    t_block = source[source.index("export function t(") : source.index("function applyToElement")]
    assert "eval(" not in t_block
    assert "Function(" not in t_block
    assert "new Function" not in t_block


def test_user_path_keys_remain_zh_en_parity():
    zh = _load_dynamic("zh")
    en = _load_dynamic("en")
    for key in USER_PATH_KEYS:
        assert key in zh
        assert key in en


def _parse_params_object(block: str) -> set[str]:
    """Extract param identifiers from `{a, b: expr}` including ES shorthand."""
    ident = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    names: set[str] = set()
    inner = block.strip()
    if inner.startswith("{") and inner.endswith("}"):
        inner = inner[1:-1]
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in inner:
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            key = part.split(":", 1)[0].strip()
            if ident.match(key):
                names.add(key)
        elif ident.match(part):
            names.add(part)
    return names


def _extract_balanced_object(src: str, start: int) -> tuple[str, int] | None:
    if start >= len(src) or src[start] != "{":
        return None
    depth = 0
    for idx in range(start, len(src)):
        ch = src[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start : idx + 1], idx + 1
    return None


def _collect_active_dynamic_calls() -> dict[str, set[str]]:
    """Map dynamic i18n key -> union of param names passed at all call sites."""
    called: dict[str, set[str]] = {}
    for fname in ALLOWED_MODULES:
        path = MODULES / fname
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        pos = 0
        while pos < len(src):
            match = T_CALL_HEAD_RE.search(src, pos)
            if not match:
                break
            key = match.group(1)
            cursor = match.end()
            rest = src[cursor:].lstrip()
            names: set[str] = set()
            if rest.startswith(","):
                rest = rest[1:].lstrip()
                if rest.startswith("{"):
                    parsed = _extract_balanced_object(rest, 0)
                    if parsed:
                        names = _parse_params_object(parsed[0])
            called.setdefault(key, set()).update(names)
            pos = cursor
    return called


def test_active_dynamic_locale_entries_have_no_legacy_dollar_placeholders():
    zh = _load_dynamic("zh")
    en = _load_dynamic("en")
    called = _collect_active_dynamic_calls()
    bad: list[str] = []
    for key in sorted(called):
        if key not in zh:
            continue
        if LEGACY_DOLLAR_PLACEHOLDER.search(zh[key]) or LEGACY_DOLLAR_PLACEHOLDER.search(en.get(key, "")):
            bad.append(key)
    assert not bad, f"active dynamic keys still use ${{: {bad[:15]}"


def test_active_dynamic_param_names_match_locale_templates():
    zh = _load_dynamic("zh")
    called = _collect_active_dynamic_calls()
    mismatches: list[str] = []
    for key, passed in sorted(called.items()):
        if key not in zh:
            continue
        expected = set(LOCALE_PARAM_RE.findall(zh[key]))
        if not expected:
            continue
        if passed != expected:
            mismatches.append(f"{key}: locale={sorted(expected)} caller={sorted(passed)}")
    assert not mismatches, f"param mismatch: {mismatches[:10]}"


def test_error_path_interpolation():
    zh = _load_dynamic("zh")
    en = _load_dynamic("en")
    assert _interpolate(zh["dynamic.appAiButlerPage.AI_管家请求失败_error"], {"error": "timeout"}) == (
        "AI 管家请求失败：timeout"
    )
    assert _interpolate(en["dynamic.transport.无法获取控制台会话_HTTP_res_sta"], {
        "status": "503",
        "detail": "unavailable",
    }) == "Cannot get console session (HTTP 503): unavailable."


def test_update_path_interpolation():
    zh = _load_dynamic("zh")
    assert _interpolate(zh["dynamic.appUpdateBanner.当前版本_current_发现新版本"], {
        "current": "1.0.0",
        "latest": "1.1.0",
    }) == "当前版本 1.0.0，发现新版本 1.1.0。"
    assert _interpolate(zh["dynamic.appUpdateBanner.pct_formatBytes"], {
        "pct": "42",
        "downloaded": "4.2 MB",
        "total": "10 MB",
    }) == "42% · 4.2 MB / 约 10 MB"


def test_model_path_interpolation():
    zh = _load_dynamic("zh")
    assert _interpolate(zh["dynamic.settingsCustomModels.确定删除模型_display_吗_该档案包"], {
        "display": "豆包档案",
        "n": "3",
    }) == "确定删除模型「豆包档案」吗？该档案包含 3 个模型 ID，将一并删除。若该档案是当前默认，将自动切换到下一条。"
    assert _interpolate(zh["dynamic.settingsModelCatalog.查看_model_id_的价格说明"], {
        "modelId": "gpt-4o",
    }) == "查看 gpt-4o 的价格说明"


def test_font_path_interpolation():
    zh = _load_dynamic("zh")
    assert _interpolate(zh["dynamic.settingsFonts.已导入字体_data_family"], {"family": "MyFont"}) == (
        "已导入字体：MyFont"
    )
    assert _interpolate(zh["dynamic.settingsFonts.导入失败_error_message"], {"error": "bad file"}) == (
        "导入失败：bad file"
    )


def test_danmu_preview_path_interpolation():
    zh = _load_dynamic("zh")
    assert _interpolate(zh["dynamic.settingsDanmuPreview.轨道_drawn_1_y_y"], {
        "trackNum": "2",
        "y": "48",
    }) == "轨道 2 @ y=48px"


def test_device_hint_path_interpolation():
    zh = _load_dynamic("zh")
    en = _load_dynamic("en")
    assert _interpolate(zh["dynamic.settings.当前将跟随_Windows_默认录音设备_d"], {
        "defaultLabel": "麦克风 (Realtek)",
    }) == "当前将跟随 Windows 默认录音设备：麦克风 (Realtek)"
    assert _interpolate(en["dynamic.settings.micHintDeviceUnavailable"], {
        "defaultLabel": "System Default",
    }) == (
        "Mic input unavailable: selected device missing; runtime falls back to system default (System Default)."
    )