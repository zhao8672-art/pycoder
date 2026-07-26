"""生成测试覆盖率报告"""
import subprocess
import sys
import os

os.chdir(r"c:\Users\Administrator\Desktop\pycode")

# 运行 pytest 并生成覆盖率报告
result = subprocess.run(
    [sys.executable, "-m", "pytest", "--cov=pycoder", "--cov-report=term-missing", "tests/", "-v", "--tb=short"],
    capture_output=True,
    text=True,
    timeout=300
)

# 保存到文件
with open("coverage_report.txt", "w", encoding="utf-8") as f:
    f.write("=== 测试覆盖率报告 ===\n\n")
    f.write(result.stdout)
    if result.stderr:
        f.write("\n\n=== 错误输出 ===\n")
        f.write(result.stderr)
    f.write(f"\n\n=== 退出码: {result.returncode} ===\n")

# 打印摘要
lines = result.stdout.split('\n')
print("=== 覆盖率摘要 ===")
for line in lines[-50:]:
    print(line)

print(f"\n完整报告已保存到: coverage_report.txt")
