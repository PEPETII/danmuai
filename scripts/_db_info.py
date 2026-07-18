import sqlite3, os
db_path = os.path.join(os.environ.get('APPDATA', ''), 'DanmuAI', 'knowledge.db')
conn = sqlite3.connect(db_path)
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
print(f"DB: {db_path}")
print(f"Size: {os.path.getsize(db_path)/1024:.1f} KB")
print(f"Tables: {tables}")
print()
for t in tables:
    cnt = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
    print(f"  {t}: {cnt} rows")
conn.close()
