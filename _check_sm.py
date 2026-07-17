"""检查 SkillsManager 状态"""
import sys, asyncio
sys.path.insert(0, r"C:\Users\Administrator\Desktop\pycode")
from pycoder.skills import SkillMarketplace

sm = SkillMarketplace()
print(f"DB path: {sm._db_path}")
print(f"DB exists: {sm._db_path.exists()}")

# Check DB directly
import sqlite3
conn = sqlite3.connect(str(sm._db_path))
count = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
print(f"DB count: {count}")
names = conn.execute("SELECT id, name FROM skills LIMIT 5").fetchall()
print(f"First 5: {names}")
conn.close()

# Search
r = asyncio.run(sm.search_skills(""))
print(f"Search results: {len(r.get('skills',[]))}")

# Install first
if r.get("skills"):
    s = r["skills"][0]
    print(f"First skill: {s.get('name')} ({s.get('id')})")
