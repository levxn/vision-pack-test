#!/usr/bin/env python3
"""fn.readers.tfrecord with a feature key missing from the key map, user style (no error handling).

amd.rocal.readers.tfrecord() prints the required keys and calls exit(), i.e. status 0, so the
misconfigured script reports success. A correct library raises (non-zero status).
"""
import tempfile

import amd.rocal.fn as fn
import amd.rocal.types as types
from amd.rocal.pipeline import Pipeline

with tempfile.TemporaryDirectory() as d:
    pipe = Pipeline(batch_size=2, num_threads=1, device_id=0, seed=1, rocal_cpu=True, tensor_layout=types.NHWC)
    with pipe:
        key_map = {"image/class/label": "image/class/label", "image/filename": "image/filename"}
        features = {"image/encoded": None, "image/class/label": None, "image/filename": None}
        fn.readers.tfrecord(d, key_map, features, reader_type=0)
print("CONTROL-INVALID: tfrecord() accepted a feature key that is missing from the key map")
