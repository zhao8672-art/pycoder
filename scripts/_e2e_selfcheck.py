"""
端到端自检：模拟发送"系统全面自检"并捕获所有事件
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

async def main():
    async with websockets.connect(WS_URL) as ws:
        raw = await ws.recv()
        connected = json.loads(raw)
        print(f"[CONNECTED] session={connected.get('session_id','')[:8]} engine={connected.get('engine')}")

        # 发送系统全面自检
        msg = "现在来完成全面的系统自检！逐项验证所有功能模块：代码质量、Git状态、依赖安全、文件结构、环境工具、运行状态"
        await ws.send(json.dumps({
            "type": "chat", "message": msg,
            "model": "deepseek-chat",
            "reasoning_effort": "medium", "enable_cache": True,
        }))
        print(f"[SEND] {msg[:60]}...\n")

        event_count = 0
        tool_calls_found = 0
        errors_found = []
        finished = False
        start = time.time()
        
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=120)
            except asyncio.TimeoutError:
                print(f"\n[TIMEOUT] after {event_count} events, {time.time()-start:.0f}s")
                break
                
            event = json.loads(raw)
            event_count += 1
            etype = event.get("type", "")
            elapsed = time.time() - start
            
            if etype == "token":
                content = event.get("data", "") or event.get("content", "")
                if "🔧" in content:
                    tool_calls_found += 1
                    print(f"  [{elapsed:4.1f}s] TOOL_CALL #{tool_calls_found}: {content.strip()[:80]}")
                elif "📋" in content:
                    print(f"  [{elapsed:4.1f}s] TOOL_RESULT: {content.strip()[:80]}")
            elif etype == "reasoning":
                pass  # 静默
            elif etype == "agent_status":
                print(f"  [{elapsed:4.1f}s] STATUS: {event.get('message','')[:80]}")
            elif etype == "done":
                content = event.get("content", "")
                tc = event.get("tool_calls_count", 0)
                elapsed_total = time.time() - start
                print(f"\n=== DONE ({elapsed_total:.1f}s) ===")
                print(f"Total events: {event_count}")
                print(f"Tool calls detected: {tool_calls_found}")
                print(f"tool_calls_count field: {tc}")
                print(f"Content length: {len(content)}")
                print(f"Content preview:\n{content[:600]}")
                finished = True
                break
            elif etype == "error":
                errors_found.append(event.get("message",""))
                print(f"  [{elapsed:4.1f}s] ERROR: {event.get('message','')[:100]}")
            elif etype == "progress":
                if event_count <= 10:
                    print(f"  [{elapsed:4.1f}s] PROGRESS: {event.get('stage','')} ({event.get('percent',0)}%)")
            elif etype in ("connected","unified_intent","unified_route","task_status","unified_merge","unified_health","plugin_event","agent_step","agent_result","agent_chunk"):
                if event_count <= 30:
                    print(f"  [{elapsed:4.1f}s] {etype}: {json.dumps(event)[:120]}")
        
        if errors_found:
            print(f"\n[ERRORS FOUND] {len(errors_found)} errors:")
            for e in errors_found:
                print(f"  - {e[:200]}")

asyncio.run(main())
