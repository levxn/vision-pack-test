"""report/triage.py: classification, verdict, counts, perf, issues."""
import datetime as dt
import gzip
import hashlib
import json

import emit
import generate_report
import merge
import publish_history
import triage

KNOWN = {"schema": 1, "issues": [
    {"id": "C1", "title": "threshold", "severity": "critical", "owner": "MIVisionX", "kind": "xfail",
     "match": ["mivisionx::parity.*::Threshold_U1*"], "added": "2026-09-25", "review_by": "2027-01-31",
     "strict": True},
    {"id": "M21", "title": "no code object", "severity": "medium", "owner": "rocCV", "kind": "xfail",
     "match": ["robustness::unsupported-gpu.*::*"], "gfx": ["gfx1036"], "added": "2026-09-25",
     "review_by": "2027-01-31"},
    {"id": "L-tf", "title": "tensorflow only in extended", "severity": "low", "owner": "rocAL", "kind": "skip",
     "match": ["rocal::golden-py.*::*tf*"], "added": "2026-09-25", "review_by": "2027-01-31"},
]}


def _merged(tmp_path, records, suites=None):
    m = tmp_path / "merged"
    m.mkdir(parents=True)
    with open(m / "results.jsonl", "w") as f:
        for rid, status in records:
            f.write(json.dumps({"suite": rid.split("::")[0], "id": rid, "status": status, "message": "m",
                                "repro": "cmd"}) + "\n")
    suites = suites or {s: {"suite": s} for s in {r[0].split("::")[0] for r in records}}
    (m / "suites.json").write_text(json.dumps(suites))
    return m


def _run(tmp_path, records, prev=None, expected=None, perf=None, suites=None, gfx="gfx1201", tier="comprehensive"):
    hist = {"prev_night": "2026-09-26" if prev else None, "prev": prev or {}, "trend": [], "perf": perf or [],
            "issues_state": {}}
    return triage.triage(_merged(tmp_path, records, suites), KNOWN, expected or {}, {}, hist, {}, tier, gfx,
                         "2026-09-27", "", "")


def _cls(t):
    return {i["id"]: i["class"] for i in t["items"]}


def test_known_failure_is_yellow_and_known_pass_is_fixed(tmp_path):
    t = _run(tmp_path, [("mivisionx::parity.1080p.GPU::Threshold_U1_U8", "fail"),
                        ("mivisionx::parity.1080p.CPU::Threshold_U1_U8", "pass"),
                        ("mivisionx::ctest::a", "pass")])
    c = _cls(t)
    assert c["mivisionx::parity.1080p.GPU::Threshold_U1_U8"] == "known_fail"
    assert c["mivisionx::parity.1080p.CPU::Threshold_U1_U8"] == "fixed"
    assert t["verdict"] == "yellow"
    assert next(k for k in t["known"] if k["id"] == "C1")["state"] == "reproduced"
    # Once every test of a strict entry passes, the report asks for its removal.
    t2 = _run(tmp_path / "all-pass", [("mivisionx::parity.1080p.GPU::Threshold_U1_U8", "pass")])
    assert next(k for k in t2["known"] if k["id"] == "C1")["state"] == "fixed"
    assert any("C1" in r and "fixed known issues" in r for r in t2["reasons"])


def test_new_and_still_failing_are_red(tmp_path):
    prev = {"rocal::ctest::a": ["pass", 0], "rocal::ctest::b": ["fail", 2]}
    t = _run(tmp_path, [("rocal::ctest::a", "fail"), ("rocal::ctest::b", "error"), ("rocal::ctest::c", "pass")],
             prev=prev)
    c = _cls(t)
    assert c["rocal::ctest::a"] == "new_failure"
    assert c["rocal::ctest::b"] == "still_failing"
    assert "rocal::ctest::c" not in c  # new passing tests are counted, not listed
    assert t["totals"]["by_class"]["new_test"] == 1 and t["delta"]["new_test"] == 1
    assert t["verdict"] == "red"
    b = next(i for i in t["items"] if i["id"] == "rocal::ctest::b")
    assert b["nights_failing"] == 3


def test_gfx_scope_and_skip_kind(tmp_path):
    t = _run(tmp_path, [("robustness::unsupported-gpu.gfx1036::flip", "fail"),
                        ("rocal::golden-py.cpu.rgb::tf_reader", "blocked")], gfx="gfx1201")
    c = _cls(t)
    assert c["robustness::unsupported-gpu.gfx1036::flip"] == "new_failure"  # M21 is scoped to gfx1036 runners
    assert c["rocal::golden-py.cpu.rgb::tf_reader"] == "known_blocked"
    t2 = _run(tmp_path / "b", [("robustness::unsupported-gpu.gfx1036::flip", "fail")], gfx="gfx1036")
    assert _cls(t2)["robustness::unsupported-gpu.gfx1036::flip"] == "known_fail"


