import asyncio, json, time
try:
    import websockets
except ImportError:
    print("нет websockets"); raise SystemExit
async def main():
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        t0=time.time(); n=0; types={}
        while time.time()-t0 < 12:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
            except asyncio.TimeoutError:
                continue
            n+=1
            try: t=json.loads(msg).get("type")
            except Exception: t="?"
            types[t]=types.get(t,0)+1
        print("за 12 с событий:", n, types)
asyncio.run(main())
