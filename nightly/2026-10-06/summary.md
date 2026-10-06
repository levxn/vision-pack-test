## Nightly QA: RED

vision-pack `10.2.0-20261006` (nightly-20261006, `d8ffdf5c12e9`) on `?`, tier **comprehensive**, 2026-10-06.

**Why:** 5 infra error; 53 new failure; 25 still failing; packaging::rpm: 207 results, expected at least 221; fixed known issues to remove from the baseline: H1, H3, H4.

Report: https://levxn.github.io/vision-pack-test/nightly/2026-10-06/

| Suite | results | new failures | still failing | known | flaky | fixed | blocked | skipped |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| loader-audit | 265 | 0 | 0 | 35 | 0 | 25 | 6 | 4 |
| mivisionx | no results | | | | | | | |
| packaging | 358 | 53 | 16 | 9 | 0 | 6 | 3 | 0 |
| robustness | no results | | | | | | | |
| robustness-nogpu | 29 | 0 | 0 | 3 | 0 | 1 | 0 | 0 |
| rocal | no results | | | | | | | |
| roccv | no results | | | | | | | |
| rocpydecode | no results | | | | | | | |
| sdk-consumer | 342 | 0 | 9 | 39 | 0 | 3 | 14 | 0 |

### New and unbaselined failures (83)

- `mivisionx::infra::no-results` (error, failing 8 nights): the suite job produced no results (job failed, timed out or was cancelled)
- `packaging::deb::amdrocm-vision-pythonpath10.2::payload.empty-dirs` (fail): owns directories with no payload of its own (CPack FILES_MATCHING copies the whole tree): /opt/rocm/core-10.2
- `packaging::deb::set::packages` (fail): 16 DEB files, 16 packages; missing: amdrocm-mivisionx, amdrocm-mivisionx-devel, amdrocm-mivisionx-test, amdrocm-pydecode, amdrocm-pydecode-test, amdrocm-rocal, 
- `packaging::install-deb::dpkg.verify` (fail, failing 8 nights): missing     /usr/share/doc/amdrocm-vision-sdk10.2/README.Debian missing     /usr/share/doc/amdrocm-vision-tests10.2/README.Debian missing     /usr/share/doc/amd
- `packaging::install-deb::import::amd.rocal` (fail): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'amd' 
- `packaging::install-deb::import::pyRocVideoDecode.decoder` (fail, failing 4 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'pyRocVideoDecode' 
- `packaging::install-deb::import::rocal_pybind` (fail, failing 4 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'rocal_pybind' 
- `packaging::install-deb::import::rocpycv` (fail, failing 4 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'rocpycv' 
- `packaging::install-deb::import::rocpydecode` (fail, failing 4 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'rocpydecode' 
- `packaging::install-deb::import::rocpyjpegdecode` (fail, failing 4 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'rocpyjpegdecode' 
- `packaging::install-deb::isolation.jpeg_std_error` (fail): isolated libjpeg missing or does not export jpeg_std_error (#39)
- `packaging::install-deb::isolation.librocal` (fail): /opt/rocm/lib/librocal.so missing or unreadable
- `packaging::install-deb::isolation.needed` (fail): no vision libraries found under /opt/rocm/lib
- `packaging::install-deb::pth.shipped` (fail): /usr/lib/python3/dist-packages/amdrocm-vision.pth missing or not '/opt/rocm/lib'
- `packaging::install-deb::pth.syspath` (fail): /opt/rocm/lib not on sys.path of Python 3.12.3: the .pth is not honoured
- `packaging::install-rpm::depends::python3.12` (fail): not in the repository (needs any; required by amdrocm-vision-pythonpath10.2)
- `packaging::install-rpm::import::amd.rocal` (fail, failing 8 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'amd' 
- `packaging::install-rpm::import::pyRocVideoDecode.decoder` (fail, failing 8 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'pyRocVideoDecode' 
- `packaging::install-rpm::import::rocal_pybind` (fail, failing 8 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'rocal_pybind' 
- `packaging::install-rpm::import::rocpycv` (fail, failing 8 nights): rc 1: Traceback (most recent call last):   File "<string>", line 1, in <module> ModuleNotFoundError: No module named 'rocpycv' 
- ... and 63 more (see the report)

### Missing tests

- `packaging::rpm`: 207 of at least 221 

### Known issues that passed tonight

- H1: librocal needs libpython (113 undefined CPython symbols, no libpython dependency)
- H3: FindMIVisionX.cmake exports include/ instead of include/mivisionx
- H4: No license texts for redistributed third-party code (libsndfile, protobuf, libjpeg-turbo, LMDB, rapidjson, pybind11, dlpack)
- N10: rocPyJpegDecode initialize_hip() terminates the interpreter without a GPU instead of raising
- L-stdcxx-leak: Leaked C++ standard-library symbols in vision libraries and Python modules
- L-hardening: Bundled parsers built without stack-protector and FORTIFY
- L-findrocal-include: Findrocal requires <rocal/rocal_api.h> rather than the documented "rocal_api.h"

### Environment

- GPU: `?`
- SDK: `?` (fallback: ?)
- Runner: ?, driver ?, kernel ?
- Upstream nightly: success https://github.com/kiritigowda/vision-pack/actions/runs/37500387090
- Compared with 2026-10-05: 53 new failures, 35 fixed, 224 new tests, 330 removed
