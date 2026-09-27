# Suite contract

Every suite is a directory `suites/<name>/` with an entrypoint `run.sh` (or the `entrypoint` given in `suites/suites.yaml`). The same script runs in three places:

- in the nightly, inside the test container on the self-hosted runner (`build_tools/run_in_container.sh`);
- in a hosted job (packaging);
- on a developer machine (`build_tools/local_run.sh`, no Docker).

## Environment

The launcher sets these; `build_tools/lib/vp.sh` (`vp_init`) validates them and derives the rest.

| Variable | Meaning |
|---|---|
| `ROCM_PATH` | ROCm SDK + vision-pack overlay prefix. **Read-only.** In containers it is `/opt/vp/rocm`, deliberately not `/opt/rocm`, so code that ignores `ROCM_PATH` fails loudly. |
| `VP_OUT` | The suite's writable output directory. Nothing may be written anywhere else. |
| `VP_REPO` | Repository root (read-only). |
| `VP_DATA` | Dataset root that **contains** `rocal_data/` (read-only; may be empty → record `blocked`). |
| `VP_TIER` | `quick`, `standard`, `comprehensive` or `full`. |
| `VP_GFX` | Chosen GPU architecture, e.g. `gfx1201` (empty on CPU-only runs). |
| `VP_MANIFEST` | vision-pack manifest JSON (`sha`, `rocm_sdk`, `submodules`, `gpu_targets`). |
| `VP_VISION_PACK_SRC` | vision-pack submodule at the tested commit (top level only; nested library submodules are not initialised in release mode). |
| `VP_EXTENDED` | `1` when the extended image (ROCm torch, tensorflow, jax) is in use. |
| `VP_UNSUPPORTED_GPUS` | `gfx:renderminor:index,...` of GPUs present but not targeted (robustness suite). The index is the host's; inside a container, find devices by enumerating agents (`rocminfo`). |
| `VP_GPU_ACCESS` | `chosen`, `all` or `none` (from `suites.yaml`): which GPUs the suite can see. |
| `VP_CACHE` | Writable download cache that persists across runs (e.g. the OpenVX CTS clone). Take a `flock` on `$VP_CACHE/<name>.lock` while filling it. It may be shared by concurrent jobs. |
| `VP_NO_CONTAINER` | `1` on bare metal (local runs). |
| `VP_DIST_TARBALL` | The vision-pack dist tarball the prefix was built from (read-only; empty when not passed). loader-audit compares it with the prefix; sdk-consumer tests it standalone. |
| `VP_PY313` | Optional Python 3.13 interpreter for loader-audit's negative import control (skipped when absent). |
| `VP_PYTEST_TIMEOUT` | Seconds per pytest session in `vp_pytest` (default 5400; scaled by `VP_TIMEOUT_SCALE`). |

