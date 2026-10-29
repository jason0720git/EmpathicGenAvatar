"""Measure same-audio gaze renders; geometry proxies, not naturalness scores."""
import json
from pathlib import Path
import wave

import cv2
import mediapipe as mp
import numpy as np

from .main import DITTO_TURN_LEAD_FRAMES


def main():
    root = Path('/data/benchmarks/gaze-speech-v1')
    with wave.open(str(root / 'input.wav')) as audio:
        speech_end = DITTO_TURN_LEAD_FRAMES * 40 + audio.getnframes() / audio.getframerate() * 1000
    detector = mp.tasks.vision.FaceLandmarker.create_from_options(mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path='/models/ditto/ditto_pytorch/aux_models/face_landmarker.task')))
    summaries = []
    for name in ('baseline', 'left', 'right', 'avert-return'):
        video = cv2.VideoCapture(str(root / f'{name}.mp4'))
        rows, tiles = [], []
        index, missing = 0, 0
        while True:
            ok, frame = video.read()
            if not ok:
                break
            if index % 2 == 0:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
                if result.face_landmarks:
                    p = np.array([(v.x, v.y) for v in result.face_landmarks[0]])
                    distance = lambda a, b: float(np.linalg.norm(p[a]-p[b]))
                    iris = []
                    for center, a, b in ((468, 33, 133), (473, 362, 263)):
                        axis = p[b]-p[a]
                        iris.append(float(np.dot(p[center]-p[a], axis) / np.dot(axis, axis)))
                    rows.append({'ms': index*40, 'mouth_gap': distance(13,14)/distance(61,291),
                                 'eye_aperture': [distance(159,145)/distance(33,133), distance(386,374)/distance(362,263)],
                                 'iris_ratio': iris})
                else:
                    missing += 1
            if index in (25, 60, 70, 85, 100, round(speech_end/40)+10):
                h,w = frame.shape[:2]
                tile = cv2.resize(frame[int(h*.18):int(h*.67),int(w*.19):int(w*.81)], (240,240))
                tile = cv2.copyMakeBorder(tile,25,0,0,0,cv2.BORDER_CONSTANT)
                cv2.putText(tile,f'{name} {index*40}ms',(5,18),cv2.FONT_HERSHEY_SIMPLEX,.4,(255,255,255),1)
                tiles.append(tile)
            index += 1
        video.release()
        if not rows:
            raise RuntimeError(f'No measured frames: {name}')
        silent = [r['mouth_gap'] for r in rows if speech_end+200 <= r['ms'] < speech_end+800]
        summary = {'name': name, 'frames': index, 'measured': len(rows), 'missing_face': missing,
                   'silence_mouth_gap_median': float(np.median(silent)),
                   'eye_aperture_min': np.min([r['eye_aperture'] for r in rows],axis=0).tolist(),
                   'limitations': 'Single avatar; stochastic native motion; landmark proxies do not prove gaze accuracy, lip sync or naturalness.'}
        summaries.append(summary)
        (root / f'{name}-geometry.json').write_text(json.dumps(rows))
        cv2.imwrite(str(root / f'{name}-timeline.jpg'), np.hstack(tiles))
        print(json.dumps(summary),flush=True)
    detector.close()
    (root / 'geometry-summary.json').write_text(json.dumps(summaries,indent=2))


if __name__ == '__main__':
    main()
