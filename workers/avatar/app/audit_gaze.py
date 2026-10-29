"""Fixed-source GPU audit of opt-in pupil control; no speech or remote calls.

Run in the existing Ditto GPU image: python -m app.audit_gaze --output /audit
Generated media belongs in ignored artifacts, never in Git.
"""
import argparse
import copy
import json
from pathlib import Path

import cv2
import numpy as np

from .main import (CacheStore, DittoLiveRuntime, GazeIntent, MotionPlan,
                   WorkerConfig, build_ditto_ctrl_info)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--avatar', default='demo-seoyeon')
    parser.add_argument('--output', type=Path, default=Path('/data/benchmarks/gaze-v1'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    config = WorkerConfig.from_env()
    source_path = CacheStore(config.data_root / 'avatar-cache').get(args.avatar)['source_path']
    runtime = DittoLiveRuntime(config)
    runtime._register_avatar(args.avatar, Path(source_path))
    sdk = runtime._load_sdk()
    source = runtime.avatar_sources[args.avatar]
    info = source['x_s_info_lst'][0]

    def setup():
        sdk.motion_stitch.setup(N_d=100, relative_d=False, drive_eye=True,
                               delta_eye_arr=sdk.default_kwargs['delta_eye_arr'],
                               delta_eye_open_n=20, x_s_info=info)

    def render(control):
        x_s, x_d = sdk.motion_stitch(info, copy.deepcopy(info), **control)
        rgb = sdk.decode_f3d(sdk.warp_f3d(source['f_s_lst'][0], x_s, x_d)).astype(np.uint8)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    tiles, records = [], []
    for name, x, y in [('center', 0, 0), ('x-negative', -1, 0), ('x-positive', 1, 0), ('down', 0, -1), ('up', 0, 1)]:
        setup()
        plan = MotionPlan(intensity=0, gaze=GazeIntent(mode='pupil', x=x, y=y))
        control = build_ditto_ctrl_info(plan, 60)[20]
        bgr = render(control)
        cv2.imwrite(str(args.output / f'{name}.jpg'), bgr)
        tile = cv2.resize(bgr, (256, 256))
        tile = cv2.copyMakeBorder(tile, 25, 0, 0, 0, cv2.BORDER_CONSTANT)
        cv2.putText(tile, name, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 255), 1)
        tiles.append(tile)
        records.append({'name': name, 'head_offsets': [control[k] for k in ('delta_yaw', 'delta_pitch', 'delta_roll')]})
    cv2.imwrite(str(args.output / 'directions.jpg'), np.hstack(tiles))
    setup()
    control = build_ditto_ctrl_info(MotionPlan(expression='surprise', intensity=.5,
                                             gaze=GazeIntent(mode='pupil', x=.8, y=.5)), 60)[20]
    blink_tiles = []
    for frame in range(38):
        bgr = render(control)
        if 20 <= frame < 35:
            blink_tiles.append(cv2.resize(bgr, (160, 160)))
    cv2.imwrite(str(args.output / 'blink.jpg'), np.vstack([np.hstack(blink_tiles[i:i+5]) for i in range(0, 15, 5)]))
    (args.output / 'audit.json').write_text(json.dumps({'avatar': args.avatar, 'static_controls': records,
        'limits': 'Single source, fixed pose, no audio; not an eye-contact accuracy or speech-quality evaluation.'}, indent=2))
    print(f'Gaze audit saved to {args.output}', flush=True)


if __name__ == '__main__':
    main()
