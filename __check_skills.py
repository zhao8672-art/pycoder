"""检查技能数据库安装状态"""
import sqlite3
c = sqlite3.connect("data/skills/skills.db")

# 内置技能安装状态
r = c.execute("SELECT COUNT(*) FROM skills WHERE is_builtin=1 AND installed_at != ''").fetchone()[0]
t = c.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
print(f"Builtin installed: {r}/12, Total skills: {t}")

# 列出全部内置技能
for row in c.execute("SELECT id, name, is_builtin, installed_at FROM skills WHERE is_builtin=1"):
    status = "INSTALLED" if row[3] else "NOT INSTALLED"
    print(f"  {row[0]}: {row[1]} -> {status}")

# 已安装计数
i = c.execute("SELECT COUNT(*) FROM skills WHERE installed_at != ''").fetchone()[0]
print(f"Total installed: {i}")

# 推荐计数（未安装）
u = c.execute("SELECT COUNT(*) FROM skills WHERE installed_at = ''").fetchone()[0]
print(f"Total recommended (uninstalled): {u}")

c.close()
