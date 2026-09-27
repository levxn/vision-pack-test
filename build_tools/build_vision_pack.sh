#!/usr/bin/env bash
# Build mode, step 1: build vision-pack from source exactly as upstream's
# build.yml does, inside the same TheRock manylinux image.
#
#   build_vision_pack.sh --out <dir> [--sdk-family gfx94X-dcgpu-tests] [--sdk-date YYYYMMDD] [--sdk-url URL]
#
# Run from the repository root with the vision-pack submodule checked out
# recursively (build_tools/pin_submodule.sh <sha> --recursive). Mirrors
# upstream: fetch the build SDK, configure, build the four libraries, stage,
# rewrite the bundled SONAMEs, verify the staged tree, write the manifest and
# pack the staging tree as <out>/vision-pack-staging.tar.gz (a tarball keeps
# symlinks and exec bits through upload-artifact). Writes version= to
# $GITHUB_OUTPUT. No upstream workflow is called and nothing is published.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="" sdk_family="${ROCM_SDK_FAMILY_DEFAULT:-gfx94X-dcgpu-tests}" sdk_date="" sdk_url=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) out="$2"; shift 2 ;;
    --sdk-family) sdk_family="${2:-${sdk_family}}"; shift 2 ;;
    --sdk-date) sdk_date="$2"; shift 2 ;;
    --sdk-url) sdk_url="$2"; shift 2 ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
[[ -n "${out}" ]] || { echo "--out is required" >&2; exit 2; }
mkdir -p "${out}"
out="$(cd "${out}" && pwd)"
export ROCM_PATH="${ROCM_PATH:-/opt/rocm-nightly}"
CMAKE_BUILD_TYPE="${CMAKE_BUILD_TYPE:-Release}"
PARALLEL="${VP_BUILD_PARALLEL:-$(nproc)}"
cd "${REPO}/vision-pack"
git config --global --add safe.directory '*'

echo "::group::build tools"
yum install -y python3-devel make curl patchelf >/dev/null 2>&1 || true
# cmake >= 3.28 honours rocCV's FetchContent EXCLUDE_FROM_ALL (dlpack must not
# be installed); < 3.30 avoids the policy changes older bundled deps trip on.
/opt/python/cp312-cp312/bin/python3 -m pip install --quiet "cmake~=3.28.0"
export PATH="/opt/python/cp312-cp312/bin:${PATH}"
hash -r
cmake --version | head -1
echo "::endgroup::"

echo "::group::build SDK"
args=(--dest "${ROCM_PATH}")
if [[ -n "${sdk_url}" ]]; then
  args+=(--url "${sdk_url}")
else
  args+=(--gpu-family "${sdk_family}")
  [[ -n "${sdk_date}" ]] && args+=(--date "${sdk_date}")
fi
python3 build_tools/fetch_rocm_sdk.py "${args[@]}" | tee /tmp/sdk-fetch.log
resolved="$(sed -n 's/^Selected[^:]*: //p' /tmp/sdk-fetch.log | head -n 1)"
for f in include/rpp/rpp.h include/rocjpeg/rocjpeg.h share/rocdecode/utils/rocvideodecode/roc_video_dec.cpp; do
  [[ -e "${ROCM_PATH}/${f}" ]] || { echo "::error::build SDK lacks ${f}"; exit 1; }
done
echo "::endgroup::"

echo "::group::configure and build"
py_args=()
[[ -d /opt/python-shared/cp312-cp312 ]] && py_args=(-DPython3_ROOT_DIR=/opt/python-shared/cp312-cp312)
cmake -B build -S . -GNinja -DCMAKE_BUILD_TYPE="${CMAKE_BUILD_TYPE}" -DROCM_PATH="${ROCM_PATH}" \
  "-DCMAKE_PREFIX_PATH=${ROCM_PATH};${ROCM_PATH}/lib/llvm" \
  -DVISION_PACK_ENABLE_MIVISIONX=ON -DVISION_PACK_ENABLE_ROCAL=ON \
  -DVISION_PACK_ENABLE_ROCCV=ON -DVISION_PACK_ENABLE_ROCPYDECODE=ON \
  -DVP_BUILD_PARALLEL_LEVEL="${PARALLEL}" ${py_args[@]+"${py_args[@]}"}
cmake --build build --parallel "${PARALLEL}" --target vp_mivisionx vp_roccv vp_rocal vp_rocpydecode
echo "::endgroup::"

echo "::group::stage"
rm -rf build/staging
mkdir -p build/staging
for proj in mivisionx roccv rocal rocpydecode; do
  stage="build/_subprojects/${proj}/stage"
  [[ -d "${stage}" ]] || { echo "::error::${proj} has no stage dir"; exit 1; }
  cp -a "${stage}/." build/staging/
done
cmake --install build --prefix build/staging --component runtime
python3 build_tools/rewrite_sonames.py build/staging
echo "::endgroup::"

