#!/usr/bin/env python3
"""Public header self-containment: each installed header must compile on its own
(a TU that includes only that header), as a consumer would use it.

Primary modes (standard tier and up; ported from gapfill a1/check_one.sh):
  headers.cxx17::mivisionx/<h>   g++ -std=c++17, -I include/mivisionx
  headers.cxx17::rocal/<h>       g++ -std=c++17, -I include/rocal
  headers.hip::roccv/<h>         amdclang++ -x hip -std=c++20 --offload-arch=$VP_GFX
Extra modes (comprehensive and up):
  headers.c99::mivisionx/<h>     gcc -std=c99 (the OpenVX API is a C API)
  headers.cxx20-host::roccv/<h>  g++ -std=c++20 host-only, excluding kernels/device/*
                                 (hip::host would suffice for most of the API, M23)
"""
from __future__ import annotations

import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor

from sdkutil import ROCM, Recorder, load_manifest, log_path, run, tier_ge, work_dir


def headers(lib: str) -> list[str]:
    base = os.path.join(ROCM, "include", lib)
    out = []
    for root, _dirs, files in os.walk(base):
        for f in files:
            if f.endswith((".h", ".hpp", ".hh", ".hxx")):
                out.append(os.path.relpath(os.path.join(root, f), os.path.join(ROCM, "include")))
    return sorted(out)


def main() -> int:
    rec = Recorder()
    wd = work_dir("headers")
    log_file = log_path("headers.log")
    gcc, gxx = shutil.which("gcc") or shutil.which("cc"), shutil.which("g++") or shutil.which("c++")
    clang = os.path.join(ROCM, "lib", "llvm", "bin", "amdclang++")
    arch = os.environ.get("VP_GFX", "")
    arch_note = ""
    if not arch:
        targets = (load_manifest().get("gpu_targets") or {}).get("libroccv") or []
        arch = targets[0] if targets else "gfx942"
        arch_note = f" (VP_GFX empty; using {arch})"

    def inc(lib: str) -> list[str]:
        return [f"-I{ROCM}/include/{lib}", f"-I{ROCM}/include"]

    modes = {
        "cxx17": (gxx, lambda lib: ["-x", "c++", "-std=c++17", "-fsyntax-only", *inc(lib)], "cpp"),
        "hip": (clang if os.path.exists(clang) else None,
                lambda lib: ["-x", "hip", "-std=c++20", f"--offload-arch={arch}", "-D__HIP_PLATFORM_AMD__",
                             "-fsyntax-only", *inc(lib)], "cpp"),
        "c99": (gcc, lambda lib: ["-x", "c", "-std=c99", "-fsyntax-only", *inc(lib)], "c"),
        "cxx20-host": (gxx, lambda lib: ["-x", "c++", "-std=c++20", "-fsyntax-only", "-D__HIP_PLATFORM_AMD__",
                                         *inc(lib)], "cpp"),
    }
    plan = [("cxx17", "mivisionx"), ("cxx17", "rocal"), ("hip", "roccv")]
    if tier_ge("comprehensive"):
        plan += [("c99", "mivisionx"), ("cxx20-host", "roccv")]

    jobs = []
    for mode, lib in plan:
        for h in headers(lib):
            if mode == "cxx20-host" and "/kernels/device/" in f"/{h}":
                continue
            jobs.append((mode, lib, h))

    def one(job):
        mode, lib, h = job
        compiler, flags, ext = modes[mode]
        if not compiler:
            return job, None, "compiler missing"
        sub = h.split("/", 1)[1]
        tu = wd / mode / (re.sub(r"[^A-Za-z0-9]", "_", h) + f".{ext}")
        tu.parent.mkdir(parents=True, exist_ok=True)
        tu.write_text(f"#include <{sub}>\nint vp_selfcontained_dummy;\n", encoding="utf-8")
        rc, out, dur = run([compiler, *flags(lib), str(tu)], timeout=300)
        return job, rc, out

    workers = max(1, min(8, (os.cpu_count() or 2) // 2))
    with ThreadPoolExecutor(max_workers=workers) as ex, open(log_file, "w", encoding="utf-8") as log:
        for (mode, _lib, h), rc, out in ex.map(one, jobs):
            tid = f"headers.{mode}::{h}"
            if rc is None:
                rec(tid, "blocked", f"{mode} compiler not available")
                continue
            log.write(f"== [{mode}] {h} rc={rc}\n{out}\n")
            if rc == 0:
                rec(tid, "pass", f"self-contained{arch_note if mode == 'hip' else ''}", log=log_file)
            else:
                err = next((ln for ln in out.splitlines() if "error" in ln), out.strip()[-300:])
                err = err.replace(f"{ROCM}/include/", "").strip()[:400]
                rec(tid, "error" if rc == 124 or rc < 0 else "fail", err, log=log_file)
    print(rec.counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
