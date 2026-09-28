# Self-hosted GPU runner

The nightly QA pipeline runs its GPU suites on one dedicated Linux machine with an AMD GPU. This directory holds everything needed to turn that machine into a locked-down runner for `levxn/vision-pack-test`.

- `setup.sh`: one-time bootstrap, run as root on the runner host.
- `hooks/job-started.sh`: the pre-job gate. It rejects every job except the nightly workflow on `main`.
- `hooks/job-completed.sh`: post-job cleanup (orphaned containers, file ownership, old run prefixes).
- `hooks/vp-reclaim.sh`: gives root-owned files written by container jobs back to the runner user.
- `cron/vp-ci-prune`: daily Docker and SDK-cache pruning.

## Before you start

1. **Hardware and OS.** Ubuntu 24.04 (22.04 also works), one AMD GPU that the vision libraries are built for (gfx908/90a/942/950, gfx1030–1032, gfx110X, gfx115X, gfx120X or gfx1250), and at least 200 GB free under `/srv`. A multi-arch ROCm SDK fallback alone is 15.6 GB.
2. **Kernel driver.** The pipeline brings its own ROCm user space (TheRock nightly tarballs), but the host needs the `amdgpu` kernel driver with KFD:
   - RDNA4 (gfx120X) needs a kernel of 6.12 or newer, or AMD's `amdgpu-dkms` package.
   - Check that `/dev/kfd` and `/dev/dri/renderD*` exist, and that `cat /sys/class/kfd/kfd/topology/nodes/*/properties | grep gfx_target_version` shows your GPU.
3. **Repository settings** (do these first; see "Security model" below):
   - Settings → Actions → General → "Fork pull request workflows from outside collaborators" → **Require approval for all external contributors**.
   - Settings → Actions → General → Workflow permissions → **Read repository contents and packages permissions**.
   - Settings → Actions → General → **Require actions to be pinned to a full-length commit SHA** (optional; the workflows are written for it).
   - Settings → Rules → a ruleset protecting `main` (block force pushes, require PRs).
   - Settings → Pages → Source: **GitHub Actions** (the report is published there).

## Install

On the runner host:

```bash
git clone https://github.com/levxn/vision-pack-test.git
cd vision-pack-test
# Token: repo Settings -> Actions -> Runners -> New self-hosted runner (valid 1 hour)
sudo ./runner/setup.sh --repo levxn/vision-pack-test --token <REGISTRATION_TOKEN> \
     --data-src /path/to/MIVisionX-data
```

What the script does:

- Installs Docker, `jq`, `curl`, `git-lfs`, `pigz`, `zstd` and Python 3 with PyYAML.
- Creates the non-root user `ci-runner` and adds it to the `docker`, `video` and `render` groups. It gets no sudo rights.
- Creates `/srv/vp-ci/{cache,data,runs}`:
  - `cache/sdk`: ROCm SDK tarballs, downloaded once and verified by sha256.
  - `data/MIVisionX-data`: a read-only copy of the rocAL test data (`--data-src` must contain `rocal_data/`). It never leaves this machine.
  - `runs/<run>`: the per-run ROCm prefix (SDK plus the vision-pack tarball overlay). The newest 5 are kept.
- Installs the hooks into `/opt/vp-hooks` (root-owned) with their config in `/etc/vp-ci/hooks.conf`.
- Disables apport, so crashing tests never write to `/var/crash`, and sets `kernel.core_pattern=core`.
- Excludes the runner service from `needrestart`, so package updates can't restart it mid-job.
- Downloads the latest `actions/runner` (verifying the checksum from its release notes), registers it with label `vp-gpu` and `--no-default-labels`, writes a root-owned `.env` that enables the hooks, and installs it as a systemd service.

Options:

- `--with-cpu-runner`: registers a second instance, `vp-cpu`, on the same machine for the CPU-only suites (loader-audit, sdk-consumer). It shortens the nightly by running them next to the GPU suites.
- `--name <name>`: runner name (default `vp-gpu-01`).
- `--runner-version <x.y.z>`: pin the runner version (2.329.0 or newer is required to register).
- `--skip-register`: install everything except the GitHub registration.

