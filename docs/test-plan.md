# Test plan

Every check of the nightly, grouped by suite. Result IDs are `<suite>::<group>::<name>`. The **Tier** column is the lowest tier that runs the group; higher tiers include it. **Count** is the number of result IDs on `nightly-20260926` (the floors in `baselines/expected_counts.yaml`). **Findings** are the baseline entries the group reproduces; see `baselines/known_issues.yaml`.

Status rules apply everywhere:
- `pass` means correct output, not just exit 0.
- A crash, signal or timeout is `error`.
- A missing dependency is `blocked`.
- Deliberate crash probes run only in CI containers; on bare hosts they are `skip`.

## packaging (hosted runners)

| Group | Tier | Count | Checks | Pass criterion | Findings |
|---|---|---|---|---|---|
| `deb` | quick | 46 | Upstream `validate_packages.sh` per package (13 + 3 metas), cross-package checks, licenses, `-test` package references | Upstream PASS; licenses present; every file a `-test` package references is in its Depends closure | H4, N1, N2 |
| `rpm` | quick | 221 | Header, payload prefix, cpio integrity, empty dirs, file lists equal to the DEBs, `.so` modes, build paths, Requires/Provides closure and isolation, scriptlets, `.pth` | No defect | H4, M1, N6, N7, N8, L-elf-hygiene, L-build-paths |
| `tarball` | quick | 45 | Safe paths, symlink and SONAME chains, runvx exec bit, manifest schema and sha, RUNPATHs, build IDs, CI paths, licenses, docs, DEB union ⊆ tarball (sha256) | No defect | H4, M3, N8, L-* |
| `install-deb` | quick | ≥ 6 | `apt install` of the metas in bare `ubuntu:24.04` against TheRock's nightly repo (fallback: equivs stubs); decoy host libraries; imports; `.pth`; ldd; purge | Real install; imports and ldd clean | N5 |
| `install-rpm` | quick | ≥ 7 | The same in `rockylinux:9` with dnf (`--nodeps` fallback) | Real install; imports and ldd clean | N5, N6 |
| `install-test::*` | full | varies | Install only the `-test` packages plus their Depends, then build and ctest each shipped tree | Trees build and pass without `-devel` | N1, N2 |

## loader-audit (GPU runner, CPU-only work)

| Group | Tier | Count | Checks | Pass criterion | Findings |
|---|---|---|---|---|---|
| `verify-install` | quick | 47 | Upstream's Verify-install gates, package.yml gates, runvx RUNPATH, gfx in manifest | Every gate holds | L-build-paths |
| `ldd.customer` | quick | 15 | `ldd -r` on every vision-pack ELF object without `LD_LIBRARY_PATH` | Nothing "not found", no escape to host libraries | (acceptance: 15/15) |
| `ldd.undefined` | quick | 15 | Undefined symbols in each object | None (Python modules may leave CPython symbols) | H1 |
| `dlopen` / `exec` | quick | 10 / 1 | RTLD_NOW load of each library; runvx starts | Loads / prints usage | H1 |
| `link` | quick | 5 | C consumers linking `-lopenvx`, `-lroccv`, `-lrocal` (with and without libpython) | Links and runs | H1 |
| `py-import.py312` | quick | 11 | Every module imports on Python 3.12 | Imports | |
| `py-import.py313-negative` | standard | 4 | The compiled modules on 3.13 (when available) | Must fail to import (cp312-only) | |
| `inventory` | quick | 15–17 | Payload vs manifest, runtime deps, protobuf-lite, pkg-config, tarball vs prefix (`VP_DIST_TARBALL`) | Consistent | L-packaging-extras |
| `fatbin.*` | quick | 13 | GPU code objects contain the tested gfx and the manifest's targets; no duplicate kernels | Holds | L-reexports |
| `license`, `license.bundled`, `docs` | quick | 17 | License text per third-party component; per-library pybind11/dlpack; no `*-asan` dirs; install doc | Present | H4, M3, L-packaging-extras |
| `cwd-hijack` (+ `.control`) | standard | 18 | Planted decoy libraries in the working directory under `LD_DEBUG=libs`, both loader modes, with positive controls built in the job | No object loads from CWD; controls are caught | |
| `interpose` (+ `.control`) | standard | 6 | Host libjpeg, LMDB, protobuf, libsndfile, turbojpeg loaded RTLD_GLOBAL first | librocal binds only to the bundled copies | M1 |
| `elf-hardening*`, `elf-hygiene.*` | standard | 50 | NX, no TEXTREL/RWX, PIE; canary/FORTIFY for the bundled parsers; build IDs; file modes | Holds | L-hardening, L-elf-hygiene |
| `symbols.*` | standard | 17 | Leaked libstdc++ symbols; libopenvx re-exports | None | L-stdcxx-leak, L-reexports |
| `hardcoded-paths.*` | standard | 19 | Build-machine paths in ELF and text files | None | L-build-paths |

