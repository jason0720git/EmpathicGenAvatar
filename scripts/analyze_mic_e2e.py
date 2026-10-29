"""Summarize actual displayed-frame boundaries; these are proxies, not naturalness scores."""
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw

root = Path('artifacts/mic-e2e')
summary = []
for name in ['normal', 'short', 'interrupt', 'auto']:
    directory = root / name
    report = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
    frames = report['frames']
    images = [cv2.imread(str(directory / f'{i:05}.jpg')) for i in range(len(frames))]
    diffs = [float(np.abs(a[45:210,60:200].astype(float)-b[45:210,60:200]).mean()) for a,b in zip(images,images[1:])]
    switches = [i for i in range(1,len(frames)) if frames[i]['live'] != frames[i-1]['live'] or frames[i]['cue'] != frames[i-1]['cue']]
    summary.append(dict(name=name, frames=len(frames), diff_median=float(np.median(diffs)), diff_p95=float(np.percentile(diffs,95)), diff_max=max(diffs),
        switches=[dict(index=i,t=frames[i]['t'],live=frames[i]['live'],diff=diffs[i-1],cue=frames[i]['cue']) for i in switches],
        events=[e for e in report['telemetry'] if e.get('event') in ['playback_ended','visual_transition']]))
    if name == 'interrupt':
        center = min(range(len(frames)), key=lambda i: abs(frames[i]['t']-report['interruptAt']))
    else:
        center = next(i for i in range(1,len(frames)) if frames[i-1]['live'] and not frames[i]['live'])
    indices = [max(0,min(len(frames)-1,center+j)) for j in [-2,0,1,2,3,4,5,7]]
    sheet = Image.new('RGB',(256*8,348),'white')
    draw = ImageDraw.Draw(sheet)
    for col,i in enumerate(indices):
        sheet.paste(Image.open(directory/f'{i:05}.jpg'),(col*256,28))
        draw.text((col*256+4,4),f'{name} {frames[i]["t"]-frames[center]["t"]:.0f}ms',fill='black')
    sheet.save(directory/'handoff.jpg')
    # Silent replay of sampled displayed frames, not the original A/V stream.
    video=cv2.VideoWriter(str(directory/'display-replay.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),12.5,(256,320))
    for frame in images: video.write(frame)
    video.release()
(root/'analysis.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
