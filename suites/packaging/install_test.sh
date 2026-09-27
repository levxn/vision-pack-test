#!/usr/bin/env bash
# install-test suite (GPU runner, full tier): install ONLY the -test packages
# plus what they declare, like a customer running apt install amdrocm-*-test,
# then build and run each shipped test tree from /opt/rocm/share/<lib>/test.
#
# Entry point of suite install-test in suites/suites.yaml; runs as root inside
# the test container with the GPU (run_in_container.sh). Inputs:
#   ROCM_PATH    the ROCm SDK + vision-pack overlay prefix (read-only mount).
#                Only its ROCm part is used: /opt/rocm is built as a symlink
#                view of it with every vision-pack path removed, standing in
#                for the customer's existing ROCm install.
#   VP_DEB_DIR   directory with the release DEBs (default /opt/vp/debs); served
#                to apt as a local repository, so apt resolves the -test
#                packages' Depends exactly as declared.
#   VP_THEROCK_DEB_REPO / VP_THEROCK_DATE  TheRock repo used only to simulate
#                whether the declared ROCm Depends would resolve.
#
# Phase "shipped": -test packages + declared Depends only. Exercises
#   N2  the tests need -devel headers the -test Depends omit
#       (install-test::<lib>::n2.headers, <lib>::shipped::configure/build);
#   N2  MIVisionX openvx_graph reads samples shipped only in mivisionx-devel
#       (install-test::mivisionx::n2.samples);
#   N1  rocPyDecode/rocPyJpegDecode regression tests call ../samples/..., in no
#       package (install-test::rocpydecode::n1.samples, ::raw_regression_test).
# Phase "with-devel": adds the -devel packages and runs the full ctest trees
# (install-test::<lib>::with-devel.ctest::<test>).
set -uo pipefail
PK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${PK_DIR}/lib/common.sh"

out="${VP_OUT:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) out="$2"; shift 2 ;;
    --debs) VP_DEB_DIR="$2"; shift 2 ;;
    -h|--help) sed -n '2,29p' "$0"; exit 0 ;;
    *) pk_die "unknown argument $1" ;;
  esac
done
[[ -n "${ROCM_PATH:-}" ]] || pk_die "ROCM_PATH must point at the ROCm SDK prefix"
SDK="$(cd "${ROCM_PATH}" && pwd)" || pk_die "ROCM_PATH ${ROCM_PATH} does not exist"
pk_init install-test "${out}"
CUST=/opt/rocm
DEB_DIR="${VP_DEB_DIR:-/opt/vp/debs}"
export DEBIAN_FRONTEND=noninteractive
APT=(apt-get -y -q -o Acquire::Retries=5 -o Acquire::http::Timeout=60 -o Dpkg::Use-Pty=0)
TESTS=(amdrocm-mivisionx-test amdrocm-rocal-test amdrocm-roccv-test amdrocm-pydecode-test)
DEVELS=(amdrocm-mivisionx-devel amdrocm-rocal-devel amdrocm-roccv-devel)

finish() { vp_finish; exit 0; }
if [[ "$(id -u)" != 0 || "${VP_NO_CONTAINER:-0}" == 1 ]] || ! pk_disposable; then
  vp_blocked install::environment "needs root in a disposable container (it installs packages into /opt/rocm)"
  finish
fi
if [[ ! -d "${DEB_DIR}" ]] || [[ -z "$(find "${DEB_DIR}" -maxdepth 1 -name '*.deb' -print -quit)" ]]; then
  vp_blocked install::environment "no DEBs in VP_DEB_DIR=${DEB_DIR}"
  finish
fi
if [[ -e "${CUST}" ]] && [[ -n "$(ls -A "${CUST}" 2>/dev/null)" ]]; then
  vp_blocked install::environment "${CUST} already exists in the container; the image must not ship ROCm there"
  finish
fi
if ! vp_require_cmd install::tools dpkg-deb dpkg-scanpackages cmake ninja; then finish; fi

