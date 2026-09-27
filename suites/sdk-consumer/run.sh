#!/usr/bin/env bash
# sdk-consumer: what an SDK developer hits when building against the installed
# vision-pack: header self-containment, find_package consumer projects built and
# run on CPU and GPU with numeric checks, install-location contamination against
# synthetic decoy ROCm trees, and the standalone-tarball ldd scenario.
#
#   standard and up  all of the above (primary header modes; rocjpeg run and the
#                    extra C99 / g++ host-only header modes from comprehensive)
#   quick            (not scheduled; for local smoke runs) consumers' find-package
#                    configures and the standalone ldd scenario only
#
# VP_SDK_GROUPS="headers consumers contamination standalone" limits the groups
# (local development). VP_DIST_TARBALL, when set, is extracted for the standalone
# scenario instead of copying the vision-pack-owned files out of the prefix.
set -uo pipefail
source "${VP_REPO}/build_tools/lib/vp.sh"
vp_init sdk-consumer

[[ -d "${ROCM_PATH}/lib" ]] || { vp__log "ROCM_PATH=${ROCM_PATH} is not a ROCm prefix"; exit 2; }
cd "${VP_WORK}" || exit 2
GROUPS_WANTED=" ${VP_SDK_GROUPS:-headers consumers contamination standalone} "
want() { [[ "${GROUPS_WANTED}" == *" $1 "* ]]; }

harness() { # <group> <timeout> <cmd...>
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
for c in cmake cc c++ readelf ldd; do command -v "${c}" >/dev/null 2>&1 || missing+=("${c}"); done
if [[ ${#missing[@]} -gt 0 ]]; then
  vp_blocked "setup::tools" "missing command(s): ${missing[*]} (cmake, gcc/g++, binutils)"
  vp_finish
  exit 0
fi

if ! vp_tier_ge standard; then
  want consumers && harness consumers 1800 "${VP_PY}" "${VP_SUITE_DIR}/consumers.py" --find-package-only
  want standalone && harness standalone 1800 "${VP_PY}" "${VP_SUITE_DIR}/standalone_ldd.py"
  vp_finish
  exit 0
fi

want headers && harness headers 2400 "${VP_PY}" "${VP_SUITE_DIR}/headers.py"
want consumers && harness consumers 3600 "${VP_PY}" "${VP_SUITE_DIR}/consumers.py"
want contamination && harness contamination 2400 "${VP_PY}" "${VP_SUITE_DIR}/contamination.py"
want standalone && harness standalone 1800 "${VP_PY}" "${VP_SUITE_DIR}/standalone_ldd.py"

vp_finish
exit 0
