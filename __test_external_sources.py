"""快速验证外部技能数据源采集"""
import sys
sys.path.insert(0, ".")

from pycoder.server.skills_external_sources import (
    fetch_techleads_skills,
    fetch_openclaw_skills,
    fetch_all_external_skills,
)

# 1. Tech Leads Club
print("=== Tech Leads Club ===")
tlc = fetch_techleads_skills()
print(f"Fetched: {len(tlc)} skills")
for s in tlc[:5]:
    print(f"  {s.name}: {s.category} (stars={s.stars}, verified={s.verified})")
print()

# 2. OpenClaw
print("=== OpenClaw ===")
oc = fetch_openclaw_skills()
print(f"Fetched: {len(oc)} skills")
for s in oc[:5]:
    print(f"  {s.name}: {s.category} (stars={s.stars})")
print()

# 3. 汇总
all_skills, statuses = fetch_all_external_skills()
print(f"=== Total: {len(all_skills)} skills ===")
for st in statuses:
    tick = "✅" if st["success"] else "❌"
    print(f"  {tick} {st['source']}: {st.get('count', 0)}")
