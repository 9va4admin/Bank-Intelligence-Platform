"""Lets the tests import the handwriting research tools from scripts/ (a plain folder, not an installed package)."""
import sys
from pathlib import Path

SCRIPTS = str(Path(__file__).resolve().parents[3] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