## sdk-consumer (standard and above)

| Group | Tier | Count | Checks | Pass criterion | Findings |
|---|---|---|---|---|---|
| `headers.cxx17` / `headers.hip` | standard | 33 / 119 | Each public header compiled on its own (C++17; HIP with `--offload-arch=$VP_GFX`) | Compiles | L-headers |
| `headers.c99` / `headers.cxx20-host` | comprehensive | 24 / 97 | C99 for MIVisionX; host-only g++ for rocCV | Compiles | L-headers |
| `consumer.mivisionx` | standard | 15 | `find_package(MIVisionX)` project on CPU and GPU: vxNot, Box3x3, border modes, vx_rpp load | Builds; numeric checks hold; unsupported borders rejected | H3, M17, L-mvx-gaps |
| `consumer.rocal` | standard | 12–13 | `find_package(rocal)` project: CPU with 1/2/4 threads, GPU, rocJPEG, vs numpy and Pillow | Builds; outputs match | H1, H7, L-findrocal-include |
| `consumer.roccv` | standard | 10 | `find_package(roccv)` project: Flip on both devices, g++ build, pending launch errors | Builds with g++; outputs match | M23, M21 |
| `contamination.*` | standard | 16 | Synthetic decoy ROCm tree; `ROCM_PATH` unset or pointing at it; explicit and implicit | Nothing resolves into the decoy | M23 |
| `standalone.ldd` | standard | 15 | The dist tarball on its own (`VP_DIST_TARBALL`) | Only the expected SDK libraries are missing (`expected_notfound.txt`) | |

## mivisionx

| Group | Tier | Count | Checks | Pass criterion | Findings |
|---|---|---|---|---|---|
| `ctest` | quick 6, standard 32 | | Installed test tree, serial, `ROCM_PATH` exported | ctest pass (32/32 since nightly-20260926 fixed M4) | |
| `api.CPU` / `api.GPU` | standard | 16 / 16 | 16 API tests, each with `AGO_DEFAULT_TARGET=CPU` and `GPU` | Exit 0 | |
| `samples.gdf` | standard | 5 | The shipped sample GDFs | Exit 0 | M2, L-mvx-gaps |
| `api-probe`, `api-probe.{CPU,GPU}`, `api-probe.exports` | standard | 1 / 8 / 369 | Every declared function exported; `vx_ext_amd.h` as C; RGBA create, Copy node, read-only threshold attributes, 9x7 convolution | Exported; correct behaviour | M18, N11, L-mvx-gaps |
| `cts.<target>.<shard>` | comprehensive | 5,957 per target | Khronos OpenVX 1.3.2 CTS: 13 filter shards per target (5,824 required + pipelining 109 + streaming 24) plus one unfiltered run proving the shards cover everything | Every test passes; `#REPORT` matches the parsed results | |
| `cts.<target>.optional` | full | 7,439 per target | `--run_disabled` optional tests (without the H12 crasher) | Pass | M16, M17, L-mvx-gaps |
| `gdf.<target>.<category>` | comprehensive | 441 per target | 416 GDFs in 9 categories plus `cpu/hidden` (25), runvx `-frames:10 -dump-profile` | Exit 0 plus the elapsed-time and GRAPH profile lines | L-gdf-hidden |
| `gpu-fallback` | comprehensive | 9 | Canny and Harris graphs on GPU | No silent CPU fallback | L-mvx-gaps |
| `vision.<target>.<size>` | comprehensive | 117 per run | runVisionTests.py per node (116) at 1080p, 5x3, 10x10, parsed per node, plus a script-honesty check | Node runs; small sizes compared with the baseline list | H11, H16, M19, L-vision-small-sizes |
| `vision.static` | comprehensive | 4 | Lint of the case table | No invalid formats, duplicates or swapped names | M19 |
| `parity.<size>.<target>` | comprehensive | 143 each | Kernels at 1920x1080 and 1282x722 against numpy references, run twice | Within tolerance and repeatable | C1, H13, H14, H15, M15, M16, M17, N11, N13 |
| `samples.<target>` | comprehensive | 5 each | Shipped skin-tone and Canny graphs with raw input vs numpy | Matches | C1, M16 |
| `vxrpp.<target>`, `.repeat`, `.ref` | comprehensive | 54 / 47 / 11 each | vx_rpp nodes; second execution equals the first; numpy references with shift detection | Matches; stable | H6, H10, N12, L-mvx-gaps |
| `crash.<target>`, `crash.cts.*` | comprehensive (CI only) | 69 each + 1 | Box3x3/filter width sweeps; ROI release order; the CTS UAF case | No crash | H11, H12 |
| `cu-mask`, `ctest-race` | comprehensive | 1 / 2 | The cu_mask feature from a scratch copy of its script; ctest run in parallel | Works | L-mvx-gaps |
| `perf.runvx.*`, `perf.openvx-mark.GPU` | full | 22 / 40 | runvx profile medians; openvx-mark at 4K with MIVisionX's perf_gate settings | Rolling perf gate | L-openvx-mark |

