"""Measure displayed live-control frames; geometry proxies do not score naturalness.

Run in a Python environment with cv2, numpy and mediapipe. Synthetic artifacts only.
"""
import argparse
import json
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='artifacts/live-control-e2e')
    parser.add_argument('--model', default='models/ditto/ditto_pytorch/aux_models/face_landmarker.task')
    args = parser.parse_args()
    root = Path(args.root)
    report = json.loads((root / 'report.json').read_text(encoding='utf-8'))
    detector = mp.tasks.vision.FaceLandmarker.create_from_options(mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=args.model),
        output_facial_transformation_matrixes=True))
    rows, missing, diffs = [], [], []
    previous = None
    for index, meta in enumerate(report['frames']):
        frame = cv2.imread(str(root / f'{index:05}.jpg'))
        if frame is None:
            raise RuntimeError(f'Missing recorded frame {index}')
        thumb = cv2.resize(frame,(256,320))
        if previous is not None:
            # Pixel levels 0..255, fixed face crop; affected by speech/blinks too.
            diffs.append(dict(index=index, at=meta['at'], displayedPts=meta['displayedPts'],
                              face_mae=float(np.abs(thumb[40:220,50:205].astype(float)-previous[40:220,50:205]).mean())))
        previous = thumb
        if index % 2:
            continue
        result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        if not result.face_landmarks:
            missing.append(index)
            continue
        p = np.array([(v.x, v.y, v.z) for v in result.face_landmarks[0]])
        distance = lambda a, b: float(np.linalg.norm(p[a, :2]-p[b, :2]))
        iris = []
        for center, a, b in ((468, 33, 133), (473, 362, 263)):
            axis = p[b, :2]-p[a, :2]
            iris.append(float(np.dot(p[center, :2]-p[a, :2], axis) / np.dot(axis, axis)))
        eye_width = distance(33, 263)
        eye_center = (p[33, :2]+p[263, :2]) / 2
        nose_offset = ((p[1, :2]-eye_center) / eye_width).tolist()
        brow = [distance(105, 159)/distance(33,133), distance(334,386)/distance(362,263)]
        eye_open = [distance(159,145)/distance(33,133), distance(386,374)/distance(362,263)]
        mouth_center = (p[13,:2]+p[14,:2])/2
        corner_raise = float((mouth_center[1]-(p[61,1]+p[291,1])/2)/distance(61,291))
        row = dict(index=index, at=meta['at'], displayedPts=meta['displayedPts'], live=meta['live'],
                   iris_ratio=iris, normalized_nose_offset=nose_offset, brow_eye_distance=brow,
                   eye_aperture=eye_open, mouth_gap=distance(13,14)/distance(61,291), mouth_corner_raise=corner_raise,
                   cheek_width=distance(234,454)/eye_width)
        if result.facial_transformation_matrixes:
            rotation = np.asarray(result.facial_transformation_matrixes[0])[:3,:3]
            row['head_euler_proxy_deg'] = np.rad2deg([
                np.arctan2(rotation[2,1],rotation[2,2]),
                np.arcsin(np.clip(-rotation[2,0],-1,1)),
                np.arctan2(rotation[1,0],rotation[0,0])]).tolist()
        rows.append(row)
    detector.close()
    if not rows:
        raise RuntimeError('No face measurements')

    commands = [c for c in report['commands'] if c.get('applied')]
    groups, tiles = [], []
    first_pts = commands[0]['applied']['pts_ms'] if commands else 0
    regions = [('baseline', 1000, first_pts)] + [
        (c['label'], c['applied']['pts_ms']+600,
         commands[i+1]['applied']['pts_ms'] if i+1<len(commands) else max((r['displayedPts'] or 0) for r in rows)-(1000 if report.get('passed') else 0))
        for i,c in enumerate(commands)]
    metrics = ('iris_ratio','normalized_nose_offset','brow_eye_distance','eye_aperture','mouth_gap','mouth_corner_raise','cheek_width','head_euler_proxy_deg')
    for label, begin, end in regions:
        selected = [r for r in rows if r['live'] and r['displayedPts'] is not None and begin <= r['displayedPts'] < end]
        group = {'label':label,'pts_window':[begin,end],'measured_frames':len(selected)}
        for metric in metrics:
            values = [r[metric] for r in selected if metric in r]
            if values:
                group[metric] = {'median':np.median(values,axis=0).tolist(),'p10':np.percentile(values,10,axis=0).tolist(),'p90':np.percentile(values,90,axis=0).tolist()}
        groups.append(group)
        if selected:
            for row in (selected[0], selected[len(selected)//2], selected[-1]):
                frame=cv2.imread(str(root/f'{row["index"]:05}.jpg'))
                frame=cv2.resize(frame,(256,320))
                tile=cv2.resize(frame[40:220,45:210],(250,270))
                tile=cv2.copyMakeBorder(tile,35,0,0,0,cv2.BORDER_CONSTANT)
                cv2.putText(tile,f'{label} {row["displayedPts"]}ms',(5,22),cv2.FONT_HERSHEY_SIMPLEX,.43,(255,255,255),1)
                tiles.append(tile)
    if tiles:
        width=3
        while len(tiles)%width:tiles.append(np.zeros_like(tiles[0]))
        cv2.imwrite(str(root/'contact-sheet.jpg'),np.vstack([np.hstack(tiles[i:i+width]) for i in range(0,len(tiles),width)]))
    boundaries=[]
    for c in commands:
        pts=c['applied']['pts_ms']
        local=[d for d in diffs if d['displayedPts'] is not None and pts-80<=d['displayedPts']<=pts+1000]
        boundaries.append(dict(label=c['label'], pts=pts, peak_face_mae=max((d['face_mae'] for d in local),default=None)))
    summary=dict(recorded_frames=len(report['frames']),measured_frames=len(rows),missing_face_indices=missing,
                 groups=groups,boundaries=boundaries,face_mae_median=float(np.median([d['face_mae'] for d in diffs])),
                 face_mae_p95=float(np.percentile([d['face_mae'] for d in diffs],95)),
                 first_effect_ms=[dict(label=c['label'],ms=c.get('firstAffectedFrameDisplayedMs')) for c in commands],
                 limitations='Single synthetic avatar and stochastic native motion. Ratios/Euler estimates are image proxies, not calibrated eye/head angles or a naturalness score. Semantic labels do not establish direction in mirrored camera space. Mouth articulation contaminates expression measurements; isolated-channel runs support stronger attribution.')
    (root/'geometry.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    (root/'analysis.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    # Preserve approximate wall-time pacing rather than treating every sample as exactly40ms.
    video=cv2.VideoWriter(str(root/'display-replay.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),25,(256,320))
    cursor=0; samples=report['frames']
    for timestamp in np.arange(samples[0]['at'], samples[-1]['at']+1,40):
        while cursor+1<len(samples) and samples[cursor+1]['at']<=timestamp:cursor+=1
        video.write(cv2.resize(cv2.imread(str(root/f'{cursor:05}.jpg')),(256,320)))
    video.release()
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
