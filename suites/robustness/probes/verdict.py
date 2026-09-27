"""Shared verdict logic for the robustness probes.

A probe observes one outcome and the caller chooses what is acceptable:

  outcome  correct       the operation completed and its output matches the reference
           wrong         the operation reported success but the output is wrong (silent failure)
           clean_error   the operation reported an error (exception or non-zero status) and exited normally
           exit0_error   the library reported an error but terminated the process with status 0
  mode     correct       only "correct" passes (supported device, CPU paths)
           honest        "correct" or "clean_error" passes (unsupported GPU: work or say so)
           error         only "clean_error" passes (a backend that cannot exist here must refuse)

Probe exit status: 0 pass, 1 fail, 70 a child process crashed (checked_run.py --error-rc 70 maps it to error).
"""
from __future__ import annotations

import sys

ACCEPT = {
    "correct": {"correct"},
    "honest": {"correct", "clean_error"},
    "error": {"clean_error"},
}
CRASH_RC = 70


def finish(mode: str, outcome: str, detail: str = "") -> None:
    ok = outcome in ACCEPT[mode]
    print(f"OUTCOME: {outcome}{(' - ' + detail) if detail else ''}", flush=True)
    print(f"VERDICT: {'PASS' if ok else 'FAIL'} (mode={mode}, accepted={sorted(ACCEPT[mode])})", flush=True)
    sys.exit(0 if ok else 1)


def crashed(detail: str) -> None:
    print(f"OUTCOME: crash - {detail}", flush=True)
    sys.exit(CRASH_RC)