## rocal

| Group | Tier | Count | Checks | Pass criterion | Findings |
|---|---|---|---|---|---|
| `ctest`, `ctest-novaenv` | quick 3, standard 21 | | Installed test tree, serial, with timeouts, VA-API environment as rocAL's CI; the rocJPEG tests once more without it | ctest pass | H2 |
| `pybind`, `env` | standard | 6 / 4 | The import tests as their own project; interpreter, cv2 and PYTHONPATH handling | Pass | N3 |
| `audio.<target>` | standard | 13 each | `audio_unit_test.py` QA mode per case on CPU and GPU (parsed PASSED/FAILED), plus the upstream-style run | Every case passes | H5, L-rocal-harness |
| `audio-cpp.<target>`, `audio-nontorch.<target>` | standard | 12 / 2 each | C++ `audio_tests` (trailing-slash `ROCAL_DATA_PATH`); a torch-free decoder and pre-emphasis check | Pass | H5 |
| `golden-cpp.<backend>.<color>` | comprehensive | 153 each | The exact `unit_tests` lines of `testAllScripts.sh` (no sudo, no rebuild, private LMDB copies), classified per call; the build must have OpenCV | Output matches the golden | C2, H6, M6, M9, N14, L-rocal-* |
| `golden-cpp-strict.*` | comprehensive | 153 each | The same outputs through the stricter analyzer: blank outputs fail, Log and golden-less deterministic cases compared host vs hip | Matches | H8, M9, L-rocal-gaps |
| `golden-py.<device>.<color>` | comprehensive | 91 rgb / 88 gray | `python_api/` through a recording `python3.12` shim | Exit 0, SUCCESS banner, output matches | C2, M8, M11 |
| `golden-cpp`, `golden-py` (aggregates) | comprehensive | 3 / 2 | Upstream comparator totals | All cases pass | L-rocal-harness |
| `readers.<device>` | comprehensive | 11 each | Every reader on private dataset copies | Reads | C2, H2, L-rocal-gaps |
| `lmdb` | comprehensive | 25 | Bundled vs host LMDB open, 0.9 to 1.0 conversion, reading the converted copy, `lock.mdb` untouched, error text | Opens; dataset unchanged | C2, M14, L-rocal-gaps |
| `probe` | comprehensive | 41 | API probes: crop position, Log, multi-threaded resize, rocJPEG batch, concurrency, copy-to-output size, symlinked datasets, one-hot, external source, build exit status, Nop, color_jitter; crash probes in CI | Documented behaviour | H1, H7, H8, H9, M5–M12, L-rocal-* |
| `perf` | full | 23 | `performance_tests` and `dataloader_multithread` on 5,120 JPEGs | Rolling perf gate | |
| `extended` | full (extended image) | 3 | torch, jax and tensorflow plugins | Work | |

## roccv

