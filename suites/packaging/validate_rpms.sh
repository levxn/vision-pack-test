#!/usr/bin/env bash
# Validate the release RPMs. Upstream's "Inspect RPM metadata" step only
# prints, so this is the gate: payload prefix, Requires/Provides sanity
# (runtime<->devel<->test, metas mirroring the DEB metas, closure of the
# automatic soname requirements), file lists matching the DEBs, build-machine
# paths, scriptlets and the .pth handling. Needs rpm, rpm2cpio and cpio
# (Ubuntu: apt install rpm cpio).
#
#   suites/packaging/validate_rpms.sh --rpms <dir> [--debs <dir>] --out <dir>
#
# Records packaging::rpm::set::* and packaging::rpm::<package>::<check>.
set -uo pipefail
PK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${PK_DIR}/lib/common.sh"

rpms="" debs="" out=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rpms) rpms="$2"; shift 2 ;;
    --debs) debs="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) pk_die "unknown argument $1" ;;
  esac
done
[[ -n "${rpms}" ]] || pk_die "--rpms is required"
rpms="$(pk_abs_dir "${rpms}")" || pk_die "no such directory: ${rpms}"
if [[ -n "${debs}" ]]; then debs="$(pk_abs_dir "${debs}")" || pk_die "no such directory: ${debs}"; fi
pk_init packaging "${out}"

if ! vp_require_cmd rpm::tools rpm rpm2cpio cpio readelf; then vp_finish; exit 0; fi
if [[ -z "$(find "${rpms}" -maxdepth 1 -name '*.rpm' -print -quit)" ]]; then
  vp_result rpm::set::packages error "no .rpm files in ${rpms}"
  vp_finish
  exit 0
fi

work="${VP_WORK}/rpm-payload"
args=(rpm --rpms "${rpms}" --work "${work}")
[[ -n "${debs}" ]] && args+=(--debs "${debs}")
pk_py "${args[@]}" >"${VP_OUT}/logs/rpm-checks.log" 2>&1 \
  || vp_result rpm::checks error "pkgcheck.py rpm failed (see logs/rpm-checks.log)" 0 "${VP_OUT}/logs/rpm-checks.log"
grep -E '^  (FAIL|ERROR)|^file counts' "${VP_OUT}/logs/rpm-checks.log" || true
pk_cleanup_work "${work}"
vp_finish
exit 0