Afterwards, the runner should show as **Idle** under Settings → Actions → Runners. Then set the repository variable `VP_HAS_SELF_HOSTED=true` (Settings → Secrets and variables → Actions → Variables): until this is set, `test.yml` assumes no self-hosted runner exists at all and runs the `needs_gpu: false` suites on a GitHub-hosted runner instead (see [README.md](../README.md#setup)); with it set, `prepare-rocm` runs here as usual, and detects whether this specific machine's GPU is usable. Optionally also set `EXPECTED_GFX` (e.g. `gfx1201`): the pipeline then fails loudly if the detected GPU ever changes, instead of silently testing a different one.

## Security model

vision-pack-test is a public repository, and GitHub warns that self-hosted runners should almost never serve public repositories. Workflow triggers alone do not protect the runner, because a fork pull request can add its own workflow that targets the runner's label. The protections, from strongest to weakest:

1. **The pre-job hook.** Before any job step runs, `/opt/vp-hooks/job-started.sh` rejects the job unless:
   - the event is `schedule` or `workflow_dispatch`;
   - the repository is `levxn/vision-pack-test`;
   - `GITHUB_WORKFLOW_REF` is `.github/workflows/nightly.yml@refs/heads/main` (jobs of reusable workflows report their caller, so `test.yml` and `report.yml` jobs pass);
   - Docker works, and at least 100 GB is free.

   A missing `/dev/kfd` or `/dev/dri/renderD*` on the GPU instance is only a warning while `VP_ALLOW_NO_GPU=1` (see "Operating notes"). It does not relax any of the checks above.

   The hook lives outside the repository and is root-owned, so no pull request can change it.
2. **Repository settings** (see "Before you start"): approval for all external contributors, read-only default token, SHA-pinned actions, protected `main`.
3. **Workflow design:** GPU jobs only exist in workflows triggered by `schedule`/`workflow_dispatch`. `lint.yml`, the only PR workflow, runs on GitHub-hosted runners.
4. **Blast radius:** the runner user has no secrets, SSH keys or sudo on the box. Membership in the `docker` group is root-equivalent, so treat anything that reaches the runner as able to become root.

Making the repository private removes most of this exposure. Runner groups (restricting a runner to one repository and workflow) exist only for organizations; if `levxn` is a personal account, the runner is registered at repository level, which is what `setup.sh` does.

## Operating notes

- **Updates:** keep runner auto-update on. A runner older than the minimum version stops receiving jobs.
- **Disk:** the pre-job hook refuses jobs below 100 GB free. `cron.daily/vp-ci-prune` removes old images and keeps the newest 6 SDK tarballs (touch `<tarball>.keep` to pin a known-good one).
- **Logs:** `journalctl -u 'actions.runner.*'`, plus `_diag/` inside `/srv/actions-runner/<name>/`.
- **Hook rejections** appear as a failed job with an error annotation `vp-ci pre-job hook: ...`. If you rename `nightly.yml` or dispatch from a branch other than `main`, that is expected.
- **No usable GPU on this machine** (the driver did not load after a kernel update, the GPU fell off the bus, or it was swapped for one the build does not target):
  - With `VP_ALLOW_NO_GPU=1` in `/etc/vp-ci/hooks.conf` (the default), the jobs still run and the pre-job hook only warns.
  - `prepare-rocm` then builds the prefix from vision-pack's build SDK, and only loader-audit, sdk-consumer and robustness-nogpu run.
  - The report is red with one "runner had no usable GPU" reason and one issue, and the release is not recorded as tested, so the next poll re-tests it once the GPU is back.
  - `VP_ALLOW_NO_GPU=0` restores the old behaviour of rejecting every job on the GPU instance.

  A GPU that differs from `EXPECTED_GFX` still fails `prepare-rocm`.
- **No self-hosted runner registered at all** (a different case from the one above: nothing here even has the `vp-gpu`/`vp-cpu` label yet, e.g. before `setup.sh` has ever run, or `VP_HAS_SELF_HOSTED` isn't set): `prepare-rocm` and the self-hosted `test-*` jobs are skipped outright, so they never queue and hang. `test.yml` instead runs `prepare-nogpu-hosted`/`test-nogpu-hosted` on a plain GitHub-hosted runner, with the same "no usable GPU" red-night behaviour. Set `VP_HAS_SELF_HOSTED=true` once this machine is registered, GPU or not, to switch back to running here.
- **Changing the hooks:** edit them in this repository, then re-run `sudo ./runner/setup.sh --repo levxn/vision-pack-test --skip-register` on the host. The hooks in `/opt/vp-hooks` are root-owned copies, so a `git pull` alone does not update them (this applies to the `VP_ALLOW_NO_GPU` change as well). `setup.sh` also rewrites `/etc/vp-ci/hooks.conf` with its defaults, so re-apply any local edits afterwards.
- **Removing the runner:** `cd /srv/actions-runner/<name> && sudo ./svc.sh uninstall && sudo -u ci-runner ./config.sh remove --token <REMOVAL_TOKEN>`.
