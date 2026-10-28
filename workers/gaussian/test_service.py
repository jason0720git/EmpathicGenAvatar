from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

import app


class WorkerSafetyTest(unittest.TestCase):
    def test_paths_cannot_escape_shared_data_root(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, "ROOT", Path(directory).resolve()):
            with self.assertRaises(HTTPException) as error:
                app.safe_path(str(Path(directory) / ".." / "private.png"))
            self.assertEqual(error.exception.status_code, 400)

    def test_directory_failure_does_not_permanently_lock_generator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source.png"
            source.write_bytes(b"fixture")
            broken_work = Mock()
            broken_work.mkdir.side_effect = PermissionError("Test filesystem unavailable")
            with patch.object(app, "ROOT", root), patch.object(app, "health", return_value={"ready": True}), patch.object(app, "job_path", return_value=broken_work):
                with self.assertRaises(HTTPException) as error:
                    app.generate(app.GenerateRequest(job_id="test", image_path=str(source), output_dir=str(root / "out")))
                self.assertEqual(error.exception.status_code, 500)
                self.assertFalse(app.lock.locked())
                self.assertIsNone(app.state["active_job"])

    def test_present_assets_do_not_claim_cuda_available_or_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample = root / "template.zip"
            sample.write_bytes(b"fixture")
            with patch.object(app, "ROOT", root), patch.object(app, "LAM_ROOT", root), patch.object(app, "SAMPLE_ZIP", sample), patch.object(app, "REQUIRED", []), patch.object(app, "CUDA_AVAILABLE", False):
                result = app.health()
                self.assertTrue(result["assets_ready"])
                self.assertFalse(result["ready"])
                self.assertFalse(result["verified_generation"])


if __name__ == "__main__":
    unittest.main()
