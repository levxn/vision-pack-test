"""Hides any installed tensorflow so the scripts' missing-tensorflow path runs deterministically."""
raise ImportError("tensorflow hidden by vision-pack-test (controlled missing-dependency case)")
