## Nightly QA: RED

vision-pack `0.2.0+gd440925` (nightly-20260926, `d440925b1b06`) on `?`, tier **comprehensive**, 2026-09-29.

**Why:** 5 infra error; 39 still failing.

Report: https://levxn.github.io/vision-pack-test/runs/36552425012/

| Suite | results | new failures | still failing | known | flaky | fixed | blocked | skipped |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| loader-audit | 265 | 0 | 0 | 60 | 0 | 0 | 6 | 4 |
| mivisionx | no results | | | | | | | |
| packaging | 425 | 0 | 31 | 80 | 0 | 0 | 5 | 0 |
| robustness | no results | | | | | | | |
| robustness-nogpu | 29 | 0 | 0 | 4 | 0 | 0 | 0 | 0 |
| rocal | no results | | | | | | | |
| roccv | no results | | | | | | | |
| rocpydecode | no results | | | | | | | |
| sdk-consumer | 342 | 0 | 8 | 42 | 0 | 0 | 14 | 0 |

### New and unbaselined failures (44)

- `mivisionx::infra::no-results` (error, failing 2 nights): the suite job produced no results (job failed, timed out or was cancelled)
- `packaging::install-deb::dpkg.verify` (fail, failing 2 nights): missing     /usr/share/doc/amdrocm-vision-sdk/README.Debian missing     /usr/share/doc/amdrocm-vision-tests/README.Debian missing     /usr/share/doc/amdrocm-vis
- `packaging::install-deb::install.therock` (fail, failing 2 nights): apt cannot resolve against TheRock's repo: The following packages have unmet dependencies: amdrocm-mivisionx : Depends: amdrocm-rpp (>= 10.2.0) but it is not go
- `packaging::install-deb::ldd::libopenvx.so` (fail, failing 2 nights): not found: libamdhip64.so.7 (vision libs sit in /opt/rocm/lib with $ORIGIN RUNPATHs; TheRock packages install to /opt/rocm/core-<ver>)
- `packaging::install-deb::ldd::librocal.so` (fail, failing 2 nights): not found: libhipfile.so.0 libomp.so librocdecode.so.1 librocjpeg.so.1 libamdhip64.so.7 librpp.so.3 libamdhip64.so.7 (vision libs sit in /opt/rocm/lib with $ORI
- `packaging::install-deb::ldd::libroccv.so` (fail, failing 2 nights): not found: libamdhip64.so.7 libomp.so (vision libs sit in /opt/rocm/lib with $ORIGIN RUNPATHs; TheRock packages install to /opt/rocm/core-<ver>)
- `packaging::install-deb::ldd::libvx_rpp.so` (fail, failing 2 nights): not found: librpp.so.3 libamdhip64.so.7 libamdhip64.so.7 (vision libs sit in /opt/rocm/lib with $ORIGIN RUNPATHs; TheRock packages install to /opt/rocm/core-<ve
- `packaging::install-deb::ldd::libvxu.so` (fail, failing 2 nights): not found: libamdhip64.so.7 libamdhip64.so.7 (vision libs sit in /opt/rocm/lib with $ORIGIN RUNPATHs; TheRock packages install to /opt/rocm/core-<ver>)
- `packaging::install-deb::ldd::rocal_pybind.cpython-312-x86_64-linux-gnu.so` (fail, failing 2 nights): not found: libomp.so librocdecode.so.1 librocjpeg.so.1 libhipfile.so.0 libamdhip64.so.7 librpp.so.3 libamdhip64.so.7 libhipfile.so.0 libomp.so librocdecode.so.1
- `packaging::install-deb::ldd::rocpycv.cpython-312-x86_64-linux-gnu.so` (fail, failing 2 nights): not found: libamdhip64.so.7 libamdhip64.so.7 libomp.so (vision libs sit in /opt/rocm/lib with $ORIGIN RUNPATHs; TheRock packages install to /opt/rocm/core-<ver>
- `packaging::install-deb::ldd::rocpydecode.cpython-312-x86_64-linux-gnu.so` (fail, failing 2 nights): not found: libamdhip64.so.7 librocdecode.so.1 (vision libs sit in /opt/rocm/lib with $ORIGIN RUNPATHs; TheRock packages install to /opt/rocm/core-<ver>)
- `packaging::install-deb::ldd::rocpyjpegdecode.cpython-312-x86_64-linux-gnu.so` (fail, failing 2 nights): not found: libamdhip64.so.7 librocjpeg.so.1 (vision libs sit in /opt/rocm/lib with $ORIGIN RUNPATHs; TheRock packages install to /opt/rocm/core-<ver>)
- `packaging::install-rpm::import::amd.rocal` (fail, failing 2 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'amd' 
- `packaging::install-rpm::import::pyRocVideoDecode.decoder` (fail, failing 2 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'pyRocVideoDecode' 
- `packaging::install-rpm::import::rocal_pybind` (fail, failing 2 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'rocal_pybind' 
- `packaging::install-rpm::import::rocpycv` (fail, failing 2 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'rocpycv' 
- `packaging::install-rpm::import::rocpydecode` (fail, failing 2 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'rocpydecode' 
- `packaging::install-rpm::import::rocpyjpegdecode` (fail, failing 2 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'rocpyjpegdecode' 
- `packaging::install-rpm::install.therock` (fail, failing 2 nights): dnf cannot resolve against TheRock's repo: Error: Problem 1: conflicting requests - nothing provides amdrocm-rpp >= 10.2.0 needed by amdrocm-mivisionx-0.2.0+gd4
- `packaging::install-rpm::isolation.jpeg_std_error` (fail, failing 2 nights): isolated libjpeg missing or does not export jpeg_std_error (#39)
- ... and 24 more (see the report)

### Environment

- GPU: `?`
- SDK: `?` (fallback: ?)
- Runner: ?, driver ?, kernel ?
- Upstream nightly: success https://github.com/kiritigowda/vision-pack/actions/runs/36225269840
- Compared with 2026-09-28: 0 new failures, 0 fixed, 27 new tests, 0 removed
