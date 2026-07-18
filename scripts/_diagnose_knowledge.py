"""诊断：真实数据 + 各环节分析"""
import sqlite3, os, json

db_path = os.path.join(os.environ.get('APPDATA', ''), 'DanmuAI', 'knowledge.db')
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# 1. 最近的 job
print("=" * 70)
print("1. RECENT JOBS")
print("=" * 70)
rows = conn.execute(
    "SELECT id, public_id, status, total_chunks, processed_chunks, "
    "failed_chunks, generated_items, deduplicated_items, "
    "input_tokens, output_tokens, error_message "
    "FROM knowledge_jobs ORDER BY id DESC LIMIT 3"
).fetchall()
for r in rows:
    print(f"\n  job id={r['id']} status={r['status']} "
          f"chunks={r['processed_chunks']}/{r['total_chunks']} "
          f"failed={r['failed_chunks']} items={r['generated_items']} "
          f"tokens: in={r['input_tokens']} out={r['output_tokens']}")
    if r['error_message']:
        print(f"    error: {r['error_message'][:200]}")

# 2. Items
print("\n" + "=" * 70)
print("2. KNOWLEDGE ITEMS")
print("=" * 70)
items = conn.execute(
    "SELECT id, kind, title, content, examples_json, triggers_json, tones_json, "
    "scopes_json, entities_json, confidence, length(content) as content_len "
    "FROM knowledge_items ORDER BY id"
).fetchall()
for it in items:
    print(f"\n  [{it['id']}] kind={it['kind']}  title=「{it['title']}」  content_len={it['content_len']}")
    print(f"       content=「{it['content']}」")
    try:
        ex = json.loads(it['examples_json']) if it['examples_json'] else []
        tr = json.loads(it['triggers_json']) if it['triggers_json'] else []
        tn = json.loads(it['tones_json']) if it['tones_json'] else []
        sc = json.loads(it['scopes_json']) if it['scopes_json'] else []
        en = json.loads(it['entities_json']) if it['entities_json'] else []
    except:
        ex = tr = tn = sc = en = []
    print(f"       examples={ex}  triggers={tr}  tones={tn}")
    print(f"       scopes={sc}  entities={en}  confidence={it['confidence']}")

# 3. Chunks 大小 + source 大小
print("\n" + "=" * 70)
print("3. CHUNKS + SOURCES SIZE")
print("=" * 70)
chunks = conn.execute(
    "SELECT c.id, c.sequence_no, c.status, c.error_message, "
    "length(c.content) as content_len, "
    "s.source_type, length(s.normalized_text) as source_len "
    "FROM knowledge_chunks c "
    "JOIN knowledge_sources s ON c.source_id = s.id "
    "ORDER BY c.source_id, c.sequence_no"
).fetchall()
for c in chunks:
    print(f"  chunk id={c['id']} seq={c['sequence_no']} status={c['status']} "
          f"chunk_len={c['content_len']}  source_type={c['source_type']}  source_total_len={c['source_len']}")
    if c['error_message']:
        print(f"    error: {c['error_message'][:100]}")

# 4. Source 归一化文本长度
print("\n" + "=" * 70)
print("4. SOURCES — extracted text length")
print("=" * 70)
sources = conn.execute(
    "SELECT id, source_type, status, length(normalized_text) as text_len, "
    "normalized_text FROM knowledge_sources ORDER BY id"
).fetchall()
for s in sources:
    print(f"\n  source id={s['id']} type={s['source_type']} status={s['status']} text_len={s['text_len']}")
    if s['normalized_text']:
        print(f"    first 500 chars: {s['normalized_text'][:500]}")
        print(f"    ...")
        print(f"    last 200 chars: {s['normalized_text'][-200:]}")

conn.close()
print("\nDone.")
