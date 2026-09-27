import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for sub in ("build_tools", "build_tools/results", "report"):
    sys.path.insert(0, str(REPO / sub))
