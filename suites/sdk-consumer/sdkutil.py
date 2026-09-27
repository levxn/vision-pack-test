"""Helpers for the sdk-consumer harnesses.

Reuses suites/loader-audit/vp_owned.py (payload ownership, ELF parsing, result
records) so both suites classify the same files the same way.
"""
from __future__ import annotations

import os
import re
import shutil
import sys

sys.path.insert(0, os.path.join(os.environ["VP_REPO"], "suites", "loader-audit"))

from vp_owned import (  # noqa: E402,F401  (re-exported for the harnesses)
    ROCM,
    Recorder,
    crashed,
    customer_env,
    load_manifest,
    log_path,
    run,
    tier_ge,
    work_dir,
)

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK_RE = re.compile(r"^CHECK (\S+) (PASS|FAIL) ?(.*)$", re.M)


def jobs() -> str:
    return os.environ.get("VP_BUILD_JOBS") or str(max(1, (os.cpu_count() or 2)))


def generator() -> list[str]:
    return ["-G", "Ninja"] if shutil.which("ninja") else []


def cmake_configure(src: str, build: str, args: list[str], env: dict, log) -> tuple[int, str]:
    shutil.rmtree(build, ignore_errors=True)
    cmd = ["cmake", "-S", src, "-B", build, *generator(), "-DCMAKE_BUILD_TYPE=Release", *args]
    rc, out, _ = run(cmd, env=env, timeout=900)
    log.write(f"$ {' '.join(cmd)}\nrc={rc}\n{out}\n")
    return rc, out


def cmake_build(build: str, env: dict, log) -> tuple[int, str]:
    cmd = ["cmake", "--build", build, "--parallel", jobs()]
    rc, out, _ = run(cmd, env=env, timeout=3600)
    log.write(f"$ {' '.join(cmd)}\nrc={rc}\n{out}\n")
    return rc, out


def first_error(text: str) -> str:
    for ln in text.splitlines():
        if re.search(r"(fatal error|error:|undefined reference|CMake Error|Could not find|Could NOT find)", ln):
            return ln.strip()[:400]
    return (text.strip().splitlines() or [""])[-1][:400]


def ingest_checks(rec: Recorder, group: str, prefix: str, expected: list[str], rc: int, out: str, *, log: str,
                  backend: str, duration: float = 0.0) -> dict[str, bool]:
    """Record CHECK lines as <group>::<prefix>.<name> (<group>::<name> with an empty
    prefix; backend "auto" takes the part before the first dot of the name).
    Expected checks the program never printed become errors (crash, timeout or
    early exit)."""
    def tid(name: str) -> str:
        return f"{group}::{prefix}.{name}" if prefix else f"{group}::{name}"

    def be(name: str) -> str:
        return name.split(".")[0] if backend == "auto" else backend

    seen: dict[str, bool] = {}
    for name, verdict, detail in CHECK_RE.findall(out):
        seen[name] = verdict == "PASS"
        rec(tid(name), "pass" if verdict == "PASS" else "fail", detail, log=log, backend=be(name), duration=duration)
    for name in expected:
        if name not in seen:
            why = "timeout" if rc == 124 else f"killed by signal {-rc}" if rc < 0 else f"exited {rc}"
            rec(tid(name), "error", f"check never reported ({why}): {first_error(out)}", log=log, backend=be(name))
    return seen