`vp_init` also:
- puts `$ROCM_PATH/bin` first on `PATH`;
- sets `PYTHONPATH=$ROCM_PATH/lib`, `PYTHONDONTWRITEBYTECODE=1`, `MPLBACKEND=Agg`, a private `HOME` under `$VP_OUT/work`, and `ROCAL_DATA_PATH=$VP_DATA`;
- **unsets** `LD_LIBRARY_PATH` (customer mode: libraries must resolve through RUNPATH; `VP_CI_PARITY=1` restores upstream CI's value), `AGO_DEFAULT_TARGET` (set it per test), `HIP_VISIBLE_DEVICES` and `HSA_OVERRIDE_GFX_VERSION`.

## Writing results

Use only these helpers (see `build_tools/lib/vp.sh`):

- `vp_run <id> [--timeout S] [--retry] [--cwd DIR] [--expect-rc N] [--backend CPU|GPU] [--env K=V] -- cmd...` runs a command and records it:
  - exit == expected → `pass`;
  - timeout or signal → `error`;
  - otherwise → `fail`;
  - with `--retry`, a pass on the second attempt → `flaky`.

  It returns 0 for pass/flaky, so `vp_run ... && next` chains dependent steps. Suites use `set -uo pipefail`, **not** `-e`.
- `vp_result <id> <status> [message] [duration] [log] [backend] [attempts] [repro]` records a result you computed yourself.
- `vp_skip <id> [why]` records a not-applicable check (e.g. a combination the test binary rejects). `vp_blocked <id> [why]` records a missing dependency, data set or tool.
- `vp_ctest <group> <build_dir> [ctest args]` runs ctest serially with JUnit, re-runs failures once, and ingests the results as `<suite>::<group>::<ctest name>`.
- `vp_pytest <group> [pytest args]` does the same for pytest (cache kept in `$VP_OUT/work`).
- `vp_ingest_junit <file> <group> [rerun.xml]` ingests any JUnit file (e.g. from `build_tools/results/cts_to_junit.py`).
- Python harnesses may import `build_tools/results/emit.py` and call `append_record(os.environ["VP_RESULTS"], suite, id, status, ...)` directly, which is much faster for thousands of records.
- `vp_perf <name> <file.json>` registers performance data, in this format:
  `{"metrics": [{"name": "...", "value": 1.2, "unit": "ms", "lower_is_better": true, "backend": "GPU"}]}`.
- `vp_finish` must be the last call. It writes `junit/<suite>.xml`, `summary.json` and `suite.json`.

### Status meanings

- `pass`: the check ran and its output is correct.
- `fail`: the check ran and produced a wrong result or a non-zero exit.
- `error`: crash, timeout, or the check could not complete.
- `skip`: not applicable.
- `blocked`: a dependency is missing.
- `flaky`: passed only on retry.

Suites **never** apply known-issue baselines: a known bug is still recorded as `fail`, and `report/triage.py` maps it to `known_fail` using `baselines/known_issues.yaml`.

### Test IDs

IDs are `<suite>::<group>::<name>`. They are stable across nights, so keep them free of timestamps, PIDs and paths. Groups use dots for dimensions, e.g.:

- `mivisionx::cts.GPU.vision-filters::Box3x3.testGraphProcessing/...`
- `rocal::golden-cpp.hip.rgb::Blur_rgb_hip`
- `roccv::pytest::test_op_flip::test_flip[GPU-...]`
- `loader-audit::dlopen::lib/librocal.so`

`baselines/known_issues.yaml` matches IDs with shell-style globs, so choose names that make a finding easy to target.

## Rules

1. **Write only under `$VP_OUT`** (and `$VP_CACHE` for reusable downloads). Scripts that write into their working directory (MIVisionX `runVisionTests.py`, rocAL `unit_tests.sh`/`unit_test.py`, the image comparators, `numpy_reader.py`, ...) run in a fresh directory under `$VP_OUT/work` per invocation. pytest keeps its cache in `$VP_OUT/work` (`vp_pytest` does this).
2. **Never** run shipped scripts that call `sudo`, `rm -rf` or rebuild in place: rocAL `testAllScripts.sh`, `video_tests/testScript.sh`, `audio_tests.py`; MIVisionX `runConformanceTests.py`; `runVisionTests.py --profiling`. Replay their commands instead.
3. **LMDB datasets:** copy them into `$VP_OUT/work` with `vp_copy_lmdb` first. rocAL's readers rewrite `lock.mdb` even when only reading (M14).
4. **Deliberate crash probes** (segfault, use-after-free and GPU-fault reproducers) are wrapped in `if vp_crash_tests_allowed; then ... else vp_skip ...; fi`. They run in CI containers and are skipped on bare hosts unless `VP_ALLOW_CRASH_TESTS=1`. On bare hosts `vp_init` also sets a 1-byte core limit, so the kernel never hands an unexpected crash to apport.
5. **Export `ROCM_PATH` for every ctest,** because nested `--build-and-test` configures otherwise fall back to `/opt/rocm`. Set `AGO_DEFAULT_TARGET` per test, never globally.
6. **Scale with the tier:** `vp_tier_ge standard|comprehensive|full`. `quick` must finish in a few minutes per suite. Anything that needs torch/tensorflow/jax runs only when `VP_EXTENDED=1` (otherwise record `blocked`).
7. **Exit status:** `run.sh` exits 0 once it has recorded its results, even if checks failed. It exits non-zero only when the suite itself cannot run (no prefix, cannot create `$VP_OUT`); the report then shows an infrastructure error.
8. **Never modify the prefix, the dataset or the vision-pack checkout.**

## Local development

```bash
build_tools/local_run.sh --suite roccv --prefix /opt/rocm-nightly --data /path/to/MIVisionX-data \
    --tier standard --out /tmp/vpt
jq -c '{id,status}' /tmp/vpt/roccv/results.jsonl | head
```
