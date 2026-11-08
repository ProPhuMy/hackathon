import subprocess
import sys
import unittest


class CliTests(unittest.TestCase):
    def test_help_exposes_feasibility_check(self):
        result = subprocess.run([sys.executable, '-m', 'fridge_person.main', '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('check-models', result.stdout)

    def test_missing_weights_fail_without_downloading(self):
        result = subprocess.run([sys.executable, '-m', 'fridge_person.main', 'check-models', '--detector', '/nonexistent/det.onnx', '--recognizer', '/nonexistent/rec.onnx', '--image', '/nonexistent/face.jpg'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Missing local file', result.stderr)
