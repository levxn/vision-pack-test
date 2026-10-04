## Nightly QA: RED

vision-pack `0.2.0+ga7f1c71` (nightly-20261004, `a7f1c713d72b`) on `?`, tier **full**, 2026-10-04.

**Why:** 6 infra error; 1 new failure; 37 still failing; fixed known issues to remove from the baseline: H1, H3, H4, N5.

Report: https://levxn.github.io/vision-pack-test/nightly/2026-10-04/

| Suite | results | new failures | still failing | known | flaky | fixed | blocked | skipped |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| install-test | no results | | | | | | | |
| loader-audit | 265 | 0 | 0 | 45 | 0 | 15 | 6 | 4 |
| mivisionx | no results | | | | | | | |
| packaging | 425 | 0 | 29 | 25 | 0 | 53 | 9 | 0 |
| robustness | no results | | | | | | | |
| robustness-nogpu | 29 | 0 | 0 | 3 | 0 | 1 | 0 | 0 |
| rocal | no results | | | | | | | |
| roccv | no results | | | | | | | |
| rocpydecode | no results | | | | | | | |
| sdk-consumer | 342 | 1 | 8 | 40 | 0 | 2 | 14 | 0 |

### New and unbaselined failures (44)

- `install-test::infra::no-results` (error, failing 2 nights): the suite job produced no results (job failed, timed out or was cancelled)
- `mivisionx::infra::no-results` (error, failing 2 nights): the suite job produced no results (job failed, timed out or was cancelled)
- `packaging::install-deb::dpkg.verify` (fail, failing 2 nights): missing     /usr/share/doc/amdrocm-vision-sdk/README.Debian missing     /usr/share/doc/amdrocm-vision-tests/README.Debian missing     /usr/share/doc/amdrocm-vis
- `packaging::install-deb::import::pyRocVideoDecode.decoder` (fail, failing 2 nights): rc 1:   File "/opt/rocm/lib/pyRocVideoDecode/decoder.py", line 21, in <module>     import rocpydecode as rocpydec ImportError: libamdhip64.so.7: cannot open sha
- `packaging::install-deb::import::rocal_pybind` (fail, failing 2 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ImportError: libomp.so: cannot open shared object file: No such file or director
- `packaging::install-deb::import::rocpycv` (fail, failing 2 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ImportError: libamdhip64.so.7: cannot open shared object file: No such file or d
- `packaging::install-deb::import::rocpydecode` (fail, failing 2 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ImportError: libamdhip64.so.7: cannot open shared object file: No such file or d
- `packaging::install-deb::import::rocpyjpegdecode` (fail, failing 2 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ImportError: libamdhip64.so.7: cannot open shared object file: No such file or d
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
- ... and 24 more (see the report)

### Known issues that passed tonight

- H1: librocal needs libpython (113 undefined CPython symbols, no libpython dependency)
- H3: FindMIVisionX.cmake exports include/ instead of include/mivisionx
- H4: No license texts for redistributed third-party code (libsndfile, protobuf, libjpeg-turbo, LMDB, rapidjson, pybind11, dlpack)
- N2: The -test packages omit their -devel build dependencies; MIVisionX openvx_graph reads samples from mivisionx-devel
- N5: DEB/RPM Depends cannot be satisfied from TheRock's nightly repos (no hip-runtime-amd; '>= 10.2.0' vs '10.2.0~<date>' versions)
- N10: rocPyJpegDecode initialize_hip() terminates the interpreter without a GPU instead of raising

### Environment

- GPU: `?`
- SDK: `?` (fallback: ?)
- Runner: ?, driver ?, kernel ?
- Upstream nightly: not-found 
- Compared with 2026-10-03: 1 new failures, 71 fixed, 0 new tests, 0 removed
