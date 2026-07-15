"""端到端最终测试：详细分析系统优缺点"""
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
    print("=" * 60)
    print("📋 任务: 详细分析系统的优缺点")
    print("=" * 60)
    start_total = time.time()

    async with websockets.connect(WS_URL) as ws:
        raw = await ws.recv()
        connected = json.loads(raw)
        print(f"[已连接] session={connected.get('session_id','')[:8]} engine={connected.get('engine')}")

        msg = "详细分析一下系统的优缺点，包括代码质量、架构设计、功能完整性、性能等方面。请逐步执行并给出最终报告。"
        await ws.send(json.dumps({
            "type": "chat", "message": msg,
            "model": "deepseek-chat",
            "reasoning_effort": "medium", "enable_cache": False,
        }))
        print(f"[发送] {msg[:60]}...\n")

        event_count = 0
        token_count = 0
        tool_calls = []
        errors = []
        has_done = False
        full_content = ""
        stages = []
        prev_pct = 0
        stall_warning = False

        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=180)
            except asyncio.TimeoutError:
                print(f"\n⚠️ 180s 无响应 — 超时中断")
                break
            event = json.loads(raw)
            event_count += 1
            etype = event.get("type", "")
            elapsed = time.time() - start_total

            if etype == "token":
                content = event.get("data","") or event.get("content","")
                token_count += len(content)
                full_content += content
                if "🔧" in content:
                    tool_calls.append(content.strip()[:60])
                stall_warning = False

            elif etype == "agent_status":
                msg_text = event.get("message","")
                print(f"  🔵 [{elapsed:5.1f}s] {msg_text[:100]}")

            elif etype == "progress":
                pct = event.get("percent", 0)
                stage = event.get("stage", "")
                if pct != prev_pct:
                    print(f"  ⏳ [{elapsed:5.1f}s] {stage} ({pct}%)")
                    prev_pct = pct

            elif etype == "agent_step":
                tn = event.get("tool_name","")
                status = "✅" if "❌" not in str(event.get("result","")) else "❌"
                print(f"  {status} [{elapsed:5.1f}s] 工具结果: {tn}")

            elif etype == "done":
                content = event.get("content","")
                tc = event.get("tool_calls_count", 0)
                print(f"\n{'='*60}")
                print(f"✅ 完成! 耗时 {elapsed:.1f}s | 事件 {event_count} | 工具调用 {tc}")
                print(f"{'='*60}")
                print(content[:1200])
                full_content = content
                has_done = True
                break

            elif etype == "reasoning":
                pass  # 静默

            elif etype == "error":
                errors.append(event.get("message",""))
                print(f"\n❌ [{elapsed:5.1f}s] 错误: {event.get('message','')}")
                break

        print(f"\n{'='*60}")
        print("📊 最终报告")
        print(f"{'='*60}")
        print(f"总事件: {event_count}")
        print(f"总 tokens: {token_count}")
        print(f"工具调用: {len(tool_calls)}")
        print(f"错误数: {len(errors)}")
        print(f"内容长度: {len(full_content)}")
        print(f"完成: {'是' if has_done else '否'}")

        if tool_calls:
            print(f"\n工具调用清单:")
            for i, tc in enumerate(tool_calls, 1):
                print(f"  {i}. {tc}")

        return has_done and len(tool_calls) > 0 and len(errors) == 0

asyncio.run(main())
