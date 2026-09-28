"""build_tools/detect_gpu.sh against fake KFD topologies (VP_KFD_TOPOLOGY)."""
import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "build_tools" / "detect_gpu.sh"
GFX1201, GFX1100 = 120001, 110000  # gfx_target_version: major * 10000 + minor * 100 + stepping


def _topology(root: Path, nodes: list[tuple[int, int]]) -> Path:
    """One node directory per (gfx_target_version, drm_render_minor); version 0 is a CPU agent."""
    topo = root / "nodes"
    topo.mkdir(parents=True)
    for i, (version, minor) in enumerate(nodes):
        (topo / str(i)).mkdir()
        (topo / str(i) / "properties").write_text(
            f"cpu_cores_count 16\ngfx_target_version {version}\ndrm_render_minor {minor}\n")
    return topo


def _manifest(root: Path, targets: list[str]) -> Path:
    m = root / "manifest.json"
    m.write_text(json.dumps({"gpu_targets": {lib: targets for lib in ("MIVisionX", "rocAL", "rocCV", "rocPyDecode")}}))
    return m


def _detect(topo: Path, *args: str, **env: str) -> tuple[int, dict, str]:
    e = {k: v for k, v in os.environ.items() if k not in ("EXPECTED_GFX", "GITHUB_OUTPUT", "GITHUB_ENV")}
    e.update(VP_KFD_TOPOLOGY=str(topo), **env)
    p = subprocess.run(["bash", str(SCRIPT), *args], env=e, capture_output=True, text=True, timeout=60)
    out = dict(line.split("=", 1) for line in p.stdout.splitlines() if "=" in line)
    return p.returncode, out, p.stderr


@pytest.mark.parametrize("case, code, reason", [
    ("missing", 3, "no KFD topology at"),
    ("cpu-only", 3, "no GPU agents in"),
    ("unsupported-only", 4, "no GPU on this host is targeted by the vision-pack build (found: gfx1100:128:0)"),
])
def test_no_usable_gpu(tmp_path, case, code, reason):
    args = []
    if case == "missing":
        topo = tmp_path / "does-not-exist"
    elif case == "cpu-only":
        topo = _topology(tmp_path, [(0, 0)])
    else:
        topo = _topology(tmp_path, [(0, 0), (GFX1100, 128)])
        args = ["--manifest", str(_manifest(tmp_path, ["gfx1201", "gfx942"]))]

    rc, out, err = _detect(topo, *args)
    assert rc == code and "::error::" in err and out == {}

    rc, out, err = _detect(topo, *args, "--allow-none")
    assert rc == 0 and "::warning::" in err
    assert out["VP_GPU_PRESENT"] == "0" and reason in out["VP_NO_GPU_REASON"]
    assert out["VP_GFX"] == out["VP_RENDER_MINOR"] == out["VP_GPU_INDEX"] == ""
    assert out["VP_UNSUPPORTED_GPUS"] == ("gfx1100:128:0" if case == "unsupported-only" else "")


def test_supported_gpu_is_chosen_with_or_without_allow_none(tmp_path):
    topo = _topology(tmp_path, [(0, 0), (GFX1100, 129), (GFX1201, 128)])
    manifest = _manifest(tmp_path, ["gfx1201", "gfx942"])
    for extra in ([], ["--allow-none"]):
        rc, out, _ = _detect(topo, "--manifest", str(manifest), *extra)
        assert rc == 0
        assert out["VP_GPU_PRESENT"] == "1" and out["VP_NO_GPU_REASON"] == ""
        assert (out["VP_GFX"], out["VP_RENDER_MINOR"], out["VP_GPU_INDEX"]) == ("gfx1201", "128", "1")
        assert out["VP_SDK_FAMILY"] == "gfx120X-all-tests"
        assert out["VP_UNSUPPORTED_GPUS"] == "gfx1100:129:0"


def test_expected_gfx_mismatch_still_fails_with_allow_none(tmp_path):
    topo = _topology(tmp_path, [(GFX1201, 128)])
    rc, out, err = _detect(topo, "--allow-none", EXPECTED_GFX="gfx942")
    assert rc == 5 and "the runner hardware changed" in err and out == {}


def test_github_outputs_without_gpu(tmp_path):
    gh_out, gh_env = tmp_path / "output", tmp_path / "env"
    rc, _, _ = _detect(tmp_path / "missing", "--allow-none", "--github",
                       GITHUB_OUTPUT=str(gh_out), GITHUB_ENV=str(gh_env))
    assert rc == 0
    outputs = dict(line.split("=", 1) for line in gh_out.read_text().splitlines())
    assert outputs["gpu_present"] == "0" and outputs["gfx"] == ""
    assert "no KFD topology" in outputs["no_gpu_reason"]
    assert "VP_GPU_PRESENT=0" in gh_env.read_text().splitlines()
