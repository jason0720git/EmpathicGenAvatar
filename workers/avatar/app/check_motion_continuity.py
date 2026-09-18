"""WAV-only before/after portrait motion audit (no Realtime/TTS calls)."""
import asyncio
import hashlib
import json
import struct
import sys
import uuid
from pathlib import Path

import cv2
import numpy as np
import websockets
from app.check_wav_test import request


def vertical_shift(reference, frame):
    # Nose/upper-face feature displacement; an image-space diagnostic, not
    # an anatomical pose estimate. Use the same region before and after.
    gray = lambda a: cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    a, b = gray(reference), gray(frame)
    h, w = a.shape
    mask = np.zeros_like(a)
    mask[int(h*.24):int(h*.52), int(w*.36):int(w*.64)] = 255
    points = cv2.goodFeaturesToTrack(a, 60, .02, 5, mask=mask)
    moved, good, _ = cv2.calcOpticalFlowPyrLK(a, b, points, None)
    delta = (moved-points).reshape(-1,2)[good.ravel()==1]
    return float(np.median(delta[:,1]))


async def main():
    label = sys.argv[1]
    revision = int(sys.argv[2])
    root = Path('/data/benchmarks')/label
    root.mkdir(parents=True,exist_ok=True)
    avatar='demo-seoyeon'
    prefix=hashlib.sha256(avatar.encode()).hexdigest()[:24]
    directory=Path('/data/idle')/f'{prefix}-r{revision}-v0'
    idle=[cv2.imread(str(directory/f'{i:04d}.jpg')) for i in range(400)]
    assert all(f is not None for f in idle)
    session=await asyncio.to_thread(request,'/api/live/sessions',{'avatar_id':avatar,'renderer_method':'ditto_realtime_trt10','mode':'wav_test'})
    turn='motion-'+uuid.uuid4().hex[:12]
    try:
        response=await asyncio.to_thread(request,f"/api/live/sessions/{session['id']}/turns",{'text':'WAV motion audit','client_turn_id':turn,'affect_override':{'emotion':'happy','intensity':1},'expression_render_mode':'speech_safe'})
        frames=[]; pcm=bytearray()
        async with websockets.connect('ws://web'+response['renderer']['stream_url'],max_size=4000000) as ws:
            while True:
                packet=await asyncio.wait_for(ws.recv(),timeout=60)
                kind,pts=struct.unpack('>BI',packet[:5])
                if kind==1: pcm.extend(packet[5:])
                elif kind==2: frames.append(cv2.imdecode(np.frombuffer(packet[5:],np.uint8),cv2.IMREAD_COLOR))
                elif kind==3: break
        anchor=idle[0]
        dy=[vertical_shift(anchor,f) for f in idle[::4]]
        speech_dy=[vertical_shift(anchor,f) for f in frames]
        mae=lambda a,b:float(np.abs(a.astype(np.float32)-b.astype(np.float32)).mean())
        result={'turn':turn,'idle_vertical_range_px':float(np.ptp(dy)),
                'speech_vertical_range_px':float(np.ptp(speech_dy)),
                'idle_start_adjacent_mae':[mae(idle[i],idle[i-1]) for i in range(1,16)],
                'entry_mae':mae(frames[0],anchor),'exit_mae':mae(frames[-1],anchor),
                'idle_loop_mae':mae(idle[-1],anchor),
                'video_frames':len(frames),'pcm_sha256':hashlib.sha256(pcm).hexdigest()}
        (root/'results.json').write_text(json.dumps(result,indent=2))
        # Keep preview-sized evidence, not a >500MB full-resolution dump.
        preview=lambda seq:np.stack([cv2.resize(f,(384,round(f.shape[0]*384/f.shape[1]))) for f in seq])
        np.savez_compressed(root/'frames.npz',idle=preview(idle),speech=preview(frames))
        print(json.dumps(result),flush=True)
    finally:
        await asyncio.to_thread(request,f"/api/live/sessions/{session['id']}",method='DELETE')


if __name__=='__main__':asyncio.run(main())
