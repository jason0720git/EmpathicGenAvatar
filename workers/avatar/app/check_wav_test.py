"""Exercise all eight expressions using only the configured WAV; no LLM calls."""
import asyncio
import hashlib
import json
import struct
import urllib.request
import uuid
from pathlib import Path
import websockets


def request(path, body=None, method=None):
    req=urllib.request.Request('http://web'+path, data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json'}, method=method)
    with urllib.request.urlopen(req,timeout=180) as response:
        return json.loads(response.read()) if response.status!=204 else None


async def main():
    session=await asyncio.to_thread(request,'/api/live/sessions',{'avatar_id':'demo-doyun','renderer_method':'ditto_realtime_trt10','mode':'wav_test'})
    assert session['mode']=='wav_test'
    results=[]
    try:
        for emotion in ('neutral','happy','angry','disgust','fear','sad','surprise','contempt'):
            turn='wav-audit-'+uuid.uuid4().hex[:12]
            response=await asyncio.to_thread(request,f"/api/live/sessions/{session['id']}/turns",{
                'text':'Fixed WAV evaluation','client_turn_id':turn,'affect_override':{'emotion':emotion,'intensity':1}})
            assert response['renderer']['applied_motion']['expression']==emotion
            pcm=bytearray(); frames=0
            async with websockets.connect('ws://web'+response['renderer']['stream_url'],max_size=4000000) as ws:
                while True:
                    packet=await asyncio.wait_for(ws.recv(),timeout=60)
                    kind,pts=struct.unpack('>BI',packet[:5])
                    if kind==1: pcm.extend(packet[5:])
                    elif kind==2: frames+=1
                    elif kind==3: break
            assert pcm and frames>100
            results.append({'emotion':emotion,'turn_id':turn,'video_frames':frames,'pcm_bytes':len(pcm),'pcm_sha256':hashlib.sha256(pcm).hexdigest()})
            print(json.dumps(results[-1]),flush=True)
        assert len({row['pcm_sha256'] for row in results})==1, 'Audio changed between expressions'
        output=Path('/data/benchmarks/wav-test'); output.mkdir(parents=True,exist_ok=True)
        (output/'results.json').write_text(json.dumps(results,indent=2))
    finally:
        await asyncio.to_thread(request,f"/api/live/sessions/{session['id']}",method='DELETE')

if __name__=='__main__': asyncio.run(main())
