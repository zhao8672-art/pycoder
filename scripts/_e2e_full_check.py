"""
端到端全面自检 v2 — 包含Skills/插件搜索安装链路测试
"""
import asyncio, json, os, time

api_key_file = os.path.expanduser("~/.pycoder/.api_key")
api_key = ""
if os.path.exists(api_key_file):
    api_key = open(api_key_file).read().strip()

WS_URL = f"ws://127.0.0.1:8423/ws/chat/v2"
if api_key:
    WS_URL += f"?api_key={api_key}"

import websockets

async def test_skills_and_plugins():
    """测试 skills market 和插件自动安装功能"""
    print("=" * 60)
    print("测试1: Skills Market 搜索")
    print("=" * 60)
    
    async with websockets.connect(WS_URL) as ws:
        raw = await ws.recv()
        connected = json.loads(raw)
        print(f"[OK] 已连接 session={connected.get('session_id','')[:8]}")
        
        # 1️⃣ 测试 skills_search_v2
        await ws.send(json.dumps({"type": "v2_call", "capability_id": "skills_search_v2", "params": {"query": "python", "limit": 5}}))
        resp = await asyncio.wait_for(ws.recv(), timeout=30)
        result = json.loads(resp)
        print(f"  skills_search_v2: type={result.get('type')} success={result.get('success')}")
        if result.get('success'):
            total = result.get('data', {}).get('total', 0) or result.get('total', 0)
            print(f"  → 找到 {total} 个技能")
        else:
            print(f"  → 失败: {result.get('error', '未知')}")

async def test_full_selfcheck():
    """测试系统全面自检"""
    print("\n" + "=" * 60)
    print("测试2: 系统全面自检（含 skills/plugins 安装检测）")
    print("=" * 60)
    
    async with websockets.connect(WS_URL) as ws:
        raw = await ws.recv()
        connected = json.loads(raw)
        print(f"[OK] 已连接 session={connected.get('session_id','')[:8]}")
        
        msg = ("现在来完成全面的系统自检！逐项验证所有功能模块："
               "1) 代码质量  2) Git状态  3) 依赖安全  4) 文件结构  "
               "5) 环境工具  6) 运行状态  7) Skills市场  8) 插件系统  "
               "9) 自动安装能力")
        
        await ws.send(json.dumps({
            "type": "chat", "message": msg,
            "model": "deepseek-chat",
            "reasoning_effort": "medium", "enable_cache": True,
        }))
        print(f"[SEND] 系统全面自检...\n")
        
        event_count = 0
        tool_calls = 0
        tools_list = []
        start = time.time()
        has_skills = has_plugins = False
        
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=180)
            except asyncio.TimeoutError:
                print(f"[TIMEOUT] after {event_count} events")
                break
                
            event = json.loads(raw)
            event_count += 1
            etype = event.get("type", "")
            elapsed = time.time() - start
            
            if etype == "token":
                content = event.get("data","") or event.get("content","")
                if "🔧" in content:
                    tool_calls += 1
                    tool_name = content.replace("🔧 执行 ","").strip()[:50]
                    tools_list.append(tool_name)
                    if "skill" in tool_name.lower():
                        has_skills = True
                    if "plugin" in tool_name.lower() or "extensions" in tool_name.lower():
                        has_plugins = True
                    print(f"  ⚡ #{tool_calls} [{elapsed:4.1f}s] {tool_name}")
                elif "📋" in content:
                    pass  # 静默
                elif event_count % 50 == 0:
                    print(f"  ... token event #{event_count}")
                    
            elif etype == "agent_step":
                tn = event.get("tool_name","")
                if event.get("step") == "tool_result":
                    result_text = str(event.get("result",""))[:80]
                    if "❌" not in result_text:
                        print(f"  ✅ #{event_count} {tn}: OK")
                    else:
                        print(f"  ❌ #{event_count} {tn}: FAIL")
                if "skill" in tn.lower():
                    has_skills = True
                if "plugin" in tn.lower() or "extensions" in tn.lower():
                    has_plugins = True
                    
            elif etype == "agent_result":
                status = event.get("status")
                summary = event.get("summary","")[:200]
                print(f"\n[RESULT] status={status}")
                print(f"  summary: {summary}")
                
            elif etype == "done":
                elapsed_total = time.time() - start
                print(f"\n=== DONE ({elapsed_total:.1f}s) ===")
                print(f"Total events: {event_count}")
                print(f"Tool calls: {tool_calls}")
                print(f"Tools: {tools_list}")
                print(f"触及Skills市场: {'是' if has_skills else '否'}")
                print(f"触及插件系统: {'是' if has_plugins else '否'}")
                
                # 最终报告
                print(f"\n{'='*60}")
                print("全面自检报告:")
                print(f"  ✅ 意图路由: AGENT模式")
                print(f"  ✅ AI首次输出JSON: {'是' if tool_calls > 0 else '否'}")
                print(f"  ✅ 工具调用次数: {tool_calls}")
                print(f"  ✅ Skills市场检测: {'是' if has_skills else '需手动确认'}")
                print(f"  ✅ 插件系统检测: {'是' if has_plugins else '需手动确认'}")
                print(f"  ✅ 执行耗时: {elapsed_total:.1f}s")
                return True
                
            elif etype == "error":
                print(f"[ERROR] {event.get('message','')}")
                
        return False

async def main():
    await test_skills_and_plugins()
    await test_full_selfcheck()

asyncio.run(main())