# --- 1. /opt/rocm = ROCm SDK without anything vision-pack ships ----------------
vlist="${VP_WORK}/vision-paths.txt"
for f in "${DEB_DIR}"/*.deb; do
  dpkg-deb -c "${f}" | awk '$1 !~ /^d/ {print $6}' | sed -n 's#^\./opt/rocm/##p'
done | sort -u >"${vlist}"
VISION_DIRS=(include/mivisionx include/rocal include/roccv share/mivisionx share/rocal share/roccv
             share/rocpydecode share/rocpyjpegdecode share/vision-pack lib/cmake/roccv lib/amd
             lib/pyRocVideoDecode lib/pyRocJpegDecode share/doc/mivisionx share/doc/rocal share/doc/roccv
             share/doc/rocpydecode share/doc/rocpyjpegdecode)
vlog="${VP_OUT}/logs/sdk-view.log"
{
  mkdir -p "${CUST}" && cp -rs "${SDK}/." "${CUST}/" || exit 1
  while IFS= read -r rel; do
    [[ -L "${CUST}/${rel}" ]] && rm -f -- "${CUST}/${rel}"
  done <"${vlist}"
  for d in "${VISION_DIRS[@]}"; do
    [[ -d "${CUST}/${d}" ]] && find "${CUST}/${d}" -type l -delete
  done
  find "${CUST}/lib" -maxdepth 1 -type l \( -name 'libopenvx*' -o -name 'libvxu*' -o -name 'libvx_rpp*' \
    -o -name 'librocal*' -o -name 'libroccv*' -o -name 'rocal_pybind*' -o -name 'rocpycv*' -o -name 'rocpydecode*' \
    -o -name 'rocpyjpegdecode*' \) -delete
  find "${CUST}/lib/rocm_sysdeps/lib" -maxdepth 1 -type l -name '*-rocm-vision*' -delete 2>/dev/null
  find "${CUST}/bin" -maxdepth 1 -type l -name runvx -delete
  find "${CUST}" -depth -type d -empty -delete
  mkdir -p "${CUST}"
} >"${vlog}" 2>&1
left="$(cd "${CUST}" && for p in lib/librocal.so lib/libopenvx.so include/mivisionx share/rocal/test; do
          [[ -e "${p}" ]] && echo "${p}"; done)"
if [[ ! -e "${CUST}/lib/libamdhip64.so" ]]; then
  vp_result install::sdk-view error "ROCm SDK view has no lib/libamdhip64.so (ROCM_PATH=${SDK})" 0 "${vlog}"
  finish
elif [[ -n "${left}" ]]; then
  vp_result install::sdk-view error "vision-pack files survived in the SDK view: ${left}" 0 "${vlog}"
  finish
fi
vp_result install::sdk-view pass "${CUST} = ROCm from ${SDK} minus $(wc -l <"${vlist}") vision-pack paths" 0 "${vlog}"

# --- 2. local apt repository with the release DEBs ------------------------------
repo="${VP_WORK}/debrepo"
mkdir -p "${repo}"
cp -f "${DEB_DIR}"/*.deb "${repo}/"
(cd "${repo}" && dpkg-scanpackages --multiversion . /dev/null >Packages 2>"${VP_OUT}/logs/scanpackages.log")
echo "deb [trusted=yes] file:${repo} ./" >/etc/apt/sources.list.d/vision-pack-local.list
alog="${VP_OUT}/logs/apt.log"
pk_retry 3 "${APT[@]}" update >"${alog}" 2>&1
if ! "${APT[@]}" install --no-install-recommends equivs >>"${alog}" 2>&1; then
  vp_result install::prereqs error "cannot install equivs" 0 "${alog}"
fi

# --- 3. would TheRock's repo satisfy the declared ROCm Depends? (simulation) -----
tlist=/etc/apt/sources.list.d/therock-nightly.list
if trepo="$(pk_therock_repo "${VP_THEROCK_DISTRO:-ubuntu2404}" "${VP_THEROCK_DATE:-}" deb)" && [[ -n "${trepo}" ]]; then
  echo "deb [trusted=yes] ${trepo} stable main" >"${tlist}"
  slog="${VP_OUT}/logs/therock-simulate.log"
  if pk_retry 3 "${APT[@]}" update >"${slog}" 2>&1 && "${APT[@]}" install -s "${TESTS[@]}" >>"${slog}" 2>&1; then
    vp_result install::resolve.therock pass "apt -s install ${TESTS[*]} resolves against ${trepo}" 0 "${slog}"
  else
    vp_result install::resolve.therock fail "unresolvable against ${trepo}: $(grep -E 'Depends:|but it is not|E: ' "${slog}" | head -6 | tr -s ' \n' ' ')" 0 "${slog}"
  fi
  rm -f "${tlist}"
  pk_retry 3 "${APT[@]}" update >>"${alog}" 2>&1
else
  vp_blocked install::resolve.therock "TheRock nightly repo unreachable"
fi

# --- 4. stubs for the external ROCm Depends (the SDK view provides the files) -----
stubs="${VP_WORK}/stubs.tsv"
"${VP_PY}" "${PK_PY}" --results "${VP_RESULTS}" --suite "${VP_SUITE}" depends --pkg-dir "${DEB_DIR}" --format deb \
  --group install --stubs-out "${stubs}" --no-records >>"${alog}" 2>&1
stubdir="${VP_WORK}/stubs"
mkdir -p "${stubdir}"
stub_ok=1
while IFS=$'\t' read -r n v; do
  [[ -n "${n}" ]] || continue
  printf 'Section: misc\nPriority: optional\nStandards-Version: 3.9.2\nPackage: %s\nVersion: %s\nArchitecture: all\nDescription: stub for %s (provided by the ROCm SDK view)\n stub\n' \
    "${n}" "${v}" "${n}" >"${stubdir}/${n}.control"
  (cd "${stubdir}" && equivs-build "${n}.control") >>"${alog}" 2>&1 || stub_ok=0
done <"${stubs}"
mapfile -t STUBDEBS < <(find "${stubdir}" -name '*.deb')
if [[ "${stub_ok}" == 1 ]] && { [[ ${#STUBDEBS[@]} -eq 0 ]] || dpkg -i "${STUBDEBS[@]}" >>"${alog}" 2>&1; }; then
  vp_result install::stubs pass "stubs: $(cut -f1 "${stubs}" | tr '\n' ' ')" 0 "${alog}"
else
  vp_result install::stubs error "could not build or install equivs stubs" 0 "${alog}"
  finish
fi

# --- 5. customer install: only the -test packages -------------------------------
if "${APT[@]}" install --no-install-recommends "${TESTS[@]}" >>"${alog}" 2>&1; then
  vp_result install::test-packages pass "installed: $(dpkg-query -W -f='${Package} ' 'amdrocm-*' 2>/dev/null)" 0 "${alog}"
else
  vp_result install::test-packages fail "apt install ${TESTS[*]} failed: $(tail -3 "${alog}" | tr '\n' ' ')" 0 "${alog}"
  finish
fi

# Customer environment from here on: ROCm at /opt/rocm, no overlay prefix, no
# PYTHONPATH (the .pth from amdrocm-vision-pythonpath must do it).
export ROCM_PATH="${CUST}"
PATH="${CUST}/bin:${CUST}/lib/llvm/bin:$(tr ':' '\n' <<<"${PATH}" | grep -vxF -e "${SDK}/bin" -e "${SDK}/lib/llvm/bin" | paste -sd:)"
export PATH
unset PYTHONPATH LD_LIBRARY_PATH
export TMPDIR="${VP_WORK}/tmp"
mkdir -p "${TMPDIR}"

declare -A SRC=([mivisionx]=share/mivisionx/test [rocal]=share/rocal/test [roccv]=share/roccv/test/cpp)
declare -A HDR=([mivisionx]=include/mivisionx/VX/vx.h [rocal]=include/rocal/rocal_api.h [roccv]=include/roccv)
declare -A EXTRA=([mivisionx]="" [rocal]="" [roccv]="-DCMAKE_EXE_LINKER_FLAGS=-pthread")

build_tree() {  # build_tree <lib> <phase>
  local lib="$1" phase="$2" src="${CUST}/${SRC[$1]}" b="${VP_WORK}/build-$1-$2" extra=()
  [[ -n "${EXTRA[$lib]}" ]] && extra=("${EXTRA[$lib]}")
  if [[ ! -d "${src}" ]]; then
    vp_result "${lib}::${phase}::configure" fail "${src} not installed"
    return 1
  fi
  vp_cmake_build "${lib}::${phase}" "${src}" "${b}" -DBACKEND=HIP ${extra[@]+"${extra[@]}"}
}

# --- 6. phase "shipped" ----------------------------------------------------------
for lib in mivisionx rocal roccv; do
  if [[ -e "${CUST}/${HDR[$lib]}" ]]; then
    vp_result "${lib}::n2.headers" pass "${HDR[$lib]} present with only the -test closure installed"
  else
    vp_result "${lib}::n2.headers" fail "${HDR[$lib]} missing: amdrocm-${lib}-test does not depend on amdrocm-${lib}-devel, but its tests include these headers (N2)"
  fi
  if build_tree "${lib}" shipped; then
    vp_ctest "${lib}::shipped.ctest" "${VP_WORK}/build-${lib}-shipped"
  fi
done
gdf="${CUST}/share/mivisionx/samples/gdf/read-gdf-sample.gdf"
if [[ -f "${gdf}" ]]; then
  vp_result mivisionx::n2.samples pass "${gdf} present"
else
  vp_result mivisionx::n2.samples fail "openvx_graph reads ${gdf}, which ships only in amdrocm-mivisionx-devel (N2)"
fi

not_ok=""
for s in share/rocpydecode/samples/rocdecode/videodecoderaw.py share/rocpyjpegdecode/samples/rocjpeg/jpegdecodebatched.py; do
  [[ -f "${CUST}/${s}" ]] || not_ok+="${s} "
done
if [[ -z "${not_ok}" ]]; then
  vp_result rocpydecode::n1.samples pass "sample scripts the regression tests call are installed"
else
  vp_result rocpydecode::n1.samples fail "regression tests call ../samples/... but no package ships: ${not_ok}(N1)"
fi
pyrun() {  # pyrun <id> <script> [args]
  local id="$1" script="$2" wd; shift 2
  wd="$(mktemp -d "${VP_WORK}/py.XXXXXX")"
  if [[ ! -f "${script}" ]]; then vp_result "${id}" fail "${script} not installed"; return; fi
  vp_run "${id}" --timeout 300 --cwd "${wd}" -- python3 "${script}" "$@"
}
T="${CUST}/share/rocpydecode/tests"
pyrun rocpydecode::types_test "${T}/types_test.py"
if [[ -f "${CUST}/share/rocdecode/video/AMD_driving_virtual_20-H264.264" ]]; then
  pyrun rocpydecode::raw_regression_test "${T}/raw_regression_test.py" --media-dir "${CUST}/share/rocdecode/video"
else
  vp_blocked rocpydecode::raw_regression_test "no raw H.264/H.265 streams in ${CUST}/share/rocdecode/video"
fi
if [[ -d "${CUST}/share/rocjpeg/images" ]]; then
  pyrun rocpyjpegdecode::jpeg_regression_test "${CUST}/share/rocpyjpegdecode/tests/jpeg_regression_test.py" \
    --media-dir "${CUST}/share/rocjpeg/images"
else
  vp_blocked rocpyjpegdecode::jpeg_regression_test "no JPEGs in ${CUST}/share/rocjpeg/images"
fi

# --- 7. phase "with-devel" (what a working setup needs) ---------------------------
if ! vp_tier_ge full; then
  vp_skip install::devel-added "with-devel phase runs in the full tier only"
  finish
fi
if "${APT[@]}" install --no-install-recommends "${DEVELS[@]}" >>"${alog}" 2>&1; then
  vp_result install::devel-added pass "added ${DEVELS[*]}" 0 "${alog}"
  for lib in mivisionx rocal roccv; do
    if build_tree "${lib}" with-devel; then
      vp_ctest "${lib}::with-devel.ctest" "${VP_WORK}/build-${lib}-with-devel"
    fi
  done
else
  vp_result install::devel-added fail "apt install ${DEVELS[*]} failed" 0 "${alog}"
fi
finish
