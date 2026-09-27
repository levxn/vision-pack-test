#!/usr/bin/env python3
"""Merge the per-suite result directories of one nightly run.

Each suite job uploads an artifact ``results-<suite>`` containing
``results.jsonl``, ``suite.json``, ``junit/``, ``logs/`` and ``perf/``. After
``actions/download-artifact`` they sit side by side under one directory. This
script collects them into a single ``merged/`` view used by report/triage.py:

    merged/results.jsonl     every record, de-duplicated by id (last one wins)
    merged/suites.json       per-suite metadata; several result directories of
                             one suite (the hosted packaging jobs) are combined
    merged/environment.json  runner, SDK, images, pre-flight (results-environment)
    merged/perf/<suite>__<name>.json

It adds synthetic ``error`` records so infrastructure problems always show:
``<suite>::infra::no-results`` for an expected suite without results,
``<suite>::infra::runner`` when the CI step reported a non-zero exit
(runner-status.json: container failure, time budget), and
``preflight::infra::gpu-preflight`` when the GPU pre-flight failed.

    merge.py --results downloaded/ --out merged/ [--expect packaging,rocal,...]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from emit import make_record, read_records  # noqa: E402

ENV_FILES = ("environment.json", "prepared.json", "manifest.json", "preflight.json")


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _combine(old: dict, new: dict) -> dict:
    """Combine two suite.json of the same suite (e.g. packaging-deb + -rpm)."""
    out = dict(old)
    out["result_dirs"] = sorted(set(old.get("result_dirs", [])) | set(new.get("result_dirs", [])))
    out["wall_seconds"] = old.get("wall_seconds", 0) + new.get("wall_seconds", 0)
    out["total"] = old.get("total", 0) + new.get("total", 0)
    counts = dict(old.get("counts", {}))
    for k, v in new.get("counts", {}).items():
        counts[k] = counts.get(k, 0) + v
    out["counts"] = counts
    return out


def merge(root: Path, out: Path, expect: list[str]) -> dict:
    (out / "perf").mkdir(parents=True, exist_ok=True)
    records: dict[str, dict] = {}
    suites: dict[str, dict] = {}
    environment: dict = {}

    for jsonl in sorted(root.rglob("results.jsonl")):
        if out in jsonl.parents:
            continue
        sdir = jsonl.parent
        meta = _load(sdir / "suite.json")
        recs = read_records(jsonl)
        suite = meta.get("suite") or (recs[0]["suite"] if recs else sdir.name)
        rel = str(sdir.relative_to(root))
        meta.update({"suite": suite, "result_dirs": [rel]})
        suites[suite] = _combine(suites[suite], meta) if suite in suites else meta
        for r in recs:
            r["result_dir"] = rel
            records[r["id"]] = r
        if (sdir / "perf").is_dir():
            for pf in sorted((sdir / "perf").glob("*.json")):
                shutil.copy(pf, out / "perf" / f"{suite}__{pf.name}")

    for status in sorted(root.rglob("runner-status.json")):
        st = _load(status)
        if st.get("rc", 0) != 0:
            suite = st.get("suite") or status.parent.name
            rec = make_record(suite, f"{suite}::infra::runner", "error",
                              message=f"the CI step {st.get('reason', 'failed')}; results may be partial")
            records[rec["id"]] = rec
            suites.setdefault(suite, {"suite": suite, "result_dirs": []})["runner"] = st

    # results-environment holds environment/ and preflight/ (test.yml); files of
    # the same name inside suite result directories are not the run's.
    for name in ENV_FILES:
        for f in sorted(root.rglob(name)):
            if out in f.parents or f.parent.name not in ("environment", "preflight"):
                continue
            environment[name.removesuffix(".json")] = _load(f)
    pre = environment.get("preflight")
    if pre is not None and not pre.get("ok", False):
        rec = make_record("preflight", "preflight::infra::gpu-preflight", "error",
                          message=f"GPU pre-flight failed: {pre.get('reason', 'unknown')}")
        records[rec["id"]] = rec

    for suite in expect:
        if suite not in suites:
            rec = make_record(suite, f"{suite}::infra::no-results", "error",
                              message="the suite job produced no results (job failed, timed out or was cancelled)")
            records[rec["id"]] = rec
            suites[suite] = {"suite": suite, "missing": True, "result_dirs": []}

    with open(out / "results.jsonl", "w", encoding="utf-8") as f:
        for r in records.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "suites.json").write_text(json.dumps(suites, indent=2) + "\n", encoding="utf-8")
    (out / "environment.json").write_text(json.dumps(environment, indent=2) + "\n", encoding="utf-8")
    return {"records": len(records), "suites": len(suites)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True, help="directory containing the downloaded suite outputs")
    ap.add_argument("--out", required=True)
    ap.add_argument("--expect", default="", help="comma-separated suites that must have produced results")
    a = ap.parse_args()
    expect = [s.strip() for s in a.expect.split(",") if s.strip()]
    stats = merge(Path(a.results), Path(a.out), expect)
    print(f"merged {stats['records']} records from {stats['suites']} suites into {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
