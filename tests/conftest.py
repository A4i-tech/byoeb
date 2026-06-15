"""Add repo root to sys.path for wizard imports."""
import sys
import pathlib

ROOT = str(pathlib.Path(__file__).parent.parent.resolve())
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
