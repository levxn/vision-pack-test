"""suites.yaml tier matrix and the baseline linter."""
import datetime as dt
from pathlib import Path

import lint_known_issues
import plan_matrix
import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((REPO / "suites" / "suites.yaml").read_text())
SUITES = set(CFG["suites"]) | lint_known_issues.SYNTHETIC_SUITES


def test_tiers_are_cumulative():
    names = []
    for tier in plan_matrix.TIERS:
        names.append(set(plan_matrix.plan(CFG, tier, set(), False, False)["expected"]))
    for smaller, larger in zip(names, names[1:]):
        assert smaller <= larger


def test_matrix_entries_and_runner_split():
    p = plan_matrix.plan(CFG, "full", set(), True, True)
    gpu = {e["suite"]: e for e in p["gpu_matrix"]["include"]}
    cpu = {e["suite"]: e for e in p["cpu_matrix"]["include"]}
    assert "packaging" in p["hosted"] and "packaging" not in gpu
    assert set(cpu) == {s for s, v in CFG["suites"].items() if v.get("runner") == "cpu"}
    assert gpu["robustness-nogpu"]["gpu_access"] == "none"
    assert gpu["install-test"]["entrypoint"] == "suites/packaging/install_test.sh"
    assert all(e["image"] == "extended" for e in gpu.values())  # extended deps + full tier


NOGPU_BY_TIER = {"quick": {"loader-audit"},
                 "standard": {"loader-audit", "sdk-consumer"},
                 "comprehensive": {"loader-audit", "sdk-consumer", "robustness-nogpu"},
                 "full": {"loader-audit", "sdk-consumer", "robustness-nogpu"}}


@pytest.mark.parametrize("has_cpu", [False, True])
@pytest.mark.parametrize("tier", plan_matrix.TIERS)
def test_nogpu_matrix_per_tier(tier, has_cpu):
    p = plan_matrix.plan(CFG, tier, set(), has_cpu, False)
    nogpu = {e["suite"]: e for e in p["nogpu_matrix"]["include"]}
    assert set(nogpu) == NOGPU_BY_TIER[tier] and p["has_nogpu"] is True
    assert all(e["gpu_access"] == "none" for e in nogpu.values())
    # Every planned self-hosted suite either runs without a GPU or is reported as needing one.
    assert set(p["gpu_required"]) == set(p["expected"]) - set(p["hosted"]) - set(nogpu)
    if "robustness-nogpu" in nogpu:
        assert nogpu["robustness-nogpu"]["entrypoint"] == "suites/robustness/nogpu.sh"


def test_nogpu_matrix_follows_the_suite_filter():
    p = plan_matrix.plan(CFG, "full", {"rocal"}, False, False)
    assert p["nogpu_matrix"]["include"] == [] and p["has_nogpu"] is False and p["gpu_required"] == ["rocal"]


def test_needs_gpu_must_be_a_bool():
    cfg = {"suites": {"x": {"runner": "gpu", "tiers": ["quick"], "needs_gpu": "no"}}}
    with pytest.raises(SystemExit, match="needs_gpu"):
        plan_matrix.plan(cfg, "quick", set(), False, False)


def test_suite_entrypoints_exist():
    for name, s in CFG["suites"].items():
        if s.get("runner") == "hosted":
            continue
        entry = REPO / s.get("entrypoint", f"suites/{name}/run.sh")
        assert entry.is_file(), f"{name}: {entry} missing"


def test_baselines_lint_clean():
    known = yaml.safe_load((REPO / "baselines" / "known_issues.yaml").read_text())
    expected = yaml.safe_load((REPO / "baselines" / "expected_counts.yaml").read_text())
    today = dt.date(2026, 9, 27)
    assert lint_known_issues.lint_known(known, SUITES, today) == []
    assert lint_known_issues.lint_expected(expected, SUITES) == []


def test_expired_entry_is_reported():
    doc = {"schema": 1, "issues": [{"id": "H1", "title": "t", "severity": "high", "owner": "rocAL",
                                    "kind": "xfail", "match": ["rocal::link::*"], "added": "2026-01-01",
                                    "review_by": "2026-02-01"}]}
    errs = lint_known_issues.lint_known(doc, SUITES, dt.date(2026, 9, 27))
    assert any("has passed" in e for e in errs)


def test_unknown_suite_in_glob_is_reported():
    doc = {"schema": 1, "issues": [{"id": "H1", "title": "t", "severity": "high", "owner": "rocAL",
                                    "kind": "xfail", "match": ["nosuch::x::*"], "added": "2026-09-01",
                                    "review_by": "2026-12-01"}]}
    assert lint_known_issues.lint_known(doc, SUITES, dt.date(2026, 9, 27))