def test_blocked_test_of_a_known_finding_is_expected(tmp_path):
    t = _run(tmp_path, [("mivisionx::parity.1080p.GPU::Threshold_U1_U8", "blocked"),
                        ("rocal::ctest::other", "blocked")])
    c = _cls(t)
    assert c["mivisionx::parity.1080p.GPU::Threshold_U1_U8"] == "known_blocked"
    assert c["rocal::ctest::other"] == "blocked"
    assert next(k for k in t["known"] if k["id"] == "C1")["state"] == "not-run"


def test_flaky_finding_that_passes_is_not_fixed(tmp_path):
    known = {"schema": 1, "issues": [
        {"id": "M5", "title": "race", "severity": "medium", "owner": "rocAL", "kind": "flaky",
         "match": ["rocal::probe::concurrent-*"], "added": "2026-09-25", "review_by": "2027-01-31"}]}
    hist = {"prev_night": None, "prev": {}, "trend": [], "perf": [], "issues_state": {}}
    t = triage.triage(_merged(tmp_path, [("rocal::probe::concurrent-build.cpu", "pass")]), known, {}, {}, hist, {},
                      "comprehensive", "gfx1201", "2026-09-27", "", "")
    assert t["known"][0]["state"] == "not-reproduced"
    assert t["verdict"] == "green"


def test_match_file_lists_exact_ids(tmp_path):
    (tmp_path / "lists").mkdir()
    (tmp_path / "lists" / "m17.txt").write_text(
        "# comment\nmivisionx::cts.CPU.optional::Box3x3.GraphProcessing/0/VX_BORDER_CONSTANT\n"
        "mivisionx::cts.GPU.optional::Median*\n")
    doc = {"schema": 1, "_base": str(tmp_path), "issues": [
        {"id": "M17", "title": "t", "severity": "medium", "owner": "MIVisionX", "kind": "xfail",
         "match_file": "lists/m17.txt", "added": "2026-09-25", "review_by": "2027-01-31"}]}
    known = triage.Known(doc, "gfx1201", "full")
    assert known.match("mivisionx::cts.CPU.optional::Box3x3.GraphProcessing/0/VX_BORDER_CONSTANT")["id"] == "M17"
    assert known.match("mivisionx::cts.CPU.optional::Box3x3.GraphProcessing/1/VX_BORDER_CONSTANT") is None
    assert known.match("mivisionx::cts.GPU.optional::Median3x3.x")["id"] == "M17"


def test_infra_records_and_flaky(tmp_path):
    t = _run(tmp_path, [("roccv::infra::no-results", "error"), ("rocal::ctest::x", "flaky")])
    c = _cls(t)
    assert c["roccv::infra::no-results"] == "infra_error"
    assert c["rocal::ctest::x"] == "flaky"
    assert t["verdict"] == "red"


def test_removed_tests_and_expected_counts(tmp_path):
    prev = {"rocal::ctest::a": ["pass", 0], "rocal::ctest::gone": ["pass", 0], "roccv::ctest::z": ["pass", 0]}
    expected = {"counts": [{"suite": "rocal", "group": "ctest", "min": 21},
                           {"suite": "rocal", "group": "golden-*", "min": 1, "tiers": ["full"]}]}
    t = _run(tmp_path, [("rocal::ctest::a", "pass")], prev=prev, expected=expected,
             suites={"rocal": {"suite": "rocal"}, "roccv": {"suite": "roccv", "missing": True}})
    assert t["delta"]["removed"] == ["rocal::ctest::gone"]  # roccv did not run: not "removed"
    rows = {(c["suite"], c["group"]): c for c in t["expected_counts"]}
    assert rows[("rocal", "ctest")]["ok"] is False
    assert ("rocal", "golden-*") not in rows  # full-tier rule
    assert t["verdict"] == "red"


def test_perf_gate(tmp_path):
    (tmp_path / "merged").mkdir()
    perf_dir = tmp_path / "merged" / "perf"
    perf_dir.mkdir()
    (perf_dir / "roccv__ops.json").write_text(json.dumps({"metrics": [
        {"name": "flip", "value": 2.0, "unit": "ms", "backend": "GPU"},
        {"name": "resize", "value": 1.05, "unit": "ms", "backend": "GPU"},
        {"name": "decode", "value": 900, "unit": "img/s", "backend": "GPU"}]}))
    hist = []
    for n in range(7):
        night = f"2026-09-{10 + n:02d}"
        hist += [{"night": night, "key": "roccv/GPU/flip", "value": 1.0},
                 {"night": night, "key": "roccv/GPU/resize", "value": 1.0},
                 {"night": night, "key": "roccv/GPU/decode", "value": 1000}]
    p = triage.perf_eval(tmp_path / "merged", {}, hist, "2026-09-27")
    by = {m["key"]: m for m in p["metrics"]}
    assert by["roccv/GPU/flip"]["status"] == "hard"      # twice as slow
    assert by["roccv/GPU/resize"]["status"] == "ok"      # within 10 %
    assert by["roccv/GPU/decode"]["status"] == "ok"      # 0.9 is exactly on the floor
    assert p["hard"] is True


