## Nightly QA: RED

vision-pack `10.2.0-20261009` (nightly-20261009, `10bdbf55dba2`) on `?`, tier **comprehensive**, 2026-10-09.

**Why:** 5 infra error; 50 still failing; packaging::rpm: 207 results, expected at least 221; packaging::install-deb: 0 results, expected at least 6; packaging::install-rpm: 0 results, expected at least 7; fixed known issues to remove from the baseline: H1, H3, H4.

Report: https://levxn.github.io/vision-pack-test/nightly/2026-10-09/

| Suite | results | new failures | still failing | known | flaky | fixed | blocked | skipped |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| loader-audit | 265 | 0 | 0 | 35 | 0 | 25 | 6 | 4 |
| mivisionx | no results | | | | | | | |
| packaging | 307 | 0 | 42 | 8 | 0 | 6 | 3 | 0 |
| robustness | no results | | | | | | | |
| robustness-nogpu | 29 | 0 | 0 | 3 | 0 | 1 | 0 | 0 |
| rocal | no results | | | | | | | |
| roccv | no results | | | | | | | |
| rocpydecode | no results | | | | | | | |
| sdk-consumer | 342 | 0 | 8 | 39 | 0 | 3 | 14 | 0 |

### New and unbaselined failures (55)

- `mivisionx::infra::no-results` (error, failing 11 nights): the suite job produced no results (job failed, timed out or was cancelled)
- `packaging::deb::amdrocm-vision-pythonpath10.2::payload.empty-dirs` (fail, failing 4 nights): owns directories with no payload of its own (CPack FILES_MATCHING copies the whole tree): /opt/rocm/core-10.2
- `packaging::deb::set::packages` (fail, failing 4 nights): 16 DEB files, 16 packages; missing: amdrocm-mivisionx, amdrocm-mivisionx-devel, amdrocm-mivisionx-test, amdrocm-pydecode, amdrocm-pydecode-test, amdrocm-rocal, 
- `packaging::rpm::amdrocm-mivisionx-devel10.2::header` (fail, failing 4 nights): unexpected package name; version 10.2.0_20261009-20261009 differs from DEB 10.2.0-20261009-20261009
- `packaging::rpm::amdrocm-mivisionx-test10.2::header` (fail, failing 4 nights): unexpected package name; version 10.2.0_20261009-20261009 differs from DEB 10.2.0-20261009-20261009
- `packaging::rpm::amdrocm-mivisionx10.2::header` (fail, failing 4 nights): unexpected package name; version 10.2.0_20261009-20261009 differs from DEB 10.2.0-20261009-20261009
- `packaging::rpm::amdrocm-mivisionx10.2::so-mode` (fail, failing 4 nights): shared libraries without the exec bit (rpmlint shared-library-not-executable; RPM's debuginfo and strip passes skip them): /opt/rocm/core-10.2/lib/libopenvx.so.
- `packaging::rpm::amdrocm-pydecode-test10.2::header` (fail, failing 4 nights): unexpected package name; version 10.2.0_20261009-20261009 differs from DEB 10.2.0-20261009-20261009
- `packaging::rpm::amdrocm-pydecode10.2::header` (fail, failing 4 nights): unexpected package name; version 10.2.0_20261009-20261009 differs from DEB 10.2.0-20261009-20261009
- `packaging::rpm::amdrocm-pydecode10.2::so-mode` (fail, failing 4 nights): shared libraries without the exec bit (rpmlint shared-library-not-executable; RPM's debuginfo and strip passes skip them): /opt/rocm/core-10.2/lib/rocpydecode.c
- `packaging::rpm::amdrocm-rocal-devel10.2::header` (fail, failing 4 nights): unexpected package name; version 10.2.0_20261009-20261009 differs from DEB 10.2.0-20261009-20261009
- `packaging::rpm::amdrocm-rocal-test10.2::header` (fail, failing 4 nights): unexpected package name; version 10.2.0_20261009-20261009 differs from DEB 10.2.0-20261009-20261009
- `packaging::rpm::amdrocm-rocal10.2::header` (fail, failing 4 nights): unexpected package name; version 10.2.0_20261009-20261009 differs from DEB 10.2.0-20261009-20261009
- `packaging::rpm::amdrocm-rocal10.2::requires.closure` (fail, failing 4 nights): automatic requirements no package provides (dnf: 'nothing provides ...'): libsndfile-rocm-vision.so.1(libsndfile.so.1.0)(64bit), libturbojpeg-rocm-vision.so.0(T
- `packaging::rpm::amdrocm-rocal10.2::so-mode` (fail, failing 4 nights): shared libraries without the exec bit (rpmlint shared-library-not-executable; RPM's debuginfo and strip passes skip them): /opt/rocm/core-10.2/lib/librocal.so.2
- `packaging::rpm::amdrocm-roccv-devel10.2::header` (fail, failing 4 nights): unexpected package name; version 10.2.0_20261009-20261009 differs from DEB 10.2.0-20261009-20261009
- `packaging::rpm::amdrocm-roccv-test10.2::header` (fail, failing 4 nights): unexpected package name; version 10.2.0_20261009-20261009 differs from DEB 10.2.0-20261009-20261009
- `packaging::rpm::amdrocm-roccv10.2::header` (fail, failing 4 nights): unexpected package name; version 10.2.0_20261009-20261009 differs from DEB 10.2.0-20261009-20261009
- `packaging::rpm::amdrocm-roccv10.2::so-mode` (fail, failing 4 nights): shared libraries without the exec bit (rpmlint shared-library-not-executable; RPM's debuginfo and strip passes skip them): /opt/rocm/core-10.2/lib/libroccv.so.0
- `packaging::rpm::amdrocm-vision-pythonpath10.2::header` (fail, failing 4 nights): unexpected package name; version 10.2.0_20261009-20261009 differs from DEB 10.2.0-20261009-20261009
- ... and 35 more (see the report)

### Missing tests

- `packaging::rpm`: 207 of at least 221 
- `packaging::install-deb`: 0 of at least 6 
- `packaging::install-rpm`: 0 of at least 7 

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
- Upstream nightly: not-found 
- Compared with 2026-10-08: 0 new failures, 35 fixed, 0 new tests, 51 removed
