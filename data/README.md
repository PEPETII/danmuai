# Danmu text pool

`danmu_pool_zh.json` — 运行时本地弹幕库（fallback 补位、`normalize_reply_batch` 填充）。

Apache-2.0 corpus attribution: [ATTRIBUTION.md](ATTRIBUTION.md).

结构：**先** `danmu_pool_zh_bootstrap.txt`（400 条公式句）**再**语料抽样（默认 1000 条），去重后合计约 **1300+ 条**（语料经敏感词过滤后会略少）。

## 生成语料 + 合并 bootstrap

```bash
python scripts/extract_danmu_pool.py --target 1000
```

仅把已有 JSON 与 bootstrap 合并（不重扫语料）：

```bash
python scripts/merge_bootstrap_into_pool.py
```

## 仅语料 1000 条（DDmkTCCorpus）

优先读取 `开源项目/**/sorted_danmaku.txt`（已下载的 DDmkTCCorpus）；找不到则从 GitHub 流式下载。

```bash
python scripts/extract_danmu_pool.py --target 1000
```

或先确保语料在：

`开源项目/DDmkTCCorpus-main/data/sorted_danmaku.txt`

筛选规则：2–15 字、含中文、去重、过滤刷屏/URL/敏感词（见 `scripts/extract_danmu_pool.py` 的 `BLOCK_SUBSTRINGS`）；与 `docs/DANMAKU_FORMULA.md` 硬约束一致。

对已生成的 JSON 做敏感词删减：

```bash
python scripts/filter_pool_sensitive.py
```

## 引导词库

`danmu_pool_zh_bootstrap.txt` — 公式文档中的 400 条（含单字 顶/行/顺）；合并进 JSON 后运行时只读 `danmu_pool_zh.json`。

## 许可

语料来源 [TinyTalks/DDmkTCCorpus](https://github.com/TinyTalks/DDmkTCCorpus)（Apache-2.0）。本目录仅为 Overlay 可用的精选子集，非完整语料再分发。
