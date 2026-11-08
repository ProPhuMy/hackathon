import subprocess
import sys
import unittest


class CliTests(unittest.TestCase):
    def test_help_exposes_feasibility_check(self):
        result = subprocess.run([sys.executable, '-m', 'fridge_person.main', '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('check-models', result.stdout)
        self.assertIn('check-detectors', result.stdout)

    def test_missing_weights_fail_without_downloading(self):
        result = subprocess.run([sys.executable, '-m', 'fridge_person.main', 'check-models', '--detector', '/nonexistent/det.onnx', '--recognizer', '/nonexistent/rec.onnx', '--image', '/nonexistent/face.jpg'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Missing local file', result.stderr)

        result_det = subprocess.run([sys.executable, '-m', 'fridge_person.main', 'check-detectors', '--image', '/nonexistent/face.jpg', '--scrfd', '/nonexistent/det.onnx', '--yolo5face', '/nonexistent/yolo.onnx'], capture_output=True, text=True)
        self.assertEqual(result_det.returncode, 1)
        self.assertIn('Missing local file', result_det.stderr)

    def test_junk_model_file_fails_helpfully(self):
        from pathlib import Path
        import tempfile
        import numpy as np
        import cv2

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            img = tmppath / 'face.jpg'
            cv2.imwrite(str(img), np.zeros((640, 640, 3), dtype=np.uint8))
            junk = tmppath / 'corrupt.onnx'
            junk.write_bytes(b'THIS_IS_NOT_AN_ONNX_MODEL_FILE')

            result = subprocess.run(
                [sys.executable, '-m', 'fridge_person.main', 'check-detectors',
                 '--image', str(img), '--scrfd', str(junk), '--yolo5face', str(junk)],
                capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn('Person service failed:', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
