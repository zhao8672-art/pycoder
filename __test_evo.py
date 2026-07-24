"""测试自我进化引擎"""
import json
import urllib.request
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:8423"
AUTH = "AX8iZWiH7B0aK2Lh1ZdC8F_hbjvA58h6QW6CkDFI9z0"

def req(method, path, data=None):
    url = f"{BASE}{path}"
    headers = {"X-API-Key": AUTH, "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(url, data=body, headers=headers, method=method)
    resp = urllib.request.urlopen(r, timeout=30)
    return json.loads(resp.read())

# 1. Health
print("="*50)
print("1. Health Check")
h = req("GET", "/api/health")
print(f"   status={h.get('status')}, uptime={h.get('server_uptime',0):.0f}s")

# 2. Evolution Stats
print("\n" + "="*50)
print("2. Evolution Stats")
s = req("GET", "/api/v2/evolution/stats")
stats = s.get("stats", {})
print(f"   total_tasks={stats.get('total_tasks')}")
print(f"   successful={stats.get('successful')}")
print(f"   v2_records={stats.get('v2_records')}")
print(f"   v2_success_rate={stats.get('v2_success_rate', 0)}")

# 3. Test Cycle (dry_run=True)
print("\n" + "="*50)
print("3. Test Self-Evolution Cycle (dry_run)")
result = req("POST", "/api/v2/evolution/test-cycle", {"dry_run": True})
print(f"   success={result.get('success')}")
print(f"   phase_count={result.get('phase_count')}")
print(f"   phases={json.dumps(result.get('phases'), ensure_ascii=False)}")
print(f"   summary={result.get('summary')}")

# 4. Verify run() method exists on engine
print("\n" + "="*50)
print("4. Verify engine.run() method")
from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine
import inspect
has_run = hasattr(SelfEvolutionEngine, 'run')
has_run_cycle = hasattr(SelfEvolutionEngine, 'run_cycle')
has_evolve = hasattr(SelfEvolutionEngine, 'evolve')
print(f"   has run(): {has_run}")
print(f"   has run_cycle(): {has_run_cycle}")
print(f"   has evolve(): {has_evolve}")
run_sig = inspect.signature(SelfEvolutionEngine.run)
print(f"   run() signature: {run_sig}")

print("\n" + "="*50)
print("ALL TESTS COMPLETE")
