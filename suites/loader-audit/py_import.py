#!/usr/bin/env python3
"""Import every shipped Python module in a fresh interpreter (customer mode:
PYTHONPATH=$ROCM_PATH/lib from vp_init, no LD_LIBRARY_PATH).

  py-import.py312::<module>          must import with the image's python3 (VP_PY).
  py-import.py313-negative::<module> negative control: the compiled modules are
                                     cp312-only, so python3.13 must fail to import
                                     them. Runs only when python3.13 exists
                                     (VP_PY313 or PATH); otherwise skip.
"""
from __future__ import annotations

import os
import shutil
import sys

from vp_owned import Recorder, crashed, customer_env, log_path, parity_env, run, tier_ge, work_dir

MODULES = ["rocal_pybind", "rocpycv", "rocpydecode", "rocpyjpegdecode", "amd.rocal", "amd.rocal.types",
           "amd.rocal.pipeline", "amd.rocal.fn", "amd.rocal.plugin.generic", "pyRocVideoDecode", "pyRocJpegDecode"]
COMPILED = ["rocal_pybind", "rocpycv", "rocpydecode", "rocpyjpegdecode"]

SNIPPET = r"""
import importlib, sys
m = sys.argv[1]
try:
    mod = importlib.import_module(m)
    print(f"OK {m} file={getattr(mod, '__file__', None)}")
except ModuleNotFoundError as e:
    print(f"NOTFOUND {m}: {e}"); sys.exit(3)
except ImportError as e:
    print(f"LINKFAIL {m}: {e}"); sys.exit(4)
except Exception as e:
    print(f"RUNTIME {m}: {type(e).__name__}: {e}"); sys.exit(5)
"""


def try_import(py: str, mod: str, env: dict, cwd: str) -> tuple[int, str, float]:
    return run([py, "-c", SNIPPET, mod], env=env, timeout=300, cwd=cwd)


def main() -> int:
    rec = Recorder()
    wd = str(work_dir("py-import"))
    log_file = log_path("py-import.log")
    py = os.environ.get("VP_PY", sys.executable)
    with open(log_file, "w", encoding="utf-8") as log:
        for mod in MODULES:
            rc, out, dur = try_import(py, mod, customer_env(), wd)
            log.write(f"== {py} import {mod} rc={rc}\n{out}\n")
            if rc == 0:
                rec(f"py-import.py312::{mod}", "pass", out.strip().splitlines()[-1][:300], log=log_file, duration=dur)
                continue
            prc, pout, _ = try_import(py, mod, parity_env(), wd)
            log.write(f"== ci-parity import {mod} rc={prc}\n{pout}\n")
            cls = "imports with the CI LD_LIBRARY_PATH: RUNPATH gap" if prc == 0 else "fails in CI-parity mode too"
            last = (out.strip().splitlines() or [""])[-1]
            rec(f"py-import.py312::{mod}", "error" if crashed(rc) else "fail", f"rc={rc} {last[:400]} [{cls}]",
                log=log_file, duration=dur)

        if not tier_ge("standard"):
            return 0
        py313 = os.environ.get("VP_PY313") or shutil.which("python3.13") or ""
        for mod in COMPILED:
            tid = f"py-import.py313-negative::{mod}"
            if not py313:
                rec(tid, "skip", "python3.13 not installed (negative control runs only where it exists)")
                continue
            rc, out, dur = try_import(py313, mod, customer_env(), wd)
            log.write(f"== {py313} import {mod} rc={rc}\n{out}\n")
            last = (out.strip().splitlines() or [""])[-1]
            if rc in (3, 4, 5):
                rec(tid, "pass", f"fails as expected on 3.13 (cp312-only): {last[:300]}", log=log_file, duration=dur)
            elif rc == 0:
                rec(tid, "fail", f"unexpectedly imported on python3.13: {last[:300]}", log=log_file, duration=dur)
            else:
                rec(tid, "error", f"rc={rc}: {last[:300]}", log=log_file, duration=dur)
    print(rec.counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
