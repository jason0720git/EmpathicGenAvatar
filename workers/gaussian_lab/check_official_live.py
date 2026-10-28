"""Exercise the actual GPU service with reproducible articulation poses."""
import asyncio,json
from pathlib import Path
import websockets

async def main():
    out=Path('artifacts/oral-v6');out.mkdir(parents=True,exist_ok=True)
    async with websockets.connect('ws://127.0.0.1:8041/gaussian-render/ws',max_size=4*1024*1024) as ws:
        for index,(name,weights) in enumerate([
            ('neutral',{}),('jaw30',{'jawOpen':.3}),('jaw60',{'jawOpen':.6}),
            ('closed-eyes',{'eyeBlinkLeft':1,'eyeBlinkRight':1}),
            ('smile',{'mouthSmileLeft':.6,'mouthSmileRight':.6,'jawOpen':.25}),
            ('pucker',{'mouthPucker':.6,'jawOpen':.15})]):
            await ws.send(json.dumps({'sequence':index,'weights':weights}))
            stats=json.loads(await ws.recv());raw=await ws.recv()
            (out/f'official-{name}.jpg').write_bytes(raw)
            print(name,stats)
asyncio.run(main())
