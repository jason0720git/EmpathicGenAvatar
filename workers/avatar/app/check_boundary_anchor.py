"""WAV-only GPU audit: actual decoded speech endpoints vs idle source anchor."""
import asyncio
import hashlib
import json
import struct
import uuid
from pathlib import Path

import cv2
import numpy as np
import websockets
from app.check_wav_test import request
from app.main import IDLE_ASSET_VERSION


async def main():
    avatar = 'demo-seoyeon'
    session = await asyncio.to_thread(request, '/api/live/sessions', {
        'avatar_id': avatar, 'renderer_method': 'ditto_realtime_trt10', 'mode': 'wav_test'})
    folder = Path(f'/data/benchmarks/boundary-v{IDLE_ASSET_VERSION}')
    folder.mkdir(parents=True, exist_ok=True)
    prefix = hashlib.sha256(avatar.encode()).hexdigest()[:24]
    anchor = cv2.imread(str(Path('/data/idle') / f'{prefix}-r{IDLE_ASSET_VERSION}-v0/0000.jpg'))
    assert anchor is not None
    results = []
    try:
        for emotion in ('fear', 'happy', 'happy'):
            turn = 'anchor-' + uuid.uuid4().hex[:12]
            response = await asyncio.to_thread(request, f"/api/live/sessions/{session['id']}/turns", {
                'text': 'Fixed WAV boundary audit', 'client_turn_id': turn,
                'affect_override': {'emotion': emotion, 'intensity': 1},
                'expression_render_mode': 'speech_safe'})
            frames = []
            pcm = bytearray()
            async with websockets.connect('ws://web'+response['renderer']['stream_url'], max_size=4000000) as ws:
                while True:
                    packet = await asyncio.wait_for(ws.recv(), timeout=60)
                    kind, pts = struct.unpack('>BI', packet[:5])
                    if kind == 1:
                        pcm.extend(packet[5:])
                    elif kind == 2:
                        frames.append(cv2.imdecode(np.frombuffer(packet[5:], np.uint8), cv2.IMREAD_COLOR))
                    elif kind == 3:
                        break
            mae = lambda a, b: float(np.abs(a.astype(np.float32)-b.astype(np.float32)).mean())
            row = {'turn': turn, 'emotion': emotion, 'frames': len(frames),
                   'first_to_idle_mae': mae(frames[0], anchor),
                   'last_to_idle_mae': mae(frames[-1], anchor),
                   'last_adjacent_mae': mae(frames[-2], frames[-1]),
                   'pcm_sha256': hashlib.sha256(pcm).hexdigest()}
            cv2.imwrite(str(folder/f'{turn}-last.jpg'), frames[-1])
            results.append(row)
            print(json.dumps(row), flush=True)
            assert row['first_to_idle_mae'] < 1 and row['last_to_idle_mae'] < 1, row
        assert len({r['pcm_sha256'] for r in results}) == 1
        (folder/'results.json').write_text(json.dumps(results, indent=2))
    finally:
        await asyncio.to_thread(request, f"/api/live/sessions/{session['id']}", method='DELETE')


if __name__ == '__main__':
    asyncio.run(main())
