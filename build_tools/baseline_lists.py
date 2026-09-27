#!/usr/bin/env python3
"""Write the exact failing result IDs of one night as a baseline match_file.

    baseline_lists.py --results merged/results.jsonl --group 'cts.*.optional' \
        [--name-contains VX_BORDER] [--exclude-name GLOB]... [--also-failing-in GROUP] \
        --out baselines/lists/M17-cts-optional-borders.txt --why "M17: border modes ignored"

For findings that cover many parameterised results (the CTS optional tests, the
vision-node runs), a glob would also cover passing siblings and report them as
"fixed" every night. This takes the failing (fail/error) IDs of a trusted night
instead. Re-run it when upstream legitimately changes the set, and review the
diff like any other baseline change.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import re
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", required=True, nargs="+")
    ap.add_argument("--suite", default="mivisionx")
    ap.add_argument("--group", required=True, help="glob over the group component")
    ap.add_argument("--name-contains", default="")
    ap.add_argument("--message-regex", default="",
                    help="keep only failures whose message matches (attributes plain-named results to a cause)")
    ap.add_argument("--statuses", default="fail,error",
                    help="statuses to collect (e.g. 'blocked' for a kind: skip entry)")
    ap.add_argument("--exclude-name", action="append", default=[], help="glob over the name component")
    ap.add_argument("--also-failing-in", default="",
                    help="keep only names that also fail in this group of the same target "
                         "(the target is the part of the group after the first dot, e.g. vision.CPU.1080p)")
    ap.add_argument("--exclude-list", action="append", default=[], help="IDs already covered by another list")
    ap.add_argument("--out", required=True)
    ap.add_argument("--why", required=True)
    a = ap.parse_args()

    recs = []
    for f in a.results:
        recs += [json.loads(line) for line in Path(f).read_text().splitlines() if line.strip()]
    statuses = {s.strip() for s in a.statuses.split(",") if s.strip()}
    failing = {r["id"] for r in recs if r["status"] in statuses}
    messages = {r["id"]: r.get("message") or "" for r in recs}
    msg_re = re.compile(a.message_regex) if a.message_regex else None
    excluded = set()
    for f in a.exclude_list:
        excluded |= {ln.strip() for ln in Path(f).read_text().splitlines() if ln.strip() and not ln.startswith("#")}

    def parts(rid: str) -> tuple[str, str, str]:
        s, g, n = (rid.split("::", 2) + ["", ""])[:3]
        return s, g, n

    out = []
    for rid in sorted(failing):
        s, g, n = parts(rid)
        if s != a.suite or not fnmatch.fnmatchcase(g, a.group) or rid in excluded:
            continue
        if a.name_contains and a.name_contains not in n:
            continue
        if msg_re and not msg_re.search(messages.get(rid, "")):
            continue
        if any(fnmatch.fnmatchcase(n, x) for x in a.exclude_name):
            continue
        if a.also_failing_in:
            target = g.split(".")[1] if "." in g else ""
            ref = a.also_failing_in.replace("{target}", target)
            if f"{s}::{ref}::{n}" not in failing:
                continue
        out.append(rid)

    header = [f"# {a.why}",
              f"# Generated {dt.date.today().isoformat()} by build_tools/baseline_lists.py from "
              f"{', '.join(Path(f).name for f in a.results)}; {len(out)} IDs.",
              f"# group={a.group} name-contains={a.name_contains or '-'} exclude-name={a.exclude_name or '-'}"
              f" also-failing-in={a.also_failing_in or '-'} message-regex={a.message_regex or '-'}"]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(header + out) + "\n")
    print(f"wrote {len(out)} IDs to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
