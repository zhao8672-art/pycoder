"""一键提交+推送 — 由 AI 助手在完成任务后调用"""
import subprocess, sys, os
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))

def run(cmd, label=""):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(f"  [{label}] exit={r.returncode}: {(r.stderr or r.stdout)[:200]}")
    else:
        print(f"  [{label}] OK")
    return r

if __name__ == "__main__":
    # 获取 commit message
    msg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    if not msg:
        msg = f"fix: auto commit {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    print("=" * 50)
    print(f"📦 提交: {msg}")
    print("=" * 50)

    # 1. git add
    run(["git", "add", "-A"], "ADD")

    # 2. git status (简短)
    r = run(["git", "status", "--short"], "STATUS")
    if r.stdout and r.stdout.strip():
        files = r.stdout.strip().split("\n")
        print(f"    共 {len(files)} 个文件变更")
        for f in files[:10]:
            print(f"      {f}")
        if len(files) > 10:
            print(f"      ... 还有 {len(files)-10} 个")

    # 3. git commit
    r = run(["git", "commit", "-m", msg], "COMMIT")
    if r.returncode != 0 and "nothing to commit" in (r.stdout + r.stderr):
        print("  ℹ️  无变更，跳过提交")
        sys.exit(0)

    # 4. git push (post-commit hook 也会自动推，但这里双重保障)
    r = run(["git", "push", "origin", "master"], "PUSH")
    if r.returncode == 0:
        print()
        print("✅ 全部完成！已提交并推送到 origin/master")
    else:
        print()
        print("⚠️  推送失败，hook 可能已自动重试")
