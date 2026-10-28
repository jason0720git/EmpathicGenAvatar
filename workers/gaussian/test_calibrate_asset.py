"""Regression checks for native rig repair against the real LAM template."""
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
from plyfile import PlyData
from calibrate_asset import calibrate, read_vectors
from export_asset import decode_glb
from test_export_asset import SAMPLE


def unpack(path):
    with zipfile.ZipFile(path) as z:
        skin = next(n for n in z.namelist() if n.endswith('/skin.glb'))
        root = skin.rsplit('/', 1)[0]
        doc, binary = decode_glb(z.read(skin))
        ply = PlyData.read(io.BytesIO(z.read(root+'/offset.ply')))['vertex'].data.copy()
        animation = z.read(root+'/animation.glb')
    mesh = doc['meshes'][0]; p = mesh['primitives'][0]
    positions = read_vectors(doc, binary, p['attributes']['POSITION'])
    morphs = {n: read_vectors(doc, binary, t['POSITION'])
              for n, t in zip(mesh['extras']['targetNames'], p['targets'])}
    return doc, positions, morphs, ply, animation


@unittest.skipUnless(SAMPLE.exists(), 'Bootstrap LAM template first')
class CalibrationTest(unittest.TestCase):
    def test_eye_repair_preserves_identity_color_skeleton_and_other_expressions(self):
        original_bytes = SAMPLE.read_bytes()
        before = unpack(SAMPLE)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'fixed.zip'
            calibrate(SAMPLE, output)
            after = unpack(output)
            np.testing.assert_array_equal(before[1], after[1])
            for field in before[3].dtype.names:
                np.testing.assert_allclose(before[3][field], after[3][field], atol=1e-7)
            self.assertEqual(before[0]['skins'], after[0]['skins'])
            self.assertEqual(before[4], after[4])
            for name, value in before[2].items():
                if not name.startswith('eyeBlink'):
                    np.testing.assert_allclose(value, after[2][name], atol=2e-7)
            self.assertTrue(any(np.max(abs(before[2][n]-after[2][n])) > 1e-5
                                for n in ('eyeBlinkLeft', 'eyeBlinkRight')))
            with self.assertRaisesRegex(ValueError, 'Already calibrated'):
                calibrate(output, Path(folder)/'twice.zip')
        self.assertEqual(SAMPLE.read_bytes(), original_bytes)

    def test_proportion_profile_keeps_finite_geometry_covariance_and_morphs(self):
        before = unpack(SAMPLE)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'fixed.zip'
            calibrate(SAMPLE, output, lower_face=True)
            after = unpack(output)
        self.assertEqual(set(before[2]), set(after[2]))
        for points in [after[1], *after[2].values()]:
            self.assertTrue(np.isfinite(points).all())
        displacement = after[1]-before[1]
        self.assertLess(np.max(np.linalg.norm(displacement, axis=1)), .02)
        self.assertGreater(displacement[:, 1].max(), .005)
        for i in range(3):
            self.assertTrue(np.isfinite(np.exp(after[3]['scale_'+str(i)])).all())
        quat = np.column_stack([after[3]['rot_'+str(i)] for i in range(4)])
        np.testing.assert_allclose(np.linalg.norm(quat, axis=1), 1, atol=1e-6)
        for field in ('f_dc_0', 'f_dc_1', 'f_dc_2', 'opacity'):
            np.testing.assert_array_equal(before[3][field], after[3][field])


if __name__ == '__main__':
    unittest.main()
