"""端到端测试：让AI执行"配置DeepSeek大模型"任务"""
import asyncio, json, os, time, sys

api_key_file = os.path.expanduser("~/.pycoder/.api_key")
api_key = open(api_key_file).read().strip() if os.path.exists(api_key_file) else ""
WS_URL = f"ws://127.0.0.1:8423/ws/chat/v2"
if api_key:
    WS_URL += f"?api_key={api_key}"

import websockets

async def main():
    print("=" * 60)
    print("测试: 配置DeepSeek大模型")
    print("=" * 60)
    start_total = time.time()
    async with websockets.connect(WS_URL) as ws:
        raw = await ws.recv()
        connected = json.loads(raw)
        print(f"[已连接] session={connected.get('session_id','')[:8]} engine={connected.get('engine')}")

        msg = "帮我配置DeepSeek大模型，设置API Key并测试连接是否正常。请逐步执行。"
        await ws.send(json.dumps({
            "type": "chat", "message": msg,
            "model": "deepseek-chat",
            "reasoning_effort": "medium", "enable_cache": False,
        }))
        print(f"[发送] {msg[:60]}...\n")
        print(f"\n{'─'*60}")
        print(f"执行过程追踪:")
        print(f"{'─'*60}\n")

        event_count = 0
        token_count = 0
        tool_calls_detected = []
        errors = []
        has_done = False
        full_content = ""
        stages = []  # timeline 记录

        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=180)
            except asyncio.TimeoutError:
                print(f"\n[TIMEOUT] 180s 无响应")
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
                    tool_calls_detected.append(content.strip()[:60])
                elif "📋" in content:
                    pass  # 静默
            elif etype == "reasoning":
                pass
            elif etype == "agent_status":
                msg_text = event.get("message","")
                icon = msg_text[:2] if msg_text else ""
                stages.append(f"[{elapsed:5.1f}s] 🔵 {msg_text}")
                print(f"[{elapsed:5.1f}s] 🔵 {msg_text}")
            elif etype == "agent_step":
                tn = event.get("tool_name","")
                status = "✅" if "❌" not in str(event.get("result","")) else "❌"
                print(f"[{elapsed:5.1f}s] {status} 工具结果: {tn}")
            elif etype == "done":
                content = event.get("content","")
                tc = event.get("tool_calls_count", 0)
                print(f"\n{'─'*60}")
                print(f"[完成] 耗时 {elapsed:.1f}s | 事件 {event_count} | 工具调用 {tc}")
                print(f"{'─'*60}")
                print(content[:800])
                full_content = content
                has_done = True
                break
            elif etype == "error":
                errors.append(event.get("message",""))
                print(f"[{elapsed:5.1f}s] ❌ ERROR: {event.get('message','')}")
                break
            elif etype == "progress":
                pct = event.get("percent", 0)
                stage = event.get("stage", "")
                if tool_calls_detected:
                    pass
                else:
                    print(f"[{elapsed:5.1f}s] ⏳ 进度: {stage} ({pct}%)")

        # 分析报告
        print(f"\n{'='*60}")
        print("分析报告")
        print(f"{'='*60}")
        print(f"总事件数: {event_count}")
        print(f"总 token 数: {token_count}")
        print(f"工具调用次数: {len(tool_calls_detected)}")
        print(f"错误数: {len(errors)}")
        print(f"是否完成: {'是' if has_done else '否'}")

        if tool_calls_detected:
            print(f"\n工具调用清单:")
            for i, tc in enumerate(tool_calls_detected, 1):
                print(f"  {i}. {tc}")

        # 检查AI是否真的执行了任务
        has_executed = len(tool_calls_detected) > 0
        has_meaningful_content = len(full_content) > 50
        print(f"\n综合评价:")
        print(f"  实际执行了工具: {'✅' if has_executed else '❌'}")
        print(f"  输出有实质内容: {'✅' if has_meaningful_content else '❌'}")
        if errors:
            print(f"  错误: {'❌ '.join(errors)}")

        if has_done and not has_executed:
            print(f"\n  ⚠️ AI只输出了文字描述而没有调用任何工具来执行任务！")
            print(f"  前200字符: {full_content[:200]}")
        elif has_done and has_executed:
            print(f"  ✅ AI正确执行了工具来完成配置任务")

asyncio.run(main())
