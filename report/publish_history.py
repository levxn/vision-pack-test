#!/usr/bin/env python3
"""File one night into a checkout of the qa-history branch.

    publish_history.py --history history/ --triage triage.json --site site/ \
        --status status.json.gz [--perf perf.jsonl] [--issues-state issues-state.json] \
        [--summary summary.md] [--record-tested] [--event schedule] [--run-id N]

Layout of the branch (also the GitHub Pages site):

    index.html                   redirect to the latest night
    index.json                   one entry per night: verdict, counts, tier, gfx, dir
    tested.txt                   fingerprints of completed runs (resolve-release skips them)
    issues-state.json            regression-issue fingerprints and their green streaks
    perf/<gfx>.jsonl             per-night performance metrics
    nightly/YYYY-MM-DD/          scheduled nights: index.html, triage.json, status.json.gz, summary.md
    runs/<run_id>/               manually dispatched runs, same files

Pruning keeps the site well under the 1 GB Pages limit: triage.json for the
last 45 entries, status.json.gz for the last 14, index.html for the last 120;
index.json, summary.md and the perf history are kept for good.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

KEEP = {"triage.json": 45, "status.json.gz": 14, "index.html": 120}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", required=True)
    ap.add_argument("--triage", required=True)
    ap.add_argument("--site", required=True, help="directory with the rendered index.html")
    ap.add_argument("--status", required=True)
    ap.add_argument("--perf", default="")
    ap.add_argument("--issues-state", default="")
    ap.add_argument("--summary", default="")
    ap.add_argument("--record-tested", action="store_true")
    ap.add_argument("--event", default="schedule")
    ap.add_argument("--run-id", default="local")
    a = ap.parse_args()

    hist = Path(a.history)
    t = json.loads(Path(a.triage).read_text())
    night, run = t["night"], t["run"]
    rel = f"nightly/{night}" if a.event == "schedule" else f"runs/{a.run_id}"
    dest = hist / rel
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(a.site) / "index.html", dest / "index.html")
    shutil.copy(a.triage, dest / "triage.json")
    shutil.copy(a.status, dest / "status.json.gz")
    if a.summary:
        shutil.copy(a.summary, dest / "summary.md")

    idx_file = hist / "index.json"
    idx = json.loads(idx_file.read_text()) if idx_file.exists() else {"nights": []}
    idx["nights"] = [n for n in idx["nights"] if n.get("dir") != rel]
    idx["nights"].append({
        "night": night, "dir": rel, "event": a.event, "run_id": a.run_id, "tier": run["tier"], "gfx": run["gfx"],
        "verdict": t["verdict"], "tag": run["tag"], "version": run["version"], "sha": run["sha"],
        "fingerprint": run["fingerprint"], "counts": t["totals"]["by_class"], "records": t["totals"]["records"],
    })
    idx["nights"].sort(key=lambda n: (n["night"], str(n.get("run_id"))))
    idx_file.write_text(json.dumps(idx, indent=1) + "\n")

    if a.perf and Path(a.perf).exists() and Path(a.perf).stat().st_size:
        perf_dir = hist / "perf"
        perf_dir.mkdir(exist_ok=True)
        with open(perf_dir / f"{run['gfx'] or 'unknown'}.jsonl", "a", encoding="utf-8") as f:
            f.write(Path(a.perf).read_text())
    if a.issues_state and Path(a.issues_state).exists():
        shutil.copy(a.issues_state, hist / "issues-state.json")
    if a.record_tested and run.get("fingerprint"):
        with open(hist / "tested.txt", "a", encoding="utf-8") as f:
            f.write(f"{run['fingerprint']} {run['tag'] or run['sha'][:12]} {run['tier']} {night} {t['verdict']}\n")

    latest = next((n for n in reversed(idx["nights"]) if n["event"] == "schedule"), idx["nights"][-1])
    (hist / "index.html").write_text(
        "<!DOCTYPE html><meta charset=\"utf-8\"><title>vision-pack nightly QA</title>"
        f"<meta http-equiv=\"refresh\" content=\"0; url={latest['dir']}/index.html\">"
        f"<a href=\"{latest['dir']}/index.html\">Latest report ({latest['night']})</a>\n")
    (hist / ".nojekyll").touch()

    dirs = [hist / n["dir"] for n in reversed(idx["nights"])]
    for name, keep in KEEP.items():
        for d in dirs[keep:]:
            (d / name).unlink(missing_ok=True)
    print(f"filed {rel} ({t['verdict']}); {len(idx['nights'])} entries in index.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
