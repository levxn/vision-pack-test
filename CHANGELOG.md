# Changelog

All notable changes to vision-pack-test are recorded here.

## [Unreleased]

### Added
- Nightly QA pipeline (`nightly.yml`) that tests the newest `nightly-YYYYMMDD` prerelease of [kiritigowda/vision-pack](https://github.com/kiritigowda/vision-pack), pinning the `vision-pack` submodule to the release commit at run time. A `mode: build` dispatch builds any vision-pack ref from source instead.
- Suites ported from the manual QA sweep of 25 Sep 2026: packaging, loader-audit, sdk-consumer, mivisionx, rocal, roccv, rocpydecode and robustness, with TheRock's quick/standard/comprehensive/full tiers.
- Self-hosted runner bootstrap (`runner/`), including the pre-job hook that only admits the nightly workflow on `main`.
- Known-issue baseline seeded with the 44 findings of the manual report (C1–C2, H1–H19, M1–M23), low-severity items and provisional findings N1–N4; expected-count floors; a rolling performance gate.
- Triage with night-over-night deltas, an HTML report published to GitHub Pages, history on the `qa-history` branch, a rolling status issue, fingerprinted regression issues and optional Slack/Teams notifications.
- Test images on TheRock's `no_rocm_image_ubuntu24_04` base (`docker/`), published by `image.yml` and consumed by digest, or built on the runner by content hash.
- Per-run ROCm prefix: the TheRock `-tests` SDK for the detected GPU family (cached, fallback chain) with the vision-pack tarball overlaid.
- Unit tests for the tooling (`tests/`), run by `lint.yml` together with actionlint 1.7.12, zizmor, shellcheck, ruff, yamllint and the baseline linter.
- Graceful degradation on a runner without a usable GPU. The pieces:
  - The pre-job hook only warns (`VP_ALLOW_NO_GPU=1`), and `detect_gpu.sh --allow-none` reports `gpu_present=0` with the reason.
  - `prepare_rocm.sh --no-gpu` builds the prefix from vision-pack's build SDK.
  - The new `test-nogpu` job runs the `needs_gpu: false` suites (loader-audit, sdk-consumer, robustness-nogpu).
  - Every GPU suite is recorded as `<suite>::infra::no-gpu`. The night is red with one "runner had no usable GPU" reason and one `runner::no-gpu` issue, and it is not recorded as tested.
  - `local_run.sh --no-gpu` emulates it locally.
  - An `EXPECTED_GFX` mismatch still fails.
- A GitHub-hosted fallback (`prepare-nogpu-hosted`/`test-nogpu-hosted`) for when no self-hosted runner is registered at all, gated by the `VP_HAS_SELF_HOSTED` repository variable so `prepare-rocm` and the self-hosted `test-*` jobs are skipped outright instead of queuing forever. Runs the same `needs_gpu: false` suites, with no persistent SDK cache.

### Baseline
- Validation run on `nightly-20260926` (vision-pack 0.2.0+gd440925, TheRock 20260926 gfx120X SDK, RX 9070 XT): every suite reproduces the manual QA metrics. M4 is fixed in this nightly (the hip_cu_mask test script now ships) and was removed from the baseline. New provisional findings N5–N14 were added while porting the suites.
