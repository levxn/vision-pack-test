#!/usr/bin/env python3
"""Install-location contamination: does a consumer configured against $ROCM_PATH
pick up anything from another ROCm install?

A synthetic decoy tree in $VP_OUT/work/decoy-rocm stands in for "another ROCm"
(/opt/rocm, an older TheRock tarball, ...): CMake configs for amd_comgr,
hsa-runtime64, AMDDeviceLibs and hip that print a marker and then include the
real ones (so configure and build still succeed, as they did against a real
other install), plus decoy MIVisionX/rocAL headers and libraries. It has no
llvm/bin/amdgpu-arch, like TheRock layouts without the llvm symlink.

Scenarios x modes, per consumer (mivisionx, rocal, roccv):
  contamination.unset.<mode>::<consumer>   ROCM_PATH unset
  contamination.decoy.<mode>::<consumer>   ROCM_PATH=<decoy>
  explicit: the consumer names the prefix (VP_PREFIX / CMAKE_PREFIX_PATH)
  implicit: mivisionx/rocal use $ENV{ROCM_PATH}; roccv is found through PATH
Pass: every resolved package dir, include dir and library lies in $ROCM_PATH, or
configure fails cleanly (nothing found). Fail: anything resolves into the decoy.
  contamination.<scenario>.<mode>::roccv-offload-arch  hip::device still carries
    --offload-arch (hip-config-amd.cmake runs $ENV{ROCM_PATH}/llvm/bin/amdgpu-arch)
M23: roccv's find_dependency(HIP) follows $ENV{ROCM_PATH} into the decoy.
"""
from __future__ import annotations

import glob
import os
import re
import shutil

from sdkutil import HERE, ROCM, Recorder, cmake_configure, customer_env, first_error, log_path, work_dir

DEPS = {"amd_comgr": "amd_comgr-config.cmake", "hsa-runtime64": "hsa-runtime64-config.cmake",
        "AMDDeviceLibs": "AMDDeviceLibsConfig.cmake", "hip": "hip-config.cmake"}
CACHE_KEYS = re.compile(r"^(\w[\w-]*_DIR|MIVisionX_INCLUDE_DIR|MIVisionX_OPENVX_LIBRARY|MIVisionX_VXU_LIBRARY|"
                        r"MIVisionX_VXRPP_LIBRARY|rocal_INCLUDE_DIR|rocal_LIBRARY|Python3_\w+):\w+=(.*)$")


def make_decoy(root: str) -> str:
    shutil.rmtree(root, ignore_errors=True)
    for pkg, cfg in DEPS.items():
        real = os.path.join(ROCM, "lib", "cmake", pkg, cfg)
        d = os.path.join(root, "lib", "cmake", pkg)
        os.makedirs(d)
        with open(os.path.join(d, cfg), "w", encoding="utf-8") as f:
            f.write(f'message(STATUS "VPDECOY {pkg} config loaded from ${{CMAKE_CURRENT_LIST_DIR}}")\n')
            if os.path.exists(real):
                f.write(f'include("{real}")\n')
        ver = os.path.join(ROCM, "lib", "cmake", pkg, cfg.replace("config.cmake", "config-version.cmake")
                           .replace("Config.cmake", "ConfigVersion.cmake"))
        if os.path.exists(ver):
            shutil.copy(ver, d)
    for rel in ("include/mivisionx/vx_ext_rpp.h", "include/mivisionx/VX/vx.h", "include/rocal/rocal_api.h"):
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("#error decoy header from another ROCm install\n")
    os.makedirs(os.path.join(root, "lib"), exist_ok=True)
    for lib in ("libopenvx.so", "libvxu.so", "libvx_rpp.so", "librocal.so"):
        open(os.path.join(root, "lib", lib), "wb").close()
    os.makedirs(os.path.join(root, "bin"), exist_ok=True)
    return root