def test_regression_issues_grouped_and_closed_after_three_green_nights(tmp_path):
    items = [{"id": "rocal::ctest::a", "class": "new_failure", "status": "fail", "nights_failing": 1},
             {"id": "rocal::ctest::b", "class": "still_failing", "status": "fail", "nights_failing": 4},
             {"id": "roccv::pytest::x", "class": "known_fail", "status": "fail", "nights_failing": 1}]
    state = {"deadbeef00": {"key": "mivisionx::cts.GPU.graph", "green_streak": 2}}
    actions, new_state = triage.regression_issues(items, state, {"rocal", "mivisionx"}, "url")
    opens = [a for a in actions if a["action"] == "open_or_comment"]
    assert len(opens) == 1 and opens[0]["key"] == "rocal::ctest" and opens[0]["nights"] == 4
    assert opens[0]["fingerprint"] in opens[0]["title"]
    assert any(a["action"] == "close" and a["fingerprint"] == "deadbeef00" for a in actions)
    assert "deadbeef00" not in new_state


NO_GPU_WHY = "no KFD topology at /sys/class/kfd/kfd/topology/nodes (amdgpu driver not loaded?)"
NO_GPU_MSG = "no GPU detected (VP_GFX empty)"  # what the needs_gpu: false suites record for their GPU checks


def _no_gpu_night(tmp_path, extra=()):
    """merge.py output of a night on a runner without a GPU: two degraded suites ran, three GPU suites could not."""
    root, out = tmp_path / "in", tmp_path / "merged"
    raw = {"loader-audit": [("elf::librocal.so", "pass", ""), ("verify::gfx-in-manifest", "blocked", NO_GPU_MSG)],
           "sdk-consumer": [("consumer.cmake::rocal.GPU", "blocked", NO_GPU_MSG),
                            ("consumer.py::numpy", "blocked", "numpy not installed for VP_PY"), *extra]}
    for suite, recs in raw.items():
        d = root / f"results-{suite}" / suite
        d.mkdir(parents=True)
        with open(d / "results.jsonl", "w") as f:
            for rid, status, msg in recs:
                f.write(json.dumps(emit.make_record(suite, rid, status, message=msg)) + "\n")
    env = root / "results-environment" / "environment"
    env.mkdir(parents=True)
    (env / "environment.json").write_text(json.dumps({"runner": "vp-gpu-1", "gpu_present": False,
                                                     "no_gpu_reason": NO_GPU_WHY}))
    (env / "prepared.json").write_text(json.dumps({"gfx": "", "mode": "no-gpu"}))
    merge.merge(root, out, ["loader-audit", "sdk-consumer", "mivisionx", "rocal", "roccv"])
    return out


def _hist(issues_state=None):
    return {"prev_night": None, "prev": {}, "trend": [], "perf": [], "issues_state": issues_state or {}}


def test_no_gpu_night_is_red_with_one_reason_and_one_issue(tmp_path):
    t = triage.triage(_no_gpu_night(tmp_path), KNOWN, {}, {}, _hist(), {}, "comprehensive", "", "2026-09-27", "",
                      "url")
    c = _cls(t)
    assert t["verdict"] == "red" and t["no_gpu"] == NO_GPU_WHY
    assert t["reasons"][0] == f"runner had no usable GPU ({NO_GPU_WHY}): 3 GPU suites did not run"
    assert not any("infra error" in r for r in t["reasons"])  # the no-GPU records are not counted twice
    assert {i for i, k in c.items() if k == "infra_error"} == {
        "preflight::infra::no-gpu", "mivisionx::infra::no-gpu", "rocal::infra::no-gpu", "roccv::infra::no-gpu"}
    opens = [a for a in t["issue_actions"] if a["action"] == "open_or_comment"]
    assert len(opens) == 1 and opens[0]["key"] == "runner::no-gpu"
    assert opens[0]["fingerprint"] in opens[0]["title"] and "mivisionx, rocal, roccv" in opens[0]["body"]
    md = triage.summary_md(t)
    assert f"- GPU: none ({NO_GPU_WHY})" in md and "| rocal | not run: no GPU |" in md and "on no GPU," in md


