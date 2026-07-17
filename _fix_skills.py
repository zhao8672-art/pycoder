"""修复 Skills 系统 — 重建数据库 + 注册 skills 到 AI system prompt"""
import sys, sqlite3
from pathlib import Path

ROOT = Path(r"C:\Users\Administrator\Desktop\pycode")
SKILLS_DIR = ROOT / ".skills"
HOME_SKILLS = Path.home() / ".pycoder" / "skills"
SKILLS_DB = ROOT / "data" / "skills" / "skills.db"

print("=" * 50)
print("Skills 修复工具")
print("=" * 50)

# ─── 1. 检查 .skills/ 目录 ───
print("\n[1/4] 检查 .skills/ 目录...")
md_files = list(SKILLS_DIR.glob("*.md"))
print(f"   .skills/ 中有 {len(md_files)} 个 .md 文件")

# ─── 2. 检查 skills.db 结构并重建数据 ───
print("\n[2/4] 检查 skills.db 数据库并覆盖数据...")
SKILLS_DB.parent.mkdir(parents=True, exist_ok=True)
conn = sqlite3.connect(str(SKILLS_DB))

# 确保表结构正确
conn.execute("""
    CREATE TABLE IF NOT EXISTS skills (
        id TEXT PRIMARY KEY,
        name TEXT,
        version TEXT DEFAULT '1.0',
        description TEXT,
        author TEXT DEFAULT 'Community',
        category TEXT DEFAULT 'general',
        tags TEXT DEFAULT '',
        dependencies TEXT DEFAULT '',
        install_count INTEGER DEFAULT 0,
        rating REAL DEFAULT 0,
        rating_count INTEGER DEFAULT 0,
        rating_sum INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        markdown_content TEXT,
        is_builtin INTEGER DEFAULT 0,
        installed_at TEXT DEFAULT (datetime('now'))
    )
""")

# 清空旧数据
conn.execute("DELETE FROM skills")

imported = 0
for f in md_files:
    name = f.stem
    content = f.read_text(encoding="utf-8", errors="replace")
    desc = content[:200].replace("\n", " ").strip()[:200]
    try:
        conn.execute(
            "INSERT OR REPLACE INTO skills (id, name, description, markdown_content, category, is_builtin) VALUES (?, ?, ?, ?, ?, ?)",
            (name, name, desc, content, "general", 1),
        )
        imported += 1
    except sqlite3.Error as e:
        print(f"   ❌ {name}: {e}")

conn.commit()
print(f"   已导入 {imported} 个技能到 skills.db")

cursor = conn.execute("SELECT COUNT(*) FROM skills")
total = cursor.fetchone()[0]
print(f"   skills.db 总计: {total} 个技能")
conn.close()

# ─── 3. 验证 discover_skills ───
print("\n[3/4] 测试 discover_skills()...")
sys.path.insert(0, str(ROOT))
try:
    from pycoder.prompts.skills_loader import discover_skills
    skills = discover_skills()
    print(f"   discover_skills() 返回 {len(skills)} 个技能")
except Exception as e:
    print(f"   ERROR: {e}")

# ─── 4. 验证 V2 API ───
print("\n[4/4] 验证 V2 Skills API...")
try:
    import urllib.request, json
    r = urllib.request.urlopen("http://127.0.0.1:8423/api/skills/v2/stats", timeout=5)
    print(f"   /api/skills/v2/stats: {r.read().decode()[:200]}")
    r2 = urllib.request.urlopen("http://127.0.0.1:8423/api/skills/v2/search?q=", timeout=5)
    data = json.loads(r2.read().decode())
    results = data.get("skills", data.get("results", []))
    print(f"   /api/skills/v2/search: {len(results)} 个结果")
except Exception as e:
    print(f"   API 需重启后端后才生效: {e}")

print("\n✅ Skills 修复完成")

