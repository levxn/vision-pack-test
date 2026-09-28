#!/usr/bin/env python3
"""Consumer CMake projects built with find_package against $ROCM_PATH, then run
on CPU and GPU with numeric checks.

consumer.mivisionx::find-package            FindMIVisionX configures
consumer.mivisionx::build                   <VX/vx.h> via MIVisionX::MIVisionX compiles (H3)
consumer.mivisionx::build-include-workaround  same with include/mivisionx added by hand
consumer.mivisionx::<CPU|GPU>.<check>       context, not, box3x3 (interior exact),
                                            border-replicate / border-constant (M17),
                                            vx_rpp-load
consumer.rocal::find-package                Findrocal configures
consumer.rocal::build                       plain rocal::rocal consumer links (H1)
consumer.rocal::include-unprefixed          upstream's #include "rocal_api.h" compiles
consumer.rocal::build-with-libpython        H1 workaround: link Python3::Python
consumer.rocal::<CPU|GPU|GPU-rocjpeg>.pipeline  decode+resize runs, shape/content sane
consumer.rocal::<CPU|GPU>.vs-reference      output vs PIL bilinear resize of the source
consumer.rocal::cpu-vs-gpu                  CPU (1 thread) vs GPU output
consumer.rocal::cpu-threads-<1|2|4>         CPU output with N threads vs GPU: no zeroed
                                            image heads (H7)
consumer.roccv::find-package / build        roccv::roccv with amdclang++
consumer.roccv::build-gxx                   the same consumer with g++ (M23: fails)
consumer.roccv::<GPU|CPU>.flip<code>        Flip output exact
consumer.roccv::GPU.launch-errors           no pending launch error after GPU ops (M21)
"""
from __future__ import annotations

import glob
import os
import shutil
import sys

from sdkutil import (
    HERE,
    ROCM,
    Recorder,
    cmake_build,
    cmake_configure,
    customer_env,
    first_error,
    ingest_checks,
    log_path,
    run,
    tier_ge,
    work_dir,
)

GPU = bool(os.environ.get("VP_GFX"))
NO_GPU = "no GPU detected (VP_GFX empty)"


def mivisionx(rec: Recorder) -> None:
    g = "consumer.mivisionx"
    wd = work_dir("mivisionx")
    log_file = log_path("consumer-mivisionx.log")
    src = os.path.join(HERE, "consumers", "mivisionx")
    env = customer_env()
    with open(log_file, "w", encoding="utf-8") as log:
        rc, out = cmake_configure(src, str(wd / "b_plain"), [f"-DVP_PREFIX={ROCM}"], env, log)
        rec(f"{g}::find-package", "pass" if rc == 0 else "fail",
            "find_package(MIVisionX) OK" if rc == 0 else first_error(out), log=log_file)
        if rc == 0:
            rc, out = cmake_build(str(wd / "b_plain"), env, log)
            rec(f"{g}::build", "pass" if rc == 0 else "fail",
                "compiles with MIVisionX::MIVisionX alone" if rc == 0 else first_error(out), log=log_file)
        else:
            rec(f"{g}::build", "error", "not run: configure failed", log=log_file)
        b = str(wd / "b_wa")
        rc, out = cmake_configure(src, b, [f"-DVP_PREFIX={ROCM}", "-DVP_WORKAROUND_INC=ON"], env, log)
        if rc == 0:
            rc, out = cmake_build(b, env, log)
        rec(f"{g}::build-include-workaround", "pass" if rc == 0 else "fail",
            "builds with include/mivisionx added" if rc == 0 else first_error(out), log=log_file)
        expected = ["context", "not", "box3x3", "border-replicate", "border-constant", "vx_rpp-load"]
        for tgt in ("CPU", "GPU"):
            if rc != 0:
                for c in expected:
                    rec(f"{g}::{tgt}.{c}", "error", "not run: consumer build failed", log=log_file, backend=tgt)
                continue
            if tgt == "GPU" and not GPU:
                for c in expected:
                    rec(f"{g}::{tgt}.{c}", "blocked", NO_GPU, backend=tgt)
                continue
            rrc, rout, dur = run([os.path.join(b, "mvx_consumer")], env=customer_env(AGO_DEFAULT_TARGET=tgt),
                                 timeout=180, cwd=str(wd))
            log.write(f"== run AGO_DEFAULT_TARGET={tgt} rc={rrc}\n{rout}\n")
            ingest_checks(rec, g, tgt, expected, rrc, rout, log=log_file, backend=tgt, duration=dur)


