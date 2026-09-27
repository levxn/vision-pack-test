#!/usr/bin/env python3
"""Validate the known-issue baseline (and the expected-count floors).

    lint_known_issues.py baselines/known_issues.yaml [--expected baselines/expected_counts.yaml]
        [--suites suites/suites.yaml] [--today YYYY-MM-DD]

Fails on schema errors, duplicate IDs, match globs whose suite does not
exist, and entries whose review_by date has passed: an expired entry must be
re-verified (extend review_by, link the upstream issue) or removed, so the
baseline cannot silently hide a bug forever.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
TIERS = {"quick", "standard", "comprehensive", "full"}
SEVERITIES = {"critical", "high", "medium", "low"}
KINDS = {"xfail", "flaky", "skip", "quarantine"}
REQUIRED = ("id", "title", "severity", "owner", "kind", "added", "review_by")
OPTIONAL = {"match", "match_file", "gfx", "tiers", "issue", "strict", "notes", "evidence"}
ID_RE = re.compile(r"^[A-Z][A-Za-z0-9.-]*$")
# Suites that exist only as synthetic records (merge.py / report.yml).
SYNTHETIC_SUITES = {"orchestrator", "preflight"}


def as_date(v) -> dt.date | None:
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v))
    except ValueError:
        return None


def _check_glob(where: str, m, suites: set[str], errors: list[str]) -> None:
    suite = str(m).split("::", 1)[0]
    if "::" not in str(m) or ("*" not in suite and suite not in suites):
        errors.append(f"{where}: glob {m!r} must start with a suite name from suites.yaml and '::'")


def lint_known(doc: dict, suites: set[str], today: dt.date, base: Path | None = None) -> list[str]:
    errors = []
    base = base or REPO / "baselines"
    if doc.get("schema") != 1:
        errors.append("known_issues.yaml: 'schema: 1' is required")
    seen = set()
    for n, e in enumerate(doc.get("issues") or []):
        where = f"issues[{n}] ({e.get('id', '?')})"
        missing = [k for k in REQUIRED if k not in e]
        if "match" not in e and "match_file" not in e:
            missing.append("match or match_file")
        if missing:
            errors.append(f"{where}: missing {', '.join(missing)}")
            continue
        if "match_file" in e:
            f = base / str(e["match_file"])
            if not f.is_file():
                errors.append(f"{where}: match_file {e['match_file']} not found next to known_issues.yaml")
            else:
                lines = [ln.strip() for ln in f.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
                if not lines:
                    errors.append(f"{where}: match_file {e['match_file']} is empty")
                for ln in lines[:1] + lines[-1:]:
                    _check_glob(f"{where} ({e['match_file']})", ln, suites, errors)
        unknown = set(e) - set(REQUIRED) - OPTIONAL
        if unknown:
            errors.append(f"{where}: unknown keys {sorted(unknown)}")
        if not ID_RE.match(str(e["id"])):
            errors.append(f"{where}: id must look like C1, H12, M3, N2 or L-name")
        if e["id"] in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(e["id"])
        if str(e["severity"]).lower() not in SEVERITIES:
            errors.append(f"{where}: severity must be one of {sorted(SEVERITIES)}")
        if e["kind"] not in KINDS:
            errors.append(f"{where}: kind must be one of {sorted(KINDS)}")
        if "match" in e:
            if not isinstance(e["match"], list) or not e["match"]:
                errors.append(f"{where}: match must be a non-empty list of result-ID globs")
            else:
                for m in e["match"]:
                    _check_glob(where, m, suites, errors)
        added, review = as_date(e["added"]), as_date(e["review_by"])
        if added is None or review is None:
            errors.append(f"{where}: added and review_by must be YYYY-MM-DD dates")
        else:
            if review < added:
                errors.append(f"{where}: review_by {review} is before added {added}")
            if review < today:
                errors.append(f"{where}: review_by {review} has passed; re-verify the finding and extend "
                              "review_by (with an upstream issue link), or remove the entry")
        if "tiers" in e and not set(e["tiers"]) <= TIERS:
            errors.append(f"{where}: tiers must be a subset of {sorted(TIERS)}")
        if "gfx" in e and not (isinstance(e["gfx"], list) and all(isinstance(g, str) for g in e["gfx"])):
            errors.append(f"{where}: gfx must be a list of globs such as gfx1201 or gfx12*")
        if e.get("issue") and not str(e["issue"]).startswith("https://"):
            errors.append(f"{where}: issue must be an https URL (or empty)")
        if "strict" in e and not isinstance(e["strict"], bool):
            errors.append(f"{where}: strict must be true or false")
    return errors


def lint_expected(doc: dict, suites: set[str]) -> list[str]:
    errors = []
    if doc.get("schema") != 1:
        errors.append("expected_counts.yaml: 'schema: 1' is required")
    for n, c in enumerate(doc.get("counts") or []):
        where = f"counts[{n}] ({c.get('suite', '?')}::{c.get('group', '?')})"
        if c.get("suite") not in suites:
            errors.append(f"{where}: unknown suite")
        if not isinstance(c.get("group"), str) or not c.get("group"):
            errors.append(f"{where}: group must be a glob over the second ID component")
        if not isinstance(c.get("min"), int) or c["min"] < 0:
            errors.append(f"{where}: min must be a non-negative integer")
        if "tiers" in c and not set(c["tiers"]) <= TIERS:
            errors.append(f"{where}: tiers must be a subset of {sorted(TIERS)}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("known")
    ap.add_argument("--expected", default="")
    ap.add_argument("--suites", default=str(REPO / "suites" / "suites.yaml"))
    ap.add_argument("--today", default="")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(dt.timezone.utc).date()
    suites = set(yaml.safe_load(Path(a.suites).read_text())["suites"]) | SYNTHETIC_SUITES

    errors = lint_known(yaml.safe_load(Path(a.known).read_text()) or {}, suites, today, Path(a.known).resolve().parent)
    if a.expected:
        errors += lint_expected(yaml.safe_load(Path(a.expected).read_text()) or {}, suites)
    for err in errors:
        print(f"::error::{err}")
    if errors:
        print(f"{len(errors)} problem(s)", file=sys.stderr)
        return 1
    print("baselines ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
