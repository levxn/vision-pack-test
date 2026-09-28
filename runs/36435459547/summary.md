## Nightly QA: RED

vision-pack `0.2.0+gd440925` (nightly-20260926, `d440925b1b06`) on `?`, tier **quick**, 2026-09-28.

**Why:** 3 infra error; 31 new failure.

Report: https://levxn.github.io/vision-pack-test/runs/36435459547/

| Suite | results | new failures | still failing | known | flaky | fixed | blocked | skipped |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| loader-audit | 149 | 0 | 0 | 20 | 0 | 0 | 6 | 0 |
| mivisionx | no results | | | | | | | |
| packaging | 388 | 31 | 0 | 70 | 0 | 0 | 5 | 0 |
| rocal | no results | | | | | | | |
| roccv | no results | | | | | | | |

### New and unbaselined failures (34)

- `mivisionx::infra::no-results` (error): the suite job produced no results (job failed, timed out or was cancelled)
- `packaging::install-deb::dpkg.verify` (fail): missing     /usr/share/doc/amdrocm-vision-sdk/README.Debian missing     /usr/share/doc/amdrocm-vision-tests/README.Debian missing     /usr/share/doc/amdrocm-vis
- `packaging::install-deb::install.therock` (fail): apt cannot resolve against TheRock's repo: The following packages have unmet dependencies: amdrocm-mivisionx : Depends: amdrocm-rpp (>= 10.2.0) but it is not go
- `packaging::install-deb::ldd::libopenvx.so` (fail): not found: libamdhip64.so.7 (vision libs sit in /opt/rocm/lib with $ORIGIN RUNPATHs; TheRock packages install to /opt/rocm/core-<ver>)
- `packaging::install-deb::ldd::librocal.so` (fail): not found: libhipfile.so.0 libomp.so librocdecode.so.1 librocjpeg.so.1 libamdhip64.so.7 librpp.so.3 libamdhip64.so.7 (vision libs sit in /opt/rocm/lib with $ORI
- `packaging::install-deb::ldd::libroccv.so` (fail): not found: libamdhip64.so.7 libomp.so (vision libs sit in /opt/rocm/lib with $ORIGIN RUNPATHs; TheRock packages install to /opt/rocm/core-<ver>)
- `packaging::install-deb::ldd::libvx_rpp.so` (fail): not found: librpp.so.3 libamdhip64.so.7 libamdhip64.so.7 (vision libs sit in /opt/rocm/lib with $ORIGIN RUNPATHs; TheRock packages install to /opt/rocm/core-<ve
- `packaging::install-deb::ldd::libvxu.so` (fail): not found: libamdhip64.so.7 libamdhip64.so.7 (vision libs sit in /opt/rocm/lib with $ORIGIN RUNPATHs; TheRock packages install to /opt/rocm/core-<ver>)
- `packaging::install-deb::ldd::rocal_pybind.cpython-312-x86_64-linux-gnu.so` (fail): not found: libomp.so librocdecode.so.1 librocjpeg.so.1 libhipfile.so.0 libamdhip64.so.7 librpp.so.3 libamdhip64.so.7 libhipfile.so.0 libomp.so librocdecode.so.1
- `packaging::install-deb::ldd::rocpycv.cpython-312-x86_64-linux-gnu.so` (fail): not found: libamdhip64.so.7 libamdhip64.so.7 libomp.so (vision libs sit in /opt/rocm/lib with $ORIGIN RUNPATHs; TheRock packages install to /opt/rocm/core-<ver>
- `packaging::install-deb::ldd::rocpydecode.cpython-312-x86_64-linux-gnu.so` (fail): not found: libamdhip64.so.7 librocdecode.so.1 (vision libs sit in /opt/rocm/lib with $ORIGIN RUNPATHs; TheRock packages install to /opt/rocm/core-<ver>)
- `packaging::install-deb::ldd::rocpyjpegdecode.cpython-312-x86_64-linux-gnu.so` (fail): not found: libamdhip64.so.7 librocjpeg.so.1 (vision libs sit in /opt/rocm/lib with $ORIGIN RUNPATHs; TheRock packages install to /opt/rocm/core-<ver>)
- `packaging::install-rpm::import::amd.rocal` (fail): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'amd' 
- `packaging::install-rpm::import::pyRocVideoDecode.decoder` (fail): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'pyRocVideoDecode' 
- `packaging::install-rpm::import::rocal_pybind` (fail): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'rocal_pybind' 
- `packaging::install-rpm::import::rocpycv` (fail): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'rocpycv' 
- `packaging::install-rpm::import::rocpydecode` (fail): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'rocpydecode' 
- `packaging::install-rpm::import::rocpyjpegdecode` (fail): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'rocpyjpegdecode' 
- `packaging::install-rpm::install.therock` (fail): dnf cannot resolve against TheRock's repo: Error: Problem 1: conflicting requests - nothing provides amdrocm-rpp >= 10.2.0 needed by amdrocm-mivisionx-0.2.0+gd4
- `packaging::install-rpm::isolation.jpeg_std_error` (fail): isolated libjpeg missing or does not export jpeg_std_error (#39)
- ... and 14 more (see the report)

### Environment

- GPU: `?`
- SDK: `?` (fallback: ?)
- Runner: ?, driver ?, kernel ?
- Upstream nightly: success https://github.com/kiritigowda/vision-pack/actions/runs/36225269840