def rocal_numeric(rec: Recorder, g: str, dumps: str, ok_runs: dict[str, bool], data_dir: str, log) -> None:
    ids = ["CPU.vs-reference", "GPU.vs-reference", "cpu-vs-gpu", "cpu-threads-1", "cpu-threads-2", "cpu-threads-4"]
    try:
        import numpy as np
    except ImportError:
        for i in ids:
            rec(f"{g}::{i}", "blocked", "numpy not installed for VP_PY")
        return
    size, bs = 224, int(os.environ.get("VP_BS_ROCAL", "4"))

    def load(tag: str):
        f = os.path.join(dumps, f"{tag}_iter0.raw")
        if not ok_runs.get(tag) or not os.path.exists(f):
            return None
        a = np.fromfile(f, dtype=np.uint8)
        return a.reshape(bs, size, size, 3).astype(np.int16) if a.size == bs * size * size * 3 else None

    cpu1, gpu = load("cpu_t1"), load("gpu")

    def heads_zeroed(a, ref) -> list[int]:
        return [b for b in range(bs) if not a[b].reshape(-1)[:8].any() and ref[b].reshape(-1)[:8].any()]

    # H7: multi-threaded CPU resize zeroes the first 8 bytes of images 1..N-1.
    ref, ref_name = (gpu, "GPU") if gpu is not None else (cpu1, "CPU 1-thread")
    for n in (1, 2, 4):
        a = load(f"cpu_t{n}")
        tid = f"{g}::cpu-threads-{n}"
        if a is None or ref is None:
            rec(tid, "error", f"no output to compare (cpu_t{n} ok={ok_runs.get(f'cpu_t{n}')}, reference {ref_name})",
                log=log.name, backend="CPU")
            continue
        z = heads_zeroed(a, ref)
        pct = float((np.abs(a - ref) > 2).mean() * 100)
        leading = [int(np.flatnonzero(a[b].reshape(-1))[0]) if a[b].any() else -1 for b in range(bs)]
        rec(tid, "fail" if z or pct > 0.5 else "pass",
            f"bs={bs} threads={n} vs {ref_name}: images with zeroed first 8 bytes={z}, leading zero bytes per image="
            f"{leading}, {pct:.3f}% bytes differ by >2", log=log.name, backend="CPU")

    if cpu1 is not None and gpu is not None:
        d = np.abs(cpu1 - gpu)
        pct, mad = float((d > 2).mean() * 100), float(d.mean())
        rec(f"{g}::cpu-vs-gpu", "pass" if pct < 0.5 and mad < 1.0 else "fail",
            f"MAD={mad:.3f} max={int(d.max())} bytes differing >2: {pct:.3f}%", log=log.name)
    elif not GPU:
        rec(f"{g}::cpu-vs-gpu", "blocked", NO_GPU, log=log.name)
    else:
        rec(f"{g}::cpu-vs-gpu", "error", "CPU or GPU output missing", log=log.name)

    try:
        from PIL import Image
    except ImportError:
        for i in ids[:2]:
            rec(f"{g}::{i}", "blocked", "Pillow not installed for VP_PY (image reference)")
        return
    refs = []
    for f in sorted(glob.glob(os.path.join(data_dir, "*")))[:64]:
        try:
            with Image.open(f) as im:
                refs.append((os.path.basename(f), np.asarray(im.convert("RGB").resize((size, size), Image.BILINEAR),
                                                             dtype=np.int16)))
        except OSError:
            continue
    for tag, name, be in (("cpu_t1", "CPU.vs-reference", "CPU"), ("gpu", "GPU.vs-reference", "GPU")):
        a = cpu1 if tag == "cpu_t1" else gpu
        if be == "GPU" and not GPU:
            rec(f"{g}::{name}", "blocked", NO_GPU, log=log.name, backend=be)
            continue
        if a is None or not refs:
            rec(f"{g}::{name}", "error", "no output or no reference images", log=log.name, backend=be)
            continue
        mads = []
        for b in range(bs):
            # image 0 only: images 1.. are affected by H7 on CPU and judged by cpu-threads-*
            best = min((float(np.abs(a[b] - r).mean()), n) for n, r in refs)
            mads.append(best)
            if tag == "cpu_t1":
                break
        worst = max(m for m, _ in mads)
        rec(f"{g}::{name}", "pass" if worst < 4.0 else "fail",
            "MAD vs PIL bilinear (best-matching source): " + ", ".join(f"{n}={m:.2f}" for m, n in mads),
            log=log.name, backend=be)


