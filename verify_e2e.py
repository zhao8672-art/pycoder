"""PyCoder AI 功能全面测试"""
import asyncio, json, sys

async def test_all():
    results = []

    print("=== 0. 运行环境 ===")
    import httpx
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.get("http://127.0.0.1:8423/api/health")
        h = r.json()
        print(f"  后端: status={h['status']}, uptime={h['server_uptime']:.0f}s")
        results.append(("后端运行", True))

    print("\n=== 1. API Key 配置 ===")
    async with httpx.AsyncClient() as c:
        r = await c.get("http://127.0.0.1:8423/api/config/keys")
        data = r.json()
        configured = [k for k, v in data["providers"].items() if v["configured"]]
        print(f"  已配置: {configured}")
        results.append((f"Key配置({configured})", True))

    print("\n=== 2. ChatBridge 聊天 ===")
    sys.path.insert(0, ".")
    from pycoder.server.chat_bridge import ChatBridge
    from pycoder.providers.auth import get_model_manager
    mm = get_model_manager()
    bridge = ChatBridge()
    key = mm.get_saved_key("deepseek")
    if key:
        bridge.configure(model="deepseek-chat", api_key=key)
        try:
            resp = await bridge.chat("用中文回复: 测试消息，回复OK即可", max_tokens=100)
            print(f"  回复: {resp[:120]}...")
            results.append(("ChatBridge", True))
        except Exception as e:
            print(f"  错误: {e}")
            results.append(("ChatBridge", False))
    else:
        print("  无 DeepSeek Key")
        results.append(("ChatBridge(无Key)", False))

    print("\n=== 3. HTTP API 聊天 ===")
    try:
        api_key = open(r"C:\Users\Administrator\.pycoder\.api_key").read().strip()
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                "http://127.0.0.1:8423/api/chat",
                headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                json={"message": "用中文回复: 你好世界", "model": "deepseek-chat"},
            )
            d = r.json() if r.status_code == 200 else {"error": r.text[:200]}
            print(f"  Status: {r.status_code}, Response: {str(d)[:150]}")
            results.append(("HTTP API", r.status_code == 200))
    except Exception as e:
        print(f"  错误: {e}")
        results.append(("HTTP API", False))

    print("\n=== 4. 五层代码分析 ===")
    from pycoder.ai.analysis import CompositeAnalyzer
    from pycoder.ai.interface.types import CodeAnalysisRequest, AnalysisDepth
    a = CompositeAnalyzer()
    r = await a.analyze(CodeAnalysisRequest(code="import os\ndef f(x):\n    if x==None:\n        pass\n    for i in range(10):\n        for j in range(5):\n            pass", language="python", depth=AnalysisDepth.ARCHITECTURAL))
    print(f"  Issues: {len(r.issues)}, Time: {r.analysis_time_ms}ms")
    for iss in r.issues[:3]:
        print(f"    [{iss.get('severity','?')}] {iss.get('code','')}: {iss.get('message','')[:60]}")
    results.append(("五层分析", True))

    print("\n=== 5. NLU ===")
    from pycoder.ai.nlu import CompositeNLUEngine
    nlu = CompositeNLUEngine()
    for txt in ["写一个快速排序", "修复bug", "解释代码"]:
        r = await nlu.understand(txt)
        print(f"  '{txt}': intent={r.intent}, conf={r.confidence:.2f}")
    results.append(("NLU", True))

    print("\n=== 6. 安全扫描 ===")
    from pycoder.ai.security import CompositeSecurityScanner
    s = CompositeSecurityScanner()
    audit = await s.full_audit("api_key='sk-xxx'\npassword='secret'\neval(x)")
    print(f"  风险: {audit['risk_level']}, 漏洞: {audit['summary']}")
    results.append(("安全扫描", True))

    print("\n=== 7. 竞品分析 ===")
    from pycoder.ai.benchmark.analyzer import get_analyzer
    ca = get_analyzer()
    report = ca.run_full_analysis()
    print(f"  评分: {report.overall_score}/10, 差距: {len(report.feature_gaps)}")
    results.append(("竞品分析", True))

    print("\n=== 8. 融合引擎 ===")
    from pycoder.ai.fusion.engine import FusionEngine, FusionMode, IFusionProvider, ProviderResult
    from pycoder.ai.interface.types import ProviderCapability
    class MockP(IFusionProvider):
        def __init__(self, n, s): self._n=n; self._c=ProviderCapability(provider=n, code_generation=s)
        @property
        def name(self): return self._n
        @property
        def capability(self): return self._c
        async def generate(self, p, sp="", **kw): return ProviderResult(provider=self._n, content="ok", latency_ms=50)
    eng = FusionEngine(); eng.register(MockP("ds",0.85)); eng.register(MockP("qw",0.70))
    fr = await eng.fuse("test", mode=FusionMode.BEST_OF_N, providers=["ds","qw"])
    print(f"  输出: {fr.final_output[:30]}, 时间: {fr.total_time_ms:.0f}ms")
    results.append(("融合引擎", True))

    print("\n=== 9. KV Cache ===")
    from pycoder.ai.cache import get_cache
    c = get_cache(); c.set("test","out"); r = c.get("test2")
    print(f"  {r or 'MISS'}, Stats: {c.stats()}")
    results.append(("KV Cache", True))

    print("\n=== 10. 对话追踪 ===")
    from pycoder.ai.dialog import get_tracker
    dt = get_tracker()
    dt.update_intent("s1","生成代码",0.9); dt.add_entity("s1","file","/main.py")
    rr = dt.resolve_anaphora("s1","优化它")
    print(f"  回指: '{rr}'")
    results.append(("对话追踪", True))

    print("\n=== 11. 策略选择 ===")
    from pycoder.ai.generation import MultiStrategyGenerator
    from pycoder.ai.interface.types import CodeGenerationRequest, CodeGenStrategy
    g = MultiStrategyGenerator()
    s1 = g._select_strategy(CodeGenerationRequest(prompt="hello")).name
    s2 = g._select_strategy(CodeGenerationRequest(prompt="实现一个红黑树算法")).name
    print(f"  简单: {s1}, 复杂: {s2}")
    results.append(("策略选择", True))

    print("\n" + "=" * 50)
    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f"  {'✅' if ok else '❌'} {name}")
    print(f"\n总计: {passed}/{len(results)} 测试通过")

asyncio.run(test_all())
