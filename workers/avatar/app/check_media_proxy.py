"""Synthetic end-to-end render/proxy smoke test; no LLM calls or user audio.

Run in TRT10 worker after benchmark_affect has created synthetic speech.wav.
"""
import asyncio
import json
import struct
import sys
import urllib.request
import uuid

import websockets


async def probe(expression='angry'):
    turn = 'proxy-smoke-' + uuid.uuid4().hex[:12]
    request = urllib.request.Request('http://127.0.0.1:8010/v1/turns/render',
        data=json.dumps({'avatar_id': 'demo-seoyeon', 'turn_id': turn,
            'audio_path': '/data/benchmarks/native8-v3/speech.wav',
            'motion_plan': {'expression': expression, 'intensity': 1, 'expression_test': True}}).encode(),
        headers={'Content-Type': 'application/json'})
    def submit():
        with urllib.request.urlopen(request, timeout=120) as response:
            json.load(response)
    await asyncio.to_thread(submit)
    counts = {1: 0, 2: 0, 3: 0}
    async with websockets.connect('ws://web/avatar-stream-trt10/v1/live/' + turn, max_size=4000000) as socket:
        while True:
            packet = await asyncio.wait_for(socket.recv(), timeout=60)
            kind, _ = struct.unpack('>BI', packet[:5])
            counts[kind] += 1
            if kind == 3:
                break
    assert counts[1] > 0 and counts[2] > 75 and counts[3] == 1
    print(json.dumps({'turn': turn, 'via': 'web nginx TRT10 proxy', 'audio_packets': counts[1], 'video_frames': counts[2], 'end': counts[3]}))


async def main():
    if '--concurrent' in sys.argv:
        await asyncio.gather(probe('happy'), probe('angry'))
    else:
        await probe()


if __name__ == '__main__':
    asyncio.run(main())
