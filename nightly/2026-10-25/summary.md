## Nightly QA: RED

vision-pack `10.2.0-20261015` (nightly-20261015, `ef871403eb79`) on no GPU, tier **comprehensive**, 2026-10-25.

**Why:** runner had no usable GPU (no self-hosted runner is registered (vp-gpu/vp-cpu); set the VP_HAS_SELF_HOSTED repo variable once one is): 5 GPU suites did not run; 3 infra error; 1 new failure; 10 still failing; packaging::deb: 0 results, expected at least 46; packaging::rpm: 0 results, expected at least 221; fixed known issues to remove from the baseline: H4, N6.

Report: https://levxn.github.io/vision-pack-test/nightly/2026-10-25/

| Suite | results | new failures | still failing | known | flaky | fixed | blocked | skipped |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| loader-audit | no results | | | | | | | |
| mivisionx | not run: no GPU | | | | | | | |
| packaging | 154 | 1 | 10 | 5 | 0 | 10 | 0 | 0 |
| preflight | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| robustness | not run: no GPU | | | | | | | |
| robustness-nogpu | no results | | | | | | | |
| rocal | not run: no GPU | | | | | | | |
| roccv | not run: no GPU | | | | | | | |
| rocpydecode | not run: no GPU | | | | | | | |
| sdk-consumer | no results | | | | | | | |

### New and unbaselined failures (20)

- `loader-audit::infra::no-results` (error, failing 2 nights): the suite job produced no results (job failed, timed out or was cancelled)
- `mivisionx::infra::no-gpu` (error, failing 2 nights): not run: the runner had no usable GPU (no self-hosted runner is registered (vp-gpu/vp-cpu); set the VP_HAS_SELF_HOSTED repo variable once one is)
- `packaging::install-deb::dpkg.verify` (fail, failing 7 nights): missing     /usr/share/doc/amdrocm-vision-sdk10.2/README.Debian missing     /usr/share/doc/amdrocm-vision-tests10.2/README.Debian missing     /usr/share/doc/amd
- `packaging::install-deb::pth.shipped` (fail, failing 7 nights): /usr/lib/python3/dist-packages/amdrocm-vision10.2.pth missing or not '/opt/rocm/lib'
- `packaging::install-deb::pth.syspath` (fail, failing 7 nights): /opt/rocm/lib not on sys.path of Python 3.12.3: the .pth is not honoured
- `packaging::install-rpm::depends::python3.12` (fail, failing 7 nights): not in the repository (needs any; required by amdrocm-pydecode10.2, amdrocm-rocal10.2, amdrocm-roccv10.2, amdrocm-vision-pythonpath10.2)
- `packaging::install-rpm::isolation.jpeg_std_error` (fail): isolated libjpeg missing or does not export jpeg_std_error (#39)
- `packaging::install-rpm::pth.python3.12` (fail, failing 7 nights): python3.12 (the only interpreter the cp312 modules load in) does not get /opt/rocm/lib: %post registered the path for Python 3.9.25 only
- `packaging::install-rpm::pth.shipped` (fail, failing 7 nights): no amdrocm-vision10.2.pth in any python3 site-packages; %post did not register it
- `packaging::install-rpm::pth.syspath` (fail, failing 7 nights): /opt/rocm/lib not on sys.path of Python 3.9.25
- `packaging::tarball::deb-subset` (fail, failing 11 nights): missing from tarball: core-10.2/lib/pkgconfig/openvx.pc (amdrocm-mivisionx-devel10.2), core-10.2/lib/pkgconfig/vx_rpp.pc (amdrocm-mivisionx-devel10.2), core-10.
- `packaging::tarball::layout` (fail, failing 4 nights): top-level: README-vision-pack.md bin include lib share; unexpected: README-vision-pack.md
- `packaging::tarball::name` (fail, failing 11 nights): file version 10.2.0-20261015, manifest version 0.2.0+gef87140
- `preflight::infra::no-gpu` (error, failing 2 nights): the runner had no usable GPU (no self-hosted runner is registered (vp-gpu/vp-cpu); set the VP_HAS_SELF_HOSTED repo variable once one is); only the needs_gpu: fa
- `robustness::infra::no-gpu` (error, failing 2 nights): not run: the runner had no usable GPU (no self-hosted runner is registered (vp-gpu/vp-cpu); set the VP_HAS_SELF_HOSTED repo variable once one is)
- `robustness-nogpu::infra::no-results` (error, failing 2 nights): the suite job produced no results (job failed, timed out or was cancelled)
- `rocal::infra::no-gpu` (error, failing 2 nights): not run: the runner had no usable GPU (no self-hosted runner is registered (vp-gpu/vp-cpu); set the VP_HAS_SELF_HOSTED repo variable once one is)
- `roccv::infra::no-gpu` (error, failing 2 nights): not run: the runner had no usable GPU (no self-hosted runner is registered (vp-gpu/vp-cpu); set the VP_HAS_SELF_HOSTED repo variable once one is)
- `rocpydecode::infra::no-gpu` (error, failing 2 nights): not run: the runner had no usable GPU (no self-hosted runner is registered (vp-gpu/vp-cpu); set the VP_HAS_SELF_HOSTED repo variable once one is)
- `sdk-consumer::infra::no-results` (error, failing 2 nights): the suite job produced no results (job failed, timed out or was cancelled)

### Missing tests

- `packaging::deb`: 0 of at least 46 upstream validate_packages.sh: 13 packages + 3 metas, plus extra checks
- `packaging::rpm`: 0 of at least 221 

### Known issues that passed tonight

- H4: No license texts for redistributed third-party code (libsndfile, protobuf, libjpeg-turbo, LMDB, rapidjson, pybind11, dlpack)
- M3: No install or usage documentation for the tarball (location, PYTHONPATH, Python 3.12 only, numpy)
- N6: amdrocm-rocal RPM auto-requires libsndfile/libturbojpeg version capabilities that no package provides

### Environment

- GPU: none (no self-hosted runner is registered (vp-gpu/vp-cpu); set the VP_HAS_SELF_HOSTED repo variable once one is)
- SDK: `?` (fallback: ?)
- Runner: github-hosted (no self-hosted runner registered), driver , kernel 
- Upstream nightly: not-found 
- Compared with 2026-10-23: 1 new failures, 10 fixed, 0 new tests, 0 removed
