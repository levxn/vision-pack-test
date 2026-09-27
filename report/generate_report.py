#!/usr/bin/env python3
"""Render the nightly HTML report from triage.json.

    generate_report.py --triage triage.json --site site/ [--max-items 4000]

Writes site/index.html (report/template.html with the data embedded) and
site/triage.json. The page is self-contained (no network requests), so it
works from GitHub Pages, from a downloaded artifact, or opened locally.
Only non-passing results are embedded; passing tests appear as per-group
counts, which keeps a night's page small even with ~35,000 results.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLACEHOLDER = "/*__REPORT_DATA__*/null"
CLASS_ORDER = ["infra_error", "new_failure", "still_failing", "flaky", "fixed", "known_fail", "known_flaky",
               "blocked", "known_blocked", "quarantined", "skip"]


def compact(triage: dict, max_items: int) -> dict:
    data = dict(triage)
    items = sorted(triage.get("items", []),
                   key=lambda i: (CLASS_ORDER.index(i["class"]) if i["class"] in CLASS_ORDER else 99, i["id"]))
    data["items_total"] = len(items)
    data["items"] = [{k: (v[:600] if isinstance(v, str) else v) for k, v in i.items()} for i in items[:max_items]]
    return data


def render(triage: dict, site: Path, max_items: int = 4000) -> Path:
    site.mkdir(parents=True, exist_ok=True)
    template = (HERE / "template.html").read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise SystemExit("template.html lost its data placeholder")
    payload = json.dumps(compact(triage, max_items), separators=(",", ":"), ensure_ascii=False)
    payload = payload.replace("</", "<\\/")  # never close the <script> element early
    html = template.replace(PLACEHOLDER, payload)
    (site / "index.html").write_text(html, encoding="utf-8")
    (site / "triage.json").write_text(json.dumps(triage, indent=1) + "\n", encoding="utf-8")
    return site / "index.html"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--triage", required=True)
    ap.add_argument("--site", required=True)
    ap.add_argument("--max-items", type=int, default=4000)
    a = ap.parse_args()
    out = render(json.loads(Path(a.triage).read_text()), Path(a.site), a.max_items)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