def main() -> int:
    rec = Recorder()
    wd = work_dir("contamination")
    log_file = log_path("contamination.log")
    decoy = make_decoy(str(wd / "decoy-rocm"))
    clang = os.path.join(ROCM, "lib", "llvm", "bin", "amdclang++")
    offload = {}
    with open(log_file, "w", encoding="utf-8") as log:
        log.write(f"decoy tree: {decoy}\n")
        for scenario in ("unset", "decoy"):
            for mode in ("explicit", "implicit"):
                for consumer in ("mivisionx", "rocal", "roccv"):
                    tid = f"contamination.{scenario}.{mode}::{consumer}"
                    env = customer_env()
                    env.pop("ROCM_PATH", None)
                    if scenario == "decoy":
                        env["ROCM_PATH"] = decoy
                    args = []
                    if consumer in ("mivisionx", "rocal") and mode == "explicit":
                        args.append(f"-DVP_PREFIX={ROCM}")
                    if consumer == "rocal":
                        args += ["-DVP_ROCAL_PREFIXED=ON"]
                    if consumer == "roccv":
                        args.append(f"-DCMAKE_CXX_COMPILER={clang}")
                        if mode == "explicit":
                            args.append(f"-DCMAKE_PREFIX_PATH={ROCM}")
                    b = str(wd / f"b_{scenario}_{mode}_{consumer}")
                    log.write(f"### {tid} ROCM_PATH={env.get('ROCM_PATH', '<unset>')}\n")
                    rc, out = cmake_configure(os.path.join(HERE, "consumers", consumer), b, args, env, log)
                    resolved = {}
                    cache = os.path.join(b, "CMakeCache.txt")
                    if os.path.exists(cache):
                        with open(cache, encoding="utf-8", errors="replace") as f:
                            for line in f:
                                m = CACHE_KEYS.match(line.strip())
                                if m and m.group(1).endswith(("_SOURCE_DIR", "_BINARY_DIR")):
                                    continue
                                if m and m.group(2) and not m.group(2).endswith("-NOTFOUND"):
                                    resolved[m.group(1)] = m.group(2)
                    in_decoy = {k: v for k, v in resolved.items() if v.startswith(decoy)}
                    markers = sorted(set(re.findall(r"VPDECOY (\S+) config", out)))
                    log.write(f"    resolved: {resolved}\n")
                    if in_decoy or markers:
                        rec(tid, "fail", "resolved into the decoy ROCm tree: "
                            + ", ".join(f"{k}={v.replace(decoy, '<decoy>')}" for k, v in sorted(in_decoy.items()))
                            + (f" (decoy configs loaded: {' '.join(markers)})" if markers else ""), log=log_file)
                    elif rc != 0:
                        clean = bool(re.search(r"(Could not find|By not providing|Could NOT find)", out))
                        expected_clean = mode == "implicit" and consumer in ("mivisionx", "rocal")
                        rec(tid, "pass" if clean and expected_clean else "fail",
                            ("fails cleanly: nothing found without an explicit prefix" if clean and expected_clean
                             else f"configure failed: {first_error(out)}"), log=log_file)
                    else:
                        outside = {k: v for k, v in resolved.items()
                                   if k != "CMAKE_HOME_DIRECTORY" and not k.startswith("Python3_")
                                   and v.startswith("/") and not v.startswith(ROCM) and not v.startswith(b)}
                        rec(tid, "fail" if outside else "pass",
                            f"resolved outside $ROCM_PATH: {outside}" if outside else
                            f"{len(resolved)} package paths, all under $ROCM_PATH", log=log_file)
                    if consumer == "roccv":
                        flags = ""
                        for fm in [*glob.glob(os.path.join(b, "CMakeFiles", "*.dir", "flags.make")),
                                   *glob.glob(os.path.join(b, "build.ninja"))]:
                            with open(fm, encoding="utf-8") as f:
                                flags += f.read()
                        has = "--offload-arch=" in flags
                        offload[(scenario, mode)] = (rc == 0, has)
                        otid = f"contamination.{scenario}.{mode}::roccv-offload-arch"
                        if rc != 0:
                            rec(otid, "error", "configure failed; flags not generated", log=log_file)
                        elif has:
                            archs = sorted(set(re.findall(r"--offload-arch=(\S+)", flags)))
                            rec(otid, "pass", f"--offload-arch present: {' '.join(archs)}", log=log_file)
                        elif scenario == "decoy" and not offload.get(("unset", mode), (False, False))[1]:
                            rec(otid, "error", "no --offload-arch, but the ROCM_PATH-unset control lacks it too "
                                "(GPU autodetection unavailable here)", log=log_file)
                        else:
                            rec(otid, "fail", "hip::device carries no --offload-arch: device code would silently "
                                "target the compiler default", log=log_file)
    print(rec.counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
