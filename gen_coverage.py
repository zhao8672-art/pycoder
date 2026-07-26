"""生成测试覆盖率报告"""
import subprocess
import sys
import os

os.chdir(r"c:\Users\Administrator\Desktop\pycode")

result = subprocess.run(
    [sys.executable, "-m", "pytest", "--cov=pycoder", "--cov-report=term-missing", "tests/", "-q", "--tb=no"],
    capture_output=True,
    text=True,
    timeout=300
)

with open("coverage_report.txt", "w", encoding="utf-8") as f:
    f.write(result.stdout)
    if result.stderr:
        f.write("\n=== STDERR ===\n")
        f.write(result.stderr)

print(f"Exit code: {result.returncode}")
print("Report saved to coverage_report.txt")
