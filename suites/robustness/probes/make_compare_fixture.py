#!/usr/bin/env python3
"""Create a golden/output pair that must fail rocAL's image_comparison.py: every pixel differs.

    make_compare_fixture.py <dir>    creates <dir>/golden/ and <dir>/rocal/ with Brightness_rgb_hip.png
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

root = Path(sys.argv[1])
for sub, value in (("golden", 0), ("rocal", 200)):
    (root / sub).mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.full((32, 32, 3), value, np.uint8)).save(root / sub / "Brightness_rgb_hip.png")
print(f"fixture in {root}: golden all 0, rocal all 200")
