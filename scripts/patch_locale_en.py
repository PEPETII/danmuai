"""Patch locale_en_strings.json with additional exact translations."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ZH_LIST = ROOT / "_zh_strings_list.json"
EN_MAP = ROOT / "locale_en_strings.json"
GEN = ROOT / "gen_locale_en_map.py"

# Load gen module
spec = importlib.util.spec_from_file_location("gen_locale", GEN)
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)  # type: ignore[union-attr]

EXTRA: dict[str, str] = {}
# Populated from _untranslated.json — key phrases with proper English
_extra_path = ROOT / "locale_en_extra.json"
if _extra_path.exists():
    EXTRA.update(json.loads(_extra_path.read_text(encoding="utf-8")))


def main() -> None:
    zh_list: list[str] = json.loads(ZH_LIST.read_text(encoding="utf-8"))
    en_map: dict[str, str] = {}
    if EN_MAP.exists():
        en_map = json.loads(EN_MAP.read_text(encoding="utf-8"))
    en_map.update(EXTRA)
    for zh in zh_list:
        cur = en_map.get(zh, "")
        if not cur or re.search(r"[\u4e00-\u9fff]", cur):
            en_map[zh] = gen.translate_zh(zh)
    bad = [k for k, v in en_map.items() if re.search(r"[\u4e00-\u9fff]", v)]
    EN_MAP.write_text(json.dumps(en_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Patched {len(en_map)} entries; {len(bad)} still contain CJK")
    if bad:
        Path(ROOT / "_untranslated.json").write_text(
            json.dumps(bad[:200], ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
