"""Offline, source-specific finite-difference audit of Ditto's implicit controls.

No API endpoints or LLM calls. Produces synthetic portraits and MediaPipe
proxies (NOT ground-truth FACS/emotion scores) for parameter interaction QA.
Run inside a GPU worker: python3 -m app.calibrate_affect
"""
import copy
import sys
import json
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from .main import CacheStore, DittoLiveRuntime, WorkerConfig, DITTO_AFFECT_DELTA_EXP


def main():
    output = Path('/data/benchmarks/affect-calibration-v3')
    output.mkdir(parents=True, exist_ok=True)
    runtime = DittoLiveRuntime(WorkerConfig.from_env())
    source_path = CacheStore(Path('/data/avatar-cache')).get('demo-seoyeon')['source_path']
    runtime._register_avatar('demo-seoyeon', Path(source_path))
    sdk = runtime._load_sdk()
    source = runtime.avatar_sources['demo-seoyeon']
    info = source['x_s_info_lst'][0]
    from core.atomic_components.motion_stitch import transform_keypoint
    x_s = transform_keypoint(info)
    options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path='/models/ditto/ditto_pytorch/aux_models/face_landmarker.task'),
        output_face_blendshapes=True)
    detector = mp.tasks.vision.FaceLandmarker.create_from_options(options)

    def render(delta, native_blink=False):
        driving = copy.deepcopy(info)
        driving['exp'] = info['exp'] + delta.reshape(1, 63)
        if native_blink:
            _, x_d = sdk.motion_stitch(info, copy.deepcopy(info), delta_exp=delta)
        else:
            x_d = sdk.motion_stitch.stitch_net(x_s, transform_keypoint(driving))
        rgb = sdk.decode_f3d(sdk.warp_f3d(source['f_s_lst'][0], x_s, x_d)).astype(np.uint8)
        result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
        if not result.face_blendshapes:
            raise RuntimeError('Face detector failed on calibration frame')
        scores = {c.category_name: c.score for c in result.face_blendshapes[0]}
        points = np.array([(p.x, p.y, p.z) for p in result.face_landmarks[0]])
        width = np.linalg.norm(points[61, :2] - points[291, :2])
        scores['lip_gap_ratio'] = float(np.linalg.norm(points[13, :2] - points[14, :2]) / width)
        return rgb, scores

    rows = []
    tiles = []
    zero = np.zeros((21, 3), np.float32)
    rgb, scores = render(zero)
    cv2.imwrite(str(output / 'baseline.jpg'), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    rows.append({'name': 'baseline', 'scores': scores})
    if '--blink' in sys.argv:
        blink_rows = []
        for name in ('fear', 'surprise'):
            sdk.motion_stitch.setup(N_d=100, relative_d=False, drive_eye=True,
                delta_eye_arr=sdk.default_kwargs['delta_eye_arr'], delta_eye_open_n=20,
                x_s_info=info)
            frames = []
            for frame in range(38):
                rgb, scores = render(DITTO_AFFECT_DELTA_EXP[name], native_blink=True)
                blink_rows.append({'emotion':name, 'frame':frame, 'scores':scores})
                frames.append(rgb)
            # Include all 15 native blink stages, not just a favorable frame.
            tiles = []
            for frame in range(20, 35):
                tile = cv2.cvtColor(cv2.resize(frames[frame][120:435,100:410],(155,158)),cv2.COLOR_RGB2BGR)
                tile = cv2.copyMakeBorder(tile,22,0,0,0,cv2.BORDER_CONSTANT)
                cv2.putText(tile,str(frame),(5,16),cv2.FONT_HERSHEY_SIMPLEX,.45,(255,255,255),1)
                tiles.append(tile)
            cv2.imwrite(str(output / f'{name}-blink.jpg'),np.vstack([np.hstack(tiles[i:i+5]) for i in range(0,15,5)]))
        (output / 'blink-scores.json').write_text(json.dumps(blink_rows,indent=2))
        detector.close()
        return
    if '--presets-only' in sys.argv:
        for name in ('neutral', 'fear', 'sad', 'surprise', 'contempt'):
            rgb, scores = render(DITTO_AFFECT_DELTA_EXP[name])
            rows.append({'name': name, 'scores': scores})
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            cv2.imwrite(str(output / (name + '.jpg')), bgr)
            # Crop rather than adding pose, so expression differences stand alone.
            tile = cv2.resize(bgr[120:435, 100:410], (310, 315))
            tile = cv2.copyMakeBorder(tile, 30, 0, 0, 0, cv2.BORDER_CONSTANT)
            cv2.putText(tile, name, (5, 22), cv2.FONT_HERSHEY_SIMPLEX, .6, (255,255,255), 1)
            tiles.append(tile)
        cv2.imwrite(str(output / 'candidate-presets.jpg'), np.hstack(tiles))
        (output / 'candidate-scores.json').write_text(json.dumps(rows, indent=2))
        detector.close()
        return
    # Deliberately exclude pupil controls 11/15 and jaw/center-lip 6/12/17/19.
    for point in (1, 2, 3, 7, 13, 16, 18, 14, 20):
        for axis in range(3):
            for sign in (-1, 1):
                d = zero.copy()
                d[point, axis] = sign * .008
                name = f'p{point}-{axis}-{sign}'
                rgb, scores = render(d)
                rows.append({'name': name, 'point': point, 'axis': axis, 'amount': sign * .008, 'scores': scores})
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                cv2.imwrite(str(output / (name + '.jpg')), bgr)
                tile = cv2.resize(bgr, (200, 200))
                tile = cv2.copyMakeBorder(tile, 25, 0, 0, 0, cv2.BORDER_CONSTANT)
                cv2.putText(tile, name, (4, 18), cv2.FONT_HERSHEY_SIMPLEX, .45, (255,255,255), 1)
                tiles.append(tile)
            print(f'audited point={point} axis={axis}', flush=True)
    for page in range(3):
        batch = tiles[page*18:(page+1)*18]
        sheet = np.vstack([np.hstack(batch[i:i+6]) for i in range(0, 18, 6)])
        cv2.imwrite(str(output / f'sweep-{page}.jpg'), sheet)
    (output / 'sensitivity.json').write_text(json.dumps(rows, indent=2))
    detector.close()


if __name__ == '__main__':
    main()
