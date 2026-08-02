"""读取最新 session 完整内容"""
import sqlite3
import json
import sys

DB = r"C:\Users\Administrator\.pycoder\unified.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.execute("SELECT id, title, updated_at FROM sessions ORDER BY updated_at DESC LIMIT 1")
row = cur.fetchone()
if not row:
    print("NO SESSIONS")
    sys.exit(0)
sid, title, ua = row
print(f"SESSION: {sid} | {title} | updated_at={ua}")

cur.execute("SELECT id, role, content, timestamp, metadata FROM messages WHERE session_id=? ORDER BY timestamp", (sid,))
rows = cur.fetchall()
print(f"messages={len(rows)}\n")
for i, (mid, role, content, ts, meta) in enumerate(rows):
    print(f"--- [{i}] role={role} ts={ts} ---")
    print(content[:3000])
    if len(content) > 3000:
        print(f"... [truncated {len(content)-3000} more chars]")
    if meta:
        try:
            m = json.loads(meta)
            print(f"[META] {json.dumps(m, ensure_ascii=False)[:500]}")
        except Exception:
            print(f"[META-raw] {str(meta)[:300]}")
    print()
conn.close()
