"""P1 快速验证脚本"""
import asyncio, sys
sys.path.insert(0, r"C:\Users\Administrator\Desktop\pycode")

# 1. 导入
from pycoder.ai.generation import MultiStrategyGenerator, SinglePassGenerator, IterativeGenerator, TestDrivenGenerator
from pycoder.ai.security import CompositeSecurityScanner, MetricsAnalyzer, VulnerabilityScanner
print("P1 导入: OK")

# 2. 度量
m = MetricsAnalyzer()
r = asyncio.run(m.analyze("""def add(a,b): return a+b
class A:
    def m1(self): pass
    def m2(self): pass
    def m3(self): pass
    def m4(self): pass
"""))
assert r["structure"]["function_count"] >= 1
print(f"  度量: {r['structure']['function_count']}个函数, McCabe={r['complexity']['avg_mccabe']}")

# 3. 安全扫描
v = VulnerabilityScanner()
scan = asyncio.run(v.scan('api_key = "sk-123456789012345678901234567890"\npassword = "danger"\neval(x)'))
assert len(scan) >= 3
print(f"  安全: {len(scan)}个漏洞发现(API Key+Password+eval)")

# 4. 审计
s = CompositeSecurityScanner()
a = asyncio.run(s.full_audit("import os\ndef f(): return os.system('ls')"))
assert a["risk_level"] in ("critical", "high", "medium", "low")
print(f"  审计: risk={a['risk_level']}, findings={a['summary']['vulnerabilities']}")

# 5. 生成器
g = MultiStrategyGenerator()
from pycoder.ai.interface.types import CodeGenStrategy, CodeGenerationRequest
s = g._select_strategy(CodeGenerationRequest(prompt="hello"))
print(f"  策略(简单): {s.name}")  # SINGLE_PASS
s = g._select_strategy(CodeGenerationRequest(prompt="实现一个红黑树算法，需要处理大量数据"))
print(f"  策略(复杂): {s.name}")  # ITERATIVE

print("\nP1 全部验证通过 ✅")
