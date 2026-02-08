import sys
from pathlib import Path
import os

sys.path.append(str(Path(__file__).resolve().parents[1]))

# Keep backend tests deterministic and side-effect free.
os.environ.setdefault("ACTION_EXECUTOR_MODE", "simulated")
