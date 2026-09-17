"""Offline geometry regression report, not an emotion/lip-sync classifier."""
import json
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np


def main():
    root = Path('/data/benchmarks/native8-v3')
    detector = mp.tasks.vision.FaceLandmarker.create_from_options(
        mp.tasks.vision.FaceLandmarkerOptions(base_options=mp.tasks.BaseOptions(
            model_asset_path='/models/ditto/ditto_pytorch/aux_models/face_landmarker.task')))
    summaries = []
    for emotion in ('neutral', 'fear', 'sad', 'surprise', 'contempt'):
        capture = cv2.VideoCapture(str(root / f'{emotion}.mp4'))
        frames = []
        values = []
        index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if index % 2 == 0:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
                if not result.face_landmarks:
                    raise RuntimeError(f'Missing face: {emotion} frame {index}')
                p = np.array([(v.x, v.y) for v in result.face_landmarks[0]])
                def distance(a, b):
                    return float(np.linalg.norm(p[a]-p[b]))
                values.append({'ms': index*40, 'mouth_gap': distance(13,14)/distance(61,291),
                               'eye_left': distance(386,374)/distance(362,263),
                               'eye_right': distance(159,145)/distance(33,133)})
                frames.append(frame)
            index += 1
        capture.release()
        assert len(values) > 50
        mouth = np.array([v['mouth_gap'] for v in values])
        eyes = np.array([[v['eye_left'], v['eye_right']] for v in values])
        blink = int(np.argmin(eyes.mean(axis=1)))
        moments = [5, 25, blink, len(frames)-8]
        tiles = []
        for i in moments:
            frame = frames[i]
            h,w = frame.shape[:2]
            tile = cv2.resize(frame[int(h*.18):int(h*.67),int(w*.19):int(w*.81)], (260,260))
            tile = cv2.copyMakeBorder(tile, 30,0,0,0,cv2.BORDER_CONSTANT)
            cv2.putText(tile, f'{emotion} {values[i]["ms"]}ms', (5,22), cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1)
            tiles.append(tile)
        cv2.imwrite(str(root / f'{emotion}-timeline.jpg'), np.hstack(tiles))
        summary = {'emotion':emotion, 'frames_measured':len(values),
                   'speech_mouth_gap_p90':float(np.percentile(mouth[5:50],90)),
                   'silence_mouth_gap_median':float(np.median(mouth[-10:-3])),
                   'eye_aperture_median':np.median(eyes,axis=0).tolist(),
                   'minimum_eye_aperture':eyes[blink].tolist(), 'minimum_eye_aperture_ms':values[blink]['ms']}
        summaries.append(summary)
        (root / f'{emotion}-geometry.json').write_text(json.dumps(values,indent=2))
        print(json.dumps(summary),flush=True)
    (root / 'geometry-summary.json').write_text(json.dumps(summaries,indent=2))
    detector.close()


if __name__ == '__main__':
    main()
