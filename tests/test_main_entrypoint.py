import unittest
from pathlib import Path


class MainEntrypointTests(unittest.TestCase):
    def test_main_py_exists(self):
        self.assertTrue((Path(__file__).resolve().parents[1] / "main.py").exists())


if __name__ == "__main__":
    unittest.main()
