"""Compare zh/en dynamic locale keys (console helper for i18n work)."""
from __future__ import annotations

import json
import os

# scripts/ → repo root
BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOCALES = os.path.join(BASE, "web", "static", "locales")


def flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, full))
        else:
            out[full] = str(v)
    return out


def main():
    zh = {}
    en = {}
    for name in ["dynamic"]:
        with open(os.path.join(LOCALES, "zh", f"{name}.json"), "r", encoding="utf-8") as f:
            zh.update(flatten(json.load(f)))
        with open(os.path.join(LOCALES, "en", f"{name}.json"), "r", encoding="utf-8") as f:
            en.update(flatten(json.load(f)))

    print("zh dynamic keys:", len(zh))
    print("en dynamic keys:", len(en))
    only_zh = set(zh) - set(en)
    only_en = set(en) - set(zh)
    print("only in zh:", len(only_zh))
    print("only in en:", len(only_en))

    identical = []
    for k in sorted(set(zh) & set(en)):
        if zh[k] == en[k]:
            identical.append(k)
    print("identical values:", len(identical))
    for k in identical[:20]:
        print(f"  {k}: {zh[k][:80]!r}")


if __name__ == "__main__":
    main()
