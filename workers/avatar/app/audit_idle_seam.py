"""Regenerate current idle assets and measure the decoded pixel seam locally."""
import hashlib
import json
import urllib.request
from pathlib import Path
import cv2
import numpy as np
from .main import CacheStore, IDLE_ASSET_VERSION
import sys

def main():
    avatar=sys.argv[1] if len(sys.argv)>1 else 'demo-seoyeon'
    cache=CacheStore(Path('/data/avatar-cache')).get(avatar)
    request=urllib.request.Request('http://127.0.0.1:8010/v1/avatars/idle',
        data=json.dumps({'avatar_id':avatar,'avatar_version':1,'source_path':cache['source_path'],'variants':3}).encode(),
        headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=240) as response:
        print(response.read().decode(),flush=True)
    output=Path(f'/data/benchmarks/idle-seam-v{IDLE_ASSET_VERSION}-{avatar}'); output.mkdir(parents=True,exist_ok=True)
    prefix=hashlib.sha256(avatar.encode()).hexdigest()[:24]
    results=[]
    for variant in range(3):
        variants={}
        for revision in (5,IDLE_ASSET_VERSION):
            folder=Path('/data/idle')/f'{prefix}-r{revision}-v{variant}'
            if not (folder/'0199.jpg').exists(): continue
            paths=sorted(folder.glob('*.jpg'))
            frames=[cv2.imread(str(path)) for path in paths]
            h,w=frames[0].shape[:2]
            face=lambda f: f[int(h*.15):int(h*.65),int(w*.2):int(w*.8)].astype(float)
            a,b=face(frames[-1]),face(frames[0])
            variants[str(revision)]={'frames':len(frames),'duration_s':len(frames)/25,'seam_mae':float(np.abs(a-b).mean()),'previous_step_mae':float(np.abs(face(frames[-2])-a).mean()),'next_step_mae':float(np.abs(face(frames[1])-b).mean())}
            clip=cv2.VideoWriter(str(output/f'idle-r{revision}-v{variant}-seam.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),25,(w,h))
            for f in frames[-25:]+frames[:25]: clip.write(f)
            clip.release()
            cv2.imwrite(str(output/f'idle-r{revision}-v{variant}-ends.jpg'),np.hstack([frames[-1],frames[0]]))
        results.append({'variant':variant,'revisions':variants})
    (output/'metrics.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results),flush=True)

if __name__=='__main__': main()
