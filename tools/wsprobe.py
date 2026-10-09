import asyncio, json
async def main():
    try:
        import websockets
    except ImportError:
        print("no websockets pkg"); return
    try:
        async with websockets.connect("ws://127.0.0.1:8765/ws", origin="http://127.0.0.1:8765", open_timeout=10) as ws:
            for _ in range(3):
                m = await asyncio.wait_for(ws.recv(), 10)
                print("<-", str(m)[:160])
    except Exception as e:
        print("WS ERR", repr(e)[:300])
asyncio.run(main())
