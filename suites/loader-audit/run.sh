#!/usr/bin/env bash
# loader-audit: RUNPATH/NEEDED resolution, dlopen and link probes, CWD hijack,
# symbol isolation, ELF hygiene, licenses and inventory of the installed
# vision-pack payload. CPU-only work (runs on the GPU runner).
#
#   quick           verify-install, ldd matrix, dlopen/exec/link probes, py-import
#                   (3.12), inventory, fatbin, licenses/docs            (~3 min)
#   standard and up + cwd-hijack, interposition (M1), ELF hardening/hygiene,
#                   exported symbols, hardcoded paths, py 3.13 negative,
#                   tarball-vs-prefix (needs VP_DIST_TARBALL)
#
# Optional: VP_DIST_TARBALL=<vision-pack-dist-*.tar.gz> makes the tarball the
# source of file ownership; otherwise the staging-layout patterns in vp_owned.py.
# VP_PY313=<python3.13> enables the 3.13 negative control where it is not on PATH.
set -uo pipefail
source "${VP_REPO}/build_tools/lib/vp.sh"
vp_init loader-audit

[[ -d "${ROCM_PATH}/lib" ]] || { vp__log "ROCM_PATH=${ROCM_PATH} is not a ROCm prefix"; exit 2; }
cd "${VP_WORK}" || exit 2

# harness <group> <timeout> <cmd...>: run one harness; a crash or timeout of the
# harness itself becomes an error record, never a silent pass.
harness() {
  local group="$1" timeout="$2"; shift 2
  local log="${VP_OUT}/logs/${group}.harness.log"
  vp__log "harness ${group}"
  timeout -k 30 "$(vp__scale_timeout "${timeout}")" "$@" >"${log}" 2>&1
  local rc=$?
  if [[ "${rc}" -ne 0 ]]; then
    vp_result "${group}::harness" error "harness exited ${rc}; see logs/${group}.harness.log: $(tail -c 800 "${log}" | tr '\n' ' ')" \
      0 "${log}"
  fi
}

missing=()
for c in readelf nm ldd jq; do command -v "${c}" >/dev/null 2>&1 || missing+=("${c}"); done
if [[ ${#missing[@]} -gt 0 ]]; then
  vp_blocked "setup::tools" "missing command(s): ${missing[*]} (binutils, libc-bin, jq)"
  vp_finish
  exit 0
fi

if ! timeout 600 "${VP_PY}" "${VP_SUITE_DIR}/vp_owned.py" write "${VP_WORK}/owned.json" >"${VP_OUT}/logs/owned.log" 2>&1; then
  vp_result "setup::owned-files" error "could not enumerate the vision-pack payload (see logs/owned.log)" 0 \
    "${VP_OUT}/logs/owned.log"
  vp_finish
  exit 0
fi
jq -r --arg r "${ROCM_PATH}" '.elfs[] | "\($r)/\(.rel)"' "${VP_WORK}/owned.json" >"${VP_WORK}/owned_elfs.txt"
vp__log "payload: $(head -1 "${VP_OUT}/logs/owned.log")"

harness verify-install 600 bash "${VP_SUITE_DIR}/verify_install.sh"
harness ldd 900 "${VP_PY}" "${VP_SUITE_DIR}/loader_matrix.py"
harness probes 900 "${VP_PY}" "${VP_SUITE_DIR}/probes.py"
harness py-import 900 "${VP_PY}" "${VP_SUITE_DIR}/py_import.py"
harness inventory 1200 "${VP_PY}" "${VP_SUITE_DIR}/inventory.py"
harness elf-audit 1200 "${VP_PY}" "${VP_SUITE_DIR}/elf_audit.py"
harness license 600 "${VP_PY}" "${VP_SUITE_DIR}/license_scan.py"
if vp_tier_ge standard; then
  harness cwd-hijack 900 "${VP_PY}" "${VP_SUITE_DIR}/cwd_hijack.py"
  harness interpose 900 "${VP_PY}" "${VP_SUITE_DIR}/interpose.py"
fi

vp_finish
exit 0