| Group | Tier | Count | Checks | Pass criterion | Findings |
|---|---|---|---|---|---|
| `ctest` | quick 5, standard 40 | Installed C++ tests (custom harness) | Exit 0 | |
| `case.<binary>` | standard | 1,704 | Every executed `TEST_CASE` (1,656 sites), via an instrumented `test_helpers.hpp` | No "Test Failed:"; a site that never reports is `error` | |
| `pybind-ctest` | standard | 20 | The pybind ctest project | Pass | |
| `pytest` | quick 1,152, standard 12,038 | All 25 Python test files, including the 6 unregistered ones | Pass | L-roccv-tests |
| `gpu-vs-cpu.*`, `numpy-ref.*` | comprehensive | 441 / 217 | GPU vs CPU agreement and numpy references, retried once | Within tolerance | M20, L-roccv-accuracy |
| `hwc.*`, `cpp-probe.hwc` | comprehensive | 100 / 18 | Unbatched HWC tensors per operator (Python and C++) | Works | M20 |
| `strided-copy.*`, `dlpack` | comprehensive | 45 / 45 | Non-contiguous views: copy_to, operators, DLPack exchange | Data preserved | H17 |
| `negative.*`, `oob.*` | comprehensive | 54 / 5 | Invalid arguments in isolated processes | Rejected (or tolerated as documented); no crash | H18, L-roccv-validation |
| `cpp-probe.wrap`, `.strided`, `.launch` | comprehensive | 7 | TensorWrapData ownership, async copies, launch status | Correct | H19 |
| `stub`, `api-doc`, `precision.*`, `repro` | comprehensive | 17 | `.pyi` validity; documented layouts; U32 precision | Correct | M22, L-roccv-accuracy |
| `samples.*` | comprehensive | 76 | C++ and Python samples, GPU and CPU, output comparisons, `-h`, bad input | Exit 0 and correct output | L-roccv-samples |
| `perf`, `perf-audit` | comprehensive | 54 / 3 | `perf_ops` per operator; relative-speed audit | Rolling perf gate | L-roccv-perf |
| `bench`, `dlpack.torch`, `samples.torch` | full | | roccv_bench (built from source); torch exchange and classification (extended) | Rolling perf gate / correct | |

## rocpydecode (media image, standard and above)

| Group | Tier | Count | Checks | Pass criterion | Findings |
|---|---|---|---|---|---|
| `layout` | standard | 2 | Samples the shipped tests reference exist; README links resolve | Present | N1, M3 |
| `import`, `api` | standard | 8 / 2 | Module imports; FFmpeg demuxer and host-backend bindings compiled in | Present | H2 |
| `video` | standard | 9 | `types_test`, raw H.264/H.265 decode (`Decoded N frames`, N > 0), regression, demuxer tests | Pass (exit 77 = skip) | H2 |
| `samples` | standard | 10 | Every video sample | Exit 0 | H2 |
| `jpeg` | standard | 5 | Batched decode (0 bad files), regression, input tests; tensor test in the extended image | Pass | |

## robustness and robustness-nogpu (comprehensive and above)

| Group | Count | Checks | Pass criterion | Findings |
|---|---|---|---|---|
| `unsupported-gpu.<gfx>` (+ `.control`, `.build`) | 4 per unsupported GPU | rocCV, MIVisionX and rocAL on a GPU without code objects, with the target GPU as control | Correct output or a reported error, never silent zeros | M21 |
| `exit-code` | 7 | Scripts that must fail: failed verify, comparator mismatch, bad arguments, missing framework | Non-zero exit | M8, H16, N9, L-rocal-harness |
| `hang` | 2 | external_source_reader without and with a trailing separator, 60 s guard | Completes | M12 |
| `robustness-nogpu::*` | 29 | No GPU device: imports, runvx CPU graph, rocCV and rocAL CPU paths, GPU requests fail cleanly | Works on CPU; clean errors | M13, M8, N10, L-roccv-validation |

## Not covered

- MIVisionX's OpenCL backend, camera and live graphs, and GUI applications.
- Multi-GPU runs (one target GPU per runner).
- rocAL and rocPyDecode video decoding while vision-pack is built without FFmpeg (H2); the checks exist and fail until it is.
- The CIFAR-10 reader (no data set) and WebDataset (disabled upstream).
- N4: vision-pack's own CI exports `AGO_DEFAULT_TARGET=CPU` globally. This suite sets it per test, so the gap is documented here rather than tested.
