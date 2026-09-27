# packaging suite

Checks on the release artifacts themselves: the 16 DEBs, 16 RPMs and the dist
tarball of a `nightly-YYYYMMDD` release, laid out by `build_tools/fetch_release.sh`
as `<dest>/deb/*.deb`, `<dest>/rpm/*.rpm`, `<dest>/tarball/*.tar.gz` and
`<dest>/release.json`.

Each script sources `build_tools/lib/vp.sh`, writes `results.jsonl`,
`junit/<suite>.xml`, `summary.json`, `suite.json` and `logs/` under `--out`, and
exits 0 once results are recorded (non-zero only for bad arguments or a missing
root). They all emit suite `packaging` (except `install_test.sh`: suite
`install-test`), so give every job its own `--out` and artifact name; the groups
(`deb`, `rpm`, `tarball`, `install-deb`, `install-rpm`) keep the IDs distinct when
the results are merged.

`vp_init` requires `ROCM_PATH`. The hosted jobs have no ROCm prefix, so when
`ROCM_PATH` is unset the scripts point it at an empty `<out>/work/no-rocm-prefix`,
which keeps any ROCm install out of `PATH` and `PYTHONPATH`. `VP_KEEP_WORK=1`
keeps the extracted RPM payloads and tarball tree in `<out>/work`; by default
they are deleted, so upload `<out>` excluding `work/`.

| Script | Where | Inputs | Test IDs |
|---|---|---|---|
| `validate_debs.sh --debs D --out O` | hosted | DEBs; `$VP_VISION_PACK_SRC` (pinned submodule) | `packaging::deb::<pkg>`, `::cross-package`, `::summary`, `::set::*`, `::<pkg>::license.*`, `::<test-pkg>::{depends.devel,refs.closure,refs.any-package}` |
| `validate_rpms.sh --rpms R [--debs D] --out O` | hosted | RPMs (+ DEBs to compare) | `packaging::rpm::set::*`, `packaging::rpm::<pkg>::<check>` |
| `verify_tarball.sh --tarball T [--debs D] [--release-json J] --out O` | hosted | tarball, DEBs, release JSON | `packaging::tarball::<check>`, `packaging::tarball::runpath::<object>` |
| `install_smoke_deb.sh --debs D --out O [--therock-date YYYYMMDD]` | `ubuntu:24.04` container, root | DEBs, network | `packaging::install-deb::*` |
| `install_smoke_rpm.sh --rpms R --out O [--therock-date YYYYMMDD]` | `rockylinux:9` container, root | RPMs, network | `packaging::install-rpm::*` |
| `install_test.sh` | GPU runner, test container (suite `install-test`, full tier) | `ROCM_PATH` (SDK prefix), `VP_DEB_DIR` | `install-test::install::*`, `install-test::<lib>::*` |

`pkgcheck.py` holds the DEB/RPM/tarball analysis and the repository-index
dependency check for all of them (Python 3.9+, stdlib only).

## TheRock nightly package repositories

Verified 2026-09-27; unsigned, so APT needs `[trusted=yes]` and dnf `gpgcheck=0`:

- APT: `https://nightly.repo.amd.com/rocm/core/packages/ubuntu2404/<YYYYMMDD>-<run id>` with suite
  `stable`, component `main` (`deb/<id>` is an alias). Other distros: `ubuntu2204`, `ubuntu2604`, `debian12`, `debian13`.
- RPM: `https://nightly.repo.amd.com/rocm/core/packages/rhel9/<YYYYMMDD>-<run id>/x86_64` (also `rhel8`,
  `rhel10`, `sles15`, `sles16`, `azl3`; `rpm/<id>/x86_64` is an alias).
- The older `https://rocm.nightlies.amd.com/{deb,rpm}/` (per-family) trees stop at 20260612 and
  `https://rocm.nightlies.amd.com/packages-multi-arch/` at 20260822.

The scripts list `<base>/<distro>/`, take the build for `--therock-date` (pass the
date from the manifest's `rocm_sdk`, e.g. `10.2.0a20260926` -> `20260926`) or the
latest, and accept `VP_THEROCK_DEB_REPO` / `VP_THEROCK_RPM_REPO` overrides. TheRock
packages install under `/opt/rocm/core-<ver>` and are versioned `10.2.0~<date>-<run id>`.

## Install modes

`install-deb::install` / `install-rpm::install` record the mode in their message:

- `therock`: everything resolved from TheRock's repository.
- `stubs+therock-libs` (DEB) / `nodeps+therock-libs` (RPM): the unresolvable ROCm Depends are stubbed (equivs) or
  ignored (`rpm -i --nodeps`), and TheRock's versioned library packages (`amdrocm-rpp10.2`, `amdrocm-runtime10.2`,
  ...) are installed so `ldd` and imports can be judged.
- `stubs` / `nodeps`: no ROCm libraries; `ldd` and import records become `blocked`.
- `force-depends`: equivs unavailable, `dpkg -i --force-depends`.

The install scripts refuse to run unless they are root in a container, on a
GitHub-hosted runner, or `VP_ALLOW_SYSTEM_INSTALL=1` is set. `--plan-only` runs the
read-only part (package list, Depends parsing, repository checks) as any user.

## test.yml usage

```yaml
validate-packages:
  runs-on: ubuntu-24.04
  steps:
    - run: sudo apt-get install -y --no-install-recommends rpm cpio jq
    - run: suites/packaging/validate_debs.sh --debs rel/deb --out out/packaging-deb
    - run: suites/packaging/validate_rpms.sh --rpms rel/rpm --debs rel/deb --out out/packaging-rpm
verify-tarball:
  runs-on: ubuntu-24.04
  steps:
    - run: suites/packaging/verify_tarball.sh --tarball rel/tarball/vision-pack-dist-linux-multiarch-*.tar.gz
             --debs rel/deb --release-json rel/release.json --out out/packaging-tarball
install-smoke-deb:
  runs-on: ubuntu-24.04
  steps:
    - run: docker run --rm -v "$PWD:/w" -w /w -e GITHUB_ACTIONS ubuntu:24.04
             suites/packaging/install_smoke_deb.sh --debs rel/deb --out out/packaging-install-deb
             --therock-date "$SDK_DATE"
install-smoke-rpm:
  runs-on: ubuntu-24.04
  steps:
    - run: docker run --rm -v "$PWD:/w" -w /w rockylinux:9
             suites/packaging/install_smoke_rpm.sh --rpms rel/rpm --out out/packaging-install-rpm
             --therock-date "$SDK_DATE"
```

The checkout must include the `vision-pack` submodule at the release commit
(`validate_debs.sh` runs its `build_tools/validate_packages.sh`; `verify_tarball.sh`
reads `packaging/CMakeLists.txt`). `validate_debs.sh` appends the "Package
validation summary" to `$GITHUB_STEP_SUMMARY`. `install_test.sh` runs through
`build_tools/run_in_container.sh` like any GPU suite; it needs the DEBs inside the
container at `VP_DEB_DIR` (default `/opt/vp/debs`).
