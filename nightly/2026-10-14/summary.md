## Nightly QA: RED

vision-pack `10.2.0-20261014` (nightly-20261014, `27b564b02575`) on `?`, tier **comprehensive**, 2026-10-14.

**Why:** 5 infra error; 16 new failure; 60 still failing; packaging::rpm: 207 results, expected at least 221; fixed known issues to remove from the baseline: H1, H3, H4, N6.

Report: https://levxn.github.io/vision-pack-test/nightly/2026-10-14/

| Suite | results | new failures | still failing | known | flaky | fixed | blocked | skipped |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| loader-audit | 265 | 0 | 0 | 23 | 0 | 37 | 6 | 4 |
| mivisionx | no results | | | | | | | |
| packaging | 358 | 16 | 52 | 5 | 0 | 10 | 3 | 0 |
| robustness | no results | | | | | | | |
| robustness-nogpu | 29 | 0 | 0 | 3 | 0 | 1 | 0 | 0 |
| rocal | no results | | | | | | | |
| roccv | no results | | | | | | | |
| rocpydecode | no results | | | | | | | |
| sdk-consumer | 342 | 0 | 8 | 39 | 0 | 3 | 14 | 0 |

### New and unbaselined failures (81)

- `mivisionx::infra::no-results` (error, failing 15 nights): the suite job produced no results (job failed, timed out or was cancelled)
- `packaging::deb::amdrocm-vision-pythonpath10.2::payload.empty-dirs` (fail, failing 8 nights): owns directories with no payload of its own (CPack FILES_MATCHING copies the whole tree): /opt/rocm/core-10.2
- `packaging::deb::set::packages` (fail, failing 8 nights): 16 DEB files, 16 packages; missing: amdrocm-mivisionx, amdrocm-mivisionx-devel, amdrocm-mivisionx-test, amdrocm-pydecode, amdrocm-pydecode-test, amdrocm-rocal, 
- `packaging::install-deb::dpkg.verify` (fail, failing 4 nights): missing     /usr/share/doc/amdrocm-vision-sdk10.2/README.Debian missing     /usr/share/doc/amdrocm-vision-tests10.2/README.Debian missing     /usr/share/doc/amd
- `packaging::install-deb::isolation.jpeg_std_error` (fail, failing 4 nights): isolated libjpeg missing or does not export jpeg_std_error (#39)
- `packaging::install-deb::isolation.librocal` (fail, failing 4 nights): /opt/rocm/lib/librocal.so missing or unreadable
- `packaging::install-deb::isolation.needed` (fail, failing 4 nights): no vision libraries found under /opt/rocm/lib
- `packaging::install-deb::pth.shipped` (fail, failing 4 nights): /usr/lib/python3/dist-packages/amdrocm-vision.pth missing or not '/opt/rocm/lib'
- `packaging::install-deb::pth.syspath` (fail, failing 4 nights): /opt/rocm/lib not on sys.path of Python 3.12.3: the .pth is not honoured
- `packaging::install-rpm::depends::python3.12` (fail, failing 4 nights): not in the repository (needs any; required by amdrocm-pydecode10.2, amdrocm-rocal10.2, amdrocm-roccv10.2, amdrocm-vision-pythonpath10.2)
- `packaging::install-rpm::isolation.jpeg_std_error` (fail, failing 4 nights): isolated libjpeg missing or does not export jpeg_std_error (#39)
- `packaging::install-rpm::isolation.librocal` (fail, failing 4 nights): /opt/rocm/lib/librocal.so missing or unreadable
- `packaging::install-rpm::isolation.needed` (fail, failing 4 nights): no vision libraries found under /opt/rocm/lib
- `packaging::install-rpm::pth.python3.12` (fail, failing 4 nights): python3.12 (the only interpreter the cp312 modules load in) does not get /opt/rocm/lib: %post registered the path for Python 3.9.25 only
- `packaging::install-rpm::pth.shipped` (fail, failing 4 nights): no amdrocm-vision.pth in any python3 site-packages; %post did not register it
- `packaging::install-rpm::pth.syspath` (fail, failing 4 nights): /opt/rocm/lib not on sys.path of Python 3.9.25
- `packaging::rpm::amdrocm-mivisionx-devel10.2::header` (fail, failing 8 nights): unexpected package name; version 10.2.0_20261014-20261014 differs from DEB 10.2.0-20261014-20261014
- `packaging::rpm::amdrocm-mivisionx-test10.2::header` (fail, failing 8 nights): unexpected package name; version 10.2.0_20261014-20261014 differs from DEB 10.2.0-20261014-20261014
- `packaging::rpm::amdrocm-mivisionx10.2::header` (fail, failing 8 nights): unexpected package name; version 10.2.0_20261014-20261014 differs from DEB 10.2.0-20261014-20261014
- `packaging::rpm::amdrocm-mivisionx10.2::payload.matches-deb` (fail): 15 files (DEB 11); only in RPM: /usr/lib/.build-id/08/c7847e2b3703b7e19618d809eb28496bfe890e, /usr/lib/.build-id/42/8aa0bb07653f6c237247b7c341e8d8707d2119, /usr
- ... and 61 more (see the report)

### Missing tests

- `packaging::rpm`: 207 of at least 221 

### Known issues that passed tonight

- H1: librocal needs libpython (113 undefined CPython symbols, no libpython dependency)
- H3: FindMIVisionX.cmake exports include/ instead of include/mivisionx
- H4: No license texts for redistributed third-party code (libsndfile, protobuf, libjpeg-turbo, LMDB, rapidjson, pybind11, dlpack)
- M3: No install or usage documentation for the tarball (location, PYTHONPATH, Python 3.12 only, numpy)
- N6: amdrocm-rocal RPM auto-requires libsndfile/libturbojpeg version capabilities that no package provides
- N10: rocPyJpegDecode initialize_hip() terminates the interpreter without a GPU instead of raising
- L-stdcxx-leak: Leaked C++ standard-library symbols in vision libraries and Python modules
- L-hardening: Bundled parsers built without stack-protector and FORTIFY
- L-findrocal-include: Findrocal requires <rocal/rocal_api.h> rather than the documented "rocal_api.h"

### Environment

- GPU: `?`
- SDK: `?` (fallback: ?)
- Runner: ?, driver ?, kernel ?
- Upstream nightly: success https://github.com/kiritigowda/vision-pack/actions/runs/38525354215
- Compared with 2026-10-13: 16 new failures, 51 fixed, 0 new tests, 0 removed
