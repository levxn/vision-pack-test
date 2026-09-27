"""Import-only stand-in for OpenCV, used when python3-opencv is missing.

It lets a script get past "import cv2" when the code under test fails before any OpenCV call. Any use
prints a marker that checked_run.py --blocked-if turns into "blocked", so it never produces a pass.
"""
import sys


def __getattr__(name):
    print(f"VPT-CV2-STUB used: cv2.{name} (python3-opencv is not installed)", file=sys.stderr, flush=True)
    raise AttributeError(f"cv2 stand-in has no {name}")
