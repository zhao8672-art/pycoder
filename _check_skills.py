"""检查 Skills 状态"""
import sys
sys.path.insert(0, r"C:\Users\Administrator\Desktop\pycode")

print("1. discover_skills():")
from pycoder.prompts.skills_loader import discover_skills
s = discover_skills()
print(f"   {len(s)} skills")
print(f"   Sources: {set(x.get('source','?') for x in s)}")

print("\n2. V2 Skills API:")
import urllib.request, json
r = urllib.request.urlopen("http://127.0.0.1:8423/api/skills/v2/search?q=", timeout=5)
d = json.loads(r.read().decode())
print(f"   Search: {len(d.get('skills',[]))} results")

print("\n3. Builtin skills:")
try:
    from pycoder.skills.builtin import BUILTIN_SKILLS
    print(f"   {len(BUILTIN_SKILLS)} builtin skills")
    if BUILTIN_SKILLS:
        print(f"   Names: {[bs.name for bs in BUILTIN_SKILLS[:5]]}")
except Exception as e:
    print(f"   ERROR: {e}")

print("\n4. Skills API list:")
try:
    r2 = urllib.request.urlopen("http://127.0.0.1:8423/api/skills/v2/search?q=a", timeout=5)
    d2 = json.loads(r2.read().decode())
    print(f"   Search 'a': {len(d2.get('skills',[]))} results")
except Exception as e:
    print(f"   ERROR: {e}")

print("\nDone")