def rocal(rec: Recorder) -> None:
    g = "consumer.rocal"
    wd = work_dir("rocal")
    log_file = log_path("consumer-rocal.log")
    src = os.path.join(HERE, "consumers", "rocal")
    env = customer_env()
    with open(log_file, "w", encoding="utf-8") as log:
        b_plain = str(wd / "b_plain")
        rc, out = cmake_configure(src, b_plain, [f"-DVP_PREFIX={ROCM}", "-DVP_ROCAL_PREFIXED=ON"], env, log)
        rec(f"{g}::find-package", "pass" if rc == 0 else "fail",
            "find_package(rocal) OK" if rc == 0 else first_error(out), log=log_file)
        if rc == 0:
            rc, out = cmake_build(b_plain, env, log)
            n_undef = out.count("undefined reference")
            rec(f"{g}::build", "pass" if rc == 0 else "fail",
                "links with rocal::rocal alone" if rc == 0 else f"{n_undef} undefined reference(s); {first_error(out)}",
                log=log_file)
        else:
            rec(f"{g}::build", "error", "not run: configure failed", log=log_file)

        def py_build(tag: str, prefixed: bool) -> tuple[int, str, bool]:
            b = str(wd / tag)
            args = [f"-DVP_PREFIX={ROCM}", "-DVP_ROCAL_LINK_PY=ON", f"-DVP_ROCAL_PREFIXED={'ON' if prefixed else 'OFF'}"]
            rc, out = cmake_configure(src, b, args, env, log)
            if rc != 0:
                return rc, out, "Python3" in out and "Could NOT find" in out
            rc, out = cmake_build(b, env, log)
            return rc, out, False

        rc, out, nopy = py_build("b_unprefixed", False)
        rec(f"{g}::include-unprefixed", "blocked" if nopy else "pass" if rc == 0 else "fail",
            "libpython development files missing (python3-dev)" if nopy else
            '#include "rocal_api.h" compiles' if rc == 0 else first_error(out), log=log_file)
        rc, out, nopy = py_build("b_py", True)
        rec(f"{g}::build-with-libpython", "blocked" if nopy else "pass" if rc == 0 else "fail",
            "libpython development files missing (python3-dev)" if nopy else
            "builds when the consumer links Python3::Python" if rc == 0 else first_error(out), log=log_file)
        binary = str(wd / "b_py" / "rocal_consumer")

        data_dir = os.path.join(ROCM, "share", "rocal", "test", "data", "images", "AMD-tinyDataSet")
        runs = [("cpu_t1", "cpu", 1, "CPU.pipeline", "CPU"), ("cpu_t2", "cpu", 2, None, "CPU"),
                ("cpu_t4", "cpu", 4, None, "CPU"), ("gpu", "gpu", 1, "GPU.pipeline", "GPU")]
        if tier_ge("comprehensive"):
            runs.append(("rocjpeg", "rocjpeg", 1, "GPU-rocjpeg.pipeline", "GPU"))
        dumps = str(wd / "dumps")
        shutil.rmtree(dumps, ignore_errors=True)
        os.makedirs(dumps)
        ok_runs: dict[str, bool] = {}
        usable = rc == 0 and os.path.exists(binary) and os.path.isdir(data_dir)
        for tag, mode, threads, tid, be in runs:
            if not usable:
                if tid:
                    why = "not run: consumer build failed" if rc != 0 else f"test images missing: {data_dir}"
                    rec(f"{g}::{tid}", "error" if rc != 0 else "blocked", why, log=log_file, backend=be)
                continue
            if be == "GPU" and not GPU:
                if tid:
                    rec(f"{g}::{tid}", "blocked", NO_GPU, backend=be)
                continue
            renv = customer_env(VP_BS=os.environ.get("VP_BS_ROCAL", "4"), VP_THREADS=str(threads), VP_ITERS="1")
            rrc, rout, dur = run([binary, data_dir + "/", mode, os.path.join(dumps, tag)], env=renv, timeout=300,
                                 cwd=str(wd))
            log.write(f"== run {tag} rc={rrc}\n{rout[-4000:]}\n")
            ok_runs[tag] = rrc == 0 and "CHECK pipeline PASS" in rout
            if tid:
                ingest_checks(rec, g, tid.rsplit(".", 1)[0], ["pipeline"], rrc, rout, log=log_file, backend=be,
                              duration=dur)
        if usable:
            rocal_numeric(rec, g, dumps, ok_runs, data_dir, log)
        else:
            for i in ["CPU.vs-reference", "GPU.vs-reference", "cpu-vs-gpu", "cpu-threads-1", "cpu-threads-2",
                      "cpu-threads-4"]:
                rec(f"{g}::{i}", "error" if rc != 0 else "blocked", "no consumer output (see build/run results)",
                    log=log_file)


