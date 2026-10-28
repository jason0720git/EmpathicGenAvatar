"""Local fixed-WAV smoke test and idle cache regeneration; no AI API calls."""
import asyncio
import hashlib
import json
import struct
import urllib.request
import uuid
from pathlib import Path

import cv2
import numpy as np
import websockets

from .main import CacheStore, IDLE_ASSET_VERSION, REST_MOUTH_PROFILE


def post(path, body):
    request = urllib.request.Request('http://127.0.0.1:8010' + path,
        data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=240) as response:
        return json.load(response)


async def main():
    output = Path('/data/benchmarks/rest-mouth-v1')
    output.mkdir(parents=True, exist_ok=True)
    source = CacheStore(Path('/data/avatar-cache')).get('demo-seoyeon')['source_path']
    idle = await asyncio.to_thread(post, '/v1/avatars/idle',
        {'avatar_id': 'demo-seoyeon', 'avatar_version': 1, 'source_path': source, 'variants': 3})
    print('idle:', idle, flush=True)
    turn = 'rest-mouth-' + uuid.uuid4().hex[:10]
    await asyncio.to_thread(post, '/v1/turns/render', {
        'avatar_id': 'demo-seoyeon', 'turn_id': turn,
        'audio_path': '/data/test-audio/reference.wav',
        'motion_plan': {'expression': 'neutral', 'intensity': 0}})
    counts = [0, 0, 0, 0]
    previous_pts = {1: -1, 2: -1}
    captures = []
    writer = None
    try:
        async with websockets.connect('ws://127.0.0.1:8010/v1/live/' + turn, max_size=4000000) as socket:
            while True:
                packet = await asyncio.wait_for(socket.recv(), timeout=90)
                kind, pts = struct.unpack('>BI', packet[:5])
                counts[kind] += 1
                if kind == 3:
                    break
                if kind in previous_pts:
                    assert pts > previous_pts[kind]
                    previous_pts[kind] = pts
                if kind != 2:
                    continue
                frame = cv2.imdecode(np.frombuffer(packet[5:], np.uint8), cv2.IMREAD_COLOR)
                assert frame is not None
                if writer is None:
                    writer = cv2.VideoWriter(str(output / 'neutral.mp4'), cv2.VideoWriter_fourcc(*'mp4v'), 25, (frame.shape[1], frame.shape[0]))
                writer.write(frame)
                if counts[2] in (1, 26, 51, 76, 101):
                    captures.append(cv2.resize(frame, (256, 256)))
    finally:
        if writer:
            writer.release()
    assert counts[1] > 0 and counts[2] > 100 and counts[3] == 1
    cv2.imwrite(str(output / 'speech.jpg'), np.hstack(captures))
    avatar_key = hashlib.sha256(b'demo-seoyeon').hexdigest()[:24]
    paths = sorted(Path(f'/data/idle/{avatar_key}-r{IDLE_ASSET_VERSION}-v0').glob('*.jpg'))
    assert len(paths) == 400
    idle_samples = [cv2.resize(cv2.imread(str(paths[i])), (256, 256)) for i in (0, 100, 200, 300, 399)]
    cv2.imwrite(str(output / 'idle.jpg'), np.hstack(idle_samples))
    report = {'profile': REST_MOUTH_PROFILE, 'turn_id': turn, 'counts': counts,
              'last_pts': previous_pts, 'idle': idle, 'idle_frames_per_loop': len(paths)}
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
