"""Build nested locale JSON shards from extracted UI strings."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web" / "static"
LOCALES = STATIC / "locales"
EXTRACTED = LOCALES / "_extracted_zh.json"
HINTS_JS = STATIC / "modules" / "settings-hints.js"
EN_MAP = Path(__file__).resolve().parent / "locale_en_extra.json"
CHECK_ONLY = False

SHARDS = ["common", "nav", "overview", "settings", "content", "modals", "hints", "dynamic"]

DYNAMIC_TEMPLATE_OVERRIDES = {
    "dynamic.appMemeBarragePage.最多只能选择_MAX_SELECTED_ME": {
        "zh": "最多只能选择 {maxTags} 个标签",
        "en": "Select at most {maxTags} tags",
    },
}

DOMAIN_TO_SHARD = {
    "sidebar": "nav",
    "overview": "overview",
    "settings": "settings",
    "content-pages": "content",
    "modals": "modals",
    "hints": "hints",
    "dynamic": "dynamic",
}

NAMESPACE = {
    "nav": "nav",
    "overview": "overview",
    "settings": "settings",
    "content": "content",
    "modals": "modals",
    "hints": "hints",
    "dynamic": "dynamic",
    "common": "common",
}

# Stable nav label keys
NAV_LABEL_KEYS = {
    "点击：官网与群聊 danmuai.xyz": "officialSite",
    "温馨控制台": "overview",
    "常用": "commonFeatures",
    "增强": "enhancedFeatures",
    "展开增强功能": "expandEnhanced",
    "收起增强功能": "collapseEnhanced",
    "弹幕人格": "persona",
    "弹幕知识库": "knowledge",
    "弹幕样式": "styleGenerator",
    "公式化弹幕库": "danmuPool",
    "弹幕设置": "settings",
    "虚拟主播": "virtualHost",
    "教程|日志|反馈|公告|群聊|直播": "guide",
    "帮助与系统": "helpSystem",
    "赞赏": "reward",
    "当前版本：": "versionCurrent",
    "最新版本：": "versionLatest",
    "检查更新": "checkUpdate",
    "下载并重启": "downloadRestart",
    "能做什么": "tooltipCanDoTitle",
    "5 个分类": "tooltipTabsTitle",
    "使用前注意": "tooltipNoticeTitle",
    "有新版本": "newVersionBadge",
}

NAV_STATIC_LABELS = {
    "versionCurrent": "\u5f53\u524d\u7248\u672c",
    "versionLatest": "\u6700\u65b0\u7248\u672c\uff1a",
    "checkUpdate": "\u68c0\u67e5\u66f4\u65b0",
    "downloadRestart": "\u4e0b\u8f7d\u5e76\u91cd\u542f",
    "settingsHelpAria": "\u5f39\u5e55\u8bbe\u7f6e\u8bf4\u660e",
    "newAnnouncementBadge": "\u6709\u65b0\u516c\u544a",
    "newVersionBadge": "\u6709\u65b0\u7248\u672c",
    "openMenu": "\u6253\u5f00\u5bfc\u822a",
    "closeMenu": "\u5173\u95ed\u5bfc\u822a",
    "sidebarAria": "\u4e3b\u5bfc\u822a",
}

COMMON_STRING_KEYS = {
    "保存": "save",
    "取消": "cancel",
    "关闭": "close",
    "删除": "delete",
    "加载中…": "loading",
    "加载中...": "loadingAlt",
    "保存配置": "saveConfig",
    "恢复默认": "restoreDefault",
    "测试连接": "testConnection",
    "发送": "send",
    "发送反馈": "sendFeedback",
    "已复制到剪贴板": "copied",
    "请求失败": "requestFailed",
    "连接失败": "connectionFailed",
    "连接成功": "connectionSuccess",
    "配置已保存~": "configSaved",
    "处理中...": "processing",
    "重试": "retry",
    "确认删除": "confirmDelete",
    "编辑": "edit",
    "默认": "defaultLabel",
    "未命名": "unnamed",
    "待接入": "comingSoon",
    "连接中": "connecting",
    "已连接": "connected",
    "导出日志": "exportLogs",
    "日志已导出": "logsExported",
    "暂无可导出的日志": "noLogsToExport",
    "重连中": "reconnecting",
    "已降级轮询": "polling",
    "实时": "realtime",
    "HTTP 同步": "httpSync",
    "待命": "standby",
    "生成中": "generating",
    "生成弹幕": "startDanmu",
    "停止弹幕": "stopDanmu",
    "否": "no",
    "是": "yes",
    "未知": "unknown",
    "自然": "natural",
    "加速": "accelerated",
    "全屏": "fullscreen",
    "随机": "random",
    "自选": "customPick",
    "本地库": "localLibrary",
    "全展示": "showAll",
    "清除": "clear",
    "刷新": "refresh",
    "上一页": "prevPage",
    "下一页": "nextPage",
    "全选本页": "selectAllPage",
    "删除选中": "deleteSelected",
    "中文": "langZh",
    "英语": "langEn",
    "黑夜模式": "darkMode",
    "浅色模式": "lightMode",
    "切换黑夜模式": "toggleDarkMode",
    "切换浅色模式": "toggleLightMode",
    "弹幕设置说明": "settingsHelpAria",
    "有新公告": "newAnnouncementBadge",
    "字段说明": "fieldHintAria",
}


def load_extracted() -> dict[str, str]:
    return json.loads(EXTRACTED.read_text(encoding="utf-8"))


def load_en_map() -> dict[str, str]:
    if EN_MAP.exists():
        return json.loads(EN_MAP.read_text(encoding="utf-8"))
    return {}


def load_existing_shard(lang: str, shard: str) -> dict:
    path = LOCALES / lang / f"{shard}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def merge_dicts(base: dict, updates: dict) -> dict:
    """Merge generated entries without deleting translations absent from extraction."""
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def set_flattened(root: dict, path: str, value: str) -> None:
    parts = path.split(".")
    set_nested(root, parts, value)


def prune_to_reference(node: dict, reference: dict) -> dict:
    pruned: dict = {}
    for key, value in node.items():
        if key not in reference:
            continue
        ref_value = reference[key]
        if isinstance(value, dict) and isinstance(ref_value, dict):
            pruned[key] = prune_to_reference(value, ref_value)
        elif not isinstance(value, dict) and not isinstance(ref_value, dict):
            pruned[key] = value
    return pruned


def flatten_locale(node: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(flatten_locale(value, path))
        else:
            out[path] = str(value)
    return out


def parse_hints_js() -> dict[str, str]:
    text = HINTS_JS.read_text(encoding="utf-8")
    existing_dynamic = flatten_locale(load_existing_shard("zh", "dynamic"))
    existing_hints = flatten_locale(load_existing_shard("zh", "hints"))

    def resolve_hint(value: str) -> str | None:
        if value.startswith("dynamic."):
            return existing_dynamic.get(value)
        if value.startswith("hints."):
            return existing_hints.get(value)
        return value

    hints: dict[str, str] = {}
    for m in re.finditer(r"(\w+)\s*:\s*\n?\s*'((?:\\'|[^'])*)'", text):
        key, val = m.group(1), m.group(2).replace("\\'", "'")
        if key in ("SETTINGS_CONTROL_HINT_IDS", "CONTENT_PAGE_CONTROL_HINT_IDS"):
            continue
        resolved = resolve_hint(val)
        if resolved:
            hints[key] = resolved
    for m in re.finditer(r"'([\w-]+)'\s*:\s*\n?\s*'((?:\\'|[^'])*)'", text):
        resolved = resolve_hint(m.group(2).replace("\\'", "'"))
        if resolved:
            hints[m.group(1)] = resolved
    return hints


def set_nested(root: dict, parts: list[str], value: str) -> None:
    cur = root
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def slug_key(text: str, used: set[str]) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", text[:40]).strip("_") or "item"
    if s[0].isdigit():
        s = f"k_{s}"
    base, n = s, 2
    while base in used:
        base = f"{s}_{n}"
        n += 1
    used.add(base)
    return base


def build_zh_shards(extracted: dict[str, str], hints: dict[str, str]) -> dict[str, dict]:
    shards: dict[str, dict] = {s: {} for s in SHARDS}
    used_keys: dict[str, set[str]] = {s: set() for s in SHARDS}

    # common
    common_root: dict = {
        "meta": {"title": "DanmuAI - 你的温馨弹幕小助手"},
    }
    for zh, key in COMMON_STRING_KEYS.items():
        if key not in ("settingsHelpAria", "newAnnouncementBadge", "fieldHintAria"):
            common_root[key] = zh
    common_root["fieldHintAria"] = "字段说明"
    shards["common"]["common"] = common_root

    # hints from JS (authoritative)
    shards["hints"]["hints"] = dict(hints)

    for key, value in NAV_STATIC_LABELS.items():
        set_nested(shards["nav"], ["nav", key], value)

    # Process extracted flat keys
    for flat_key, value in extracted.items():
        parts = flat_key.split(".")
        domain = parts[0]
        shard = DOMAIN_TO_SHARD.get(domain)
        if not shard:
            continue
        ns = NAMESPACE[shard]

        if domain == "hints":
            continue  # use JS hints

        if domain == "sidebar":
            kind = parts[1] if len(parts) > 1 else "text"
            if kind == "text":
                if value in NAV_LABEL_KEYS:
                    set_nested(shards["nav"], ["nav", NAV_LABEL_KEYS[value]], value)
                elif value.startswith("：") or "设置 AI 接口" in value:
                    tip_key = slug_key(value, used_keys["nav"])
                    set_nested(shards["nav"], ["nav", "tooltip", tip_key], value.lstrip("："))
                elif value in ("能做什么", "5 个分类", "使用前注意"):
                    pass  # titles handled via NAV_LABEL_KEYS
                else:
                    k = slug_key(value, used_keys["nav"])
                    set_nested(shards["nav"], ["nav", k], value)
            elif kind == "aria_label":
                if value == "弹幕设置说明":
                    set_nested(shards["nav"], ["nav", "settingsHelpAria"], value)
                elif value == "有新公告":
                    set_nested(shards["nav"], ["nav", "newAnnouncementBadge"], value)
                elif value == "菜单分类":
                    set_nested(shards["nav"], ["nav", "categoryAria"], value)
                else:
                    k = slug_key(value, used_keys["nav"])
                    set_nested(shards["nav"], ["nav", "aria", k], value)
            continue

        if domain == "dynamic":
            module = parts[1] if len(parts) > 1 else "app"
            rest = parts[2] if len(parts) > 2 else slug_key(value, set())
            # camelCase module names
            mod_key = re.sub(r"[-_](\w)", lambda m: m.group(1).upper(), module)
            sub_key = slug_key(rest if len(parts) > 2 else value, used_keys["dynamic"])
            set_nested(shards["dynamic"], ["dynamic", mod_key, sub_key], value)
            continue

        # HTML partials: overview, settings, content-pages, modals
        kind = parts[1] if len(parts) > 1 else "text"
        if value in COMMON_STRING_KEYS and shard != "settings":
            ck = COMMON_STRING_KEYS[value]
            if ck not in shards["common"]["common"]:
                shards["common"]["common"][ck] = value
            continue

        if kind == "text":
            k = slug_key(value, used_keys[shard])
            set_nested(shards[shard], [ns, "text", k], value)
        elif kind == "placeholder":
            k = slug_key(value, used_keys[shard])
            set_nested(shards[shard], [ns, "placeholder", k], value)
        elif kind == "aria_label":
            k = slug_key(value, used_keys[shard])
            set_nested(shards[shard], [ns, "aria", k], value)

    # Add nav tooltip bodies from sidebar
    for k, v in extracted.items():
        if k.startswith("sidebar.text.") and ("设置 AI" in v or "API 与模型" in v or "请先在" in v):
            body = v.lstrip("：")
            tip_k = slug_key(body[:24], used_keys["nav"])
            set_nested(shards["nav"], ["nav", "tooltip", tip_k], body)

    return shards


def flatten_paths(node: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in node.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten_paths(v, path))
        else:
            out[path] = str(v)
    return out


def translate_tree(node: dict, en_by_zh: dict[str, str], path: str = "") -> dict | str:
    if isinstance(node, dict):
        return {
            k: translate_tree(v, en_by_zh, f"{path}.{k}" if path else k)
            for k, v in node.items()
        }
    if isinstance(node, str):
        if node in en_by_zh:
            return en_by_zh[node]
        if "${" in node or not re.search(r"[\u4e00-\u9fff]", node):
            return node
        return en_by_zh.get(node, node)
    return node


def count_leaves(node) -> int:
    if isinstance(node, dict):
        return sum(count_leaves(v) for v in node.values())
    return 1


def write_json(path: Path, data: dict) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if len(text.splitlines()) > 1200:
        raise SystemExit(f"{path.name} exceeds 1200 lines ({len(text.splitlines())})")
    if CHECK_ONLY:
        if not path.is_file() or json.loads(path.read_text(encoding='utf-8')) != data:
            raise SystemExit(f'{path.relative_to(ROOT)} is stale; run python scripts/build_locale_shards.py.')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")


def main() -> None:
    extracted = load_extracted()
    hints = parse_hints_js()
    zh_shards = build_zh_shards(extracted, hints)
    en_by_zh = load_en_map()

    write_json(LOCALES / "manifest.json", {
        "version": 1,
        "languages": ["zh", "en"],
        "shards": SHARDS,
    })

    counts: dict[str, dict[str, int]] = {"zh": {}, "en": {}}
    for shard in SHARDS:
        generated_zh = zh_shards.get(shard, {shard: {}})
        existing_zh = load_existing_shard("zh", shard)
        zh_data = merge_dicts(existing_zh, generated_zh)
        generated_en = translate_tree(generated_zh, en_by_zh)
        existing_en = load_existing_shard("en", shard)
        en_data = merge_dicts(existing_en, generated_en)
        for path, values in DYNAMIC_TEMPLATE_OVERRIDES.items():
            if path.startswith(f"{shard}."):
                set_flattened(zh_data, path, values["zh"])
                set_flattened(en_data, path, values["en"])
        en_flat = flatten_locale(en_data)
        for path, zh_value in flatten_locale(zh_data).items():
            if path not in en_flat:
                set_flattened(en_data, path, en_by_zh.get(zh_value, zh_value))
        en_data = prune_to_reference(en_data, zh_data)
        write_json(LOCALES / "zh" / f"{shard}.json", zh_data)
        write_json(LOCALES / "en" / f"{shard}.json", en_data)
        counts["zh"][shard] = count_leaves(zh_data)
        counts["en"][shard] = count_leaves(en_data)

    write_json(LOCALES / "_shard_counts.json", counts)
    print("Shard key counts:")
    for shard in SHARDS:
        print(f"  {shard}: zh={counts['zh'][shard]} en={counts['en'][shard]}")
    print(f"  TOTAL: zh={sum(counts['zh'].values())} en={sum(counts['en'].values())}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate generated JSON without rewriting files.')
    CHECK_ONLY = parser.parse_args().check
    main()
