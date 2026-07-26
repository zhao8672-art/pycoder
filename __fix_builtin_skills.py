"""修复内置技能的 is_builtin 标记和安装状态"""
import sqlite3
import datetime

c = sqlite3.connect("data/skills/skills.db")
builtin_ids = [
    "code-review", "test-generator", "doc-generator", "refactor-helper",
    "security-scanner", "performance-analyzer", "git-helper", "dependency-checker",
    "lint-fixer", "api-doc-generator", "code-explainer", "project-scaffolder",
]

now = datetime.datetime.now().isoformat()
fixed = 0

c.execute("BEGIN")
for bid in builtin_ids:
    c.execute(
        "UPDATE skills SET is_builtin=1, installed_at=? WHERE id=? AND (installed_at IS NULL OR installed_at='')",
        (now, bid),
    )
    if c.total_changes:
        fixed += 1

c.commit()
print(f"Fixed {fixed} builtin skills")

# 验证
for row in c.execute(
    "SELECT id, is_builtin, installed_at FROM skills WHERE id IN ({})".format(
        ",".join("?" for _ in builtin_ids)
    ),
    builtin_ids,
):
    print(f"  {row[0]}: is_builtin={row[1]}, installed={bool(row[2])}")

# 总数
i = c.execute("SELECT COUNT(*) FROM skills WHERE installed_at != ''").fetchone()[0]
u = c.execute("SELECT COUNT(*) FROM skills WHERE installed_at = ''").fetchone()[0]
print(f"\nInstalled: {i}, Recommended (uninstalled): {u}")
c.close()
