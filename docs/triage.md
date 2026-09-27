# Triage guide

How to read a nightly report and keep the baselines honest.

## Where to look

- **The report:** `https://<owner>.github.io/vision-pack-test/`. It opens the latest scheduled night; dispatched runs are under `runs/<run_id>/`.
- **The job summary** of the `report` job has the same headline: verdict, per-suite counts, the first 20 unbaselined failures with repro commands, and the environment.
- **The rolling "Nightly QA status" issue** always holds the latest summary.
- **Per-regression issues:** titled `Nightly regression: <suite>::<group> [<fingerprint>]`, one per failing group.
- **Raw evidence:** `results-<suite>` artifacts (logs, JUnit, `results.jsonl`; 30 days), and the `report` artifact (90 days). For older nights, `qa-history` keeps `triage.json` and a compact status per night.

## Verdicts

| Verdict | Meaning |
|---|---|
| **Red** | At least one new failure, unbaselined failure that persists (still failing), infrastructure error, suite with no results, expected-count shortfall, or hard performance regression. |
| **Yellow** | Only known failures, flaky tests, blocked checks, known issues that passed ("fixed"), removed tests, or soft performance drops. |
| **Green** | Everything passed or matched the baseline. |
| Skipped | No new nightly. `resolve-release` found the fingerprint in `qa-history/tested.txt`, and nothing else ran. |

## Classes

Every result ID (`<suite>::<group>::<name>`) gets exactly one class. The previous night is the latest earlier night with the **same tier and GPU**.

| Class | When |
|---|---|
| `pass` / `new_test` | Passed (a new ID if it did not exist in the previous night) |
| `new_failure` | Fails tonight, passed (or did not exist) in the previous night, not in the baseline |
| `still_failing` | Fails tonight and failed in the previous night, not in the baseline; the report counts the nights |
| `infra_error` | `…::infra::…` records: no results, the CI step failed or timed out, GPU pre-flight failed, fetch or build failed |
| `known_fail` / `known_flaky` | Fails, and a baseline entry of kind `xfail` or `flaky` matches |
| `fixed` | Passes, although an `xfail` entry matches |
| `flaky` | Failed, then passed on the automatic retry (never green) |
| `blocked` / `known_blocked` | A dependency or data set was missing; expected when any baseline entry matches (a `skip` entry, or a finding that already explains the test) |
| `skip` | Not applicable |
| `quarantined` | Matched a `quarantine` entry; shown but ignored by the verdict |

## A new failure

1. **Look at the evidence.** Open the item in the report's failure table: it shows the message, the log path inside `results-<suite>`, and the repro command.
2. **Reproduce locally** on any machine with a ROCm + vision-pack prefix:

   ```bash
   build_tools/local_run.sh --suite <suite> --prefix <prefix> --data <MIVisionX-data> --tier <tier>
   ```

   On the runner itself, the step log of the failing job prints the exact `run_in_container.sh` command, with the same prefix and image.
3. **Decide what it is:**
   - **A vision-pack or upstream bug:** file it upstream with the reproducer, then add a baseline entry (below) that links the issue. The regression issue closes after three green nights.
   - **A harness bug:** fix the suite. Suites never apply baselines themselves, so don't hide a harness problem in `known_issues.yaml`.
   - **An environment problem:** see "Infrastructure errors".

## Baseline entries (`baselines/known_issues.yaml`)

```yaml
- id: H17                    # C/H/M/N numbering from the QA report, or L-<name> for low items
  title: copy_to() of non-contiguous tensor views silently corrupts data
  severity: high             # critical | high | medium | low
  owner: rocCV
  kind: xfail                # xfail | flaky | skip | quarantine
  match:                     # shell-style globs over result IDs
    - "roccv::probe::strided-copy*"
  gfx: ["*"]                 # optional: scope to GPUs, e.g. ["gfx1036"]
  tiers: [comprehensive, full]   # optional
  issue: https://github.com/ROCm/rocm-libraries/issues/NNN
  added: 2026-09-25
  review_by: 2026-12-31      # lint fails after this date
  strict: true               # report an unexpected pass prominently
```

- **Match precisely.** A glob that also matches passing tests turns those into `fixed` every night. For example, if a bug only affects GPU, match only the GPU IDs.
- **Long exact lists** go in a `match_file` (relative to `baselines/`, one ID or glob per line), for findings whose failing and passing parameter combinations interleave, such as the CTS optional border tests. Generate the list from a trusted night with `build_tools/baseline_lists.py` and review its diff like any other baseline change.
- **Nondeterministic bugs** (races) use `kind: flaky`. Their failures classify as known, and their passes are not reported as fixed.
- **`review_by`** is at most about three months out. When it passes, `lint.yml` fails. Re-verify the finding, then either extend the date (with an issue link) or remove the entry.
- **A known issue that passes** shows as `fixed` in the report, and the entry's state becomes "fixed" once all its tests pass. For `kind: flaky` entries a clean night is "not reproduced", not fixed. Remove the entry in the same PR that confirms the upstream fix. With `strict: true`, the verdict reasons list it until you do.
- **`skip` entries** mark checks that are expected to be blocked in some tiers, e.g. tensorflow-only readers outside the extended image.
- **`quarantine`** is for tests that are too unstable to judge. Use it sparingly and always with a `review_by`.

## Expected counts (`baselines/expected_counts.yaml`)

Each rule gives a minimum number of result IDs for a suite and group glob in the listed tiers, for example `rocal::ctest` at least 21. A shortfall is red because tests disappeared silently: a CMake change, a crash before the test list, or an empty JUnit file. When upstream legitimately adds or removes tests, update the floor in the same PR.

## Infrastructure errors

| Record | Usual cause | Where to look |
|---|---|---|
| `<suite>::infra::no-results` | The job failed before writing results: runner offline, pre-job hook rejected it, image build failed | The job log; the runner's `_diag` logs |
| `<suite>::infra::runner` | The suite exceeded its time budget, or the container failed | `runner-status.json` in the artifact; raise `timeout_minutes` in `suites/suites.yaml` only if the suite legitimately got slower |
| `preflight::infra::gpu-preflight` | Driver or runtime problem: `rocminfo` shows no agent, or the HIP sanity kernel fails | `results-environment/preflight/preflight.log`; reboot or reset the GPU |
| `orchestrator::infra::fetch-release` | A release asset is missing or has a mismatched sha256 or SHA triple | The `fetch-release` log; usually upstream re-publishing, which the next poll picks up |
| `orchestrator::infra::build` | Build mode failed | The `build` job log |

Runs whose tests did not complete are not written to `tested.txt`, so the next poll retries automatically.

The SDK fallback shows in the environment block. A `multiarch-*` fallback means TheRock has no `-tests` SDK for the GPU family on the manifest's date.

## Performance

The rolling gate is described in `baselines/perf_policy.yaml`: the median of the last 7 nights on the same GPU.
- **Soft drop (yellow):** a metric below 0.90 of its median.
- **Hard regression (red):** a metric below 0.75, or a geometric mean below 0.95.
- **Warning only:** noisy metrics (CV above 10%) and timings under 1 ms.

Perf runs share the GPU with nothing else, but one noisy night can still happen. Confirm the drop over two nights before filing it.

## Re-running

- **Actions → nightly → Run workflow:**
  - `force: true` re-tests a release that was already tested.
  - `suites: rocal` runs a subset. Subset runs are never written to `tested.txt`.
  - `tier: full` adds the optional and extended checks.
- **A specific release:** `release_tag: nightly-YYYYMMDD`.
- **Build mode:** `mode: build` with `vision_pack_ref` builds any upstream ref from source.