def roccv(rec: Recorder) -> None:
    g = "consumer.roccv"
    wd = work_dir("roccv")
    log_file = log_path("consumer-roccv.log")
    src = os.path.join(HERE, "consumers", "roccv")
    env = customer_env()
    clang = os.path.join(ROCM, "lib", "llvm", "bin", "amdclang++")
    with open(log_file, "w", encoding="utf-8") as log:
        b = str(wd / "b_clang")
        rc, out = cmake_configure(src, b, [f"-DCMAKE_PREFIX_PATH={ROCM}", f"-DCMAKE_CXX_COMPILER={clang}"], env, log)
        rec(f"{g}::find-package", "pass" if rc == 0 else "fail",
            "find_package(roccv CONFIG) OK" if rc == 0 else first_error(out), log=log_file)
        if rc == 0:
            rc, out = cmake_build(b, env, log)
            rec(f"{g}::build", "pass" if rc == 0 else "fail", "builds with amdclang++" if rc == 0 else first_error(out),
                log=log_file)
        else:
            rec(f"{g}::build", "error", "not run: configure failed", log=log_file)
        gxx = shutil.which("g++")
        if not gxx:
            rec(f"{g}::build-gxx", "blocked", "g++ not installed")
        else:
            bg = str(wd / "b_gxx")
            grc, gout = cmake_configure(src, bg, [f"-DCMAKE_PREFIX_PATH={ROCM}", f"-DCMAKE_CXX_COMPILER={gxx}"], env,
                                        log)
            if grc == 0:
                grc, gout = cmake_build(bg, env, log)
            rec(f"{g}::build-gxx", "pass" if grc == 0 else "fail",
                "a g++ consumer of roccv::roccv builds" if grc == 0 else
                f"roccv::roccv forces HIP compile flags on a g++ consumer: {first_error(gout)}", log=log_file)
        expected = [f"{d}.flip{c}" for c in (1, 0, -1) for d in ("GPU", "CPU")] + ["GPU.launch-errors"]
        if rc != 0:
            for c in expected:
                rec(f"{g}::{c}", "error", "not run: consumer build failed", log=log_file)
            return
        which = "gpu,cpu" if GPU else "cpu"
        rrc, rout, dur = run([os.path.join(b, "roccv_consumer"), which], env=env, timeout=300, cwd=str(wd))
        log.write(f"== run {which} rc={rrc}\n{rout}\n")
        if not GPU:
            for c in expected:
                if c.startswith("GPU"):
                    rec(f"{g}::{c}", "blocked", NO_GPU, backend="GPU")
            expected = [c for c in expected if not c.startswith("GPU")]
        # CHECK names already carry the device ("GPU.flip1").
        ingest_checks(rec, g, "", expected, rrc, rout, log=log_file, backend="auto", duration=dur)


def find_package_only(rec: Recorder) -> None:
    clang = os.path.join(ROCM, "lib", "llvm", "bin", "amdclang++")
    cases = [("mivisionx", [f"-DVP_PREFIX={ROCM}"]), ("rocal", [f"-DVP_PREFIX={ROCM}", "-DVP_ROCAL_PREFIXED=ON"]),
             ("roccv", [f"-DCMAKE_PREFIX_PATH={ROCM}", f"-DCMAKE_CXX_COMPILER={clang}"])]
    log_file = log_path("consumer-find-package.log")
    with open(log_file, "w", encoding="utf-8") as log:
        for name, args in cases:
            rc, out = cmake_configure(os.path.join(HERE, "consumers", name), str(work_dir(name) / "b_fp"), args,
                                      customer_env(), log)
            rec(f"consumer.{name}::find-package", "pass" if rc == 0 else "fail",
                "configures" if rc == 0 else first_error(out), log=log_file)


def main(argv: list[str]) -> int:
    rec = Recorder()
    if "--find-package-only" in argv:
        find_package_only(rec)
        return 0
    which = argv or ["mivisionx", "rocal", "roccv"]
    for w in which:
        {"mivisionx": mivisionx, "rocal": rocal, "roccv": roccv}[w](rec)
    print(rec.counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
