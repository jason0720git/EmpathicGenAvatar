"""Same-audio, zero-pose comparison for the eight facial presets.

Run inside the GPU worker: python3 -m app.benchmark_affect
Outputs are synthetic evaluation media, never user conversation recordings.
"""
import asyncio
import json
import struct
import subprocess
import urllib.request
import uuid
import wave
import sys
from pathlib import Path

import cv2
import numpy as np
import websockets

from .main import DITTO_EMOTION_INDEX


async def main():
    ab = '--speech-ab' in sys.argv
    output = Path('/data/benchmarks/speech-ab-v5' if ab else '/data/benchmarks/native8-v5')
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(['espeak-ng', '-w', str(output / 'input.wav'),
                    'Hello. This is the same sentence for every expression.'], check=True)
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(output / 'input.wav'),
                    '-ar', '16000', '-ac', '1', str(output / 'speech.wav')], check=True)
    with wave.open(str(output / 'speech.wav'), 'rb') as source:
        params = source.getparams()
        pcm = source.readframes(source.getnframes())
    speech_ms = len(pcm) / 32
    # A full second of silence checks whether a preset forces the jaw open.
    with wave.open(str(output / 'speech.wav'), 'wb') as target:
        target.setparams(params)
        target.writeframes(pcm + bytes(32000))
    silence_moment = int(speech_ms + 400)
    rows = []
    tiles = []
    silence_tiles = []
    variants = [(f'{emotion}-{mode}',emotion,mode) for emotion in ('happy','angry') for mode in ('off','native','legacy','speech_safe')] if ab else [(name,name,'speech_safe') for name in DITTO_EMOTION_INDEX]
    for label, emotion, mode in variants:
        turn = 'native8-' + emotion + '-' + uuid.uuid4().hex[:8]
        request = urllib.request.Request('http://127.0.0.1:8010/v1/turns/render',
            data=json.dumps({'avatar_id': 'demo-seoyeon', 'turn_id': turn,
                'audio_path': str(output / 'speech.wav'),
                'motion_plan': {'expression': emotion, 'intensity': 1,
                                'expression_render_mode': mode,
                                'expression_test': True}}).encode(),
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=120) as response:
            json.load(response)
        counts = [0, 0, 0, 0]
        captures = {}
        writer = None
        audio_packets = []
        try:
            async with websockets.connect('ws://127.0.0.1:8010/v1/live/' + turn,
                                          max_size=4000000) as socket:
                while True:
                    packet = await asyncio.wait_for(socket.recv(), timeout=60)
                    kind, pts = struct.unpack('>BI', packet[:5])
                    counts[kind] += 1
                    if kind == 3:
                        break
                    if kind != 2:
                        if kind == 1:
                            audio_packets.append((pts,packet[5:]))
                        continue
                    frame = cv2.imdecode(np.frombuffer(packet[5:], np.uint8), cv2.IMREAD_COLOR)
                    assert frame is not None
                    if writer is None:
                        writer = cv2.VideoWriter(str(output / (label + '.mp4')),
                            cv2.VideoWriter_fourcc(*'mp4v'), 25, (frame.shape[1], frame.shape[0]))
                    writer.write(frame)
                    for moment in (400, 1000, 2000, 3000, silence_moment):
                        if pts >= moment and moment not in captures:
                            captures[moment] = frame.copy()
                            cv2.imwrite(str(output / f'{label}-{moment}.jpg'), frame)
        finally:
            if writer is not None:
                writer.release()
        assert counts[1] > 0 and counts[2] > 75
        pcm = bytearray()
        for pts, payload in audio_packets:
            position = pts * 32
            if len(pcm) < position:
                pcm.extend(bytes(position-len(pcm)))
            pcm[position:position+len(payload)] = payload
        with wave.open(str(output / f'{label}-playback.wav'), 'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000); audio.writeframes(pcm)
        subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(output / f'{label}.mp4'),'-i',str(output / f'{label}-playback.wav'),'-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(output / f'{label}-av.mp4')],check=True)
        # Face-centered comparison; all frames use the same audio timestamp.
        frame = captures[2000]
        h, w = frame.shape[:2]
        tile = cv2.resize(frame[int(h*.18):int(h*.67), int(w*.19):int(w*.81)], (300, 300))
        tile = cv2.copyMakeBorder(tile, 35, 0, 0, 0, cv2.BORDER_CONSTANT)
        cv2.putText(tile, label, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, .5, (255,255,255), 1)
        tiles.append(tile)
        frame = captures[silence_moment]
        tile = cv2.resize(frame[int(h*.18):int(h*.67), int(w*.19):int(w*.81)], (300, 300))
        tile = cv2.copyMakeBorder(tile, 35, 0, 0, 0, cv2.BORDER_CONSTANT)
        cv2.putText(tile, label, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, .5, (255,255,255), 1)
        silence_tiles.append(tile)
        row = {'emotion': emotion, 'mode': mode, 'turn_id': turn, 'audio_packets': counts[1], 'video_frames': counts[2]}
        rows.append(row)
        print(json.dumps(row), flush=True)
    cv2.imwrite(str(output / 'comparison.jpg'), np.vstack([np.hstack(tiles[:4]), np.hstack(tiles[4:])]))
    cv2.imwrite(str(output / 'silence-comparison.jpg'), np.vstack([np.hstack(silence_tiles[:4]), np.hstack(silence_tiles[4:])]))
    (output / 'results.json').write_text(json.dumps(rows, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
