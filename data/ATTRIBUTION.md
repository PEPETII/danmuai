# Data attribution — `danmu_pool_zh.json`

## Source corpus

- **Upstream**: [TinyTalks/DDmkTCCorpus](https://github.com/TinyTalks/DDmkTCCorpus)
- **License**: [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)

## Modifications in DanmuAI

The file `danmu_pool_zh.json` is a **curated subset**, not a full redistribution of DDmkTCCorpus:

- Short lines suitable for on-screen overlay (length cap, see `scripts/extract_danmu_pool.py`)
- Sensitive-word filtering (`scripts/filter_pool_sensitive.py` when used)
- Merged with project-authored bootstrap lines (`danmu_pool_zh_bootstrap.txt`)
- Metadata fields (`version`, `sources`, `license_note`) for runtime and compliance

To regenerate from corpus:

```bash
python scripts/extract_danmu_pool.py
```

Corpus path defaults are documented in [data/README.md](README.md) and [scripts/README.md](../scripts/README.md).

## Content disclaimer

Danmu lines reflect user-generated Bilibili-style commentary from the upstream dataset. DanmuAI does not endorse specific statements. Use and redistribution are subject to the Apache-2.0 license on the corpus subset and GPL-3.0-or-later on project code.
