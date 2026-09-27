#!/usr/bin/env bash
# Port of vision-pack's build.yml "Verify install" step (plus the two
# package.yml tarball gates) to the merged ROCm prefix, one result per gate:
#   loader-audit::verify-install::<check>
# Upstream scans build/staging, which holds only vision-pack files; here the
# lib/*.so* scans are limited to the vision-pack-owned ELF objects, because
# $ROCM_PATH/lib also holds every SDK library. readelf replaces patchelf (not
# in the test image). Additions: bin/runvx RUNPATH, the detected gfx in the
# manifest's gpu_targets, sysdep SONAME chains, and manifest presence.
set -uo pipefail
source "${VP_REPO}/build_tools/lib/vp.sh"

G=verify-install
R="${ROCM_PATH}"
SYSDEPS="${R}/lib/rocm_sysdeps/lib"
OWNED_ELFS="${VP_WORK}/owned_elfs.txt"   # absolute paths, one per line (written by run.sh)
LOG="${VP_OUT}/logs/verify-install.log"
: >"${LOG}"

check() { # <name> <pass|fail|blocked|error> <message>
  echo "[$2] $1: $3" >>"${LOG}"
  vp_result "${G}::$1" "$2" "$3" 0 "${LOG}"
}
needed()  { readelf -dW "$1" 2>/dev/null | sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p'; }
runpath() { readelf -dW "$1" 2>/dev/null | sed -n 's/.*(R\(UN\)\{0,1\}PATH).*\[\(.*\)\]/\2/p'; }
bad_rpath_entries() { # non-$ORIGIN or empty RUNPATH tokens, space separated
  local rp="$1"
  [[ -z "${rp}" ]] && return 0
  printf '%s' "${rp}" | tr ':' '\n' | sed 's/^$/<empty>/' | grep -v '^\$ORIGIN' | tr '\n' ' '
}

mapfile -t ELFS < <(cat "${OWNED_ELFS}" 2>/dev/null)
LIBS=()
for so in "${ELFS[@]}"; do
  case "${so}" in "${R}"/lib/*.so*) LIBS+=("${so}") ;; esac
done

# --- presence (upstream list) ---
while IFS='|' read -r name pattern label; do
  [[ -z "${name}" ]] && continue
  if compgen -G "${R}/${pattern}" >/dev/null; then
    check "present.${name}" pass "${label}: OK"
  else
    check "present.${name}" fail "${label} missing (${pattern})"
  fi
done <<'EOF'
libopenvx|lib/libopenvx.so|mivisionx libopenvx
librocal|lib/librocal.so|rocAL librocal
libroccv|lib/libroccv.so|rocCV libroccv
rocal_pybind|lib/rocal_pybind*.so|rocAL Python binding
rocpycv|lib/rocpycv*.so|rocCV Python binding
rocpydecode|lib/rocpydecode*.so|rocPyDecode Python binding
rocpyjpegdecode|lib/rocpyjpegdecode*.so|rocPyJPEGDecode Python binding
pyRocVideoDecode|lib/pyRocVideoDecode|rocPyDecode Python package
pyRocJpegDecode|lib/pyRocJpegDecode|rocPyJPEGDecode Python package
rocpydecode-tests|share/rocpydecode/tests|rocPyDecode test sources
runvx|bin/runvx|mivisionx runvx tool
rocal-test-data|share/rocal/test/data/images/AMD-tinyDataSet|rocAL test data
turbojpeg|lib/rocm_sysdeps/lib/libturbojpeg-rocm-vision.so*|bundled turbojpeg
protobuf|lib/rocm_sysdeps/lib/libprotobuf-rocm-vision.so*|bundled protobuf
lmdb|lib/rocm_sysdeps/lib/liblmdb-rocm-vision.so*|bundled lmdb
libsndfile|lib/rocm_sysdeps/lib/libsndfile-rocm-vision.so*|bundled libsndfile
EOF

# --- build-time-only deps must not ship ---
for neg in "dlpack-headers|include/dlpack" "dlpack-cmake|lib/cmake/dlpack"; do
  name="${neg%%|*}" rel="${neg#*|}"
  if [[ -e "${R}/${rel}" ]]; then
    check "absent.${name}" fail "${rel} leaked into the install"
  else
    check "absent.${name}" pass "${rel} absent: OK"
  fi
done

# --- rocpydecode modules in lib/, not lib64/ ---
for mod in rocpydecode rocpyjpegdecode; do
  if compgen -G "${R}/lib64/${mod}*.so" >/dev/null; then
    check "libdir.${mod}" fail "${mod} installed in lib64/ instead of lib/"
  elif compgen -G "${R}/lib/${mod}*.so" >/dev/null; then
    check "libdir.${mod}" pass "${mod} in lib/: OK"
  else
    check "libdir.${mod}" fail "${mod} missing from lib/"
  fi
done

# --- librocal linkage ---
ROCAL="${R}/lib/librocal.so"
if [[ -e "${ROCAL}" ]]; then
  NEEDED="$(needed "${ROCAL}")"
  if grep -qi 'libprotobuf-rocm-vision' <<<"${NEEDED}"; then
    check librocal-needs-isolated-protobuf pass "librocal NEEDs the isolated protobuf"
  else
    check librocal-needs-isolated-protobuf fail "librocal.so does not list libprotobuf-rocm-vision.so as NEEDED"
  fi
  STOCK="$(grep -Ei 'lib(protobuf|protobuf-lite|turbojpeg|jpeg|lmdb|sndfile)\.so' <<<"${NEEDED}" | grep -iv rocm-vision | tr '\n' ' ')"
  if [[ -n "${STOCK}" ]]; then
    check librocal-no-stock-sonames fail "librocal.so still NEEDs stock bundled SONAME(s): ${STOCK}"
  else
    check librocal-no-stock-sonames pass "no stock bundled SONAMEs referenced"
  fi
  RP="$(runpath "${ROCAL}")"
  if grep -q 'rocm_sysdeps/lib' <<<"${RP}"; then
    check librocal-runpath-sysdeps pass "RUNPATH [${RP}]"
  else
    check librocal-runpath-sysdeps fail "librocal.so has no RUNPATH to rocm_sysdeps/lib ([${RP:-none}])"
  fi
  if grep -qi 'libjpeg-rocm-vision\.so' <<<"${NEEDED}"; then
    check librocal-needs-isolated-libjpeg pass "librocal NEEDs the isolated libjpeg"
  else
    check librocal-needs-isolated-libjpeg fail "librocal.so has no NEEDED on libjpeg-rocm-vision.so (jpeg_std_error unresolved)"
  fi
  missing=()
  for so in $(grep -oiE 'lib[a-z0-9._-]*-rocm-vision\.so[0-9.]*' <<<"${NEEDED}"); do
    [[ -e "${SYSDEPS}/${so}" ]] || missing+=("${so}")
  done
  if [[ ${#missing[@]} -eq 0 ]]; then
    check isolated-soname-links pass "every isolated NEEDED of librocal resolves in rocm_sysdeps/lib"
  else
    check isolated-soname-links fail "NEEDED without file/symlink in rocm_sysdeps/lib: ${missing[*]}"
  fi
else
  for c in librocal-needs-isolated-protobuf librocal-no-stock-sonames librocal-runpath-sysdeps \
           librocal-needs-isolated-libjpeg isolated-soname-links; do
    check "${c}" fail "lib/librocal.so missing"
  done
fi

# --- libomp consumers carry llvm/lib in RUNPATH (#43) ---
bad=()
n=0
for so in "${LIBS[@]}"; do
  grep -q '^libomp\.so' <<<"$(needed "${so}")" || continue
  n=$((n + 1))
  grep -q 'llvm/lib$' <<<"$(runpath "${so}" | tr ':' '\n')" || bad+=("${so#"${R}"/}")
done
if [[ ${#bad[@]} -eq 0 ]]; then
  check libomp-runpath pass "${n} libomp consumer(s), all with llvm/lib in RUNPATH"
else
  check libomp-runpath fail "NEED libomp.so without llvm/lib in RUNPATH: ${bad[*]}"
fi

# --- RUNPATHs relocatable: only $ORIGIN entries, no empty tokens (#45) ---
bad=()
for so in "${LIBS[@]}"; do
  b="$(bad_rpath_entries "$(runpath "${so}")")"
  [[ -n "${b}" ]] && bad+=("${so#"${R}"/}: ${b}")
done
if [[ ${#bad[@]} -eq 0 ]]; then
  check runpath-relocatable pass "${#LIBS[@]} shared objects: RUNPATHs are \$ORIGIN-relative"
else
  check runpath-relocatable fail "non-relocatable RUNPATH entries: ${bad[*]}"
fi

RUNVX="${R}/bin/runvx"
if [[ -f "${RUNVX}" ]]; then
  rp="$(runpath "${RUNVX}")"
  b="$(bad_rpath_entries "${rp}")"
  if [[ -z "${b}" ]]; then
    check runvx-runpath pass "bin/runvx RUNPATH [${rp}]"
  else
    check runvx-runpath fail "bin/runvx RUNPATH has non-\$ORIGIN entries (build-machine dirs): ${b}"
  fi
  if [[ -x "${RUNVX}" ]]; then
    check runvx-executable pass "bin/runvx mode $(stat -c %a "${RUNVX}")"
  else
    check runvx-executable fail "bin/runvx is not executable (mode $(stat -c %a "${RUNVX}"), #44)"
  fi
else
  check runvx-runpath fail "bin/runvx missing"
  check runvx-executable fail "bin/runvx missing"
fi

# --- deps come from rocm_sysdeps, not host copies of what ROCm vendors ---
BASE_RE='^(libc|libm|libdl|libpthread|librt|libstdc\+\+|libgcc_s|ld-linux-x86-64|libomp)\.so'
bad=()
for so in "${ELFS[@]}"; do
  for n in $(needed "${so}"); do
    case "${n}" in librocm_sysdeps_*|*rocm-vision*) continue ;; esac
    grep -qE "${BASE_RE}" <<<"${n}" && continue
    stem="$(sed -n 's/^lib\([a-z0-9+_-]*\)\.so.*/\1/p' <<<"${n}")"
    [[ -n "${stem}" ]] || continue
    if compgen -G "${SYSDEPS}/librocm_sysdeps_${stem}.so*" >/dev/null; then
      bad+=("${so#"${R}"/} NEEDs ${n} (ROCm vendors librocm_sysdeps_${stem})")
    fi
  done
done
if [[ ${#bad[@]} -eq 0 ]]; then
  check no-host-duplicate-deps pass "no NEEDED on a host copy of a ROCm-vendored sysdep"
else
  check no-host-duplicate-deps fail "${bad[*]}"
fi

# --- versioned SONAME chains are one real file + symlinks (#43) ---
for base in libopenvx libvxu libvx_rpp librocal libroccv \
            libjpeg-rocm-vision libturbojpeg-rocm-vision libprotobuf-rocm-vision liblmdb-rocm-vision libsndfile-rocm-vision; do
  dir="${R}/lib"
  [[ "${base}" == *-rocm-vision ]] && dir="${SYSDEPS}"
  real=0 links=0
  for so in "${dir}/${base}".so*; do
    [[ -e "${so}" ]] || continue
    if [[ -L "${so}" ]]; then links=$((links + 1)); else real=$((real + 1)); fi
  done
  if [[ "${real}" -eq 1 ]]; then
    check "soname-chain.${base}" pass "1 real file + ${links} symlink(s)"
  elif [[ "${real}" -eq 0 ]]; then
    check "soname-chain.${base}" fail "no ${base}.so* file"
  else
    check "soname-chain.${base}" fail "${real} real files: the SONAME chain was flattened into copies"
  fi
done

# --- each GPU library ships code objects ---
for base in libopenvx libvx_rpp libroccv librocal; do
  so="$(readlink -f "${R}/lib/${base}.so" 2>/dev/null || true)"
  if [[ -z "${so}" || ! -f "${so}" ]]; then
    check "gpu-code-objects.${base}" fail "lib/${base}.so missing"
    continue
  fi
  arches="$("${VP_PY}" "${VP_SUITE_DIR}/vp_owned.py" fatbin "${so}" 2>>"${LOG}")"
  count="$(wc -w <<<"${arches}")"
  if [[ "${count}" -gt 0 ]]; then
    check "gpu-code-objects.${base}" pass "${count} arch(es): ${arches}"
  else
    check "gpu-code-objects.${base}" fail "ships no GPU code objects"
  fi
done

# --- isolated libjpeg exports jpeg_std_error (package.yml) ---
jl="$(compgen -G "${SYSDEPS}/libjpeg-rocm-vision.so*" | head -1)"
dynsyms=""
[[ -n "${jl}" ]] && dynsyms="$(readelf -W --dyn-syms "$(readlink -f "${jl}")" 2>/dev/null)"
# a here-string, not a pipe: grep -q would SIGPIPE readelf and fail under pipefail
if grep -qE ' jpeg_std_error(@|$)' <<<"${dynsyms}"; then
  check libjpeg-exports-jpeg_std_error pass "jpeg_std_error exported"
else
  check libjpeg-exports-jpeg_std_error fail "isolated libjpeg missing or does not export jpeg_std_error"
fi

# --- manifest and the detected GPU ---
if jq -e '.version and .sha and (.gpu_targets | type == "object")' "${VP_MANIFEST}" >/dev/null 2>&1; then
  check manifest pass "$(jq -r '"version \(.version) sha \(.sha[0:12])"' "${VP_MANIFEST}")"
else
  check manifest fail "manifest missing or invalid: ${VP_MANIFEST}"
fi
if [[ -z "${VP_GFX}" ]]; then
  check gfx-in-manifest blocked "no GPU detected (VP_GFX empty)"
else
  missing="$(jq -r --arg g "${VP_GFX}" '(.gpu_targets // {}) | to_entries[] | select((.value | index($g)) | not) | .key' \
    "${VP_MANIFEST}" 2>/dev/null | tr '\n' ' ')"
  if ! jq -e '.gpu_targets | length > 0' "${VP_MANIFEST}" >/dev/null 2>&1; then
    check gfx-in-manifest fail "manifest has no gpu_targets"
  elif [[ -z "${missing}" ]]; then
    check gfx-in-manifest pass "${VP_GFX} listed for every library in gpu_targets"
  else
    check gfx-in-manifest fail "${VP_GFX} missing from gpu_targets of: ${missing}"
  fi
fi
exit 0
