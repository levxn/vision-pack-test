"""build_tools/resolve_release.py with a fake GitHub API."""
import argparse

import resolve_release

SHA = "d440925b1b06417460ce48bd15a5c5d4ee239cba"


def _release(tag, n_deb=16, digest="sha256:" + "a" * 64, target=SHA, version="0.2.0+gd440925"):
    assets = [{"name": f"amdrocm-vision-{version}-Linux-lib{i}.deb", "size": 1, "digest": digest,
               "state": "uploaded", "browser_download_url": "u"} for i in range(n_deb)]
    assets += [{"name": f"amdrocm-vision-{version}-Linux-lib{i}.rpm", "size": 1, "digest": digest,
                "state": "uploaded", "browser_download_url": "u"} for i in range(16)]
    assets.append({"name": f"vision-pack-dist-linux-multiarch-{version}.tar.gz", "size": 1, "digest": digest,
                   "state": "uploaded", "browser_download_url": "u"})
    return {"tag_name": tag, "target_commitish": target, "assets": assets, "html_url": "h",
            "published_at": "2026-09-26T07:52:53Z", "prerelease": True}


def _args(**kw):
    base = dict(repo="o/vp", mode="release", tag="", ref="main", tier="comprehensive", sdk_family="", sdk_date="",
                sdk_url="", tested_file="", force=False, max_age_days=3, expect_deb=16, expect_rpm=16,
                expect_tarball=1)
    base.update(kw)
    return argparse.Namespace(**base)


def _fake(monkeypatch, releases):
    def api(path, retries=4):
        if path.startswith("/repos/o/vp/releases?"):
            return releases
        if path.startswith("/repos/o/vp/releases/tags/"):
            return next(r for r in releases if r["tag_name"] == path.rsplit("/", 1)[1])
        if "/git/ref/tags/" in path:
            return {"object": {"type": "commit", "sha": SHA}}
        if "/actions/workflows/" in path:
            return {"workflow_runs": [{"head_sha": SHA, "status": "completed", "conclusion": "success",
                                       "created_at": "2026-09-26T06:56:45Z", "html_url": "r", "id": 1}]}
        raise AssertionError(path)
    monkeypatch.setattr(resolve_release, "api", api)


def test_picks_newest_nightly_and_checks_assets(monkeypatch):
    _fake(monkeypatch, [_release("nightly-20260925"), _release("nightly-20260926"), _release("v0.1.0")])
    p = resolve_release.plan_release(_args())
    assert p["tag"] == "nightly-20260926" and p["version"] == "0.2.0+gd440925"
    assert p["assets"] == {"deb": 16, "rpm": 16, "tarball": 1} and p["problems"] == []
    assert p["upstream_nightly"]["conclusion"] == "success"


def test_problems_are_reported(monkeypatch):
    _fake(monkeypatch, [_release("nightly-20260926", n_deb=15, target="f" * 40, version="0.2.0+g1234567")])
    problems = " | ".join(resolve_release.plan_release(_args())["problems"])
    assert "expected 16 deb assets, found 15" in problems
    assert "target_commitish" in problems and "does not match tag commit" in problems


def test_fingerprint_changes_with_digest_and_tier(monkeypatch):
    _fake(monkeypatch, [_release("nightly-20260926")])
    a = resolve_release.plan_release(_args())["fingerprint"]
    b = resolve_release.plan_release(_args(tier="full"))["fingerprint"]
    _fake(monkeypatch, [_release("nightly-20260926", digest="sha256:" + "b" * 64)])
    c = resolve_release.plan_release(_args())["fingerprint"]
    assert len({a, b, c}) == 3
