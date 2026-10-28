import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from source_camera import source_camera


class SourceCameraTest(unittest.TestCase):
    def test_view_preserves_projection_after_root_rotation_and_export_translation(self):
        # Catch camera inversion, handedness and forgotten FLAME joint pivots.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            rv = np.array([.15, -.07, .03]); R = Rotation.from_rotvec(rv).as_matrix()
            t = np.array([.02, .01, -.03]); pivot = np.array([0., -.14, -.08])
            offset = np.array([0., 1.67, .04]); C = np.array([.01, .02, .83])
            c2w = np.eye(4); c2w[:3, 3] = C
            np.savez(path/'pose.npz', rotation=rv[None], translation=t[None])
            (path/'transforms.json').write_text(json.dumps({'frames':[{
                'transform_matrix':c2w.tolist(), 'flame_param_path':'pose.npz',
                'h':1024, 'w':1024, 'fl_y':2380.}]}))
            result = source_camera(path, offset, pivot)
        points = np.array([[.03,.04,.06],[-.02,-.02,.04],[0.,-.08,.08]])
        original_camera = ((R @ (points-pivot).T).T+pivot+t)-C
        # Canonical camera's axes are R.T times the original camera axes.
        restored_camera = (R @ (points+offset-np.array(result['position'])).T).T
        np.testing.assert_allclose(original_camera, restored_camera, atol=1e-12)
        np.testing.assert_allclose(result['up'], R.T @ [0,1,0], atol=1e-12)
        self.assertAlmostEqual(result['fov'], np.degrees(2*np.arctan(1024/4760)))


if __name__ == '__main__':
    unittest.main()
