"""一键提交+推送 — 由 AI 助手在完成任务后调用"""
import os
import subprocess
import sys
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

    # 1. git add (-u 仅暂存已跟踪文件的修改/删除, 避免误提交未跟踪的
    #    敏感文件如 .env / credentials; 新文件需显式 `git add <file>`)
    run(["git", "add", "-u"], "ADD")

    # 2. git status (简短)
    r = run(["git", "status", "--short"], "STATUS")
    if r.stdout and r.stdout.strip():
        files = r.stdout.strip().split("\n")
        print(f"    共 {len(files)} 个文件变更")
        for f in files[:10]:
            print(f"      {f}")
        if len(files) > 10:
            print(f"      ... 还有 {len(files)-10} 个")
        # 提示未跟踪文件 (git add -u 不会暂存这些, 需手动 git add)
        untracked = [f for f in files if f.startswith("??")]
        if untracked:
            print(f"    ℹ️  检测到 {len(untracked)} 个未跟踪文件未提交 (需手动 `git add`):")
            for f in untracked[:5]:
                print(f"      {f}")

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
        sys.exit(1)
