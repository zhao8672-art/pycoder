"""测试 OpenClaw 分类文件解析"""
import urllib.request, re, time

url = "https://raw.githubusercontent.com/VoltAgent/awesome-openclaw-skills/main/categories/git-and-github.md"
t0 = time.time()
req = urllib.request.Request(url, headers={"User-Agent": "PyCoder"})
content = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
p = re.compile(r"\[([^\]]+)\]\(https://clawskills\.sh/skills/([^)]+)\)\s*[-–—]\s*([^\n]+)")
matches = p.findall(content)
t = time.time() - t0
print(f"git-and-github.md: {len(matches)} skills, parsed in {t:.1f}s")
for m in matches[:5]:
    print(f"  {m[0]}: {m[2][:60]}...")
