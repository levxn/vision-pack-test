#!/usr/bin/env python3
"""A user-style amd.rocal script whose GPU pipeline fails rocalVerify (a crop far larger than the image).

    rocal_verify_fail.py <jpeg_dir>

No error handling on purpose: a failed build must end the process with a non-zero status. rocAL's
Pipeline.build() prints "Verify graph failed" and calls exit(0) instead (M8), so the script "succeeds".
If build() returns, the controlled failure no longer fails and the check itself is invalid.
"""
import sys

import amd.rocal.fn as fn
import amd.rocal.types as types
from amd.rocal.pipeline import Pipeline

data = sys.argv[1].rstrip("/") + "/"
pipe = Pipeline(batch_size=2, num_threads=1, device_id=0, seed=1, rocal_cpu=False, tensor_layout=types.NHWC)
with pipe:
    jpegs, _ = fn.readers.file(file_root=data)
    images = fn.decoders.image(jpegs, file_root=data, output_type=types.RGB, random_shuffle=False)
    images = fn.crop(images, crop=(100000, 100000))
    pipe.set_outputs(images)
pipe.build()
print("CONTROL-INVALID: build() returned; the oversized crop no longer fails verification")
