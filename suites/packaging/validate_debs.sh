#!/usr/bin/env bash
# Validate the release DEBs with the pinned submodule's validate_packages.sh,
# plus license (H4) and test-dependency (N1/N2) checks.
#
#   suites/packaging/validate_debs.sh --debs <dir> --out <dir>
#
# Records (suite packaging):
#   packaging::deb::<package>                upstream verdict per package
#   packaging::deb::cross-package            upstream overlap/produced checks
#   packaging::deb::summary                  the "Package validation summary"
#   packaging::deb::set::{packages,version}
#   packaging::deb::<package>::license.<component>
#   packaging::deb::<package>::{payload.empty-dirs,payload.build-paths}
#   packaging::deb::<test-package>::{depends.devel,refs.closure,refs.any-package}
# Appends the summary table to $GITHUB_STEP_SUMMARY when set.
set -uo pipefail
PK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${PK_DIR}/lib/common.sh"

debs="" out=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --debs) debs="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) pk_die "unknown argument $1" ;;
  esac
done
[[ -n "${debs}" ]] || pk_die "--debs is required"
debs="$(pk_abs_dir "${debs}")" || pk_die "no such directory: ${debs}"
pk_init packaging "${out}"

if ! vp_require_cmd deb::tools dpkg-deb; then vp_finish; exit 0; fi
n_debs="$(find "${debs}" -maxdepth 1 -name '*.deb' | wc -l)"
if [[ "${n_debs}" -eq 0 ]]; then
  vp_result deb::summary error "no .deb files in ${debs}"
  vp_finish
  exit 0
fi

validator="${VP_VISION_PACK_SRC}/build_tools/validate_packages.sh"
log="${VP_OUT}/logs/validate_packages.log"
if [[ ! -f "${validator}" ]]; then
  vp_result deb::summary error "${validator} not found (is the vision-pack submodule checked out?)"
else
  timeout -k 30 900 bash "${validator}" "${debs}" >"${log}" 2>&1
  rc=$?
  pk_py upstream-log --log "${log}" --log-rel logs/validate_packages.log --rc "${rc}" --debs "${debs}" \
    --summary-md "${VP_WORK}/validation-summary.txt" || vp_result deb::summary error "could not parse ${log}"
  if [[ -s "${VP_WORK}/validation-summary.txt" ]]; then
    {
      echo "### Package validation summary (DEB, $(basename "$(dirname "${debs}")"))"
      echo
      echo '```'
      cat "${VP_WORK}/validation-summary.txt"
      echo '```'
    } >"${VP_WORK}/validation-summary.md"
    pk_step_summary "${VP_WORK}/validation-summary.md"
    cat "${VP_WORK}/validation-summary.txt"
  fi
fi

work="${VP_WORK}/deb-payload"
pk_py deb --debs "${debs}" --work "${work}" >"${VP_OUT}/logs/deb-extra.log" 2>&1 \
  || vp_result deb::extra-checks error "pkgcheck.py deb failed (see logs/deb-extra.log)" 0 "${VP_OUT}/logs/deb-extra.log"
pk_cleanup_work "${work}"
vp_finish
exit 0
