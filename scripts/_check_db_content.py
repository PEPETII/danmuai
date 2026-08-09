"""检查知识库内容（调试用）"""
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

apd = os.environ.get("APPDATA", "")
src = Path(apd) / "DanmuAI" / "knowledge.db"

# Checkpoint WAL
conn = sqlite3.connect(str(src))
conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
conn.close()

# Copy to temp
tmpdir = Path(tempfile.mkdtemp())
dst = tmpdir / "knowledge.db"
shutil.copy2(str(src), str(dst))

conn2 = sqlite3.connect(str(dst))
conn2.row_factory = sqlite3.Row
c = conn2.execute(
    "SELECT id, kind, title, substr(content,1,200) as preview, use_count "
    "FROM knowledge_items ORDER BY id"
)
for r in c:
    title = r["title"]
    content = str(r["preview"])
    has_elden = "\u827e\u5c14\u767b" in title or "\u827e\u5c14\u767b" in content
    has_fahuan = "\u6cd5\u73af" in title or "\u6cd5\u73af" in content
    print(f"id={r['id']} uses={r['use_count']} kind={r['kind']}")
    print(f"  title={title}")
    print(f"  content={content[:120]}...")
    print(f"  含艾尔登={has_elden} 含法环={has_fahuan}")
    print()

# All items
print("--- ALL ITEMS ---")
for r in conn2.execute("SELECT id, title, content FROM knowledge_items"):
    print(f"  id={r['id']} title={r['title']}")
    print(f"  content={str(r['content'])[:80]}")

conn2.close()
shutil.rmtree(tmpdir)
