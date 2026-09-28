## Nightly QA: RED

vision-pack `0.2.0+gd440925` (nightly-20260926, `d440925b1b06`) on `?`, tier **comprehensive**, 2026-09-28.

**Why:** 8 infra error; 30 new failure; loader-audit::verify-install: 0 results, expected at least 47; loader-audit::ldd.customer: 0 results, expected at least 15; loader-audit::ldd.undefined: 0 results, expected at least 15; loader-audit::dlopen: 0 results, expected at least 10; loader-audit::link: 0 results, expected at least 5; loader-audit::py-import.py312: 0 results, expected at least 11; loader-audit::inventory: 0 results, expected at least 15; loader-audit::fatbin.has-gfx: 0 results, expected at least 5; loader-audit::license: 0 results, expected at least 8; loader-audit::license.bundled: 0 results, expected at least 8; loader-audit::cwd-hijack: 0 results, expected at least 15; loader-audit::cwd-hijack.control: 0 results, expected at least 3; loader-audit::interpose: 0 results, expected at least 5; loader-audit::elf-hardening: 0 results, expected at least 15; loader-audit::elf-hygiene.*: 0 results, expected at least 30; loader-audit::symbols.*: 0 results, expected at least 17; loader-audit::hardcoded-paths.*: 0 results, expected at least 19; sdk-consumer::headers.cxx17: 0 results, expected at least 33; sdk-consumer::headers.hip: 0 results, expected at least 119; sdk-consumer::headers.c99: 0 results, expected at least 24; sdk-consumer::headers.cxx20-host: 0 results, expected at least 97; sdk-consumer::consumer.mivisionx: 0 results, expected at least 15; sdk-consumer::consumer.rocal: 0 results, expected at least 12; sdk-consumer::consumer.roccv: 0 results, expected at least 10; sdk-consumer::contamination.*: 0 results, expected at least 16; sdk-consumer::standalone.ldd: 0 results, expected at least 15; robustness-nogpu::env: 0 results, expected at least 1; robustness-nogpu::import: 0 results, expected at least 18; robustness-nogpu::mivisionx: 0 results, expected at least 2; robustness-nogpu::roccv: 0 results, expected at least 3; robustness-nogpu::rocal: 0 results, expected at least 3; robustness-nogpu::rocpydecode: 0 results, expected at least 2.

Report: https://levxn.github.io/vision-pack-test/runs/36429359918/

| Suite | results | new failures | still failing | known | flaky | fixed | blocked | skipped |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| loader-audit | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| mivisionx | no results | | | | | | | |
| packaging | 388 | 30 | 0 | 70 | 0 | 0 | 5 | 0 |
| robustness | no results | | | | | | | |
| robustness-nogpu | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| rocal | no results | | | | | | | |
| roccv | no results | | | | | | | |
| rocpydecode | no results | | | | | | | |
| sdk-consumer | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

### New and unbaselined failures (38)

- `loader-audit::infra::runner` (error): the CI step exited 1; results may be partial
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
- ... and 18 more (see the report)

### Missing tests

- `loader-audit::verify-install`: 0 of at least 47 
- `loader-audit::ldd.customer`: 0 of at least 15 all 15 vision-pack ELF objects
- `loader-audit::ldd.undefined`: 0 of at least 15 
- `loader-audit::dlopen`: 0 of at least 10 
- `loader-audit::link`: 0 of at least 5 
- `loader-audit::py-import.py312`: 0 of at least 11 
- `loader-audit::inventory`: 0 of at least 15 
- `loader-audit::fatbin.has-gfx`: 0 of at least 5 
- `loader-audit::license`: 0 of at least 8 
- `loader-audit::license.bundled`: 0 of at least 8 
- `loader-audit::cwd-hijack`: 0 of at least 15 
- `loader-audit::cwd-hijack.control`: 0 of at least 3 
- `loader-audit::interpose`: 0 of at least 5 
- `loader-audit::elf-hardening`: 0 of at least 15 
- `loader-audit::elf-hygiene.*`: 0 of at least 30 
- `loader-audit::symbols.*`: 0 of at least 17 
- `loader-audit::hardcoded-paths.*`: 0 of at least 19 
- `sdk-consumer::headers.cxx17`: 0 of at least 33 
- `sdk-consumer::headers.hip`: 0 of at least 119 
- `sdk-consumer::headers.c99`: 0 of at least 24 
- `sdk-consumer::headers.cxx20-host`: 0 of at least 97 
- `sdk-consumer::consumer.mivisionx`: 0 of at least 15 
- `sdk-consumer::consumer.rocal`: 0 of at least 12 
- `sdk-consumer::consumer.roccv`: 0 of at least 10 
- `sdk-consumer::contamination.*`: 0 of at least 16 
- `sdk-consumer::standalone.ldd`: 0 of at least 15 
- `robustness-nogpu::env`: 0 of at least 1 
- `robustness-nogpu::import`: 0 of at least 18 
- `robustness-nogpu::mivisionx`: 0 of at least 2 
- `robustness-nogpu::roccv`: 0 of at least 3 
- `robustness-nogpu::rocal`: 0 of at least 3 
- `robustness-nogpu::rocpydecode`: 0 of at least 2 

### Environment

- GPU: `?`
- SDK: `?` (fallback: ?)
- Runner: ?, driver ?, kernel ?
- Upstream nightly: success https://github.com/kiritigowda/vision-pack/actions/runs/36225269840
