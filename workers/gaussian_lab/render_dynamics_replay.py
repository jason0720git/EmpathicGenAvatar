"""Render exact frontend-controller replay with official 306 checkpoint (no LLM)."""
import asyncio, json, subprocess
from pathlib import Path
import websockets
import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/dynamics-v8'

async def main():
    frames = json.loads((OUT/'replay/happy.json').read_text(encoding='utf-8'))
    dest = OUT/'official-replay'
    dest.mkdir(exist_ok=True)
    async with websockets.connect('ws://127.0.0.1:8041/gaussian-render/ws', max_size=4*1024*1024) as ws:
        for i, frame in enumerate(frames):
            await ws.send(json.dumps(frame))
            stats = json.loads(await ws.recv())
            raw = await ws.recv()
            if not isinstance(raw, bytes):
                raise RuntimeError(stats)
            (dest/f'{i:04}.jpg').write_bytes(raw)
    wav = ROOT/'data/gaussian/test-audio/ash_gpt-4o-mini-tts_1x_2026-09-29T04_28_07-868Z.wav'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-framerate','30','-i',str(dest/'%04d.jpg'),'-i',str(wav),'-af','adelay=2000:all=1,apad','-t','8.6','-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-c:a','aac',str(OUT/'official-causal-dynamics.mp4')], check=True, capture_output=True)
    print(f'Rendered {len(frames)} frames: {OUT / "official-causal-dynamics.mp4"}')

asyncio.run(main())
