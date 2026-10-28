"""Preserve the tracked source view instead of inventing a portrait lens/angle."""
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation


def source_camera(tracked: Path, template_translation, root_joint):
    frame = json.loads((tracked/'transforms.json').read_text())['frames'][0]
    params = np.load(tracked/frame['flame_param_path'])
    # Express the tracked camera in the canonical (unrotated) head frame.
    rotation = Rotation.from_rotvec(params['rotation'].reshape(3)).as_matrix()
    c2w = np.asarray(frame['transform_matrix'], dtype=float)
    offset = np.asarray(template_translation, dtype=float)
    pivot = np.asarray(root_joint, dtype=float)
    origin = rotation.T @ (c2w[:3, 3]-pivot-params['translation'].reshape(3)) + pivot + offset
    forward = rotation.T @ (-c2w[:3, 2])
    up = rotation.T @ c2w[:3, 1]
    return {'version': 'tracked-source-view-v1', 'position': origin.tolist(), 'root_joint': pivot.tolist(),
            'target': (origin+forward*.8).tolist(), 'up': up.tolist(),
            'fov': float(np.degrees(2*np.arctan(frame['h']/(2*frame['fl_y'])))),
            'aspect': float(frame['w']/frame['h']),
            'scope': 'global_pose_and_intrinsics; neutral_expression; neck_pose_not_baked'}
