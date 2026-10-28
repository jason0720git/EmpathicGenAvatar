"""Opt-in live local lab test; uses configured Realtime service and logs its cost-bearing turn."""
import argparse
import asyncio
import base64
import json
import sys
import time
import wave
from pathlib import Path

import httpx
from websockets.asyncio.client import connect


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--avatar')
    parser.add_argument('--audio', type=Path)
    parser.add_argument('--text', default='오늘 조금 지쳤어. 짧게 한마디 해줘.')
    parser.add_argument('--emotion', choices=['neutral','happy','sad','angry','fear','surprise'])
    args = parser.parse_args()
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8030', timeout=60, trust_env=False) as client:
        avatar = args.avatar
        if not avatar:
            candidates = (await client.get('/gaussian-api/avatars')).json()
            avatar = next((a['id'] for a in candidates if a['status'] == 'ready'), None)
        if not avatar:
            source = Path('vendor/LAM_WebRender/asset/arkit/p2-1.zip')
            response = await client.post('/gaussian-api/avatars/import', files={'file': ('sample.zip', source.read_bytes(), 'application/zip')}, data={'name':'LAM 공식 예제 · 연동 검증용'})
            response.raise_for_status()
            avatar = response.json()['id']
        response = await client.post('/gaussian-api/sessions', json={'avatar_id':avatar,'voice':'marin'})
        response.raise_for_status()
        session = response.json()
        stats = {'session_id':session['id'],'avatar_id':avatar,'audio_chunks':0,'audio_bytes':0,'motion_frames':0,'jaw_max':0,'first_audio_ms':None,'first_motion_ms':None}
        started = time.monotonic()
        async with connect('ws://127.0.0.1:8030'+session['ws_url'],max_size=4*1024*1024) as socket:
            await socket.recv()
            if args.emotion:
                await socket.send(json.dumps({'type':'control','auto':False,'emotion':args.emotion,'intensity':.8}))
            if args.audio:
                with wave.open(str(args.audio),'rb') as source:
                    if (source.getframerate(),source.getnchannels(),source.getsampwidth()) != (24000,1,2):
                        raise ValueError('Smoke WAV must be 24kHz mono PCM16')
                    data = source.readframes(source.getnframes())
                await socket.send(json.dumps({'type':'input.start'}))
                for offset in range(0,len(data),24000):
                    await socket.send(json.dumps({'type':'input.audio','pcm_base64':base64.b64encode(data[offset:offset+24000]).decode()}))
                await socket.send(json.dumps({'type':'input.commit'}))
            else:
                await socket.send(json.dumps({'type':'input.text','text':args.text}))
            while True:
                event = json.loads(await asyncio.wait_for(socket.recv(),timeout=100))
                kind = event['type']
                if kind == 'audio.chunk':
                    stats['audio_chunks']+=1
                    stats['audio_bytes']+=len(base64.b64decode(event['pcm_base64']))
                    if stats['first_audio_ms'] is None: stats['first_audio_ms']=round((time.monotonic()-started)*1000)
                elif kind=='animation.frame' and event.get('turn_id')!='idle':
                    stats['motion_frames']+=1
                    stats['jaw_max']=max(stats['jaw_max'],event['weights'].get('jawOpen',0))
                    for channel in ('mouthSmileLeft','mouthFrownLeft','browInnerUp','browDownLeft','eyeWideLeft'):
                        stats[channel+'_max']=max(stats.get(channel+'_max',0),event['weights'].get(channel,0))
                    if args.emotion and event.get('behavior',{}).get('emotion') != args.emotion:
                        raise AssertionError('Manual expression was overwritten by automatic behavior')
                    if stats['first_motion_ms'] is None: stats['first_motion_ms']=round((time.monotonic()-started)*1000)
                elif kind=='transcript.final':
                    stats[event['role']+'_text']=event['text']
                elif kind=='behavior':
                    stats['behavior']=event.get('plan')
                elif kind=='error':
                    raise RuntimeError(event)
                elif kind=='turn.done':
                    stats['metrics']=event.get('metrics')
                    break
            if not stats['audio_bytes'] or not stats['motion_frames'] or stats['jaw_max'] <=0:
                raise AssertionError(stats)
            if args.emotion=='sad' and (stats['browInnerUp_max']<.3 or stats['mouthSmileLeft_max']>.04):
                raise AssertionError('Sad expression did not persist over speech')
            await socket.send(json.dumps({'type':'telemetry','event':'smoke.complete','stats':stats}))
        feedback = await client.post(f"/gaussian-api/sessions/{session['id']}/feedback", json={'rating':3,'comment':'Automated integration smoke; not a human quality rating'})
        feedback.raise_for_status()
        archive = await client.get(f"/gaussian-api/sessions/{session['id']}/logs.zip")
        archive.raise_for_status()
        stats['archive_bytes']=len(archive.content)
        output = Path('data/gaussian/smoke-'+session['id']+'.json')
        output.write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(stats,ensure_ascii=False,indent=2))


if __name__=='__main__':
    asyncio.run(main())
