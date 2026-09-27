"""emit.py, cts_to_junit.py and merge.py."""
import json

import cts_to_junit
import emit
import merge


def _junit(path, cases):
    body = "".join(
        f'<testcase classname="{c}" name="{n}" time="0.1">{inner}</testcase>' for c, n, inner in cases)
    path.write_text(f'<?xml version="1.0"?><testsuites><testsuite name="s">{body}</testsuite></testsuites>')
    return str(path)


def test_ingest_junit_marks_rerun_pass_as_flaky(tmp_path):
    first = _junit(tmp_path / "a.xml", [("t1", "t1", ""), ("t2", "t2", "<failure message='boom'/>"),
                                        ("t3", "t3", "<failure message='bad'/>")])
    rerun = _junit(tmp_path / "b.xml", [("t2", "t2", ""), ("t3", "t3", "<failure message='still bad'/>")])
    out = tmp_path / "r.jsonl"
    emit.ingest_junit(str(out), "s", "ctest", first, rerun)
    recs = {r["id"]: r for r in emit.read_records(out)}
    assert recs["s::ctest::t1"]["status"] == "pass"
    assert recs["s::ctest::t2"]["status"] == "flaky" and recs["s::ctest::t2"]["attempts"] == 2
    assert recs["s::ctest::t3"]["status"] == "fail" and recs["s::ctest::t3"]["attempts"] == 2


def test_ingest_junit_pytest_classname_kept_and_notrun_is_error(tmp_path):
    first = _junit(tmp_path / "a.xml", [("tests.test_x", "test_a[GPU]", ""), ("t9", "t9", "")])
    text = (tmp_path / "a.xml").read_text().replace('name="t9" time="0.1"', 'name="t9" time="0.1" status="notrun"')
    (tmp_path / "a.xml").write_text(text)
    out = tmp_path / "r.jsonl"
    emit.ingest_junit(str(out), "roccv", "pytest", first)
    recs = {r["id"]: r["status"] for r in emit.read_records(out)}
    assert recs["roccv::pytest::tests.test_x::test_a[GPU]"] == "pass"
    assert recs["roccv::pytest::t9"] == "error"


def test_make_record_rejects_unknown_status():
    try:
        emit.make_record("s", "g::n", "passed")
    except ValueError:
        return
    raise AssertionError("invalid status accepted")


# Lines in the format the openvx_1.3.2 CTS really prints (test_engine.c).
CLEAN_LOG = [
    "[ RUN 0001 ] GraphBase.vxCreateGraph ...",
    "[     DONE ] GraphBase.vxCreateGraph (1.2 ms)",
    "[ RUN 0002 ] vxuCanny.BitExactL1/0/3x3 thresh=120 output=VX_DF_IMAGE_U8 ...",
    "[ !FAILED! ] Test setup",
    "[ !FAILED! ] vxuCanny.BitExactL1/0/3x3 thresh=120 output=VX_DF_IMAGE_U8 (3.1 ms)",
    "[ PASSED   ] 1 test(s)",
    "[ FAILED   ] 1 test(s), listed below:",
    "[ FAILED   ] vxuCanny.BitExactL1/0/3x3 thresh=120 output=VX_DF_IMAGE_U8",
    "#REPORT: 20260925012033 ALL 5 3 2 2 1 1 (version 1.3.2)",
]


def test_cts_parses_real_format():
    state, report = cts_to_junit.parse(CLEAN_LOG)
    assert set(state) == {"GraphBase.vxCreateGraph", "vxuCanny.BitExactL1/0/3x3 thresh=120 output=VX_DF_IMAGE_U8"}
    assert state["GraphBase.vxCreateGraph"]["status"] == "pass"
    assert state["GraphBase.vxCreateGraph"]["time"] == 0.0012
    assert state["vxuCanny.BitExactL1/0/3x3 thresh=120 output=VX_DF_IMAGE_U8"]["status"] == "fail"
    assert report == {"id": "ALL", "total": 5, "disabled": 3, "started": 2, "completed": 2, "passed": 1, "failed": 1}
    ts, summary = cts_to_junit.build("cts.GPU.x", state, report, rc=1)
    assert summary["problems"] == []
    assert "#REPORT" not in [tc.get("name") for tc in ts.iter("testcase")]


def test_cts_crash_and_abnormal_exit_are_errors():
    log = ["[ RUN 0001 ] Box.test/0 ...", "[     DONE ] Box.test/0 (3 ms)",
           "[ RUN 0002 ] Box.test/1 ..."]  # never finishes: crash, no #REPORT
    state, report = cts_to_junit.parse(log)
    assert state["Box.test/1"]["status"] == "crash"
    ts, summary = cts_to_junit.build("cts.CPU.x", state, report, rc=139)
    assert "#REPORT" in [tc.get("name") for tc in ts.iter("testcase")]
    assert any("signal 11" in p for p in summary["problems"]) and any("truncated" in p for p in summary["problems"])


def _suite_dir(root, name, suite, records, status=None):
    d = root / name
    d.mkdir(parents=True)
    with open(d / "results.jsonl", "w") as f:
        for rid, st in records:
            f.write(json.dumps(emit.make_record(suite, rid, st)) + "\n")
    (d / "suite.json").write_text(json.dumps({"suite": suite, "wall_seconds": 10, "total": len(records),
                                              "counts": {"pass": len(records)}}))
    if status:
        (d / "runner-status.json").write_text(json.dumps(status))
    return d


def test_merge_combines_suites_and_records_infra(tmp_path):
    root, out = tmp_path / "in", tmp_path / "out"
    _suite_dir(root, "results-packaging-packages/packaging-deb", "packaging", [("deb::a", "pass")])
    _suite_dir(root, "results-packaging-packages/packaging-rpm", "packaging", [("rpm::a", "pass")])
    _suite_dir(root, "results-rocal/rocal", "rocal", [("ctest::x", "pass")],
               status={"suite": "rocal", "rc": 124, "reason": "time budget of 100s exhausted"})
    pre = root / "results-environment" / "preflight"
    pre.mkdir(parents=True)
    (pre / "preflight.json").write_text(json.dumps({"ok": False, "reason": "rocminfo shows no GPU agent"}))
    merge.merge(root, out, ["packaging", "rocal", "roccv"])
    recs = {r["id"]: r for r in emit.read_records(out / "results.jsonl")}
    suites = json.loads((out / "suites.json").read_text())
    assert suites["packaging"]["total"] == 2 and len(suites["packaging"]["result_dirs"]) == 2
    assert recs["rocal::infra::runner"]["status"] == "error"
    assert recs["roccv::infra::no-results"]["status"] == "error"
    assert recs["preflight::infra::gpu-preflight"]["status"] == "error"
    env = json.loads((out / "environment.json").read_text())
    assert env["preflight"]["ok"] is False
