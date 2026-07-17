"""修复 Skills: 生成 .skills-registry-enhanced.json"""
import json
from pathlib import Path

root = Path(r"C:\Users\Administrator\Desktop\pycode")
skills_dir = root / ".skills"
reg_file = root / ".skills-registry-enhanced.json"

skills = []
for f in sorted(skills_dir.glob("*.md")):
    content = f.read_text(encoding="utf-8", errors="replace")
    skills.append({
        "id": f.stem, "name": f.stem, "version": "1.0",
        "description": content[:300].replace("\n", " ").strip(),
        "author": "PyCoder Community", "category": "general",
        "tags": ["skill"], "content": content,
        "install_count": 0, "rating": 0,
        "created_at": "2026-01-01", "updated_at": "2026-07-18",
        "is_builtin": True,
    })

reg_file.write_text(
    json.dumps({"skills": skills}, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
print(f"Written {len(skills)} skills to {reg_file.name}")
