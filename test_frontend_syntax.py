"""Catch a broken entry script before it strands visitors at the welcome gate."""
import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parent


class FrontendSyntaxTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_frontend_scripts_parse(self):
        for path in sorted(ROOT.glob("app-*.js")):
            with self.subTest(script=path.name):
                result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
