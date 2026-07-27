import os
import sys

# make the repo root importable so `scripts/*.py` can be loaded from tests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
