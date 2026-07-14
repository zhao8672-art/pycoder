import asyncio
from pycoder.server.chat_handler import _run_chat_stream


async def main():
    out = ""
    async for ev in _run_chat_stream(None, "请用python写一个打印hello world的函数", "deepseek-chat"):
        t = ev.get("type")
        if t == "token":
            out += ev.get("data", "")
        elif t == "error":
            print("ERROR:", ev)
            return
        elif t == "done":
            print("DONE len=", len(out))
            print(out[:600])
            return
    print("NO_DONE", out[:200])


asyncio.run(main())
