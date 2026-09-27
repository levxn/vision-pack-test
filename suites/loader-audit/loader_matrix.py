#!/usr/bin/env python3
"""`ldd -r` on every shipped ELF object, customer mode and CI-parity mode.

Results (customer mode decides; the CI-parity run only classifies gaps):
  ldd.customer::<obj>   every DT_NEEDED resolves inside $ROCM_PATH (or to base
                        glibc/gcc libraries): no "not found", no host escape.
  ldd.undefined::<obj>  no undefined symbols attributed to the object itself.
                        Python extension modules may leave CPython (Py*/_Py*)
                        symbols to the interpreter; a plain library may not (H1).
"""
from __future__ import annotations

import json
import os
import re

from vp_owned import BASE_LIB_RE, ROCM, Recorder, customer_env, load_owned, log_path, parity_env, run

PY_SYM = re.compile(r"^_?Py")


def ldd(path: str, env: dict) -> dict:
    rc, out, dur = run(["ldd", "-r", path], env=env, timeout=180)
    deps, notfound, undef = {}, [], []
    for line in out.splitlines():
        line = line.strip()
        m = re.match(r"^undefined symbol: (\S+)\s+\((.*)\)", line)
        if m:
            undef.append((m.group(1), m.group(2)))
            continue
        m = re.match(r"^(\S+) => not found", line)
        if m:
            notfound.append(m.group(1))
            continue
        m = re.match(r"^(\S+) => (\S+) \(0x", line)
        if m:
            deps[m.group(1)] = m.group(2)
            continue
        m = re.match(r"^(/\S+) \(0x", line)
        if m:
            deps[os.path.basename(m.group(1))] = m.group(1)
    host = {}
    for so, p in deps.items():
        rp = os.path.realpath(p)
        if p.startswith(ROCM + "/") or rp.startswith(os.path.realpath(ROCM) + "/") or BASE_LIB_RE.match(so):
            continue
        host[so] = p
    return {"rc": rc, "notfound": sorted(set(notfound)), "host": host, "undefined": undef,
            "in_tree": sum(1 for p in deps.values() if p.startswith(ROCM + "/")), "raw": out, "seconds": dur}


def main() -> int:
    rec = Recorder()
    owned = load_owned()
    report = {}
    log = log_path("loader-matrix.log")
    with open(log, "w", encoding="utf-8") as lf:
        for e in owned["elfs"]:
            cust, par = ldd(e["path"], customer_env()), ldd(e["path"], parity_env())
            report[e["name"]] = {"customer": {k: v for k, v in cust.items() if k != "raw"},
                                 "ci_parity": {k: v for k, v in par.items() if k != "raw"}}
            lf.write(f"===== {e['name']} (customer)\n{cust['raw']}\n===== {e['name']} (ci-parity)\n{par['raw']}\n")

            problems = []
            if cust["notfound"]:
                problems.append(f"not found: {' '.join(cust['notfound'])}")
            if cust["host"]:
                problems.append("host escape: " + " ".join(f"{k}=>{v}" for k, v in cust["host"].items()))
            if cust["rc"] not in (0, 1) and not cust["raw"].strip():
                problems.append(f"ldd rc {cust['rc']}")
            if problems:
                par_bad = par["notfound"] or par["host"]
                cls = ("gap: resolves only with the CI LD_LIBRARY_PATH (RUNPATH does not cover it)" if not par_bad
                       else "fails in CI-parity mode too (not a RUNPATH gap)")
                rec(f"ldd.customer::{e['name']}", "fail", "; ".join(problems) + f" [{cls}]", log=log)
            else:
                rec(f"ldd.customer::{e['name']}", "pass",
                    f"{cust['in_tree']} deps in-tree, no host escape (CI-parity: "
                    f"{'clean' if not (par['notfound'] or par['host']) else 'differs'})", log=log)

            real = os.path.realpath(e["path"])
            own = [s for s, where in cust["undefined"] if os.path.realpath(where) == real]
            if e["kind"] == "pyext":
                own = [s for s in own if not PY_SYM.match(s)]
            if own:
                py = sum(1 for s in own if PY_SYM.match(s))
                rec(f"ldd.undefined::{e['name']}", "fail",
                    f"{len(own)} undefined symbol(s) ({py} CPython) and no provider in NEEDED, "
                    f"e.g. {' '.join(own[:6])}", log=log)
            else:
                rec(f"ldd.undefined::{e['name']}", "pass",
                    "no unresolved symbols" + (" (CPython symbols left to the interpreter)"
                                               if e["kind"] == "pyext" else ""), log=log)
    with open(os.path.join(os.environ["VP_OUT"], "raw", "loader_matrix.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(rec.counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
