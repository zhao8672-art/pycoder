"""查询 session 数据库"""
import sqlite3, os
db = os.path.expanduser("~/.pycoder/pycoder.db")
conn = sqlite3.connect(db)
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables:", [r[0] for r in c.fetchall()])
c.execute("SELECT * FROM behavior_logs ORDER BY id DESC LIMIT 5")
print("Behavior logs:")
for r in c.fetchall():
    print(f"  {r}")
conn.close()
