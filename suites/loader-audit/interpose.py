#!/usr/bin/env python3
"""Symbol-level isolation of the bundled third-party libraries (finding M1).

vision-pack renames the bundled sysdeps to *-rocm-vision SONAMEs, which stops a
host copy from being *loaded* instead, but not from being *bound to*: the symbol
names are unversioned or keep upstream version nodes. Here the host copies
(Ubuntu libjpeg-turbo8, liblmdb0, libprotobuf32t64, libsndfile1, libturbojpeg)
are dlopen'ed RTLD_GLOBAL first, then rocal_pybind (which loads librocal) is
imported with LD_BIND_NOW=1 and LD_DEBUG=bindings; every binding made from
librocal is attributed to the isolated or the host copy. Python is required
because librocal only loads inside an interpreter (H1).

  interpose.control::no-host-libs   without host libs, all librocal bindings for the
                                    bundled deps go to the *-rocm-vision copies
  interpose::<dep>                  with host libs loaded first, librocal still binds
                                    to its bundled copy (fails today: M1)
"""
from __future__ import annotations

import collections
import glob
import json
import os
import re

from vp_owned import Recorder, customer_env, log_path, run, work_dir

HOST = {  # test name -> (host SONAME, filename marker of the library that provides the symbols)
    "libjpeg": ("libjpeg.so.8", "libjpeg"),
    "lmdb": ("liblmdb.so.0", "liblmdb"),
    "protobuf": ("libprotobuf.so.32", "libprotobuf"),
    "libsndfile": ("libsndfile.so.1", "libsndfile"),
    "libturbojpeg": ("libturbojpeg.so.0", "libturbojpeg"),
}
CHILD = r"""
import ctypes, os, sys
for so in sys.argv[1:]:
    ctypes.CDLL(so, mode=ctypes.RTLD_GLOBAL)
import rocal_pybind
for line in open('/proc/self/maps'):
    p = line.split()[-1]
    if p.startswith('/') and ('rocm-vision' in p or 'librocal' in p or any(s.split('.so')[0] in p for s in sys.argv[1:])):
        print('MAPPED', p)
print('IMPORT_OK', rocal_pybind.__file__)
"""
BIND = re.compile(r"binding file (\S+) \[\d+\] to (\S+) \[\d+\]: normal symbol `([^']+)'")


def available(soname: str, wd: str) -> str:
    rc, out, _ = run([os.environ.get("VP_PY", "python3"), "-c",
                      "import ctypes,sys; ctypes.CDLL(sys.argv[1]); "
                      "print(next(l.split()[-1] for l in open('/proc/self/maps') if sys.argv[1].split('.so')[0] in l))",
                      soname], env=customer_env(), timeout=60, cwd=wd)
    return out.strip().splitlines()[-1] if rc == 0 and out.strip() else ""


def bindings(tag: str, preload: list[str], wd: str, log) -> tuple[int, dict, str]:
    dbg = os.path.join(wd, f"bind_{tag}")
    for old in glob.glob(dbg + ".*"):
        os.remove(old)
    env = customer_env(LD_BIND_NOW="1", LD_DEBUG="bindings", LD_DEBUG_OUTPUT=dbg)
    rc, out, _ = run([os.environ.get("VP_PY", "python3"), "-c", CHILD, *preload], env=env, timeout=300, cwd=wd)
    log.write(f"== run {tag} preload={preload} rc={rc}\n{out[-3000:]}\n")
    per_dep: dict[str, collections.Counter] = {k: collections.Counter() for k in HOST}
    examples: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for f in glob.glob(dbg + ".*"):
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = BIND.search(line)
                if not m or "librocal.so" not in os.path.basename(m.group(1)):
                    continue
                dst, sym = m.group(2), m.group(3)
                base = os.path.basename(dst)
                for dep, (_so, marker) in HOST.items():
                    if base.startswith(marker + ".") or base.startswith(marker + "-rocm-vision"):
                        side = "isolated" if "rocm-vision" in base else "host"
                        per_dep[dep][side] += 1
                        if len(examples[(dep, side)]) < 3:
                            examples[(dep, side)].append(f"{sym}->{base}")
        os.remove(f)
    summary = {d: dict(c) for d, c in per_dep.items()}
    log.write(f"   bindings from librocal: {json.dumps(summary)}\n")
    ex = {f"{d}/{s}": v for (d, s), v in examples.items()}
    return rc, summary, json.dumps(ex)


def main() -> int:
    rec = Recorder()
    wd = str(work_dir("interpose"))
    log_file = log_path("interpose.log")
    with open(log_file, "w", encoding="utf-8") as log:
        rc, ctrl, _ = bindings("control", [], wd, log)
        ctrl_ok = rc == 0 and all(ctrl[d].get("host", 0) == 0 for d in HOST) and \
            sum(ctrl[d].get("isolated", 0) for d in HOST) > 0
        rec("interpose.control::no-host-libs", "pass" if ctrl_ok else ("error" if rc else "fail"),
            f"import rc={rc}; librocal bindings: " + ", ".join(f"{d}={ctrl[d]}" for d in HOST), log=log_file)

        paths = {dep: available(so, wd) for dep, (so, _m) in HOST.items()}
        log.write(f"host libraries: {paths}\n")
        present = [HOST[d][0] for d in HOST if paths[d]]
        rc, res, examples = bindings("host", present, wd, log) if present else (0, {}, "{}")
        log.write(f"examples: {examples}\n")
        for dep, (so, _m) in HOST.items():
            tid = f"interpose::{dep}"
            if not paths[dep]:
                rec(tid, "blocked", f"host {so} not installed in the image")
            elif not ctrl_ok or rc != 0:
                rec(tid, "error", f"cannot attribute bindings (control ok={ctrl_ok}, host run rc={rc})", log=log_file)
            elif ctrl[dep].get("isolated", 0) == 0:
                rec(tid, "skip", f"librocal makes no {dep} bindings at load time (nothing to interpose)")
            else:
                host_n, iso_n = res[dep].get("host", 0), res[dep].get("isolated", 0)
                rec(tid, "fail" if host_n else "pass",
                    f"with host {paths[dep]} loaded RTLD_GLOBAL first: {host_n} librocal binding(s) go to the host "
                    f"copy, {iso_n} to the bundled copy" if host_n else
                    f"all {iso_n} librocal binding(s) stay on the bundled copy despite host {paths[dep]}",
                    log=log_file)
    print(rec.counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