echo "::group::verify the staged tree"
fail=0
err() { echo "::error::verify: $*"; fail=1; }
S=build/staging
SYSDEPS="${S}/lib/rocm_sysdeps/lib"
for pat in lib/libopenvx.so lib/librocal.so lib/libroccv.so 'lib/rocal_pybind*.so' 'lib/rocpycv*.so' \
    'lib/rocpydecode*.so' 'lib/rocpyjpegdecode*.so' lib/pyRocVideoDecode lib/pyRocJpegDecode \
    share/rocpydecode/tests bin/runvx share/rocal/test/data/images/AMD-tinyDataSet \
    'lib/rocm_sysdeps/lib/libturbojpeg-rocm-vision.so*' 'lib/rocm_sysdeps/lib/libprotobuf-rocm-vision.so*' \
    'lib/rocm_sysdeps/lib/liblmdb-rocm-vision.so*' 'lib/rocm_sysdeps/lib/libsndfile-rocm-vision.so*'; do
  compgen -G "${S}/${pat}" >/dev/null || err "missing ${pat}"
done
for neg in include/dlpack lib/cmake/dlpack; do
  [[ ! -e "${S}/${neg}" ]] || err "build-time-only ${neg} leaked into staging"
done
compgen -G "${S}/lib64/rocpy*decode*.so" >/dev/null && err "rocpydecode modules staged in lib64/"
needed="$(readelf -d "${S}/lib/librocal.so" | grep -i NEEDED || true)"
grep -qi 'libprotobuf-rocm-vision' <<<"${needed}" || err "librocal.so does not NEED libprotobuf-rocm-vision"
grep -qi 'libjpeg-rocm-vision' <<<"${needed}" || err "librocal.so does not NEED libjpeg-rocm-vision"
if grep -Ei 'lib(protobuf|protobuf-lite|turbojpeg|jpeg|lmdb|sndfile)\.so' <<<"${needed}" | grep -qiv rocm-vision; then
  err "librocal.so still NEEDs a stock bundled SONAME"
fi
readelf -d "${S}/lib/librocal.so" | grep -Ei 'R(UN)?PATH' | grep -q 'rocm_sysdeps/lib' \
  || err "librocal.so has no RUNPATH to rocm_sysdeps/lib"
for so in "${S}"/lib/*.so* "${SYSDEPS}"/lib*.so*; do
  [[ -f "${so}" && ! -L "${so}" ]] || continue
  rp="$(patchelf --print-rpath "${so}" 2>/dev/null || true)"
  if patchelf --print-needed "${so}" 2>/dev/null | grep -q '^libomp\.so' \
     && ! tr ':' '\n' <<<"${rp}" | grep -q 'llvm/lib$'; then
    err "$(basename "${so}") NEEDs libomp.so but its RUNPATH lacks llvm/lib"
  fi
  [[ -n "${rp}" ]] || continue
  if tr ':' '\n' <<<"${rp}" | sed 's/^$/<empty>/' | grep -qv '^\$ORIGIN'; then
    err "$(basename "${so}") has non-relocatable RUNPATH ${rp}"
  fi
done
for base in libopenvx libvxu libvx_rpp librocal libroccv; do
  real=0
  for so in "${S}/lib/${base}".so*; do [[ -e "${so}" && ! -L "${so}" ]] && real=$((real + 1)); done
  ((real <= 1)) || err "${base} SONAME chain flattened into ${real} regular files"
done
for base in libopenvx libvx_rpp libroccv librocal; do
  so="$(readlink -f "${S}/lib/${base}.so" 2>/dev/null || true)"
  [[ -n "${so}" && -f "${so}" ]] || continue
  fat="$(mktemp)"
  arches=""
  if objcopy -O binary --only-section=.hip_fatbin "${so}" "${fat}" 2>/dev/null && [[ -s "${fat}" ]]; then
    arches="$(strings -a "${fat}" | grep -oE 'gfx[0-9a-f]+' | sort -u | tr '\n' ' ')"
  fi
  rm -f "${fat}"
  echo "  ${base}: ${arches:-<none>}"
  [[ -n "${arches}" ]] || err "${base} ships no GPU code objects"
done
((fail == 0)) || { echo "::error::staged install verification failed"; exit 1; }
echo "::endgroup::"

ver="$(git describe --tags --dirty 2>/dev/null || true)"
ver="${ver#v}"
if [[ -z "${ver}" ]]; then
  proj_ver="$(sed -n 's/^ *VERSION \([0-9][0-9.]*\).*/\1/p' CMakeLists.txt | head -n 1)"
  ver="${proj_ver:-0.2.0}+g$(git rev-parse --short HEAD)"
fi
python3 build_tools/generate_manifest.py \
  --output "${S}/share/vision-pack/vision-pack-manifest.json" --version "${ver}" \
  --rocm-path "${ROCM_PATH}" --rocm-sdk "${resolved}" --build-type "${CMAKE_BUILD_TYPE}" \
  --release-type ci --staging-dir "${S}"
tar -czf "${out}/vision-pack-staging.tar.gz" -C "${S}" .
echo "built ${ver}: $(du -h "${out}/vision-pack-staging.tar.gz" | cut -f1)"
[[ -n "${GITHUB_OUTPUT:-}" ]] && echo "version=${ver}" >>"${GITHUB_OUTPUT}"
exit 0
