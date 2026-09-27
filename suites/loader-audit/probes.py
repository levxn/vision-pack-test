#!/usr/bin/env python3
"""Runtime loader probes from a plain C process (no Python in the process).

  dlopen::<lib>        dlopen(RTLD_NOW|RTLD_LOCAL) of each shipped shared library,
                       customer mode; a failure is re-run in CI-parity mode to
                       classify it. (Extension modules are covered by py-import.)
  exec::bin/runvx      runvx starts and prints its usage banner.
  link::<lib>-c-consumer       `cc main.c -l<lib>` links (openvx and roccv are
                               positive controls; rocal fails: H1).
  link::rocal-c-consumer-run   forced link (--allow-shlib-undefined), then run:
                               H1 makes it die at startup.
  link::rocal-c-consumer-libpython  the documented workaround (link libpython).
"""
from __future__ import annotations

import os
import shutil

from vp_owned import ROCM, Recorder, crashed, customer_env, load_owned, log_path, parity_env, run, work_dir

HERE = os.path.dirname(os.path.abspath(__file__))


def compile_c(cc: str, src: str, out: str, extra: list[str], log) -> tuple[int, str]:
    cmd = [cc, "-O1", "-o", out, src, *extra]
    rc, text, _ = run(cmd, timeout=300)
    log.write(f"$ {' '.join(cmd)}\n{text}\nrc={rc}\n")
    return rc, text


def main() -> int:
    rec = Recorder()
    owned = load_owned()
    wd = work_dir("probes")
    log_file = log_path("probes.log")
    cc = shutil.which("cc") or shutil.which("gcc")
    libs = [e for e in owned["elfs"] if e["kind"] == "lib"]
    exes = [e for e in owned["elfs"] if e["kind"] == "exe"]

    with open(log_file, "w", encoding="utf-8") as log:
        probe = str(wd / "dlopen_probe")
        if not cc:
            for e in libs:
                rec(f"dlopen::{e['name']}", "blocked", "no C compiler (cc/gcc) in the image")
        elif compile_c(cc, os.path.join(HERE, "dlopen_probe.c"), probe, [], log)[0] != 0:
            for e in libs:
                rec(f"dlopen::{e['name']}", "error", "could not build dlopen_probe.c", log=log_file)
        else:
            for e in libs:
                rc, out, dur = run([probe, e["path"], "now"], env=customer_env(), timeout=120, cwd=str(wd))
                log.write(f"== dlopen {e['name']} customer rc={rc}\n{out}\n")
                if rc == 0 and "DLOPEN_OK" in out:
                    rec(f"dlopen::{e['name']}", "pass", "RTLD_NOW OK (customer mode)", log=log_file, duration=dur)
                    continue
                prc, pout, _ = run([probe, e["path"], "now"], env=parity_env(), timeout=120, cwd=str(wd))
                log.write(f"== dlopen {e['name']} ci-parity rc={prc}\n{pout}\n")
                cls = ("passes with the CI LD_LIBRARY_PATH: RUNPATH gap" if prc == 0
                       else "also fails with the CI LD_LIBRARY_PATH: not a search-path problem")
                status = "error" if crashed(rc) else "fail"
                rec(f"dlopen::{e['name']}", status, f"{out.strip()[:600]} [{cls}]", log=log_file, duration=dur,
                    repro=f"env -u LD_LIBRARY_PATH dlopen_probe {e['path']} now")

        for e in exes:
            rc, out, dur = run([e["path"]], env=customer_env(), timeout=60, cwd=str(wd))
            log.write(f"== exec {e['name']} rc={rc}\n{out}\n")
            if "error while loading shared libraries" in out or crashed(rc):
                rec(f"exec::{e['name']}", "error" if crashed(rc) else "fail",
                    f"rc={rc}: {out.strip()[:500]}", log=log_file, duration=dur)
            elif "Usage" in out:
                rec(f"exec::{e['name']}", "pass", f"starts and prints usage (rc={rc})", log=log_file, duration=dur)
            else:
                rec(f"exec::{e['name']}", "fail", f"rc={rc}, no usage banner: {out.strip()[:300]}",
                    log=log_file, duration=dur)

        # --- link probes ---
        src = os.path.join(HERE, "link_consumer.c")
        link_ids = ["openvx-c-consumer", "roccv-c-consumer", "rocal-c-consumer", "rocal-c-consumer-run",
                    "rocal-c-consumer-libpython"]
        if not cc:
            for i in link_ids:
                rec(f"link::{i}", "blocked", "no C compiler (cc/gcc) in the image")
            return 0
        base = ["-Wl,--no-as-needed", f"-L{ROCM}/lib", f"-Wl,-rpath,{ROCM}/lib"]

        def link_and_run(test_id: str, lib: str, extra: list[str] | None = None, run_it: bool = True):
            out_bin = str(wd / f"link_{test_id}")
            rc, text = compile_c(cc, src, out_bin, [*base, f"-l{lib}", *(extra or [])], log)
            if rc != 0:
                undef = sum(1 for ln in text.splitlines() if "undefined reference" in ln)
                first = next((ln for ln in text.splitlines() if "undefined reference" in ln or "error" in ln), "")
                rec(f"link::{test_id}", "fail",
                    f"link failed ({undef} undefined reference(s)); first: {first.strip()[:300]}", log=log_file)
                return
            if not run_it:
                rec(f"link::{test_id}", "pass", "links", log=log_file)
                return
            rrc, rout, dur = run([out_bin], env=customer_env(), timeout=120, cwd=str(wd))
            log.write(f"== run {test_id} rc={rrc}\n{rout}\n")
            if rrc == 0 and "LINKED_START_OK" in rout:
                rec(f"link::{test_id}", "pass", "links and starts (customer mode)", log=log_file, duration=dur)
            else:
                rec(f"link::{test_id}", "error" if crashed(rrc) else "fail",
                    f"linked, but startup failed rc={rrc}: {rout.strip()[:400]}", log=log_file, duration=dur)

        link_and_run("openvx-c-consumer", "openvx")
        link_and_run("roccv-c-consumer", "roccv")
        link_and_run("rocal-c-consumer", "rocal")
        link_and_run("rocal-c-consumer-run", "rocal", ["-Wl,--allow-shlib-undefined"])

        py = os.environ.get("VP_PY", "python3")
        rc, out, _ = run([py, "-c", "import sysconfig as s; print(s.get_config_var('LIBDIR')); "
                                    "print(s.get_config_var('LDLIBRARY'))"], timeout=60)
        lines = out.split()
        libdir, ldlib = (lines + ["", ""])[:2]
        if rc != 0 or not ldlib.endswith(".so") or not os.path.exists(os.path.join(libdir, ldlib)):
            rec("link::rocal-c-consumer-libpython", "blocked",
                f"no shared libpython for {py} (install python3-dev): LIBDIR={libdir} LDLIBRARY={ldlib}")
        else:
            name = ldlib[3:-3]
            link_and_run("rocal-c-consumer-libpython", "rocal", [f"-L{libdir}", f"-l{name}"])
    print(rec.counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
