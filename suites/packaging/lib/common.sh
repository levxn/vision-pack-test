# shellcheck shell=bash
# Shared helpers for suites/packaging/*.sh. Source after setting PK_DIR:
#
#   PK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "${PK_DIR}/lib/common.sh"
#
# The hosted packaging jobs have no ROCm prefix, but vp_init requires
# ROCM_PATH. pk_init points it at an empty directory under $VP_OUT/work, so
# nothing from a real ROCm install leaks into PATH or PYTHONPATH.

VP_REPO="${VP_REPO:-$(cd "${PK_DIR}/../.." && pwd)}"
PK_PY="${PK_DIR}/pkgcheck.py"
PK_CURL=(curl -fsSL --retry 5 --retry-delay 5 --retry-all-errors --connect-timeout 20)
PK_THEROCK_BASE="${VP_THEROCK_BASE:-https://nightly.repo.amd.com/rocm/core/packages}"

pk_die() { echo "error: $1" >&2; exit "${2:-2}"; }

# pk_init <suite> <out>: VP_OUT from --out, harmless ROCM_PATH, vp_init.
pk_init() {
  local suite="$1" out="$2"
  [[ -n "${out}" ]] || pk_die "--out is required"
  mkdir -p "${out}" || pk_die "cannot create ${out}"
  VP_OUT="$(cd "${out}" && pwd)"
  export VP_OUT VP_REPO
  if [[ -z "${ROCM_PATH:-}" ]]; then
    ROCM_PATH="${VP_OUT}/work/no-rocm-prefix"
    mkdir -p "${ROCM_PATH}"
    export ROCM_PATH
  fi
  source "${VP_REPO}/build_tools/lib/vp.sh"
  vp_init "${suite}"
}

# pk_abs_dir <dir>: absolute path of an existing directory, or empty.
pk_abs_dir() { [[ -d "$1" ]] && (cd "$1" && pwd); }

# pk_fetch <url> <dest> [max_seconds]: download with retries, atomically.
pk_fetch() {
  local url="$1" dest="$2" max="${3:-600}"
  "${PK_CURL[@]}" --max-time "${max}" -o "${dest}.part" "${url}" && mv -f "${dest}.part" "${dest}"
}

# pk_retry <attempts> cmd...: retry a command with a growing pause (apt/dnf).
pk_retry() {
  local n="$1" i=1; shift
  until "$@"; do
    (( i >= n )) && return 1
    echo "### attempt ${i} failed: $*; retrying in $((i * 10))s" >&2
    sleep $((i * 10))
    i=$((i + 1))
  done
}

# pk_therock_repo <distro> <date|''> <deb|rpm>: echo the repository URL.
# Layout (verified 2026-09-27): <base>/<distro>/<YYYYMMDD>-<run id>/ with
# dists/stable (APT) or x86_64/repodata (RPM). Unsigned: apt needs
# [trusted=yes], dnf gpgcheck=0. VP_THEROCK_{DEB,RPM}_REPO override it.
pk_therock_repo() {
  local distro="$1" date="$2" kind="$3" ids id
  if [[ "${kind}" == deb && -n "${VP_THEROCK_DEB_REPO:-}" ]]; then echo "${VP_THEROCK_DEB_REPO}"; return 0; fi
  if [[ "${kind}" == rpm && -n "${VP_THEROCK_RPM_REPO:-}" ]]; then echo "${VP_THEROCK_RPM_REPO}"; return 0; fi
  ids="$("${PK_CURL[@]}" --max-time 60 "${PK_THEROCK_BASE}/${distro}/" | grep -oE '[0-9]{8}-[0-9]+' | sort -u)" \
    || return 1
  [[ -n "${ids}" ]] || return 1
  id=""
  [[ -n "${date}" ]] && id="$(grep "^${date}-" <<<"${ids}" | tail -1)"
  [[ -n "${id}" ]] || id="$(tail -1 <<<"${ids}")"
  if [[ "${kind}" == deb ]]; then
    echo "${PK_THEROCK_BASE}/${distro}/${id}"
  else
    echo "${PK_THEROCK_BASE}/${distro}/${id}/x86_64"
  fi
}

# pk_disposable: true in a container, on a GitHub-hosted runner, or when the
# caller explicitly allows modifying this system.
pk_disposable() {
  [[ -f /.dockerenv || -f /run/.containerenv ]] && return 0
  grep -qaE 'docker|containerd|kubepods|libpod|lxc' /proc/1/cgroup 2>/dev/null && return 0
  [[ "${RUNNER_ENVIRONMENT:-}" == github-hosted ]] && return 0
  [[ "${VP_ALLOW_SYSTEM_INSTALL:-0}" == 1 ]]
}

