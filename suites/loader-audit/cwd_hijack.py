#!/usr/bin/env python3
"""CWE-427 current-directory library hijack test.

Each shipped object is loaded (dlopen, or exec for executables) from a directory
planted with decoy libstdc++.so.6 / libm.so.6 / libgcc_s.so.1, in customer and
CI-parity mode, under LD_DEBUG=libs. An object is hijackable if the loader tries
a relative path (a CWD search: empty RUNPATH token or relative RUNPATH entry) or
a decoy constructor runs.

  cwd-hijack.control::empty-runpath     positive control, RUNPATH ":::"  -> must be caught
  cwd-hijack.control::relative-runpath  positive control, RUNPATH "."    -> must be caught
  cwd-hijack.control::origin-runpath    negative control, RUNPATH $ORIGIN -> must be safe
  cwd-hijack::<obj>                     shipped objects -> must be safe
If a positive control is not caught the harness cannot be trusted and the
object results are recorded as error.
"""
from __future__ import annotations

import glob
import os
import re
import shutil

from vp_owned import Recorder, customer_env, load_owned, log_path, parity_env, run, work_dir

HERE = os.path.dirname(os.path.abspath(__file__))
DECOYS = ("libstdc++.so.6", "libm.so.6", "libgcc_s.so.1")


def build(cc, args, log) -> bool:
    rc, out, _ = run([cc, *args], timeout=300)
    log.write(f"$ {cc} {' '.join(args)}\nrc={rc}\n{out}\n")
    return rc == 0


def main() -> int:
    rec = Recorder()
    owned = load_owned()
    wd = work_dir("cwd-hijack")
    plant, ctrl, dbg = wd / "plant", wd / "ctrl", wd / "ld_debug"
    for d in (plant, ctrl, dbg):
        d.mkdir(exist_ok=True)
    log_file = log_path("cwd-hijack.log")
    cc = shutil.which("cc") or shutil.which("gcc")
    controls = [("empty-runpath", ":::", True), ("relative-runpath", ".", True), ("origin-runpath", "$ORIGIN", False)]
    objects = owned["elfs"]
    if not cc:
        for name, _, _ in controls:
            rec(f"cwd-hijack.control::{name}", "blocked", "no C compiler (cc/gcc)")
        for e in objects:
            rec(f"cwd-hijack::{e['name']}", "blocked", "no C compiler (cc/gcc)")
        return 0

    with open(log_file, "w", encoding="utf-8") as log:
        ok = all(build(cc, ["-shared", "-fPIC", "-o", str(plant / n), f"-Wl,-soname,{n}", os.path.join(HERE, "decoy.c")],
                       log) for n in DECOYS)
        probe = str(wd / "dlopen_probe")
        ok = ok and build(cc, ["-o", probe, os.path.join(HERE, "dlopen_probe.c")], log)
        for name, rpath, _ in controls:
            ok = ok and build(cc, ["-shared", "-fPIC", "-o", str(ctrl / f"libvp_ctrl_{name}.so"),
                                   os.path.join(HERE, "ctrl_lib.c"), "-lm", "-Wl,--enable-new-dtags",
                                   f"-Wl,-rpath,{rpath}"], log)
        if not ok:
            for name, _, _ in controls:
                rec(f"cwd-hijack.control::{name}", "error", "could not build the controls/decoys", log=log_file)
            for e in objects:
                rec(f"cwd-hijack::{e['name']}", "error", "could not build the controls/decoys", log=log_file)
            return 0

        def probe_one(label: str, target: str, exe: bool) -> tuple[bool, str]:
            findings = []
            for mode, envf in (("customer", customer_env), ("ci-parity", parity_env)):
                tag = re.sub(r"[^A-Za-z0-9._-]", "_", f"{label}_{mode}")
                for old in glob.glob(str(dbg / f"{tag}.*")):
                    os.remove(old)
                env = envf(LD_DEBUG="libs", LD_DEBUG_OUTPUT=str(dbg / tag))
                cmd = [target] if exe else [probe, target, "lazy"]
                rc, out, _ = run(cmd, env=env, timeout=120, cwd=str(plant))
                trace = ""
                for f in glob.glob(str(dbg / f"{tag}.*")):
                    with open(f, encoding="utf-8", errors="replace") as fh:
                        trace += fh.read()
                    os.remove(f)
                rel = sorted({m.group(1) for m in re.finditer(r"trying file=([^/\s]\S*)", trace)})
                ctor = "CWD-HIJACK" in out
                log.write(f"== {label} [{mode}] rc={rc} ctor={ctor} relative={rel}\n{out[:800]}\n")
                if rel or ctor:
                    findings.append(f"{mode}: relative probes {' '.join(rel[:6])}" + ("; decoy ctor ran" if ctor else ""))
            return bool(findings), "; ".join(findings)

        trusted = True
        for name, rpath, expect in controls:
            hijacked, detail = probe_one(f"control_{name}", str(ctrl / f"libvp_ctrl_{name}.so"), False)
            good = hijacked == expect
            trusted &= good or not expect
            rec(f"cwd-hijack.control::{name}", "pass" if good else "fail",
                f"RUNPATH [{rpath}]: {'hijacked as expected' if hijacked and expect else 'safe as expected' if good else 'unexpected result'}"
                + (f" ({detail})" if detail else ""), log=log_file)

        for e in objects:
            hijacked, detail = probe_one(e["name"], e["path"], e["kind"] == "exe")
            if not trusted:
                rec(f"cwd-hijack::{e['name']}", "error", "positive control was not caught; result not trusted",
                    log=log_file)
            else:
                rec(f"cwd-hijack::{e['name']}", "fail" if hijacked else "pass",
                    detail if hijacked else "no current-directory probes in either loader mode", log=log_file)
    print(rec.counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
