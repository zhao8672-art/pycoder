"""读取最新会话信息"""
import sqlite3, os

db = os.path.expanduser("~/.pycoder/pycoder.db")
conn = sqlite3.connect(db)
c = conn.cursor()

# 表结构
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables:", c.fetchall())

# 最新5个会话
c.execute("SELECT id, message_count, session_id, model, created_at FROM sessions ORDER BY id DESC LIMIT 5")
print("\nLatest 5 sessions:")
for r in c.fetchall():
    print(f"  id={r[0]} msgs={r[1]} sid={str(r[2])[:12]}... model={r[3]} created={r[4]}")

# 最新10条消息
c.execute("SELECT id, session_id, role, substr(content,1,80) as preview, created_at FROM messages ORDER BY id DESC LIMIT 10")
print("\nLatest 10 messages:")
for r in c.fetchall():
    print(f"  id={r[0]} sid={str(r[1])[:8]}... role={r[2]} preview={r[3]} time={r[4]}")

conn.close()