# pk_step_summary <markdown-file>: append to the GitHub job summary if any.
pk_step_summary() {
  [[ -n "${GITHUB_STEP_SUMMARY:-}" && -f "$1" ]] && cat "$1" >>"${GITHUB_STEP_SUMMARY}"
  return 0
}

# pk_py <subcommand> args...: run pkgcheck.py with the suite's results file.
pk_py() { "${VP_PY}" "${PK_PY}" --results "${VP_RESULTS}" --suite "${VP_SUITE}" "$@"; }

# pk_cleanup_work <dir>: drop large scratch under $VP_OUT/work unless kept.
pk_cleanup_work() {
  local d="$1"
  [[ "${VP_KEEP_WORK:-0}" == 1 || -z "${d}" || "${d}" != "${VP_OUT}/work/"* ]] && return 0
  rm -rf -- "${d}"
}

# pk_real_vision_libs: real ELF files the vision packages installed into
# /opt/rocm/lib and lib/rocm_sysdeps/lib, one per line.
pk_real_vision_libs() {
  local f
  for f in /opt/rocm/lib/*.so* /opt/rocm/lib/rocm_sysdeps/lib/*-rocm-vision.so*; do
    [[ -f "${f}" && ! -L "${f}" ]] && printf '%s\n' "${f}"
  done
}

# pk_lib_id <path>: stable test-ID name for a library (version suffix dropped).
pk_lib_id() { local b; b="$(basename "$1")"; printf '%s' "${b%%.so*}.so"; }

# Stock SONAMEs the bundled sysdeps were renamed away from.
PK_STOCK_RE='lib(protobuf|protobuf-lite|turbojpeg|jpeg|lmdb|sndfile)\.so'
PK_ROCM_LIB_RE='libamdhip64|librpp|librocdecode|librocjpeg|libhipfile|libomp|libhsa-runtime64|libamd_comgr'
PK_PY_MODULES=(rocal_pybind rocpycv rocpydecode rocpyjpegdecode amd.rocal pyRocVideoDecode.decoder)

# pk_isolation_checks <group> <planted-count>: port of upstream smoke-test's
# "bundled SONAMEs are isolated" and "host copies do not shadow" steps.
pk_isolation_checks() {
  local g="$1" planted="$2" lib n stock bad="" checked=0 out outside badres=""
  while IFS= read -r lib; do
    [[ "${lib}" == */rocm_sysdeps/* ]] && continue
    checked=$((checked + 1))
    n="$(readelf -d "${lib}" 2>/dev/null | grep -i NEEDED || true)"
    stock="$(grep -Ei "${PK_STOCK_RE}" <<<"${n}" | grep -iv rocm-vision || true)"
    [[ -n "${stock}" ]] && bad+="$(basename "${lib}"): $(tr -s ' \n' ' ' <<<"${stock}"); "
  done < <(pk_real_vision_libs)
  if [[ "${checked}" -eq 0 ]]; then
    vp_result "${g}::isolation.needed" fail "no vision libraries found under /opt/rocm/lib"
  elif [[ -n "${bad}" ]]; then
    vp_result "${g}::isolation.needed" fail "stock bundled SONAMEs NEEDed: ${bad}"
  else
    vp_result "${g}::isolation.needed" pass "${checked} libraries reference only *-rocm-vision SONAMEs"
  fi
  n="$(readelf -d /opt/rocm/lib/librocal.so 2>/dev/null | grep -i NEEDED || true)"
  if [[ -z "${n}" ]]; then
    vp_result "${g}::isolation.librocal" fail "/opt/rocm/lib/librocal.so missing or unreadable"
  elif grep -qi libprotobuf-rocm-vision <<<"${n}" && grep -qi libjpeg-rocm-vision <<<"${n}"; then
    vp_result "${g}::isolation.librocal" pass "librocal NEEDs the isolated protobuf and libjpeg"
  else
    vp_result "${g}::isolation.librocal" fail "librocal lacks libprotobuf-rocm-vision or libjpeg-rocm-vision NEEDED (#39)"
  fi
  lib="$(find /opt/rocm/lib/rocm_sysdeps/lib -name 'libjpeg-rocm-vision.so*' -type f 2>/dev/null | head -1)"
  if [[ -n "${lib}" ]] && readelf -sW "${lib}" | grep -q ' jpeg_std_error$'; then
    vp_result "${g}::isolation.jpeg_std_error" pass "$(basename "${lib}") exports jpeg_std_error"
  else
    vp_result "${g}::isolation.jpeg_std_error" fail "isolated libjpeg missing or does not export jpeg_std_error (#39)"
  fi
  if [[ "${planted}" -eq 0 ]]; then
    vp_result "${g}::isolation.decoys" fail "no stock decoy libraries could be planted, so isolation is unproven"
    return 0
  fi
  while IFS= read -r lib; do
    out="$(ldd "${lib}" 2>/dev/null | grep -i 'rocm-vision' || true)"
    [[ -n "${out}" ]] || continue
    outside="$(grep -v 'rocm_sysdeps/lib' <<<"${out}" || true)"
    [[ -n "${outside}" ]] && badres+="$(basename "${lib}"): $(tr -s ' \n' ' ' <<<"${outside}"); "
  done < <(pk_real_vision_libs)
  if [[ -n "${badres}" ]]; then
    vp_result "${g}::isolation.decoys" fail "isolated deps resolved outside rocm_sysdeps: ${badres}"
  else
    vp_result "${g}::isolation.decoys" pass "${planted} stock decoy SONAME(s) planted; isolated deps still bind to rocm_sysdeps"
  fi
}

# pk_plant_decoys <installer cmd...>: install host copies of the stock libs one
# package at a time (a single unknown name must not abort the rest).
pk_count_decoys() {
  local so planted=0
  for so in libturbojpeg.so.0 libprotobuf.so libprotobuf-lite.so liblmdb.so libsndfile.so.1 libjpeg.so; do
    ldconfig -p 2>/dev/null | grep -qF "${so}" && planted=$((planted + 1))
  done
  echo "${planted}"
}

# pk_import_checks <group> <python> <mode> <label>: import every vision module
# with no PYTHONPATH. A missing ROCm runtime library in a stub/force mode is
# blocked (not a vision-pack defect); anything else is a failure.
pk_import_checks() {
  local g="$1" py="$2" mode="$3" mod log rc
  for mod in "${PK_PY_MODULES[@]}"; do
    log="${VP_OUT}/logs/$(vp__slug "${g}::import::${mod}").log"
    env -u PYTHONPATH -u LD_LIBRARY_PATH timeout -k 10 120 "${py}" -c "import ${mod}" >"${log}" 2>&1
    rc=$?
    if [[ "${rc}" -eq 0 ]]; then
      vp_result "${g}::import::${mod}" pass "imported with ${py} and no PYTHONPATH" 0 "${log}"
    elif [[ "${mode}" != therock ]] && grep -qE "${PK_ROCM_LIB_RE}" "${log}"; then
      vp_result "${g}::import::${mod}" blocked "ROCm runtime library absent in ${mode} mode: $(tail -1 "${log}")" 0 "${log}"
    else
      vp_result "${g}::import::${mod}" fail "rc ${rc}: $(tail -3 "${log}" | tr '\n' ' ')" 0 "${log}"
    fi
  done
}

# pk_ldd_checks <group> <mode>: every vision library resolves all NEEDED.
pk_ldd_checks() {
  local g="$1" mode="$2" lib id nf log
  while IFS= read -r lib; do
    id="$(pk_lib_id "${lib}")"
    log="${VP_OUT}/logs/$(vp__slug "${g}::ldd::${id}").log"
    ldd "${lib}" >"${log}" 2>&1
    nf="$(grep 'not found' "${log}" | awk '{print $1}' | tr '\n' ' ')"
    if [[ -z "${nf}" ]]; then
      vp_result "${g}::ldd::${id}" pass "all NEEDED resolve (${mode} mode)" 0 "${log}"
    elif [[ "${mode}" == stubs || "${mode}" == force-depends || "${mode}" == nodeps ]]; then
      vp_result "${g}::ldd::${id}" blocked "ROCm libraries are not installed in ${mode} mode: ${nf}" 0 "${log}"
    else
      vp_result "${g}::ldd::${id}" fail "not found: ${nf}(vision libs sit in /opt/rocm/lib with \$ORIGIN RUNPATHs; TheRock packages install to /opt/rocm/core-<ver>)" 0 "${log}"
    fi
  done < <(pk_real_vision_libs)
}
