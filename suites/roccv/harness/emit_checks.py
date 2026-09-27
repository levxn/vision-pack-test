"""Turn "@@VPCHECK<TAB>group<TAB>name<TAB>status<TAB>message" lines (C++ probes) into result records.

    emit_checks.py <log> [--expect group::name ...]

Expected checks that never printed a line (the probe crashed first) are recorded as error.
"""
from __future__ import annotations

import sys

from common import record, summary


def main():
    log, expect = sys.argv[1], []
    if "--expect" in sys.argv:
        expect = sys.argv[sys.argv.index("--expect") + 1:]
    seen = set()
    for line in open(log, encoding="utf-8", errors="replace"):
        if not line.startswith("@@VPCHECK\t"):
            continue
        parts = line.rstrip("\n").split("\t")
        _, group, name, status = parts[:4]
        msg = parts[4] if len(parts) > 4 else ""
        if status not in ("pass", "fail", "error", "skip"):
            status, msg = "error", f"bad status {status!r}: {msg}"
        record(group, name, status, msg, backend="GPU" if name.endswith("GPU") else "CPU" if name.endswith("CPU") else "")
        seen.add(f"{group}::{name}")
    for e in expect:
        if e not in seen:
            group, name = e.split("::", 1)
            record(group, name, "error", f"the probe ended before reporting this check (see {log.rsplit('/', 1)[-1]})")
    summary()


if __name__ == "__main__":
    main()
