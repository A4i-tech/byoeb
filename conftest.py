"""Root conftest — adds repo root to sys.path so wizard package is importable."""
import sys
import pathlib

ROOT = str(pathlib.Path(__file__).parent.resolve())
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
