"""简化版测试运行器 - 生成测试报告"""
import subprocess
import sys
import os

os.chdir(r"c:\Users\Administrator\Desktop\pycode")

# 运行测试（不使用覆盖率，更快）
result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
    capture_output=True,
    text=True,
    timeout=300
)

# 保存报告
with open("test_report.txt", "w", encoding="utf-8") as f:
    f.write("=== PyCoder 测试报告 ===\n\n")
    f.write(result.stdout)
    if result.stderr:
        f.write("\n=== 错误输出 ===\n")
        f.write(result.stderr)
    f.write(f"\n\n=== 退出码: {result.returncode} ===\n")

# 打印摘要
lines = result.stdout.split('\n')
print("=== 测试结果摘要 ===")
for line in lines[-30:]:
    print(line)

print(f"\n完整报告已保存到: test_report.txt")
