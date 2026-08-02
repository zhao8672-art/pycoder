"""查看 unified.db 的表结构和最新对话"""
import sqlite3
import json

DB = r"C:\Users\Administrator\.pycoder\unified.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()

# 1. 所有表
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print("TABLES:")
for t in tables:
    print(" -", t)

# 2. 每个表的 schema（只看相关表）
print("\n=== SCHEMAS ===")
for t in tables:
    cur.execute(f"PRAGMA table_info({t})")
    cols = cur.fetchall()
    if cols:
        print(f"\n[{t}]")
        for c in cols:
            print(f"  {c[1]:30s} {c[2]}")

# 3. 找 sessions 表
if "sessions" in tables:
    cur.execute("SELECT id, title, created_at, updated_at, message_count FROM sessions ORDER BY updated_at DESC LIMIT 5")
    print("\n=== LATEST SESSIONS ===")
    for r in cur.fetchall():
        print(r)

conn.close()
