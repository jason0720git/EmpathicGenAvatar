"""Produce a reproducible A2F -> FLAME -> actual 306 rendering with source WAV."""
import asyncio,json,sys,wave,subprocess
from pathlib import Path
import websockets
import imageio_ffmpeg
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'apps/api'))
from app.gaussian_a2f import A2FClient

async def main():
    out=ROOT/'artifacts/oral-v6/wav-frames';out.mkdir(parents=True,exist_ok=True)
    wav=out.parent/'reference-24000.wav'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-i',str(ROOT/'data/gaussian/test-audio/reference.wav'),'-ar','24000','-ac','1','-c:a','pcm_s16le',str(wav)],check=True,capture_output=True)
    with wave.open(str(wav)) as source:
        assert (source.getframerate(),source.getnchannels(),source.getsampwidth())==(24000,1,2)
        pcm=source.readframes(source.getnframes())
    async def chunks():
        for start in range(0,len(pcm),12000):yield pcm[start:start+12000]
    frames=[]
    async with websockets.connect('ws://127.0.0.1:8041/gaussian-render/ws',max_size=4*1024*1024) as ws:
        async for motion in A2FClient('127.0.0.1:52000').stream(chunks()):
            i=len(frames)
            await ws.send(json.dumps({'sequence':i,'turn_id':'offline-wav-validation','pts_ms':motion.time_seconds*1000,'weights':motion.weights}))
            stats=json.loads(await ws.recv());raw=await ws.recv()
            (out/f'{i:04}.jpg').write_bytes(raw)
            frames.append({'pts':motion.time_seconds,'weights':motion.weights,**stats})
    (out.parent/'official-wav-frames.json').write_text(json.dumps(frames,indent=2))
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-framerate','30','-i',str(out/'%04d.jpg'),'-i',str(wav),'-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(out.parent/'official-a2f-wav.mp4')],check=True,capture_output=True)
    print(json.dumps({'frames':len(frames),'output':str(out.parent/'official-a2f-wav.mp4'),'max_jaw':max(f['weights'].get('jawOpen',0) for f in frames)}))
asyncio.run(main())
