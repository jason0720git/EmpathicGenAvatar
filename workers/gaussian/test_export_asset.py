from pathlib import Path
import os
import tempfile
import unittest
import zipfile

import numpy as np

from export_asset import accessor_array, decode_glb, export_avatar, template_data

ANCESTORS = Path(__file__).resolve().parents
REPO = ANCESTORS[2] if len(ANCESTORS) > 2 else Path("/")
FBX = Path(os.environ.get("LAM_ROOT", str(REPO / "vendor/LAM"))) / "assets/sample_oac/template_file.fbx"
SAMPLE = Path(os.environ.get("LAM_TEMPLATE_ZIP", str(REPO / "vendor/LAM_WebRender/asset/arkit/p2-1.zip")))


@unittest.skipUnless(FBX.exists() and SAMPLE.exists(), "Run LAM asset bootstrap first")
class ExportCompatibilityTest(unittest.TestCase):
    def test_replacement_preserves_rig_morphs_and_exact_vertex_correspondence(self):
        doc, binary, idx, translation, faces, animation = template_data(FBX, SAMPLE)
        original_positions = accessor_array(doc, binary, idx).reshape(-1, 3).copy()
        vertices = original_positions - translation
        vertices[:, 0] *= 1.07
        vertices[:, 2] += 0.003
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            ply = path / "offset.ply"
            with zipfile.ZipFile(SAMPLE) as source:
                ply.write_bytes(source.read("p2-1/offset.ply"))
            result = export_avatar(vertices, faces, ply, path / "avatar.zip", FBX, SAMPLE)
            with zipfile.ZipFile(path / "avatar.zip") as exported:
                self.assertEqual(set(exported.namelist()), {"avatar/", "avatar/skin.glb", "avatar/offset.ply", "avatar/animation.glb", "avatar/vertex_order.json"})
                self.assertTrue(exported.getinfo("avatar/").is_dir())
                actual_doc, actual_bin = decode_glb(exported.read("avatar/skin.glb"))
                self.assertEqual(exported.read("avatar/animation.glb"), animation)
                self.assertEqual(exported.read("avatar/offset.ply"), ply.read_bytes())
            self.assertEqual(doc["nodes"], actual_doc["nodes"])
            self.assertEqual(doc["skins"], actual_doc["skins"])
            self.assertEqual(doc["meshes"], actual_doc["meshes"])
            expected = np.asarray(vertices + translation, dtype="<f4")
            np.testing.assert_array_equal(accessor_array(actual_doc, actual_bin, idx).reshape(-1, 3), expected)
            view = doc["bufferViews"][doc["accessors"][idx]["bufferView"]]
            start, length = view.get("byteOffset", 0), view["byteLength"]
            self.assertEqual(binary[:start], actual_bin[:start])
            self.assertEqual(binary[start+length:], actual_bin[start+length:])
            self.assertEqual(len(result["blendshapes"]), 51)

    def test_changed_topology_is_rejected(self):
        doc, binary, idx, translation, faces, _ = template_data(FBX, SAMPLE)
        vertices = accessor_array(doc, binary, idx).reshape(-1, 3) - translation
        faces = faces.copy()
        faces[0, 0] = faces[0, 1]
        with self.assertRaisesRegex(ValueError, "topology"):
            export_avatar(vertices, faces, Path("unused.ply"), Path("unused.zip"), FBX, SAMPLE)

    def test_nonfinite_geometry_is_rejected(self):
        _, _, _, _, faces, _ = template_data(FBX, SAMPLE)
        vertices = np.zeros((20018, 3))
        vertices[0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "finite"):
            export_avatar(vertices, faces, Path("unused.ply"), Path("unused.zip"), FBX, SAMPLE)


if __name__ == "__main__":
    unittest.main()