def test_no_gpu_blocked_checks_are_known_blocked_only_without_a_gpu(tmp_path):
    t = triage.triage(_no_gpu_night(tmp_path), KNOWN, {}, {}, _hist(), {}, "comprehensive", "", "2026-09-27", "", "")
    c = _cls(t)
    assert c["loader-audit::verify::gfx-in-manifest"] == "known_blocked"
    assert c["sdk-consumer::consumer.cmake::rocal.GPU"] == "known_blocked"
    assert c["sdk-consumer::consumer.py::numpy"] == "blocked"  # not a GPU reason
    rec = {"id": "loader-audit::verify::gfx-in-manifest", "status": "blocked", "message": NO_GPU_MSG}
    assert triage.classify(rec, None, None, False) == "blocked"  # a GPU night: the missing GPU is news


def test_gfx_none_scope_applies_only_without_a_gpu(tmp_path):
    known = {"schema": 1, "issues": [
        {"id": "M13-nogpu", "title": "t", "severity": "medium", "owner": "rocAL", "kind": "xfail", "gfx": ["none"],
         "match": ["sdk-consumer::consumer.rocal::CPU.pipeline"], "added": "2026-09-28", "review_by": "2026-12-31"}]}
    night = _no_gpu_night(tmp_path, [("consumer.rocal::CPU.pipeline", "fail", "vxVerifyGraph failed -1")])
    t = triage.triage(night, known, {}, {}, _hist(), {}, "comprehensive", "", "2026-09-27", "", "")
    assert _cls(t)["sdk-consumer::consumer.rocal::CPU.pipeline"] == "known_fail"
    # With a GPU the check passes, and the entry is out of scope: no "fixed" noise every night.
    t = triage.triage(_merged(tmp_path / "gpu", [("sdk-consumer::consumer.rocal::CPU.pipeline", "pass")]), known, {},
                      {}, _hist(), {}, "comprehensive", "gfx1201", "2026-09-28", "", "")
    assert t["totals"]["by_class"] == {"pass": 1} and t["known"][0]["state"] == "out-of-scope"


def test_no_gpu_issue_closes_after_three_nights_with_a_gpu(tmp_path):
    fp = hashlib.sha1(triage.NO_GPU_KEY.encode()).hexdigest()[:10]
    state = {fp: {"key": triage.NO_GPU_KEY, "green_streak": 2}}
    # Still no GPU: the issue gets a comment and its streak restarts.
    t = triage.triage(_no_gpu_night(tmp_path), KNOWN, {}, {}, _hist(state), {}, "comprehensive", "", "2026-09-27",
                      "", "")
    assert [a["action"] for a in t["issue_actions"]] == ["open_or_comment"]
    assert t["_issues_state"][fp]["green_streak"] == 0
    # A night without the GPU suites (e.g. packaging only) does not count; a night with a GPU does.
    actions, new_state = triage.regression_issues([], state, {"packaging"}, "url")
    assert actions == [] and new_state[fp]["green_streak"] == 2
    t = _run(tmp_path / "gpu", [("rocal::ctest::a", "pass")])
    assert t["no_gpu"] is None
    t = triage.triage(_merged(tmp_path / "gpu2", [("rocal::ctest::a", "pass")]), KNOWN, {}, {}, _hist(state), {},
                      "comprehensive", "gfx1201", "2026-09-28", "", "")
    assert any(a["action"] == "close" and a["fingerprint"] == fp for a in t["issue_actions"])


def test_history_render_and_publish(tmp_path):
    t = _run(tmp_path, [("rocal::ctest::a", "fail"), ("rocal::ctest::b", "pass")])
    public = {k: v for k, v in t.items() if not k.startswith("_")}
    site = tmp_path / "site"
    generate_report.render(public, site)
    html = (site / "index.html").read_text()
    assert "/*__REPORT_DATA__*/" not in html and '"verdict":"red"' in html
    (tmp_path / "triage.json").write_text(json.dumps(public))
    with gzip.open(tmp_path / "status.json.gz", "wt") as f:
        json.dump(t["_status"], f)
    hist = tmp_path / "history"
    hist.mkdir()
    import sys
    argv = sys.argv
    sys.argv = ["publish_history.py", "--history", str(hist), "--triage", str(tmp_path / "triage.json"),
                "--site", str(site), "--status", str(tmp_path / "status.json.gz"), "--record-tested"]
    try:
        assert publish_history.main() == 0
    finally:
        sys.argv = argv
    idx = json.loads((hist / "index.json").read_text())
    assert idx["nights"][0]["verdict"] == "red" and (hist / "nightly" / "2026-09-27" / "index.html").exists()
    loaded = triage.load_history(hist, "comprehensive", "gfx1201", "2026-09-28")
    assert loaded["prev_night"] == "2026-09-27" and loaded["prev"]["rocal::ctest::a"] == ["fail", 1]
    assert dt.date.fromisoformat(idx["nights"][0]["night"])
